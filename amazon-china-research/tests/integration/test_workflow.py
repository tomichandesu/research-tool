"""ワークフロー統合テスト"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.models.product import ProductDetail, AlibabaProduct
from src.models.result import MatchResult, ProfitResult, ResearchResult
from src.modules.amazon.filter import ProductFilter
from src.modules.calculator.sales_estimator import SalesEstimator
from src.modules.calculator.profit import ProfitCalculator


class TestFilterCalculatorIntegration:
    """フィルタ + 計算モジュールの統合テスト"""

    @pytest.fixture
    def sample_products(self):
        """テスト用商品リスト"""
        return [
            # 有望な商品（全条件通過）
            ProductDetail(
                asin="B001GOOD", title="有望商品A",
                price=3000, image_url="https://example.com/a.jpg",
                bsr=5000, category="ホーム＆キッチン",
                review_count=15, is_fba=True,
                product_url="https://amazon.co.jp/dp/B001GOOD",
            ),
            # 価格で不通過
            ProductDetail(
                asin="B002LOW", title="低価格商品",
                price=1000, image_url="https://example.com/b.jpg",
                bsr=3000, category="ホーム＆キッチン",
                review_count=10, is_fba=True,
                product_url="https://amazon.co.jp/dp/B002LOW",
            ),
            # レビュー多すぎで不通過
            ProductDetail(
                asin="B003REV", title="人気商品",
                price=5000, image_url="https://example.com/c.jpg",
                bsr=1000, category="ホーム＆キッチン",
                review_count=500, is_fba=True,
                product_url="https://amazon.co.jp/dp/B003REV",
            ),
            # FBM + 低BSRで通過
            ProductDetail(
                asin="B004FBM", title="FBM商品",
                price=2500, image_url="https://example.com/d.jpg",
                bsr=30000, category="スポーツ&アウトドア",
                review_count=25, is_fba=False,
                product_url="https://amazon.co.jp/dp/B004FBM",
            ),
        ]

    def test_filter_then_estimate_sales(self, sample_products):
        """フィルタリング後に販売数を推定"""
        product_filter = ProductFilter()
        sales_estimator = SalesEstimator()

        # カテゴリー正規化マッピング（ProductFilterと同じ）
        category_mapping = {
            "ホーム＆キッチン": "home_kitchen",
            "スポーツ&アウトドア": "default",
        }

        # フィルタリング
        filtered = product_filter.filter_with_details(sample_products)

        # 2件通過（B001GOOD, B004FBM）
        assert len(filtered) == 2

        # 販売数推定
        for product, filter_result in filtered:
            # フィルタと同じカテゴリーを使用して推定
            category = category_mapping.get(product.category, "default")
            estimated_sales = sales_estimator.estimate(product.bsr, category)
            assert estimated_sales > 0
            # フィルタ結果と一致
            assert filter_result.estimated_monthly_sales == estimated_sales

    def test_filter_then_calculate_profit(self, sample_products):
        """フィルタリング後に利益を計算"""
        product_filter = ProductFilter()
        profit_calculator = ProfitCalculator()

        # フィルタリング
        filtered = product_filter.filter_with_details(sample_products)

        # 利益計算
        for product, filter_result in filtered:
            # 仮の1688価格（30元）で計算
            profit_result = profit_calculator.calculate(
                amazon_price=product.price,
                cny_price=30.0,
                is_fba=product.is_fba,
            )

            # 利益計算結果が返される
            assert profit_result.amazon_price == product.price
            assert profit_result.profit == profit_result.amazon_price - profit_result.total_cost


class TestMatcherCalculatorIntegration:
    """マッチャー + 計算モジュールの統合テスト"""

    @pytest.fixture
    def amazon_product(self):
        return ProductDetail(
            asin="B08TEST",
            title="Amazon商品",
            price=3000,
            image_url="https://images-amazon.com/test.jpg",
            bsr=5000,
            category="ホーム＆キッチン",
            review_count=20,
            is_fba=True,
            product_url="https://amazon.co.jp/dp/B08TEST",
        )

    @pytest.fixture
    def alibaba_product(self):
        return AlibabaProduct(
            price_cny=50.0,
            image_url="https://cbu01.alicdn.com/test.jpg",
            product_url="https://detail.1688.com/test",
            shop_name="テストショップ",
        )

    def test_match_then_calculate_profit(self, amazon_product, alibaba_product):
        """マッチング後に利益計算"""
        profit_calculator = ProfitCalculator()

        # マッチング結果を作成
        match_result = MatchResult(
            amazon_product=amazon_product,
            alibaba_product=alibaba_product,
            is_matched=True,
            hamming_distance=3,
        )

        # 利益計算
        profit_result = profit_calculator.calculate(
            amazon_price=amazon_product.price,
            cny_price=alibaba_product.price_cny,
            is_fba=amazon_product.is_fba,
        )

        # 結果の検証
        assert profit_result.amazon_price == 3000
        assert profit_result.cost_1688_jpy == int(50.0 * 23.0)  # 1150円
        assert profit_result.profit > 0


class TestResearchResultIntegration:
    """リサーチ結果の統合テスト"""

    @pytest.fixture
    def complete_result(self):
        """完全なリサーチ結果"""
        amazon_product = ProductDetail(
            asin="B08COMPLETE",
            title="テスト貯金箱 子供用",
            price=2500,
            image_url="https://images-amazon.com/test.jpg",
            bsr=8000,
            category="ホーム＆キッチン",
            review_count=25,
            is_fba=True,
            product_url="https://amazon.co.jp/dp/B08COMPLETE",
            rating=4.2,
        )

        alibaba_product = AlibabaProduct(
            price_cny=35.0,
            image_url="https://cbu01.alicdn.com/test.jpg",
            product_url="https://detail.1688.com/test",
            shop_name="広州製造有限公司",
            min_order=10,
        )

        profit_result = ProfitResult(
            amazon_price=2500,
            cost_1688_jpy=753,   # 35 * 21.5
            shipping=650,        # 0.5kg * 1300
            customs=0,           # 閾値以下
            referral_fee=375,    # 2500 * 15%
            fba_fee=530,         # 2500円 → 530円
            total_cost=2308,
            profit=192,
            profit_rate=0.077,
            is_profitable=True,
        )

        return ResearchResult(
            amazon_product=amazon_product,
            alibaba_product=alibaba_product,
            profit_result=profit_result,
            estimated_monthly_sales=80,
            estimated_monthly_revenue=200000,
        )

    def test_research_result_monthly_profit(self, complete_result):
        """月間利益の計算"""
        expected_monthly_profit = complete_result.profit_result.profit * complete_result.estimated_monthly_sales
        assert complete_result.estimated_monthly_profit == expected_monthly_profit

    def test_research_result_score(self, complete_result):
        """リサーチスコアの計算"""
        score = complete_result.score
        assert score > 0
        assert score < 100

    def test_research_result_to_csv_row(self, complete_result):
        """CSV出力用データの生成"""
        csv_row = complete_result.to_csv_row()

        # 必須フィールドの存在確認
        assert csv_row["ASIN"] == "B08COMPLETE"
        assert csv_row["商品タイトル"] == "テスト貯金箱 子供用"
        assert csv_row["Amazon価格（円）"] == 2500
        assert csv_row["1688価格（元）"] == 35.0
        assert csv_row["利益（円）"] == 192
        assert "利益率（%）" in csv_row
        assert "推定月間利益（円）" in csv_row
        assert "リサーチスコア" in csv_row

    def test_research_result_to_dict(self, complete_result):
        """辞書変換"""
        data = complete_result.to_dict()

        assert "amazon_product" in data
        assert "alibaba_product" in data
        assert "profit_result" in data
        assert data["estimated_monthly_sales"] == 80
        assert data["estimated_monthly_revenue"] == 200000


class TestEndToEndWorkflow:
    """エンドツーエンド ワークフローテスト"""

    def test_full_workflow_simulation(self):
        """完全なワークフローのシミュレーション"""
        # 1. 商品データを作成（Amazon検索結果のシミュレーション）
        amazon_products = [
            ProductDetail(
                asin=f"B08SIM{i:03d}",
                title=f"シミュレーション商品{i}",
                price=2000 + i * 500,
                image_url=f"https://example.com/{i}.jpg",
                bsr=5000 + i * 1000,
                category="ホーム＆キッチン",
                review_count=10 + i * 5,
                is_fba=i % 2 == 0,
                product_url=f"https://amazon.co.jp/dp/B08SIM{i:03d}",
            )
            for i in range(10)
        ]

        # 2. フィルタリング
        product_filter = ProductFilter()
        filtered = product_filter.filter_with_details(amazon_products)

        # フィルタを通過する商品があること
        assert len(filtered) > 0

        # 3. 利益計算
        profit_calculator = ProfitCalculator()
        profitable_count = 0

        for product, filter_result in filtered:
            # 仮の1688価格でシミュレーション
            cny_price = product.price / 21.5 * 0.3  # Amazon価格の約30%

            profit_result = profit_calculator.calculate(
                amazon_price=product.price,
                cny_price=cny_price,
                is_fba=product.is_fba,
            )

            if profit_result.is_profitable:
                profitable_count += 1

                # リサーチ結果を作成
                alibaba_product = AlibabaProduct(
                    price_cny=cny_price,
                    image_url="https://example.com/1688.jpg",
                    product_url="https://detail.1688.com/test",
                )

                result = ResearchResult(
                    amazon_product=product,
                    alibaba_product=alibaba_product,
                    profit_result=profit_result,
                    estimated_monthly_sales=filter_result.estimated_monthly_sales,
                    estimated_monthly_revenue=filter_result.estimated_monthly_revenue,
                )

                # 結果が正しく構築されていること
                assert result.amazon_product.asin == product.asin
                assert result.profit_result.profit > 0
                assert result.estimated_monthly_profit > 0

        # 少なくとも1件は利益商品があること
        assert profitable_count > 0
