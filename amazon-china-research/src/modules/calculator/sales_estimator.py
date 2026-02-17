"""販売数推定モジュール"""
from __future__ import annotations

import logging
from typing import Optional

from ...config import get_config, SalesEstimationConfig

logger = logging.getLogger(__name__)


class SalesEstimator:
    """BSRから月間販売数を推定する

    推定方法:
    1. テーブルベース: BSR範囲に対応する最低販売数
    2. 係数ベース: a * (BSR ^ -b) * 30

    BSR-販売数テーブル（デフォルト）:
    - 1-3,000位: 300個以上/月
    - 3,001-10,000位: 100個以上/月
    - 10,001-30,000位: 30個以上/月
    - 30,001-100,000位: 10個以上/月
    - 100,001-300,000位: 3個以上/月
    - 300,001位以下: 1個以上/月
    """

    # デフォルトのカテゴリ別係数
    DEFAULT_COEFFICIENTS = {
        "home_kitchen": (5000, 0.75),
        "toys": (3500, 0.80),
        "beauty": (8000, 0.70),
        "electronics": (2500, 0.85),
        "default": (4000, 0.78),
    }

    # デフォルトのBSR-販売数テーブル
    DEFAULT_TABLE = [
        (3000, 300),
        (10000, 100),
        (30000, 30),
        (100000, 10),
        (300000, 3),
        (1000000, 1),
    ]

    def __init__(self, config: Optional[SalesEstimationConfig] = None):
        if config is None:
            config = get_config().sales_estimation
        self.config = config

        # 設定からテーブルと係数を取得
        self._table = self._load_table()
        self._coefficients = self._load_coefficients()

    def _load_table(self) -> list[tuple[int, int]]:
        """設定からテーブルを読み込む"""
        if self.config and self.config.table:
            return [
                (entry.bsr_max, entry.units_min)
                for entry in self.config.table
            ]
        return self.DEFAULT_TABLE

    def _load_coefficients(self) -> dict[str, tuple[float, float]]:
        """設定から係数を読み込む"""
        if self.config and self.config.category_coefficients:
            return {
                k: (v.a, v.b)
                for k, v in self.config.category_coefficients.items()
            }
        return self.DEFAULT_COEFFICIENTS

    def estimate(self, bsr: int, category: str = "default") -> int:
        """月間販売数を推定

        Args:
            bsr: 大カテゴリーランキング
            category: カテゴリ名

        Returns:
            推定月間販売数
        """
        if bsr <= 0:
            return 0

        # 両方の方法で推定し、大きい方を採用
        table_estimate = self._estimate_by_table(bsr)
        formula_estimate = self._estimate_by_formula(bsr, category)

        # 保守的に小さい方を採用することも可能
        # ここでは要件定義に従い、テーブルベースを優先
        result = max(table_estimate, formula_estimate)

        logger.debug(
            f"販売数推定: BSR={bsr}, カテゴリ={category}, "
            f"テーブル={table_estimate}, 係数={formula_estimate}, "
            f"結果={result}"
        )

        return result

    def _estimate_by_table(self, bsr: int) -> int:
        """テーブルベースで推定"""
        for bsr_max, units_min in self._table:
            if bsr <= bsr_max:
                return units_min

        # テーブル範囲外
        return 1

    def _estimate_by_formula(self, bsr: int, category: str) -> int:
        """係数ベースで推定

        式: monthly_sales = a * (bsr ^ -b) * 30
        """
        coefficients = self._coefficients.get(
            category,
            self._coefficients.get("default", (4000, 0.78)),
        )
        a, b = coefficients

        # 月間販売数を計算
        daily_sales = a * (bsr ** (-b))
        monthly_sales = daily_sales * 30

        return max(1, int(monthly_sales))

    def estimate_monthly_revenue(
        self,
        bsr: int,
        price: int,
        category: str = "default",
    ) -> int:
        """月間売上を推定

        Args:
            bsr: 大カテゴリーランキング
            price: 販売価格（円）
            category: カテゴリ名

        Returns:
            推定月間売上（円）
        """
        monthly_sales = self.estimate(bsr, category)
        return monthly_sales * price

    def get_bsr_for_target_sales(
        self,
        target_sales: int,
        category: str = "default",
    ) -> int:
        """目標販売数に必要なBSRを逆算

        Args:
            target_sales: 目標月間販売数
            category: カテゴリ名

        Returns:
            必要なBSR（概算）
        """
        if target_sales <= 0:
            return 1000000  # 非常に低いランキング

        coefficients = self._coefficients.get(
            category,
            self._coefficients.get("default", (4000, 0.78)),
        )
        a, b = coefficients

        # monthly_sales = a * (bsr ^ -b) * 30
        # bsr = (monthly_sales / (a * 30)) ^ (-1/b)
        daily_target = target_sales / 30
        bsr = (daily_target / a) ** (-1 / b)

        return max(1, int(bsr))
