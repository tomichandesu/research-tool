"""1688画像検索モジュール"""
from __future__ import annotations

import logging
import re
import asyncio
import tempfile
import os
from typing import Optional
from pathlib import Path

import aiohttp
from PIL import Image
from playwright.async_api import Page

from ...utils.browser import BrowserManager, RetryStrategy
from ...models.product import AlibabaProduct
from ...config import get_config

logger = logging.getLogger(__name__)


class AlibabaImageSearcher:
    """1688で画像検索を実行する

    1688の画像検索機能を使用して、商品画像から類似商品を検索する。
    画像をダウンロードしてファイルアップロード形式で検索を実行する。
    ページを使い回して高速化する。
    """

    IMAGE_SEARCH_URL = "https://s.1688.com/youyuan/index.htm"

    def __init__(self, browser: BrowserManager, max_results: int = 10):
        self.browser = browser
        self.max_results = max_results
        self._page: Optional[Page] = None
        self._temp_files: list[str] = []

    async def _ensure_page(self) -> Page:
        """検索ページを準備（毎回新規作成）

        ページ再利用すると2回目以降の画像検索で
        pages-fast.1688.comからs.1688.com/selloffer/にフォールバックし、
        画像検索結果ではなくテキスト検索結果が返される問題があるため、
        毎回新しいページを作成する。
        """
        if self._page is not None:
            try:
                await self._page.close()
            except Exception:
                pass
            self._page = None

        self._page = await self.browser.new_page()
        return self._page

    async def close(self) -> None:
        """検索ページを閉じる"""
        if self._page:
            try:
                await self._page.close()
            except Exception:
                pass
            self._page = None
        self._cleanup_temp_files()

    async def _download_image(self, url: str) -> Optional[str]:
        """画像をダウンロードして一時ファイルに保存"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as f:
                            f.write(await response.read())
                            self._temp_files.append(f.name)
                            return f.name
        except Exception as e:
            logger.warning(f"画像ダウンロード失敗: {url} - {e}")
        return None

    def _cleanup_temp_files(self):
        """一時ファイルをクリーンアップ"""
        for path in self._temp_files:
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except Exception:
                pass
        self._temp_files = []

    async def search_by_image(
        self,
        image_url: str,
        max_results: Optional[int] = None,
    ) -> list[AlibabaProduct]:
        """画像URLで1688を検索

        Args:
            image_url: 検索する画像のURL
            max_results: 取得する結果数

        Returns:
            類似商品リスト
        """
        max_results = max_results or self.max_results

        logger.info(f"1688画像検索開始: {image_url[:50]}...")

        try:
            page = await self._ensure_page()
            products = await RetryStrategy.with_retry(
                self._search_by_image_url,
                page,
                image_url,
                max_results,
            )
            logger.info(f"1688検索完了: {len(products)}件取得")
            return products

        except Exception as e:
            logger.error(f"1688画像検索失敗: {e}")
            # ページが壊れた場合はリセット
            self._page = None
            return []

    PAGES_FAST_URL = (
        "https://pages-fast.1688.com/wow/cbu/srch_rec/image_search"
        "/youyuan/index.html?tab=imageSearch&imageId={image_id}"
    )

    async def _search_by_image_url(
        self,
        page: Page,
        image_url: str,
        max_results: int,
    ) -> list[AlibabaProduct]:
        """画像URLで検索を実行

        手順:
        1. 画像をダウンロードしてファイルアップロード
        2. 「搜索图片」ボタンをクリック
        3. 自然遷移で検索結果ページに到達するのを待つ
        4. 検索結果をパース
        5. 結果が0件の場合、imageIdがあればpages-fast直接アクセスをフォールバック
        """
        try:
            # 1. 画像をダウンロード
            logger.debug(f"画像ダウンロード中: {image_url[:50]}...")
            image_path = await self._download_image(image_url)
            if not image_path:
                logger.warning("画像ダウンロード失敗")
                return []

            # 2. 1688画像検索ページにアクセス
            await self.browser.navigate(page, self.IMAGE_SEARCH_URL)
            await asyncio.sleep(3)

            # 3. ファイルアップロード（リトライ付き）
            file_input = None
            for attempt in range(3):
                file_input = await page.query_selector('input[type="file"]')
                if file_input:
                    break
                logger.debug(f"ファイル入力待機中... ({attempt + 1}/3)")
                await asyncio.sleep(2)

            if not file_input:
                logger.warning("ファイル入力フィールドが見つかりません")
                return []

            # imageIdをキャプチャするリスナーを設定
            captured_image_id = None

            def _capture_image_id(request):
                nonlocal captured_image_id
                url = request.url
                if 'imageId=' in url and captured_image_id is None:
                    match = re.search(r'imageId=(\d+)', url)
                    if match:
                        captured_image_id = match.group(1)
                        logger.debug(f"imageIdキャプチャ: {captured_image_id}")

            page.on('request', _capture_image_id)

            await file_input.set_input_files(image_path)
            logger.debug("画像アップロード完了")
            await asyncio.sleep(3)  # ポップアップ表示を待機

            # 4. 「搜索图片」ボタンをクリック
            search_btn = await page.query_selector('div.search-btn')
            if not search_btn:
                search_btn = await page.query_selector('.search-btn')
            if not search_btn:
                # テキストで搜索图片ボタンを探す
                search_btn = await page.query_selector('text=搜索图片')
            if search_btn:
                await search_btn.click()
                logger.debug("搜索图片ボタンクリック完了")
            else:
                logger.warning("搜索图片ボタンが見つかりません")
                page.remove_listener('request', _capture_image_id)
                return []

            # 5. 自然遷移で検索結果が表示されるのを待つ（ルートブロックなし）
            products = []
            for i in range(30):
                await asyncio.sleep(1)
                products = await self._parse_search_results_flexible(page, max_results)
                if products:
                    logger.debug(f"自然遷移で結果取得: {len(products)}件 ({i+1}秒)")
                    break

            page.remove_listener('request', _capture_image_id)

            # 6. 結果が0件の場合、pages-fast直接アクセスをフォールバック
            if not products and captured_image_id:
                logger.debug(
                    f"自然遷移で結果なし。pages-fastフォールバック"
                    f" (imageId={captured_image_id})"
                )
                pages_fast_url = self.PAGES_FAST_URL.format(
                    image_id=captured_image_id
                )
                try:
                    await page.goto(
                        pages_fast_url,
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                    for i in range(20):
                        await asyncio.sleep(1)
                        products = await self._parse_search_results_flexible(
                            page, max_results
                        )
                        if products:
                            logger.debug(
                                f"pages-fastフォールバックで結果取得:"
                                f" {len(products)}件"
                            )
                            break
                except Exception as e:
                    logger.debug(f"pages-fastフォールバック失敗: {e}")

            return products

        finally:
            self._cleanup_temp_files()

    async def _parse_search_results_flexible(
        self,
        page: Page,
        max_results: int,
    ) -> list[AlibabaProduct]:
        """複数のセレクタパターンで検索結果をパースする"""
        # パターン1: pages-fast (既存)
        items = await page.query_selector_all(
            'div[class*="searchOfferWrapper"]'
        )
        if items:
            logger.debug(f"searchOfferWrapperで取得: {len(items)}件")
            return await self._parse_items(items, page, max_results)

        # パターン2: selloffer/offer-list系
        items = await page.query_selector_all(
            'div[class*="offer-list"] div[class*="offer-item"]'
        )
        if items:
            logger.debug(f"offer-itemで取得: {len(items)}件")
            return await self._parse_items(items, page, max_results)

        # パターン3: カード系
        items = await page.query_selector_all('[class*="offerCard"]')
        if items:
            logger.debug(f"offerCardで取得: {len(items)}件")
            return await self._parse_items(items, page, max_results)

        # パターン4: data-renderkey属性
        items = await page.query_selector_all('[data-renderkey]')
        if items:
            logger.debug(f"data-renderkeyで取得: {len(items)}件")
            return await self._parse_items(items, page, max_results)

        # パターン5: detail.1688.comリンクを含む要素の親
        links = await page.query_selector_all(
            'a[href*="detail.1688.com"]'
        )
        if links:
            logger.debug(f"detail.1688.comリンクで取得: {len(links)}件")
            # リンクの親要素を取得して商品カードとして扱う
            items = []
            for link in links[:max_results]:
                parent = await link.evaluate_handle(
                    'el => el.closest("div[class]") || el.parentElement'
                )
                if parent:
                    items.append(parent)
            if items:
                return await self._parse_items(items, page, max_results)

        return []

    async def _parse_items(
        self,
        items,
        page: Page,
        max_results: int,
    ) -> list[AlibabaProduct]:
        """アイテムリストから商品データをパースする"""
        products = []
        for i, item in enumerate(items[:max_results]):
            try:
                product = await self._parse_product_item(item, page)
                if product:
                    products.append(product)
            except Exception as e:
                logger.debug(f"商品パース失敗 ({i}): {e}")
        return products

    async def _parse_search_results(
        self,
        page: Page,
        max_results: int,
    ) -> list[AlibabaProduct]:
        """検索結果をパースする

        pages-fast.1688.comの画像検索結果ページから商品情報を取得する。
        商品カードはdiv[class*="searchOfferWrapper"]で、
        商品URLはdata-renderkey属性のoffer IDから構築する。
        """
        products = []

        current_url = page.url
        logger.debug(f"検索結果ページURL: {current_url}")

        # pages-fast.1688.comの画像検索結果のみ取得（テキスト検索結果は使わない）
        items = await page.query_selector_all('div[class*="searchOfferWrapper"]')
        if items:
            logger.debug(f"searchOfferWrapperで取得: {len(items)}件")

        if not items:
            logger.warning(f"検索結果が見つかりません (URL: {current_url[:80]})")
            return []

        for i, item in enumerate(items[:max_results]):
            try:
                product = await self._parse_product_item(item, page)
                if product:
                    products.append(product)
            except Exception as e:
                logger.debug(f"商品パース失敗 ({i}): {e}")

        return products

    async def _parse_product_item(
        self,
        item,
        page: Page,
    ) -> Optional[AlibabaProduct]:
        """商品アイテムをパースする"""
        try:
            # 価格を取得
            price_cny = await self._extract_price(item)

            # 画像URLを取得
            image_url = await self._extract_image_url(item)

            # 商品URLを取得
            product_url = await self._extract_product_url(item)

            # 店舗名を取得
            shop_name = await self._extract_shop_name(item)

            # 店舗URLを取得
            shop_url = await self._extract_shop_url(item, product_url)

            # タイトルを取得
            title = await self._extract_title(item)

            # 最小注文数を取得
            min_order = await self._extract_min_order(item)

            if price_cny == 0:
                logger.debug("価格が取得できませんでした")
                return None

            return AlibabaProduct(
                price_cny=price_cny,
                image_url=image_url,
                product_url=product_url,
                shop_name=shop_name,
                shop_url=shop_url,
                min_order=min_order,
                title=title,
            )

        except Exception as e:
            logger.debug(f"商品パースエラー: {e}")
            return None

    async def _extract_price(self, item) -> float:
        """価格を抽出"""
        # 新UI: span.number + span.unit (例: "26" + ".00")
        try:
            number_el = await item.query_selector('span[class*="number"]')
            unit_el = await item.query_selector('span[class*="unit"]')
            if number_el:
                number_text = await number_el.inner_text()
                unit_text = ""
                if unit_el:
                    unit_text = await unit_el.inner_text()
                price_str = number_text + unit_text
                match = re.search(r'(\d+\.?\d*)', price_str.replace(',', ''))
                if match:
                    return float(match.group(1))
        except Exception:
            pass

        # priceWrap内のテキストからパース
        try:
            price_wrap = await item.query_selector('div[class*="priceWrap"]')
            if price_wrap:
                text = await price_wrap.inner_text()
                match = re.search(r'¥?(\d+\.?\d*)', text.replace(',', ''))
                if match:
                    return float(match.group(1))
        except Exception:
            pass

        # 旧UIセレクタにフォールバック
        price_selectors = [
            'span.price',
            'span.offer-price',
            'div.price',
            'em.value',
            '.price-range',
            'span[class*="price"]',
        ]

        for selector in price_selectors:
            try:
                element = await item.query_selector(selector)
                if element:
                    text = await element.inner_text()
                    match = re.search(r'(\d+\.?\d*)', text.replace(',', ''))
                    if match:
                        return float(match.group(1))
            except Exception:
                continue

        return 0.0

    async def _extract_image_url(self, item) -> str:
        """画像URLを抽出"""
        img_selectors = [
            'img[class*="mainImg"]',
            'img[class*="MainImg"]',
            'img.offer-img',
            'img.main-img',
            'img.image',
            'img[src*="cbu01.alicdn.com"]',
            'img[src*="alicdn.com"]',
            'img',
        ]

        for selector in img_selectors:
            try:
                element = await item.query_selector(selector)
                if element:
                    url = await element.get_attribute('data-lazy-src')
                    if not url:
                        url = await element.get_attribute('data-src')
                    if not url:
                        url = await element.get_attribute('src')
                    if url and 'alicdn.com' in url:
                        if url.endswith('.webp'):
                            url = url[:-5]
                        return url
            except Exception:
                continue

        return ""

    async def _extract_product_url(self, item) -> str:
        """商品URLを抽出

        pages-fastではdata-renderkey属性からoffer IDを抽出する。
        renderkey形式: "1_{index}_{type}_b2b-{sellerId}{hash}_{offerId}"
        例: "1_1_normal_b2b-2218789620187ab194_847411995095"
        """
        # data-renderkeyからoffer IDを抽出（pages-fast用）
        try:
            renderkey = await item.get_attribute('data-renderkey')
            if renderkey:
                # 末尾の数字がoffer ID
                match = re.search(r'_(\d{9,})$', renderkey)
                if match:
                    offer_id = match.group(1)
                    return f"https://detail.1688.com/offer/{offer_id}.html"
        except Exception:
            pass

        # item自体がaタグの場合（旧UI）
        try:
            href = await item.get_attribute('href')
            if href and 'detail.1688.com' in href:
                return href
        except Exception:
            pass

        # data-offer-id属性
        try:
            offer_id = await item.get_attribute('data-offer-id')
            if offer_id and offer_id.isdigit():
                return f"https://detail.1688.com/offer/{offer_id}.html"
        except Exception:
            pass

        # 内部リンクから取得
        try:
            element = await item.query_selector('a[href*="detail.1688.com"]')
            if element:
                href = await element.get_attribute('href')
                if href:
                    if href.startswith('//'):
                        href = 'https:' + href
                    return href
        except Exception:
            pass

        return ""

    async def _extract_shop_name(self, item) -> Optional[str]:
        """店舗名を抽出"""
        shop_selectors = [
            # pages-fast用
            'div[class*="overseasSellerInfoWrap"] span',
            'div[class*="sellerInfo"] span',
            # 旧UI用
            'span[class*="company"]',
            'div[class*="seller"] span',
            'a[class*="shop"]',
            'span.company-name',
            'a.company',
            'div.seller-name',
            'span.supplier-name',
            'a[href*="company"]',
        ]

        for selector in shop_selectors:
            try:
                element = await item.query_selector(selector)
                if element:
                    text = await element.inner_text()
                    if text and len(text.strip()) > 1:
                        return text.strip()
            except Exception:
                continue

        try:
            sale_info = await item.query_selector('span[class*="saleAmount"]')
            if sale_info:
                text = await sale_info.inner_text()
                if '厂' in text or '工厂' in text:
                    return "工厂直销"
        except Exception:
            pass

        return None

    async def _extract_shop_url(self, item, product_url: str) -> Optional[str]:
        """店舗URLを抽出"""
        # data-renderkeyからseller IDを取得（pages-fast用）
        try:
            renderkey = await item.get_attribute('data-renderkey')
            if renderkey and 'b2b-' in renderkey:
                match = re.search(r'b2b-(\d+)', renderkey)
                if match:
                    seller_id = match.group(1)
                    return f"https://shop{seller_id[-7:]}.1688.com/"
        except Exception:
            pass

        # リンクベース（旧UI用）
        shop_link_selectors = [
            'a[href*="shop"][href*="1688.com"]',
            'a[href*="company"][href*="1688.com"]',
            'a[href*="winport.1688.com"]',
        ]

        for selector in shop_link_selectors:
            try:
                element = await item.query_selector(selector)
                if element:
                    href = await element.get_attribute('href')
                    if href:
                        if href.startswith('//'):
                            href = 'https:' + href
                        if '1688.com' in href:
                            return href
            except Exception:
                continue

        return None

    async def _extract_title(self, item) -> Optional[str]:
        """タイトルを抽出"""
        title_selectors = [
            # pages-fast用
            'div[class*="titleWrap"]',
            'span[class*="offerTitle"]',
            'span[class*="OfferTitle"]',
            'div[class*="TitleWrap"] span',
            # 旧UI用
            'a.offer-title',
            'div.title',
            'h4.offer-title',
            'span.title-text',
            'a[title]',
        ]

        for selector in title_selectors:
            try:
                element = await item.query_selector(selector)
                if element:
                    title = await element.get_attribute('title')
                    if not title:
                        title = await element.inner_text()
                    if title and len(title.strip()) > 3:
                        return title.strip()
            except Exception:
                continue

        return None

    async def _extract_min_order(self, item) -> Optional[int]:
        """最小注文数を抽出"""
        # pages-fast: overseasTagInfoWrapに「最小発注 N」が含まれる
        try:
            tag_info = await item.query_selector('div[class*="overseasTagInfoWrap"]')
            if tag_info:
                text = await tag_info.inner_text()
                match = re.search(r'(\d+)', text)
                if match:
                    return int(match.group(1))
        except Exception:
            pass

        order_selectors = [
            'span[class*="moq"]',
            'span[class*="minOrder"]',
            'span.min-order',
            'div.moq',
        ]

        for selector in order_selectors:
            try:
                element = await item.query_selector(selector)
                if element:
                    text = await element.inner_text()
                    match = re.search(r'(\d+)', text)
                    if match:
                        return int(match.group(1))
            except Exception:
                continue

        return None
