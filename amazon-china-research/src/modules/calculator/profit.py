"""利益計算モジュール"""
from __future__ import annotations

import logging
from typing import Optional

from ...models.result import ProfitResult
from ...config import get_config, ProfitConfig, FbaFeesConfig

logger = logging.getLogger(__name__)


class ProfitCalculator:
    """利益を計算する

    計算式:
    1. 仕入原価 = 1688価格 × 為替レート(23円/元)
    2. 中国国内送料 = 2元 × 為替レート
    3. 代行手数料 = 仕入原価 × 3%
    4. 容積重量 = L × W × H ÷ 6000
    5. 国際送料 = MAX(実重量, 容積重量) × 10元/kg × 為替レート
    6. 関税 = (仕入原価 + 国際送料) × 10%
    7. 紹介料 = 販売価格 × カテゴリ別料率
    8. FBA手数料 = サイズ・重量別テーブルから
    9. 利益 = 販売価格 - 総コスト
    """

    # デフォルトのカテゴリ別紹介料率
    DEFAULT_REFERRAL_RATES = {
        "toys_hobbies": 0.10,
        "diy_tools": 0.15,
        "home_kitchen": 0.15,
        "electronics": 0.08,
        "electronics_accessories": 0.10,
        "beauty": 0.10,
        "sports": 0.10,
        "pet_supplies": 0.15,
        "garden": 0.15,
        "office": 0.15,
        "automotive": 0.10,
        "baby": 0.15,
        "default": 0.15,
    }

    def __init__(
        self,
        profit_config: Optional[ProfitConfig] = None,
        fba_config: Optional[FbaFeesConfig] = None,
        referral_rates: Optional[dict[str, float]] = None,
    ):
        config = get_config()

        self.profit_config = profit_config or config.profit
        self.fba_config = fba_config or config.fba_fees
        self.referral_rates = referral_rates or config.referral_rates

        # デフォルト値を設定
        if not self.referral_rates:
            self.referral_rates = self.DEFAULT_REFERRAL_RATES

    @property
    def exchange_rate(self) -> float:
        """為替レート（1元 = X円）"""
        return self.profit_config.exchange_rate

    @property
    def china_domestic_shipping(self) -> float:
        """中国国内送料（元）"""
        return self.profit_config.china_domestic_shipping

    @property
    def agent_fee_rate(self) -> float:
        """代行手数料率"""
        return self.profit_config.agent_fee_rate

    @property
    def international_shipping_per_kg(self) -> float:
        """国際送料（元/kg）"""
        return self.profit_config.international_shipping_per_kg

    @property
    def customs_rate(self) -> float:
        """関税率"""
        return self.profit_config.customs_rate

    @property
    def default_weight(self) -> float:
        """デフォルト重量（kg）"""
        return self.profit_config.default_weight

    @property
    def default_dimensions(self) -> tuple[int, int, int]:
        """デフォルト寸法 (L, W, H) cm"""
        dims = self.profit_config.default_dimensions
        return (dims.length, dims.width, dims.height)

    def calculate(
        self,
        amazon_price: int,
        cny_price: float,
        is_fba: bool,
        category: str = "default",
        weight_kg: Optional[float] = None,
        dimensions: Optional[tuple[int, int, int]] = None,
    ) -> ProfitResult:
        """利益を計算

        Args:
            amazon_price: Amazon販売価格（円）
            cny_price: 1688価格（元）
            is_fba: FBA出品かどうか
            category: カテゴリ名
            weight_kg: 実重量（kg）、Noneの場合はデフォルト値を使用
            dimensions: 寸法 (L, W, H) cm、Noneの場合はデフォルト値を使用

        Returns:
            ProfitResult: 利益計算結果
        """
        # 重量・寸法設定
        actual_weight = weight_kg or self.default_weight
        dims = dimensions or self.default_dimensions

        # 容積重量を計算
        volumetric_weight = self._calculate_volumetric_weight(dims)

        # 送料計算用重量（実重量と容積重量の大きい方）
        shipping_weight = max(actual_weight, volumetric_weight)

        # 1. 仕入原価（円）= 1688価格 × 為替レート
        cost_1688_jpy = self._calculate_cny_to_jpy(cny_price)

        # 2. 中国国内送料（円）
        china_shipping_jpy = int(self.china_domestic_shipping * self.exchange_rate)

        # 3. 代行手数料（円）= 仕入原価 × 3%
        agent_fee = int(cost_1688_jpy * self.agent_fee_rate)

        # 4. 国際送料（円）= 送料重量 × 10元/kg × 為替レート
        international_shipping = self._calculate_shipping(shipping_weight)

        # 5. 関税（円）= (仕入原価 + 国際送料) × 10%
        customs = self._calculate_customs(cost_1688_jpy + international_shipping)

        # 6. Amazon紹介料（円）
        referral_fee = self._calculate_referral_fee(amazon_price, category)

        # 7. FBA手数料（円）- サイズ・重量別
        fba_fee = self._calculate_fba_fee_by_size(
            dims, actual_weight
        ) if is_fba else 0

        # 8. 総コスト
        total_cost = (
            cost_1688_jpy +
            china_shipping_jpy +
            agent_fee +
            international_shipping +
            customs +
            referral_fee +
            fba_fee
        )

        # 9. 利益
        profit = amazon_price - total_cost

        # 10. 利益率
        profit_rate = profit / amazon_price if amazon_price > 0 else 0

        # 11. 利益が出るかどうか
        is_profitable = profit > 0

        result = ProfitResult(
            amazon_price=amazon_price,
            cost_1688_jpy=cost_1688_jpy,
            shipping=international_shipping,
            customs=customs,
            referral_fee=referral_fee,
            fba_fee=fba_fee,
            total_cost=total_cost,
            profit=profit,
            profit_rate=profit_rate,
            is_profitable=is_profitable,
        )

        logger.debug(
            f"利益計算: Amazon={amazon_price}円, 1688={cny_price}元, "
            f"利益={profit}円 ({profit_rate:.1%})"
        )

        return result

    def _calculate_volumetric_weight(self, dimensions: tuple[int, int, int]) -> float:
        """容積重量を計算（L × W × H ÷ 6000）

        Args:
            dimensions: (長さ, 幅, 高さ) cm

        Returns:
            容積重量 (kg)
        """
        length, width, height = dimensions
        return (length * width * height) / 6000

    def _calculate_cny_to_jpy(self, cny_price: float) -> int:
        """人民元から日本円に換算"""
        return int(cny_price * self.exchange_rate)

    def _calculate_shipping(self, weight_kg: float) -> int:
        """国際送料を計算（元/kg → 円に換算）"""
        shipping_cny = weight_kg * self.international_shipping_per_kg
        return int(shipping_cny * self.exchange_rate)

    def _calculate_customs(self, base_cost_jpy: int) -> int:
        """関税を計算

        関税 = 対象金額 × 10%（常に適用）
        """
        return int(base_cost_jpy * self.customs_rate)

    def _calculate_referral_fee(self, price: int, category: str) -> int:
        """紹介料を計算

        紹介料 = 販売価格 × カテゴリ別料率
        """
        rate = self.referral_rates.get(
            category,
            self.referral_rates.get("default", 0.15),
        )
        return int(price * rate)

    def _calculate_fba_fee_by_size(
        self,
        dimensions: tuple[int, int, int],
        weight_kg: float,
    ) -> int:
        """FBA手数料をサイズ・重量で計算

        Args:
            dimensions: (長さ, 幅, 高さ) cm
            weight_kg: 重量 (kg)

        Returns:
            FBA手数料（円）
        """
        length, width, height = dimensions
        dims_sum = length + width + height

        # 小型チェック
        if self.fba_config and self.fba_config.small:
            small = self.fba_config.small
            if dims_sum <= small.max_dimensions_sum and weight_kg <= small.max_weight:
                return small.fee

        # 標準サイズチェック
        if self.fba_config and self.fba_config.standard:
            for tier in self.fba_config.standard:
                if dims_sum <= tier.max_dimensions_sum and weight_kg <= tier.max_weight:
                    return tier.fee

        # 大型サイズチェック
        if self.fba_config and self.fba_config.large:
            for tier in self.fba_config.large:
                if dims_sum <= tier.max_dimensions_sum and weight_kg <= tier.max_weight:
                    return tier.fee

        # デフォルト
        return self.fba_config.default_fee if self.fba_config else 434

    def calculate_break_even_price(
        self,
        cny_price: float,
        is_fba: bool,
        category: str = "default",
        weight_kg: Optional[float] = None,
        dimensions: Optional[tuple[int, int, int]] = None,
        target_profit_rate: float = 0.0,
    ) -> int:
        """損益分岐点の販売価格を計算

        Args:
            cny_price: 1688価格（元）
            is_fba: FBA出品かどうか
            category: カテゴリ名
            weight_kg: 実重量（kg）
            dimensions: 寸法 (L, W, H) cm
            target_profit_rate: 目標利益率（0.0 = 損益分岐点）

        Returns:
            損益分岐点の販売価格（円）
        """
        # 反復計算で正確な価格を求める
        for test_price in range(1000, 50000, 50):
            result = self.calculate(
                amazon_price=test_price,
                cny_price=cny_price,
                is_fba=is_fba,
                category=category,
                weight_kg=weight_kg,
                dimensions=dimensions,
            )
            actual_rate = result.profit / test_price if test_price > 0 else 0
            if actual_rate >= target_profit_rate:
                return test_price

        return 50000  # 上限

    def calculate_minimum_profit_price(
        self,
        cny_price: float,
        is_fba: bool,
        category: str = "default",
        weight_kg: Optional[float] = None,
        dimensions: Optional[tuple[int, int, int]] = None,
        min_profit: int = 500,
    ) -> int:
        """最低利益を確保するための販売価格を計算

        Args:
            cny_price: 1688価格（元）
            is_fba: FBA出品かどうか
            category: カテゴリ名
            weight_kg: 実重量（kg）
            dimensions: 寸法 (L, W, H) cm
            min_profit: 最低利益（円）

        Returns:
            必要な販売価格（円）
        """
        # 反復計算で正確な価格を求める
        for test_price in range(1000, 50000, 50):
            result = self.calculate(
                amazon_price=test_price,
                cny_price=cny_price,
                is_fba=is_fba,
                category=category,
                weight_kg=weight_kg,
                dimensions=dimensions,
            )
            if result.profit >= min_profit:
                return test_price

        return 50000  # 上限
