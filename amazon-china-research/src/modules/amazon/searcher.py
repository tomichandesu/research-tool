"""Amazon検索モジュール"""
from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import quote_plus

from playwright.async_api import Page

from ...utils.browser import BrowserManager, RetryStrategy

logger = logging.getLogger(__name__)


class AmazonSearcher:
    """Amazon.co.jpでキーワード検索を実行する

    Attributes:
        browser: BrowserManagerインスタンス
        base_url: Amazon.co.jpのベースURL
    """

    BASE_URL = "https://www.amazon.co.jp"
    SEARCH_URL = "https://www.amazon.co.jp/s?k={keyword}&page={page}"

    def __init__(self, browser: BrowserManager, organic_only: bool = False):
        self.browser = browser
        self.organic_only = organic_only

    async def search(
        self,
        keyword: str,
        max_pages: int = 3,
    ) -> list[dict]:
        """キーワードで商品を検索

        Args:
            keyword: 検索キーワード
            max_pages: 取得するページ数

        Returns:
            商品リスト（ASIN, タイトル, 価格, 画像URL）
        """
        products = []

        async with self.browser.page_context() as page:
            for page_num in range(1, max_pages + 1):
                logger.info(f"検索中: '{keyword}' - ページ {page_num}/{max_pages}")

                page_products = await RetryStrategy.with_retry(
                    self._search_page,
                    page,
                    keyword,
                    page_num,
                )

                if not page_products:
                    logger.info(f"ページ {page_num} で商品が見つかりませんでした")
                    break

                products.extend(page_products)
                logger.info(f"ページ {page_num}: {len(page_products)}件取得")

        logger.info(f"検索完了: 合計 {len(products)}件")
        return products

    async def _search_page(
        self,
        page: Page,
        keyword: str,
        page_num: int,
    ) -> list[dict]:
        """検索結果の1ページを取得"""
        url = self.SEARCH_URL.format(
            keyword=quote_plus(keyword),
            page=page_num,
        )

        await self.browser.navigate(page, url)

        # 検索結果の読み込みを待機
        await self.browser.wait_for_selector(
            page,
            'div[data-component-type="s-search-result"]',
            timeout=15000,
        )

        # スクロールして遅延読み込みを実行
        await self.browser.scroll_to_bottom(page)

        # 商品アイテムを取得
        items = await page.query_selector_all(
            'div[data-component-type="s-search-result"]'
        )

        products = []
        sponsored_count = 0
        for item in items:
            product = await self._parse_search_item(item)
            if product:
                if product.pop("_is_sponsored", False) and self.organic_only:
                    sponsored_count += 1
                    continue
                products.append(product)

        if self.organic_only and sponsored_count > 0:
            logger.info(f"スポンサー広告 {sponsored_count}件を除外")

        return products

    async def _is_sponsored(self, item) -> bool:
        """スポンサー広告かどうかを判定する"""
        try:
            sponsor_elem = await item.query_selector(
                "span.puis-label-popover-default"
            )
            return sponsor_elem is not None
        except Exception:
            return False

    async def _parse_search_item(self, item) -> Optional[dict]:
        """検索結果アイテムをパースする"""
        try:
            # ASIN取得
            asin = await item.get_attribute("data-asin")
            if not asin:
                return None

            # タイトル取得
            title_elem = await item.query_selector(
                'h2 a span, h2 span.a-text-normal'
            )
            title = await title_elem.inner_text() if title_elem else ""

            # 価格取得
            price = await self._extract_price(item)

            # 画像URL取得
            img_elem = await item.query_selector('img.s-image')
            image_url = await img_elem.get_attribute("src") if img_elem else ""

            # 商品URL取得
            link_elem = await item.query_selector('h2 a')
            product_url = ""
            if link_elem:
                href = await link_elem.get_attribute("href")
                if href:
                    product_url = f"{self.BASE_URL}{href}" if href.startswith("/") else href

            # レビュー数（概算）
            review_count = await self._extract_review_count(item)

            # 評価
            rating = await self._extract_rating(item)

            # スポンサー広告判定
            is_sponsored = await self._is_sponsored(item)

            return {
                "asin": asin,
                "title": title.strip() if title else "",
                "price": price,
                "image_url": image_url,
                "product_url": product_url,
                "review_count": review_count,
                "rating": rating,
                "_is_sponsored": is_sponsored,
            }

        except Exception as e:
            logger.debug(f"商品パース失敗: {e}")
            return None

    async def _extract_price(self, item) -> int:
        """価格を抽出する"""
        try:
            # 通常価格
            price_elem = await item.query_selector(
                'span.a-price span.a-offscreen, '
                'span.a-price-whole'
            )
            if price_elem:
                price_text = await price_elem.inner_text()
                # 「￥1,234」から数値を抽出
                price_match = re.search(r'[\d,]+', price_text.replace(',', ''))
                if price_match:
                    return int(price_match.group().replace(',', ''))
        except Exception as e:
            logger.debug(f"価格抽出失敗: {e}")

        return 0

    async def _extract_review_count(self, item) -> int:
        """レビュー数を抽出する"""
        try:
            # レビュー数のリンク
            review_elem = await item.query_selector(
                'a[href*="customerReviews"] span, '
                'span[aria-label*="レビュー"]'
            )
            if review_elem:
                review_text = await review_elem.inner_text()
                # 「1,234」から数値を抽出
                review_match = re.search(r'[\d,]+', review_text)
                if review_match:
                    return int(review_match.group().replace(',', ''))
        except Exception as e:
            logger.debug(f"レビュー数抽出失敗: {e}")

        return 0

    async def _extract_rating(self, item) -> Optional[float]:
        """評価を抽出する"""
        try:
            # 評価のaria-label
            rating_elem = await item.query_selector(
                'i[class*="a-star"] span.a-icon-alt, '
                'span[aria-label*="5つ星"]'
            )
            if rating_elem:
                rating_text = await rating_elem.get_attribute("aria-label")
                if not rating_text:
                    rating_text = await rating_elem.inner_text()
                # 「5つ星のうち4.5」から数値を抽出
                rating_match = re.search(r'(\d+\.?\d*)', rating_text)
                if rating_match:
                    return float(rating_match.group(1))
        except Exception as e:
            logger.debug(f"評価抽出失敗: {e}")

        return None
