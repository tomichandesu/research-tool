"""1688商品情報パースモジュール"""
from __future__ import annotations

import logging
import re
from typing import Optional

from playwright.async_api import Page

from ...utils.browser import BrowserManager, RetryStrategy
from ...models.product import AlibabaProduct

logger = logging.getLogger(__name__)


class AlibabaProductParser:
    """1688商品詳細ページから情報を取得する"""

    def __init__(self, browser: BrowserManager):
        self.browser = browser

    async def get_product_detail(
        self,
        product_url: str,
    ) -> Optional[AlibabaProduct]:
        """商品詳細を取得

        Args:
            product_url: 1688商品ページURL

        Returns:
            AlibabaProduct: 商品情報
        """
        async with self.browser.page_context() as page:
            try:
                return await RetryStrategy.with_retry(
                    self._fetch_product_detail,
                    page,
                    product_url,
                )
            except Exception as e:
                logger.error(f"商品詳細取得失敗: {product_url} - {e}")
                return None

    async def _fetch_product_detail(
        self,
        page: Page,
        product_url: str,
    ) -> Optional[AlibabaProduct]:
        """商品詳細ページをフェッチしてパースする"""
        logger.debug(f"1688商品詳細取得: {product_url}")

        await self.browser.navigate(page, product_url)

        # ページ読み込み待機
        await self.browser.wait_for_selector(
            page,
            'div.d-content, div.detail-content, div.mod-detail',
            timeout=15000,
        )

        # 各情報を取得
        price_cny = await self._get_price(page)
        image_url = await self._get_main_image(page)
        title = await self._get_title(page)
        shop_name = await self._get_shop_name(page)
        min_order = await self._get_min_order(page)

        if price_cny == 0:
            logger.warning(f"価格取得失敗: {product_url}")
            return None

        return AlibabaProduct(
            price_cny=price_cny,
            image_url=image_url,
            product_url=product_url,
            shop_name=shop_name,
            min_order=min_order,
            title=title,
        )

    async def _get_price(self, page: Page) -> float:
        """価格を取得"""
        selectors = [
            'span.price-text',
            'span.value',
            'em.value',
            'span.price',
            'div.price-area span',
            'span[class*="price"]',
        ]

        for selector in selectors:
            text = await self.browser.get_text(page, selector)
            if text:
                # 「¥12.50」「12.50-15.00」などから最小価格を抽出
                match = re.search(r'(\d+\.?\d*)', text.replace(',', ''))
                if match:
                    return float(match.group(1))

        return 0.0

    async def _get_main_image(self, page: Page) -> str:
        """メイン画像URLを取得"""
        selectors = [
            'img.detail-gallery-img',
            'img.vertical-img',
            'img.main-img',
            'div.detail-gallery img',
            'img[src*="cbu01.alicdn.com"]',
        ]

        for selector in selectors:
            url = await self.browser.get_attribute(page, selector, 'src')
            if url:
                if url.startswith('//'):
                    url = 'https:' + url
                return url

        return ""

    async def _get_title(self, page: Page) -> Optional[str]:
        """タイトルを取得"""
        selectors = [
            'h1.title-text',
            'div.title-text',
            'h1.d-title',
            'span.title-text',
            'title',
        ]

        for selector in selectors:
            text = await self.browser.get_text(page, selector)
            if text:
                return text.strip()

        return None

    async def _get_shop_name(self, page: Page) -> Optional[str]:
        """店舗名を取得"""
        selectors = [
            'a.company-name',
            'span.company-name',
            'div.seller-name a',
            'a[href*="winport"]',
        ]

        for selector in selectors:
            text = await self.browser.get_text(page, selector)
            if text:
                return text.strip()

        return None

    async def _get_min_order(self, page: Page) -> Optional[int]:
        """最小注文数を取得"""
        selectors = [
            'span.min-order',
            'span.moq-text',
            'div.moq span',
        ]

        for selector in selectors:
            text = await self.browser.get_text(page, selector)
            if text:
                match = re.search(r'(\d+)', text)
                if match:
                    return int(match.group(1))

        return None

    async def get_product_images(
        self,
        page: Page,
    ) -> list[str]:
        """商品画像一覧を取得"""
        images = []

        img_selectors = [
            'div.detail-gallery img',
            'ul.thumb-list img',
            'div.thumb-list img',
        ]

        for selector in img_selectors:
            elements = await page.query_selector_all(selector)
            for element in elements:
                url = await element.get_attribute('src')
                if not url:
                    url = await element.get_attribute('data-lazy-src')
                if url:
                    if url.startswith('//'):
                        url = 'https:' + url
                    if 'alicdn.com' in url:
                        images.append(url)

        return images

    async def get_price_tiers(
        self,
        page: Page,
    ) -> list[tuple[int, float]]:
        """価格帯情報を取得（数量別価格）

        Returns:
            [(数量, 価格), ...] のリスト
        """
        tiers = []

        tier_selectors = [
            'div.price-tier',
            'ul.price-list li',
            'div.sku-price-tier',
        ]

        for selector in tier_selectors:
            elements = await page.query_selector_all(selector)
            for element in elements:
                text = await element.inner_text()
                # 「1-99件 ¥15.00」「100件以上 ¥12.00」などをパース
                qty_match = re.search(r'(\d+)', text)
                price_match = re.search(r'¥?(\d+\.?\d*)', text)
                if qty_match and price_match:
                    qty = int(qty_match.group(1))
                    price = float(price_match.group(1))
                    tiers.append((qty, price))

        return tiers
