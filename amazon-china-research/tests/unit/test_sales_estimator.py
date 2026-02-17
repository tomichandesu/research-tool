"""SalesEstimator ユニットテスト"""
import pytest
from src.modules.calculator.sales_estimator import SalesEstimator


class TestSalesEstimator:
    """SalesEstimatorのテストクラス"""

    @pytest.fixture
    def estimator(self):
        """SalesEstimatorインスタンスを生成"""
        return SalesEstimator()

    # ============================================
    # BSR→販売数推定テスト（テーブルベース）
    # ============================================

    @pytest.mark.parametrize("bsr,expected_min", [
        (1, 300),        # 1位 → 300個以上
        (1000, 300),     # 1000位 → 300個以上
        (3000, 300),     # 3000位 → 300個以上
        (3001, 100),     # 3001位 → 100個以上
        (5000, 100),     # 5000位 → 100個以上
        (10000, 100),    # 10000位 → 100個以上
        (10001, 30),     # 10001位 → 30個以上
        (30000, 30),     # 30000位 → 30個以上
        (30001, 10),     # 30001位 → 10個以上
        (100000, 10),    # 100000位 → 10個以上
        (100001, 3),     # 100001位 → 3個以上
        (300000, 3),     # 300000位 → 3個以上
        (300001, 1),     # 300001位 → 1個以上
        (1000000, 1),    # 1000000位 → 1個以上
    ])
    def test_estimate_by_table(self, estimator, bsr, expected_min):
        """テーブルベースの推定が正しいことを確認"""
        result = estimator.estimate(bsr)
        assert result >= expected_min, f"BSR {bsr}: 期待値 >= {expected_min}, 実際 {result}"

    # ============================================
    # 境界値テスト
    # ============================================

    def test_estimate_boundary_3000_3001(self, estimator):
        """BSR 3000/3001 の境界テスト"""
        result_3000 = estimator.estimate(3000)
        result_3001 = estimator.estimate(3001)
        assert result_3000 >= 300
        assert result_3001 >= 100
        # 3000位の方が販売数が多いはず
        assert result_3000 >= result_3001

    def test_estimate_boundary_10000_10001(self, estimator):
        """BSR 10000/10001 の境界テスト"""
        result_10000 = estimator.estimate(10000)
        result_10001 = estimator.estimate(10001)
        assert result_10000 >= 100
        assert result_10001 >= 30
        assert result_10000 >= result_10001

    # ============================================
    # 異常値テスト
    # ============================================

    def test_estimate_bsr_zero(self, estimator):
        """BSR 0 の場合は0を返す"""
        result = estimator.estimate(0)
        assert result == 0

    def test_estimate_bsr_negative(self, estimator):
        """BSR 負数 の場合は0を返す"""
        result = estimator.estimate(-100)
        assert result == 0

    def test_estimate_bsr_very_large(self, estimator):
        """非常に大きいBSRでも1以上を返す"""
        result = estimator.estimate(10000000)
        assert result >= 1

    # ============================================
    # カテゴリ別係数テスト
    # ============================================

    def test_estimate_category_home_kitchen(self, estimator):
        """ホーム＆キッチンカテゴリの推定"""
        result = estimator.estimate(5000, category="home_kitchen")
        assert result > 0

    def test_estimate_category_toys(self, estimator):
        """おもちゃカテゴリの推定"""
        result = estimator.estimate(5000, category="toys")
        assert result > 0

    def test_estimate_category_beauty(self, estimator):
        """ビューティーカテゴリの推定"""
        result = estimator.estimate(5000, category="beauty")
        assert result > 0

    def test_estimate_category_electronics(self, estimator):
        """家電カテゴリの推定"""
        result = estimator.estimate(5000, category="electronics")
        assert result > 0

    def test_estimate_category_unknown(self, estimator):
        """未知のカテゴリはdefaultを使用"""
        result_unknown = estimator.estimate(5000, category="unknown_category")
        result_default = estimator.estimate(5000, category="default")
        assert result_unknown == result_default

    # ============================================
    # 月間売上推定テスト
    # ============================================

    def test_estimate_monthly_revenue(self, estimator):
        """月間売上の推定"""
        bsr = 5000
        price = 2000
        revenue = estimator.estimate_monthly_revenue(bsr, price)
        expected_sales = estimator.estimate(bsr)
        assert revenue == expected_sales * price

    def test_estimate_monthly_revenue_high_price(self, estimator):
        """高価格商品の月間売上"""
        revenue = estimator.estimate_monthly_revenue(5000, 10000)
        assert revenue > 0

    # ============================================
    # 逆算テスト
    # ============================================

    def test_get_bsr_for_target_sales(self, estimator):
        """目標販売数から必要BSRを逆算"""
        target_sales = 100
        bsr = estimator.get_bsr_for_target_sales(target_sales)
        # 逆算したBSRで推定すると目標に近い値になるはず
        estimated = estimator.estimate(bsr)
        # 誤差を許容（±50%）
        assert estimated >= target_sales * 0.5

    def test_get_bsr_for_target_sales_zero(self, estimator):
        """目標販売数0の場合"""
        bsr = estimator.get_bsr_for_target_sales(0)
        assert bsr == 1000000  # 非常に低いランキング

    def test_get_bsr_for_target_sales_negative(self, estimator):
        """目標販売数負数の場合"""
        bsr = estimator.get_bsr_for_target_sales(-10)
        assert bsr == 1000000


class TestSalesEstimatorRequirements:
    """要件定義に基づくテスト（FR-205）"""

    @pytest.fixture
    def estimator(self):
        return SalesEstimator()

    def test_fr205_bsr_5000_estimate(self, estimator):
        """FR-205: BSR 5,000位で推定販売数が50-300個になること"""
        result = estimator.estimate(5000)
        # 要件: 50-300個
        assert 50 <= result <= 300, f"BSR 5000の推定販売数: {result}（期待: 50-300）"

    def test_fr205_bsr_range_estimation(self, estimator):
        """FR-205: BSR範囲による推定が要件通りであること"""
        # 1-3000位: 300個以上
        assert estimator.estimate(2000) >= 300

        # 3001-10000位: 100個以上
        assert estimator.estimate(5000) >= 100

        # 10001-30000位: 30個以上
        assert estimator.estimate(20000) >= 30

        # 30001-100000位: 10個以上
        assert estimator.estimate(50000) >= 10
