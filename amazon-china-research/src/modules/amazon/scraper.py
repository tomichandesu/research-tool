"""Amazon商品詳細取得モジュール"""
from __future__ import annotations

import logging
import re
from typing import Optional

from playwright.async_api import Page

from ...models.product import ProductDetail
from ...utils.browser import BrowserManager, RetryStrategy
from ...config import get_config

logger = logging.getLogger(__name__)


class AmazonScraper:
    """商品詳細ページから情報を取得する"""

    BASE_URL = "https://www.amazon.co.jp"
    PRODUCT_URL = "https://www.amazon.co.jp/dp/{asin}"

    def __init__(self, browser: BrowserManager, use_fba_simulator: bool = False):
        """
        Args:
            browser: ブラウザマネージャー
            use_fba_simulator: 未使用（後方互換のため残す）
        """
        self.browser = browser

    async def get_product_detail(self, asin: str) -> Optional[ProductDetail]:
        """商品詳細を取得

        Args:
            asin: Amazon商品ID

        Returns:
            ProductDetail: BSR, レビュー数, FBA/FBM等を含む
        """
        async with self.browser.page_context() as page:
            return await RetryStrategy.with_retry(
                self._fetch_product_detail,
                page,
                asin,
            )

    async def get_product_details_batch(
        self,
        asins: list[str],
        progress_callback: Optional[callable] = None,
    ) -> list[ProductDetail]:
        """複数商品の詳細を一括取得

        Args:
            asins: ASINリスト
            progress_callback: 進捗コールバック関数

        Returns:
            ProductDetailリスト
        """
        products = []
        total = len(asins)

        async with self.browser.page_context() as page:
            for i, asin in enumerate(asins):
                try:
                    product = await RetryStrategy.with_retry(
                        self._fetch_product_detail,
                        page,
                        asin,
                    )
                    if product:
                        products.append(product)

                    if progress_callback:
                        progress_callback(i + 1, total, asin)

                except Exception as e:
                    logger.warning(f"商品詳細取得失敗: {asin} - {e}")

        return products

    async def _fetch_product_detail(
        self,
        page: Page,
        asin: str,
    ) -> Optional[ProductDetail]:
        """商品詳細ページをフェッチしてパースする"""
        url = self.PRODUCT_URL.format(asin=asin)
        logger.debug(f"商品詳細取得: {asin}")

        await self.browser.navigate(page, url)

        # 商品タイトルの読み込みを待機
        await self.browser.wait_for_selector(
            page,
            '#productTitle, #title',
            timeout=10000,
        )

        # 日本製チェック（タイトル・特徴・説明文を早期確認）
        if await self._is_made_in_japan(page):
            logger.info(f"日本製のためスキップ: {asin}")
            return None

        # 各情報を取得
        title = await self._get_title(page)
        price = await self._get_price(page)
        image_url = await self._get_image_url(page)
        bsr, category = await self._get_bsr_and_category(page)
        review_count = await self._get_review_count(page)
        rating = await self._get_rating(page)

        # 出荷元・販売元を一度だけ取得（冗長なDOM問い合わせを回避）
        shipped_by, sold_by = await self._get_fulfillment_info(page)
        logger.debug(f"出荷元: {shipped_by}, 販売元: {sold_by}")

        # Amazon直販判定（出荷元・販売元ともにAmazon）
        is_amazon_direct = (
            self._is_amazon_entity(shipped_by)
            and self._is_amazon_entity(sold_by)
        )

        # FBA判定（出荷元がAmazon、販売元が第三者）
        is_fba = await self._determine_is_fba(
            shipped_by, sold_by, page
        )

        # 販売元名
        seller_name = sold_by or await self._get_seller_name_fallback(page)

        variation_count = await self._get_variation_count(page)
        dimensions = await self._get_dimensions(page)
        weight_kg = await self._get_weight(page)

        # サイズが取得できない場合、デフォルト値を使用
        if dimensions is None or weight_kg is None:
            config = get_config()
            if dimensions is None:
                d = config.profit.default_dimensions
                dimensions = (d.length, d.width, d.height)
                logger.debug(f"デフォルト寸法を使用: {dimensions}")
            if weight_kg is None:
                weight_kg = config.profit.default_weight
                logger.debug(f"デフォルト重量を使用: {weight_kg}kg")

        if not title:
            logger.warning(f"タイトル取得失敗: {asin}")
            return None

        return ProductDetail(
            asin=asin,
            title=title,
            price=price,
            image_url=image_url,
            bsr=bsr,
            category=category,
            review_count=review_count,
            is_fba=is_fba,
            is_amazon_direct=is_amazon_direct,
            product_url=url,
            rating=rating,
            seller_name=seller_name,
            variation_count=variation_count,
            dimensions=dimensions,
            weight_kg=weight_kg,
        )

    async def _get_title(self, page: Page) -> str:
        """商品タイトルを取得"""
        selectors = ['#productTitle', '#title', 'h1.product-title-word-break']
        for selector in selectors:
            text = await self.browser.get_text(page, selector)
            if text:
                return text.strip()
        return ""

    async def _get_price(self, page: Page) -> int:
        """価格を取得"""
        selectors = [
            '#corePrice_feature_div span.a-price span.a-offscreen',
            '#priceblock_ourprice',
            '#priceblock_dealprice',
            '#priceblock_saleprice',
            'span.a-price span.a-offscreen',
            '#price_inside_buybox',
        ]

        for selector in selectors:
            text = await self.browser.get_text(page, selector)
            if text:
                # 「￥1,234」から数値を抽出
                match = re.search(r'[\d,]+', text.replace(',', ''))
                if match:
                    return int(match.group().replace(',', ''))

        return 0

    async def _get_image_url(self, page: Page) -> str:
        """メイン画像URLを取得"""
        selectors = [
            '#landingImage',
            '#imgBlkFront',
            '#main-image',
            'img[data-a-dynamic-image]',
        ]

        for selector in selectors:
            url = await self.browser.get_attribute(page, selector, "src")
            if url:
                return url

            # data-a-dynamic-image から高解像度画像を取得
            dynamic = await self.browser.get_attribute(
                page, selector, "data-a-dynamic-image"
            )
            if dynamic:
                # JSON形式 {"url1": [...], "url2": [...]}
                match = re.search(r'"(https://[^"]+)"', dynamic)
                if match:
                    return match.group(1)

        return ""

    async def _get_bsr_and_category(self, page: Page) -> tuple[int, str]:
        """BSR（大カテゴリー）とカテゴリー名を取得

        Amazonの形式（2025年現在）:
            Amazon 売れ筋ランキング
            おもちゃ - 9,034位 (おもちゃの売れ筋ランキングを見る)
            貯金箱 (おもちゃ) - 64位
        → 最初の「カテゴリ - N位」が大カテゴリBSR
        """
        bsr = 0
        category = ""

        bsr_selectors = [
            '#productDetails_detailBullets_sections1',
            '#productDetails_db_sections',
            '#detailBulletsWrapper_feature_div',
            '#prodDetails',
        ]

        for selector in bsr_selectors:
            content = await self.browser.get_text(page, selector)
            if not content or '売れ筋ランキング' not in content:
                continue

            # パターン1（2025現在）: 「カテゴリ名 - 9,034位」
            # 大カテゴリ（最初に出てくる「XX - N位」）を取得
            cat_rank_match = re.search(
                r'売れ筋ランキング.*?([^\n\t]+?)\s*-\s*([\d,]+)位',
                content,
                re.DOTALL,
            )
            if cat_rank_match:
                category = cat_rank_match.group(1).strip()
                bsr = int(cat_rank_match.group(2).replace(',', ''))
                # カテゴリ名の先頭の不要文字を除去
                category = re.sub(r'^[\s\n\t]+', '', category)
                logger.debug(f"BSR取得(パターン1): {bsr}位 / {category}")
                break

            # パターン2（旧形式）: 「売れ筋ランキング: 5,234位」
            rank_match = re.search(
                r'売れ筋ランキング[：:]\s*([\d,]+)位',
                content,
            )
            if rank_match:
                bsr = int(rank_match.group(1).replace(',', ''))
                # カテゴリを別途取得
                cat_match = re.search(
                    r'売れ筋ランキング[：:]\s*[\d,]+位\s*[\(（]([^）\)]+)',
                    content,
                )
                if cat_match:
                    category = cat_match.group(1).strip()
                logger.debug(f"BSR取得(パターン2): {bsr}位 / {category}")
                break

        return bsr, category

    async def _get_review_count(self, page: Page) -> int:
        """レビュー数を取得"""
        selectors = [
            '#acrCustomerReviewText',
            '#acrCustomerReviewLink',
            'span[data-hook="total-review-count"]',
        ]

        for selector in selectors:
            text = await self.browser.get_text(page, selector)
            if text:
                match = re.search(r'[\d,]+', text)
                if match:
                    return int(match.group().replace(',', ''))

        return 0

    async def _get_rating(self, page: Page) -> Optional[float]:
        """評価を取得
        Amazonの形式: 「5つ星のうち4.1」
        「のうち」の後の数値を抽出する。なければ最後の数値を使用。
        """
        selectors = [
            '#acrPopover',
            'span[data-hook="rating-out-of-text"]',
            'i.a-icon-star span.a-icon-alt',
        ]

        for selector in selectors:
            text = await self.browser.get_attribute(page, selector, "title")
            if not text:
                text = await self.browser.get_text(page, selector)
            if text:
                # パターン1: 「5つ星のうち4.1」→「4.1」を抽出
                match = re.search(r'のうち(\d+\.?\d*)', text)
                if match:
                    return float(match.group(1))
                # パターン2: 「4.1 out of 5」（英語版）
                match = re.search(r'(\d+\.?\d*)\s*out\s*of', text)
                if match:
                    return float(match.group(1))
                # パターン3: フォールバック - 最後の数値を使用
                matches = re.findall(r'(\d+\.\d+)', text)
                if matches:
                    return float(matches[-1])

        return None

    async def _determine_is_fba(
        self,
        shipped_by: Optional[str],
        sold_by: Optional[str],
        page: Page,
    ) -> bool:
        """FBA出品かどうかを判定

        FBA = 出荷元がAmazon、販売元が第三者セラー
        注意: Amazon直販（出荷元・販売元ともにAmazon）はFBAではない
        """
        shipped_by_amazon = self._is_amazon_entity(shipped_by)
        sold_by_amazon = self._is_amazon_entity(sold_by)

        # 出荷元がAmazon かつ 販売元が第三者セラー → FBA
        if shipped_by_amazon and not sold_by_amazon:
            return True

        # 出荷元・販売元の両方が取得できない場合、プライムバッジで判定
        if not shipped_by and not sold_by:
            prime_badge = await page.query_selector(
                'i.a-icon-prime, span.a-icon-prime, #prime-badge'
            )
            if prime_badge:
                return True

        return False

    async def _get_fulfillment_info(
        self, page: Page
    ) -> tuple[Optional[str], Optional[str]]:
        """出荷元と販売元を取得

        複数のページレイアウトに対応:
        1. tabular-buybox: 出荷元/販売元が別々の行
        2. offer-display-feature: 「出荷元 / 販売元」が一括表示
        3. fulfillerInfo / merchant-info: 個別フォールバック

        Returns:
            (shipped_by, sold_by) のタプル
        """
        shipped_by = None
        sold_by = None

        try:
            # パターン1: tabular-buybox形式（出荷元と販売元が別々の行）
            buybox = await self.browser.get_text(
                page, '#tabular-buybox'
            )
            if buybox:
                lines = [l.strip() for l in buybox.split('\n') if l.strip()]
                for i, line in enumerate(lines):
                    if '出荷元' in line and i + 1 < len(lines):
                        shipped_by = lines[i + 1]
                    if '販売元' in line and i + 1 < len(lines):
                        sold_by = lines[i + 1]
                if shipped_by or sold_by:
                    return (shipped_by, sold_by)

            # パターン2: offer-display-feature形式
            # 「出荷元 / 販売元  Amazon.co.jp」のように一括表示されるケース
            offer_label = await self.browser.get_text(
                page, 'div.offer-display-feature-label'
            )
            if offer_label and '出荷元' in offer_label and '販売元' in offer_label:
                offer_value = await self.browser.get_text(
                    page, 'div.offer-display-feature-text'
                )
                if offer_value:
                    value = offer_value.strip()
                    return (value, value)

            # パターン3: fulfillerInfo形式（出荷元のみ）
            fulfiller = await self.browser.get_text(
                page, '#fulfillerInfoFeature_feature_div'
            )
            if fulfiller and 'amazon' in fulfiller.lower():
                shipped_by = 'Amazon.co.jp'

            # パターン4: merchant-info形式（販売元のみ）
            merchant = await self.browser.get_text(
                page, '#merchant-info'
            )
            if merchant:
                sold_by = merchant.strip()

            return (shipped_by, sold_by)
        except Exception:
            return (None, None)

    def _is_amazon_entity(self, name: Optional[str]) -> bool:
        """Amazon自身の出品/出荷かどうかを判定"""
        if not name:
            return False
        name_lower = name.lower().strip()
        return any(kw in name_lower for kw in [
            'amazon.co.jp', 'amazon', 'アマゾン',
        ])

    async def _get_seller_name_fallback(self, page: Page) -> Optional[str]:
        """出品者名を追加セレクタから取得（sold_byが取得できなかった場合のフォールバック）"""
        selectors = [
            '#sellerProfileTriggerId',
            '#merchant-info a',
            '#tabular-buybox-truncate-1',
        ]

        for selector in selectors:
            text = await self.browser.get_text(page, selector)
            if text:
                return text.strip()

        return None

    async def _get_variation_count(self, page: Page) -> int:
        """バリエーション数を取得

        色、サイズ、スタイルなどのバリエーション選択肢の数をカウント。
        バリエーションがない場合は1を返す。
        """
        variation_count = 0

        # バリエーションセレクタ（色・サイズ等の選択肢のみ）
        # 注意: #altImages は商品画像サムネイルなのでバリエーションではない
        variation_selectors = [
            # ドロップダウン型バリエーション
            '#variation_color_name option',
            '#variation_size_name option',
            '#variation_style_name option',
            '#variation_pattern_name option',
            'select[name*="variation"] option',
            # ボタン型バリエーション（色・サイズ選択ボタン）
            '#variation_color_name li.swatchAvailable',
            '#variation_size_name li.swatchAvailable',
            '#variation_style_name li.swatchAvailable',
            'ul.a-unordered-list.swatches li.swatchAvailable',
            # イメージ型バリエーション（色違い選択画像）
            '#variation_color_name img',
            # 新UIのバリエーション
            '#twister-plus-inline-twister-card li',
            'div[id*="variation"] ul li[data-dp-url]',
        ]

        # 各セレクタでバリエーションを検索
        for selector in variation_selectors:
            try:
                elements = await page.query_selector_all(selector)
                if elements and len(elements) > 0:
                    # option要素の場合、最初の「選択してください」を除外
                    if 'option' in selector:
                        count = len([e for e in elements if e])
                        # 「選択してください」を除外
                        if count > 1:
                            count -= 1
                        variation_count = max(variation_count, count)
                    else:
                        variation_count = max(variation_count, len(elements))
            except Exception:
                continue

        # バリエーションが見つからない場合は1
        if variation_count == 0:
            variation_count = 1

        logger.debug(f"バリエーション数: {variation_count}")
        return variation_count

    async def _get_dimensions(self, page: Page) -> Optional[tuple[float, float, float]]:
        """商品寸法を取得 (長さ, 幅, 高さ) cm

        Amazonの商品詳細ページから寸法情報を抽出する。
        """
        # 商品詳細テーブルから寸法を取得
        detail_selectors = [
            '#detailBulletsWrapper_feature_div',
            '#productDetails_detailBullets_sections1',
            '#productDetails_db_sections',
            '#productDetails_techSpec_section_1',
            '#prodDetails',
        ]

        for selector in detail_selectors:
            content = await self.browser.get_text(page, selector)
            if content:
                # パターン1: 「商品サイズ: 30 x 20 x 10 cm」
                match = re.search(
                    r'(?:商品サイズ|梱包サイズ|寸法|サイズ)[：:\s]*'
                    r'(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*cm',
                    content,
                    re.IGNORECASE
                )
                if match:
                    dims = (
                        float(match.group(1)),
                        float(match.group(2)),
                        float(match.group(3)),
                    )
                    logger.debug(f"寸法取得: {dims} cm")
                    return dims

                # パターン2: 「30 x 20 x 10 センチメートル」
                match = re.search(
                    r'(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*'
                    r'(?:センチメートル|センチ|cm)',
                    content,
                    re.IGNORECASE
                )
                if match:
                    dims = (
                        float(match.group(1)),
                        float(match.group(2)),
                        float(match.group(3)),
                    )
                    logger.debug(f"寸法取得: {dims} cm")
                    return dims

        return None

    async def _get_weight(self, page: Page) -> Optional[float]:
        """商品重量を取得 (kg)

        Amazonの商品詳細ページから重量情報を抽出する。
        """
        # 商品詳細テーブルから重量を取得
        detail_selectors = [
            '#detailBulletsWrapper_feature_div',
            '#productDetails_detailBullets_sections1',
            '#productDetails_db_sections',
            '#productDetails_techSpec_section_1',
            '#prodDetails',
        ]

        for selector in detail_selectors:
            content = await self.browser.get_text(page, selector)
            if content:
                # パターン1: 「商品の重量: 1.5 kg」
                match = re.search(
                    r'(?:商品の重量|重量|発送重量)[：:\s]*(\d+(?:\.\d+)?)\s*kg',
                    content,
                    re.IGNORECASE
                )
                if match:
                    weight = float(match.group(1))
                    logger.debug(f"重量取得: {weight} kg")
                    return weight

                # パターン2: 「500 g」をkgに変換
                match = re.search(
                    r'(?:商品の重量|重量|発送重量)[：:\s]*(\d+(?:\.\d+)?)\s*g(?:ram)?',
                    content,
                    re.IGNORECASE
                )
                if match:
                    weight = float(match.group(1)) / 1000  # gをkgに変換
                    logger.debug(f"重量取得: {weight} kg (from grams)")
                    return weight

                # パターン3: 「1.5 キログラム」
                match = re.search(
                    r'(\d+(?:\.\d+)?)\s*キログラム',
                    content,
                )
                if match:
                    weight = float(match.group(1))
                    logger.debug(f"重量取得: {weight} kg")
                    return weight

                # パターン4: 「500 グラム」
                match = re.search(
                    r'(\d+(?:\.\d+)?)\s*グラム',
                    content,
                )
                if match:
                    weight = float(match.group(1)) / 1000
                    logger.debug(f"重量取得: {weight} kg (from grams)")
                    return weight

        return None

    async def _is_made_in_japan(self, page: Page) -> bool:
        """商品ページに「日本製」の表記があるかチェック

        タイトル、箇条書き特徴、商品説明、詳細テーブルを確認する。
        """
        made_in_japan_keywords = [
            "日本製",
            "MADE IN JAPAN",
            "Made in Japan",
            "国産",
            "日本産",
            "日本国内生産",
            "日本国内製造",
        ]

        # チェック対象エリア（軽量な順）
        check_selectors = [
            '#productTitle',                          # タイトル
            '#feature-bullets',                       # 箇条書き特徴
            '#productDescription',                    # 商品説明
            '#detailBulletsWrapper_feature_div',       # 詳細情報
            '#productDetails_detailBullets_sections1', # 詳細テーブル
            '#aplus',                                 # A+コンテンツ
        ]

        for selector in check_selectors:
            text = await self.browser.get_text(page, selector)
            if text:
                for keyword in made_in_japan_keywords:
                    if keyword.lower() in text.lower():
                        logger.debug(f"日本製検出: {selector} に '{keyword}'")
                        return True

        return False
