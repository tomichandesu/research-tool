"""ProfitCalculator ユニットテスト"""
import pytest
from src.modules.calculator.profit import ProfitCalculator


class TestProfitCalculator:
    """ProfitCalculatorのテストクラス"""

    @pytest.fixture
    def calculator(self):
        """ProfitCalculatorインスタンスを生成"""
        return ProfitCalculator()

    # ============================================
    # 基本利益計算テスト
    # ============================================

    def test_calculate_basic_profit(self, calculator):
        """基本的な利益計算"""
        result = calculator.calculate(
            amazon_price=3000,
            cny_price=50.0,
            is_fba=True,
            category="default",
        )
        assert result.amazon_price == 3000
        assert result.cost_1688_jpy > 0
        assert result.profit == result.amazon_price - result.total_cost

    def test_calculate_profit_rate(self, calculator):
        """利益率の計算"""
        result = calculator.calculate(
            amazon_price=3000,
            cny_price=50.0,
            is_fba=True,
        )
        expected_rate = result.profit / result.amazon_price
        assert abs(result.profit_rate - expected_rate) < 0.001

    def test_calculate_is_profitable(self, calculator):
        """利益が出るかどうかの判定"""
        # 低価格仕入れ → 利益あり
        result_profit = calculator.calculate(
            amazon_price=5000,
            cny_price=30.0,
            is_fba=True,
        )
        assert result_profit.is_profitable is True

        # 高価格仕入れ → 利益なし
        result_loss = calculator.calculate(
            amazon_price=1500,
            cny_price=100.0,
            is_fba=True,
        )
        assert result_loss.is_profitable is False

    # ============================================
    # 為替換算テスト（新レート: 1元=23円）
    # ============================================

    def test_cny_to_jpy_conversion(self, calculator):
        """人民元→日本円の換算（1元=23円）"""
        result = calculator.calculate(
            amazon_price=3000,
            cny_price=100.0,
            is_fba=True,
        )
        expected_jpy = int(100.0 * calculator.exchange_rate)
        assert result.cost_1688_jpy == expected_jpy

    def test_exchange_rate_default(self, calculator):
        """デフォルト為替レートが23円であること"""
        assert calculator.exchange_rate == 23.0

    # ============================================
    # 送料計算テスト（容積重量ベース）
    # ============================================

    def test_shipping_volumetric_weight(self, calculator):
        """容積重量での国際送料計算"""
        # 容積重量 = 20 × 15 × 10 ÷ 6000 = 0.5kg
        # 実重量 = 0.3kg → 容積重量を使用
        # 国際送料 = 0.5kg × 10元/kg × 23円/元 = 115円
        result = calculator.calculate(
            amazon_price=3000,
            cny_price=50.0,
            is_fba=True,
            weight_kg=0.3,
            dimensions=(20, 15, 10),
        )
        expected_shipping = int(0.5 * 10 * 23)  # 115円
        assert result.shipping == expected_shipping

    def test_shipping_actual_weight_heavier(self, calculator):
        """実重量が容積重量より重い場合"""
        # 容積重量 = 20 × 15 × 10 ÷ 6000 = 0.5kg
        # 実重量 = 1.0kg → 実重量を使用
        # 国際送料 = 1.0kg × 10元/kg × 23円/元 = 230円
        result = calculator.calculate(
            amazon_price=3000,
            cny_price=50.0,
            is_fba=True,
            weight_kg=1.0,
            dimensions=(20, 15, 10),
        )
        expected_shipping = int(1.0 * 10 * 23)  # 230円
        assert result.shipping == expected_shipping

    def test_shipping_default_dimensions(self, calculator):
        """デフォルト寸法での送料計算"""
        # デフォルト: 20×15×10cm → 容積重量0.5kg
        result = calculator.calculate(
            amazon_price=3000,
            cny_price=50.0,
            is_fba=True,
        )
        expected_shipping = int(0.5 * 10 * 23)  # 115円
        assert result.shipping == expected_shipping

    # ============================================
    # 関税計算テスト（常時10%適用）
    # ============================================

    def test_customs_always_applied(self, calculator):
        """関税は常に10%適用"""
        result = calculator.calculate(
            amazon_price=3000,
            cny_price=30.0,
            is_fba=True,
        )
        # 関税 = (仕入原価 + 国際送料) × 10%
        expected_customs = int((result.cost_1688_jpy + result.shipping) * 0.10)
        assert result.customs == expected_customs

    def test_customs_rate(self, calculator):
        """関税率が10%であること"""
        assert calculator.customs_rate == 0.10

    # ============================================
    # Amazon紹介料テスト
    # ============================================

    def test_referral_fee_default(self, calculator):
        """デフォルト紹介料率（15%）"""
        result = calculator.calculate(
            amazon_price=3000,
            cny_price=50.0,
            is_fba=True,
            category="default",
        )
        expected_fee = int(3000 * 0.15)
        assert result.referral_fee == expected_fee

    def test_referral_fee_home_kitchen(self, calculator):
        """ホーム＆キッチン紹介料率（15%）"""
        result = calculator.calculate(
            amazon_price=3000,
            cny_price=50.0,
            is_fba=True,
            category="home_kitchen",
        )
        expected_fee = int(3000 * 0.15)
        assert result.referral_fee == expected_fee

    def test_referral_fee_beauty(self, calculator):
        """ビューティー紹介料率（10%）"""
        result = calculator.calculate(
            amazon_price=3000,
            cny_price=50.0,
            is_fba=True,
            category="beauty",
        )
        expected_fee = int(3000 * 0.10)
        assert result.referral_fee == expected_fee

    def test_referral_fee_electronics(self, calculator):
        """家電紹介料率（8%）"""
        result = calculator.calculate(
            amazon_price=3000,
            cny_price=50.0,
            is_fba=True,
            category="electronics",
        )
        expected_fee = int(3000 * 0.08)
        assert result.referral_fee == expected_fee

    def test_referral_fee_toys(self, calculator):
        """おもちゃ紹介料率（10%）"""
        result = calculator.calculate(
            amazon_price=3000,
            cny_price=50.0,
            is_fba=True,
            category="toys_hobbies",
        )
        expected_fee = int(3000 * 0.10)
        assert result.referral_fee == expected_fee

    # ============================================
    # FBA手数料テスト（サイズ・重量ベース）
    # ============================================

    def test_fba_fee_small_size(self, calculator):
        """小型サイズのFBA手数料（288円）"""
        # 小型: 縦+横+高さ <= 45cm かつ 重量 <= 0.25kg
        result = calculator.calculate(
            amazon_price=2000,
            cny_price=10.0,
            is_fba=True,
            weight_kg=0.2,
            dimensions=(15, 10, 5),  # 合計30cm
        )
        assert result.fba_fee == 288

    def test_fba_fee_standard_size(self, calculator):
        """標準サイズのFBA手数料"""
        # 標準サイズ: 縦+横+高さ <= 68cm かつ 重量 <= 1.0kg → 318円
        result = calculator.calculate(
            amazon_price=2000,
            cny_price=20.0,
            is_fba=True,
            weight_kg=0.5,
            dimensions=(20, 15, 10),  # 合計45cm
        )
        assert result.fba_fee == 318

    def test_fba_fee_large_size(self, calculator):
        """大型サイズのFBA手数料"""
        # 大型サイズ: 縦+横+高さ > 100cm
        result = calculator.calculate(
            amazon_price=5000,
            cny_price=100.0,
            is_fba=True,
            weight_kg=3.0,
            dimensions=(50, 30, 25),  # 合計105cm
        )
        # 大型サイズ区分に該当
        assert result.fba_fee >= 589  # 大型の最小値

    # ============================================
    # FBM（自己発送）テスト
    # ============================================

    def test_fbm_no_fba_fee(self, calculator):
        """FBMの場合はFBA手数料なし"""
        result = calculator.calculate(
            amazon_price=3000,
            cny_price=50.0,
            is_fba=False,
        )
        assert result.fba_fee == 0

    def test_fbm_vs_fba_profit(self, calculator):
        """FBMの方がFBAより利益が多い"""
        result_fba = calculator.calculate(
            amazon_price=3000,
            cny_price=50.0,
            is_fba=True,
        )
        result_fbm = calculator.calculate(
            amazon_price=3000,
            cny_price=50.0,
            is_fba=False,
        )
        assert result_fbm.profit > result_fba.profit

    # ============================================
    # 総コスト計算テスト
    # ============================================

    def test_total_cost_includes_all_fees(self, calculator):
        """総コストに全ての費用が含まれていること"""
        result = calculator.calculate(
            amazon_price=3000,
            cny_price=50.0,
            is_fba=True,
        )
        # 総コストには以下が含まれる:
        # 仕入原価 + 中国国内送料 + 代行手数料 + 国際送料 + 関税 + 紹介料 + FBA手数料
        # ProfitResultにはcost_1688_jpy, shipping, customs, referral_fee, fba_feeのみ表示
        # 中国国内送料と代行手数料はtotal_costに含まれているが個別フィールドがない
        assert result.total_cost > (
            result.cost_1688_jpy +
            result.shipping +
            result.customs +
            result.referral_fee +
            result.fba_fee
        )

    # ============================================
    # 損益分岐点テスト
    # ============================================

    def test_break_even_price(self, calculator):
        """損益分岐点価格の計算"""
        cny_price = 50.0
        break_even = calculator.calculate_break_even_price(
            cny_price=cny_price,
            is_fba=True,
        )
        # 損益分岐点で計算すると利益が0に近いはず
        result = calculator.calculate(
            amazon_price=break_even,
            cny_price=cny_price,
            is_fba=True,
        )
        # 誤差許容（±100円）
        assert abs(result.profit) < 100

    def test_minimum_profit_price(self, calculator):
        """最低利益確保価格の計算"""
        cny_price = 50.0
        min_profit = 500
        min_price = calculator.calculate_minimum_profit_price(
            cny_price=cny_price,
            is_fba=True,
            min_profit=min_profit,
        )
        result = calculator.calculate(
            amazon_price=min_price,
            cny_price=cny_price,
            is_fba=True,
        )
        assert result.profit >= min_profit


class TestProfitCalculatorRequirements:
    """要件定義に基づくテスト"""

    @pytest.fixture
    def calculator(self):
        return ProfitCalculator()

    def test_profit_calculation_formula(self, calculator):
        """利益計算式が正しいこと"""
        result = calculator.calculate(
            amazon_price=2000,
            cny_price=30.0,
            is_fba=True,
        )
        # 利益 = Amazon価格 - 総コスト
        assert result.profit == result.amazon_price - result.total_cost
        # 利益率 = 利益 / Amazon価格
        assert abs(result.profit_rate - (result.profit / result.amazon_price)) < 0.001

    def test_exchange_rate_23yen(self, calculator):
        """為替レート1元=23円が適用されること"""
        result = calculator.calculate(
            amazon_price=3000,
            cny_price=100.0,
            is_fba=True,
        )
        assert result.cost_1688_jpy == int(100.0 * 23.0)

    def test_volumetric_weight_shipping(self, calculator):
        """容積重量で国際送料が計算されること"""
        # 30×20×15cm → 容積重量 = 1.5kg
        # 実重量 = 0.5kg → 容積重量を使用
        result = calculator.calculate(
            amazon_price=3000,
            cny_price=50.0,
            is_fba=True,
            weight_kg=0.5,
            dimensions=(30, 20, 15),
        )
        volumetric_weight = (30 * 20 * 15) / 6000  # 1.5kg
        expected_shipping = int(volumetric_weight * 10 * 23)  # 345円
        assert result.shipping == expected_shipping

    def test_customs_10_percent(self, calculator):
        """関税が10%適用されること"""
        result = calculator.calculate(
            amazon_price=2000,
            cny_price=30.0,
            is_fba=True,
            category="home_kitchen",
        )
        # 関税 = (仕入原価 + 国際送料) × 10%
        expected_customs = int((result.cost_1688_jpy + result.shipping) * 0.10)
        assert result.customs == expected_customs

    def test_fba_fee_by_size_weight(self, calculator):
        """FBA手数料がサイズ・重量で決まること"""
        # 小型サイズ: 288円
        result_small = calculator.calculate(
            amazon_price=2000,
            cny_price=20.0,
            is_fba=True,
            weight_kg=0.2,
            dimensions=(15, 10, 5),  # 合計30cm <= 45cm
        )
        assert result_small.fba_fee == 288

        # 標準サイズ: 318円
        result_standard = calculator.calculate(
            amazon_price=2000,
            cny_price=20.0,
            is_fba=True,
            weight_kg=0.5,
            dimensions=(20, 15, 10),  # 合計45cm <= 68cm
        )
        assert result_standard.fba_fee == 318
