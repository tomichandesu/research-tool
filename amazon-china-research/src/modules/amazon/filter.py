"""商品フィルタリングモジュール"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from ...models.product import ProductDetail
from ...config import FilterConfig, get_config
from ..calculator.sales_estimator import SalesEstimator

logger = logging.getLogger(__name__)


@dataclass
class FilterResult:
    """フィルタリング結果

    Attributes:
        passed: フィルタを通過したかどうか
        reason: 不通過の理由
        estimated_monthly_sales: 推定月間販売数
        estimated_monthly_revenue: 推定月間売上
    """
    passed: bool
    reason: Optional[str] = None
    estimated_monthly_sales: int = 0
    estimated_monthly_revenue: int = 0


class ProductFilter:
    """商品フィルタリングを行う

    フィルタ条件:
    - 価格 >= min_price (デフォルト: 1,500円)
    - 価格 <= max_price (デフォルト: 4,000円)
    - レビュー数 <= max_reviews (デフォルト: 50件)
    - BSR >= min_bsr (デフォルト: 5,000)
    - BSR <= max_bsr (デフォルト: 50,000)
    - バリエーション数 <= max_variations (デフォルト: 5個)
    - FBA: 月売上 >= fba_min_monthly_sales (デフォルト: 20,000円)
    - FBM: 月販売数 >= fbm_min_monthly_units (デフォルト: 3個)
    """

    def __init__(
        self,
        config: Optional[FilterConfig] = None,
        sales_estimator: Optional[SalesEstimator] = None,
    ):
        if config is None:
            config = get_config().filter
        self.config = config
        self.sales_estimator = sales_estimator or SalesEstimator()

    @property
    def min_price(self) -> int:
        return self.config.min_price

    @property
    def max_price(self) -> int:
        return self.config.max_price

    @property
    def max_reviews(self) -> int:
        return self.config.max_reviews

    @property
    def max_rating(self) -> float:
        return self.config.max_rating

    @property
    def min_bsr(self) -> int:
        return self.config.min_bsr

    @property
    def max_bsr(self) -> int:
        return self.config.max_bsr

    @property
    def max_variations(self) -> int:
        return self.config.max_variations

    @property
    def fba_min_monthly_sales(self) -> int:
        return self.config.fba_min_monthly_sales

    @property
    def fbm_min_monthly_units(self) -> int:
        return self.config.fbm_min_monthly_units

    @property
    def excluded_categories(self) -> list[str]:
        return self.config.excluded_categories

    @property
    def prohibited_keywords(self) -> list[str]:
        return self.config.prohibited_keywords

    def filter(self, products: list[ProductDetail]) -> list[ProductDetail]:
        """条件に合う商品のみを抽出

        Args:
            products: フィルタリング対象の商品リスト

        Returns:
            フィルタを通過した商品リスト
        """
        filtered = []

        for product in products:
            result = self.check(product)
            if result.passed:
                filtered.append(product)
            else:
                logger.debug(
                    f"フィルタ不通過: {product.asin} - {result.reason}"
                )

        logger.info(
            f"フィルタ結果: {len(filtered)}/{len(products)}件通過"
        )

        return filtered

    def check(self, product: ProductDetail) -> FilterResult:
        """1商品をチェック

        Args:
            product: チェック対象の商品

        Returns:
            FilterResult: チェック結果
        """
        # 0. Amazon直販除外（出荷元・販売元ともにAmazon）
        if product.is_amazon_direct:
            return FilterResult(
                passed=False,
                reason="Amazon直販（出荷元・販売元ともにAmazon）",
            )

        # 1. 除外カテゴリフィルタ（最初にチェック）
        category_result = self.check_category(product)
        if not category_result[0]:
            return FilterResult(
                passed=False,
                reason=f"除外カテゴリ: {category_result[1]}",
            )

        # 2. 禁止キーワードフィルタ
        keyword_result = self.check_prohibited_keywords(product)
        if not keyword_result[0]:
            return FilterResult(
                passed=False,
                reason=f"禁止キーワード: {keyword_result[1]}",
            )

        # 3. 最低価格フィルタ
        if not self.check_min_price(product):
            return FilterResult(
                passed=False,
                reason=f"価格 {product.price}円 < {self.min_price}円",
            )

        # 4. 最高価格フィルタ
        if not self.check_max_price(product):
            return FilterResult(
                passed=False,
                reason=f"価格 {product.price}円 > {self.max_price}円",
            )

        # 5. レビュー数フィルタ
        if not self.check_reviews(product):
            return FilterResult(
                passed=False,
                reason=f"レビュー数 {product.review_count}件 > {self.max_reviews}件",
            )

        # 6. 評価フィルタ（★5.0のみ除外）
        if not self.check_rating(product):
            return FilterResult(
                passed=False,
                reason=f"評価 {product.rating} > {self.max_rating}",
            )

        # 6b. BSR下限フィルタ（売れすぎている商品を除外）
        if not self.check_min_bsr(product):
            return FilterResult(
                passed=False,
                reason=f"BSR {product.bsr:,} < {self.min_bsr:,}（売れすぎ）",
            )

        # 7. BSRフィルタ（カテゴリ別・FBA/FBM別）
        if not self.check_bsr(product):
            bsr_threshold = self._get_bsr_threshold(product)
            cat_key = self._normalize_category(product.category)
            fulfillment = "FBA" if product.is_fba else "FBM"
            return FilterResult(
                passed=False,
                reason=f"BSR {product.bsr:,} > {bsr_threshold:,}（{cat_key}/{fulfillment}）",
            )

        # 8. バリエーション数フィルタ
        if not self.check_variations(product):
            return FilterResult(
                passed=False,
                reason=f"バリエーション数 {product.variation_count} > {self.max_variations}",
            )

        # 9. 大型サイズフィルタ
        if not self.check_size(product):
            return FilterResult(
                passed=False,
                reason=self._get_large_size_reason(product),
            )

        # 10. BSR有効性チェック（BSRが取得できていること）
        if product.bsr == 0:
            return FilterResult(
                passed=False,
                reason="BSR未取得",
            )

        # 全フィルタ通過
        # 推定販売数を計算して返す（参考情報として）
        estimated_sales = self.sales_estimator.estimate(
            bsr=product.bsr,
            category=self._normalize_category(product.category),
        )
        estimated_revenue = estimated_sales * product.price

        return FilterResult(
            passed=True,
            estimated_monthly_sales=estimated_sales,
            estimated_monthly_revenue=estimated_revenue,
        )

    def check_min_price(self, product: ProductDetail) -> bool:
        """最低価格フィルタ

        Args:
            product: チェック対象の商品

        Returns:
            True: 価格 >= min_price
        """
        return product.price >= self.min_price

    def check_max_price(self, product: ProductDetail) -> bool:
        """最高価格フィルタ

        Args:
            product: チェック対象の商品

        Returns:
            True: 価格 <= max_price
        """
        return product.price <= self.max_price

    def check_reviews(self, product: ProductDetail) -> bool:
        """レビュー数フィルタ

        Args:
            product: チェック対象の商品

        Returns:
            True: レビュー数 <= max_reviews
        """
        return product.review_count <= self.max_reviews

    def check_rating(self, product: ProductDetail) -> bool:
        """評価フィルタ（★5.0のみ除外）

        Args:
            product: チェック対象の商品

        Returns:
            True: 評価 <= max_rating または rating未取得
        """
        if product.rating is None:
            return True
        return product.rating <= self.max_rating

    def check_min_bsr(self, product: ProductDetail) -> bool:
        """BSR下限フィルタ（売れすぎている商品を除外）

        Args:
            product: チェック対象の商品

        Returns:
            True: BSR >= min_bsr または BSR未取得
        """
        if product.bsr == 0:
            return True  # BSR未取得は一旦通す
        return product.bsr >= self.min_bsr

    def check_bsr(self, product: ProductDetail) -> bool:
        """BSRフィルタ（カテゴリ別・FBA/FBM別閾値）

        Args:
            product: チェック対象の商品

        Returns:
            True: BSR <= カテゴリ別閾値 または BSR未取得
        """
        if product.bsr == 0:
            return True  # BSR未取得は一旦通す（sales checkで弾く）
        max_bsr = self._get_bsr_threshold(product)
        return product.bsr <= max_bsr

    def _get_bsr_threshold(self, product: ProductDetail) -> int:
        """商品のカテゴリとFBA/FBMからBSR閾値を取得"""
        cat_key = self._normalize_category(product.category)
        thresholds = self.config.category_bsr_thresholds.get(
            cat_key, self.config.category_bsr_thresholds.get("default", {})
        )
        return thresholds.get("fba" if product.is_fba else "fbm", self.max_bsr)

    def check_variations(self, product: ProductDetail) -> bool:
        """バリエーション数フィルタ

        Args:
            product: チェック対象の商品

        Returns:
            True: バリエーション数 <= max_variations
        """
        return product.variation_count <= self.max_variations

    def check_size(self, product: ProductDetail) -> bool:
        """大型サイズフィルタ

        Amazon大型基準（以下のいずれかに該当するとNG）:
        - 寸法合計（縦+横+高さ）> 100cm
        - 重量 > 9kg

        Args:
            product: チェック対象の商品

        Returns:
            True: 標準サイズ以下（大型ではない）
            False: 大型サイズ（フィルタNG）
        """
        # is_large_size が True なら NG (return False)
        return not product.is_large_size

    def _get_large_size_reason(self, product: ProductDetail) -> str:
        """大型サイズの詳細理由を取得"""
        reasons = []
        if product.dimensions is not None:
            dims_sum = sum(product.dimensions)
            if dims_sum > 100:
                reasons.append(f"寸法合計 {dims_sum:.1f}cm > 100cm")
        if product.weight_kg is not None:
            if product.weight_kg > 9.0:
                reasons.append(f"重量 {product.weight_kg:.1f}kg > 9kg")
        return "大型サイズ: " + ", ".join(reasons) if reasons else "大型サイズ"

    def check_category(self, product: ProductDetail) -> tuple[bool, str]:
        """除外カテゴリフィルタ

        ファッション、ビューティー、飲食系、ベビー・おもちゃなど
        輸入規制や取り扱い困難なカテゴリを除外する。

        Args:
            product: チェック対象の商品

        Returns:
            (True, "") : 対象カテゴリ（フィルタ通過）
            (False, マッチしたカテゴリ): 除外カテゴリ（フィルタNG）
        """
        if not self.excluded_categories:
            return (True, "")

        category = product.category.lower() if product.category else ""

        for excluded in self.excluded_categories:
            if excluded.lower() in category:
                logger.debug(f"除外カテゴリ検出: {product.asin} - {excluded}")
                return (False, excluded)

        return (True, "")

    def check_prohibited_keywords(self, product: ProductDetail) -> tuple[bool, str]:
        """禁止キーワードフィルタ

        商品タイトルに以下のキーワードが含まれる場合は除外:
        - ファッション・アクセサリー関連
        - 飲食・サプリ関連
        - 食品衛生法対象（口に触れるもの）
        - PSE対象（電気用品）
        - その他規制対象

        Args:
            product: チェック対象の商品

        Returns:
            (True, ""): 禁止キーワードなし（フィルタ通過）
            (False, マッチしたキーワード): 禁止キーワードあり（フィルタNG）
        """
        if not self.prohibited_keywords:
            return (True, "")

        title = product.title.lower() if product.title else ""

        for keyword in self.prohibited_keywords:
            if keyword.lower() in title:
                logger.debug(f"禁止キーワード検出: {product.asin} - {keyword}")
                return (False, keyword)

        return (True, "")

    def check_sales(self, product: ProductDetail) -> FilterResult:
        """販売数フィルタ（FBA/FBM別）

        Args:
            product: チェック対象の商品

        Returns:
            FilterResult: チェック結果（推定販売数を含む）
        """
        # BSRが取得できない場合はスキップ
        if product.bsr == 0:
            return FilterResult(
                passed=False,
                reason="BSR未取得",
            )

        # 月間販売数を推定
        estimated_sales = self.sales_estimator.estimate(
            bsr=product.bsr,
            category=self._normalize_category(product.category),
        )

        # 月間売上を計算
        estimated_revenue = estimated_sales * product.price

        if product.is_fba:
            # FBA: 月売上 >= fba_min_monthly_sales
            if estimated_revenue >= self.fba_min_monthly_sales:
                return FilterResult(
                    passed=True,
                    estimated_monthly_sales=estimated_sales,
                    estimated_monthly_revenue=estimated_revenue,
                )
            else:
                return FilterResult(
                    passed=False,
                    reason=(
                        f"FBA月売上 {estimated_revenue:,}円 < "
                        f"{self.fba_min_monthly_sales:,}円"
                    ),
                    estimated_monthly_sales=estimated_sales,
                    estimated_monthly_revenue=estimated_revenue,
                )
        else:
            # FBM: 月販売数 >= fbm_min_monthly_units
            if estimated_sales >= self.fbm_min_monthly_units:
                return FilterResult(
                    passed=True,
                    estimated_monthly_sales=estimated_sales,
                    estimated_monthly_revenue=estimated_revenue,
                )
            else:
                return FilterResult(
                    passed=False,
                    reason=(
                        f"FBM月販売数 {estimated_sales}個 < "
                        f"{self.fbm_min_monthly_units}個"
                    ),
                    estimated_monthly_sales=estimated_sales,
                    estimated_monthly_revenue=estimated_revenue,
                )

    def _normalize_category(self, category: str) -> str:
        """カテゴリー名を正規化"""
        category_mapping = {
            "ホーム＆キッチン": "home_kitchen",
            "ホーム&キッチン": "home_kitchen",
            "ドラッグストア": "drugstore",
            "車&バイク": "automotive",
            "車＆バイク": "automotive",
            "カー＆バイク用品": "automotive",
            "カー&バイク用品": "automotive",
            "ペット用品": "pet_supplies",
            "おもちゃ": "toys",
            "文房具・オフィス用品": "office",
            "DIY・工具・ガーデン": "diy_tools",
            "DIY・工具": "diy_tools",
            "スポーツ&アウトドア": "sports",
            "スポーツ＆アウトドア": "sports",
            "産業・研究開発用品": "industrial",
            "パソコン・周辺機器": "pc",
            "PC・周辺機器": "pc",
            "楽器・音響機器": "musical_instruments",
            "ビューティー": "beauty",
            "家電": "electronics",
        }
        return category_mapping.get(category, "default")

    def filter_with_details(
        self,
        products: list[ProductDetail],
    ) -> list[tuple[ProductDetail, FilterResult]]:
        """フィルタリングと詳細結果を返す

        Args:
            products: フィルタリング対象の商品リスト

        Returns:
            (商品, フィルタ結果) のタプルリスト（通過した商品のみ）
        """
        results = []

        for product in products:
            result = self.check(product)
            if result.passed:
                results.append((product, result))

        return results
