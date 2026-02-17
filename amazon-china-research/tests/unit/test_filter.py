"""ProductFilter ユニットテスト"""
import pytest
from unittest.mock import MagicMock, patch

from src.modules.amazon.filter import ProductFilter, FilterResult
from src.models.product import ProductDetail
from src.config import FilterConfig


class TestProductFilter:
    """ProductFilterのテストクラス"""

    @pytest.fixture
    def filter_config(self):
        """テスト用フィルタ設定"""
        return FilterConfig(
            min_price=1500,
            max_price=4000,
            max_reviews=50,
            max_rating=4.2,
            min_bsr=5000,
            max_bsr=50000,
            fba_min_monthly_sales=20000,
            fbm_min_monthly_units=3,
        )

    @pytest.fixture
    def product_filter(self, filter_config):
        """ProductFilterインスタンス"""
        return ProductFilter(config=filter_config)

    @pytest.fixture
    def valid_fba_product(self):
        """フィルタを通過するFBA商品"""
        return ProductDetail(
            asin="B08TEST001",
            title="テスト商品 FBA",
            price=2000,
            image_url="https://example.com/image.jpg",
            bsr=5000,  # 推定100個以上/月
            category="ホーム＆キッチン",
            review_count=20,
            is_fba=True,
            product_url="https://www.amazon.co.jp/dp/B08TEST001",
            rating=3.8,
        )

    @pytest.fixture
    def valid_fbm_product(self):
        """フィルタを通過するFBM商品"""
        return ProductDetail(
            asin="B08TEST002",
            title="テスト商品 FBM",
            price=3000,
            image_url="https://example.com/image.jpg",
            bsr=30000,  # 推定30個以上/月, BSR <= 50000
            category="ホーム＆キッチン",
            review_count=30,
            is_fba=False,
            product_url="https://www.amazon.co.jp/dp/B08TEST002",
            rating=3.5,
        )

    # ============================================
    # 価格フィルタテスト（FR-201）
    # ============================================

    def test_price_filter_pass(self, product_filter, valid_fba_product):
        """価格1500円以上は通過"""
        valid_fba_product.price = 1500
        assert product_filter.check_min_price(valid_fba_product) is True

    def test_price_filter_fail(self, product_filter, valid_fba_product):
        """価格1500円未満は不通過"""
        valid_fba_product.price = 1499
        assert product_filter.check_min_price(valid_fba_product) is False

    def test_price_filter_boundary_1499(self, product_filter, valid_fba_product):
        """境界値: 1499円は不通過"""
        valid_fba_product.price = 1499
        assert product_filter.check_min_price(valid_fba_product) is False

    def test_price_filter_boundary_1500(self, product_filter, valid_fba_product):
        """境界値: 1500円は通過"""
        valid_fba_product.price = 1500
        assert product_filter.check_min_price(valid_fba_product) is True

    def test_price_filter_high_price(self, product_filter, valid_fba_product):
        """高価格商品（max_price以下）は通過"""
        valid_fba_product.price = 4000
        assert product_filter.check_min_price(valid_fba_product) is True
        assert product_filter.check_max_price(valid_fba_product) is True

    # ============================================
    # レビュー数フィルタテスト（FR-202）
    # ============================================

    def test_reviews_filter_pass(self, product_filter, valid_fba_product):
        """レビュー50件以下は通過"""
        valid_fba_product.review_count = 50
        assert product_filter.check_reviews(valid_fba_product) is True

    def test_reviews_filter_fail(self, product_filter, valid_fba_product):
        """レビュー51件以上は不通過"""
        valid_fba_product.review_count = 51
        assert product_filter.check_reviews(valid_fba_product) is False

    def test_reviews_filter_boundary_40(self, product_filter, valid_fba_product):
        """境界値: 50件は通過"""
        valid_fba_product.review_count = 50
        assert product_filter.check_reviews(valid_fba_product) is True

    def test_reviews_filter_boundary_41(self, product_filter, valid_fba_product):
        """境界値: 51件は不通過"""
        valid_fba_product.review_count = 51
        assert product_filter.check_reviews(valid_fba_product) is False

    def test_reviews_filter_zero(self, product_filter, valid_fba_product):
        """レビュー0件は通過"""
        valid_fba_product.review_count = 0
        assert product_filter.check_reviews(valid_fba_product) is True

    # ============================================
    # FBA販売数フィルタテスト（FR-203）
    # ============================================

    def test_fba_sales_filter_pass(self, product_filter, valid_fba_product):
        """FBA月売上2万円以上は通過"""
        # BSR 5000位 → 推定100個/月 × 2000円 = 20万円
        valid_fba_product.bsr = 5000
        valid_fba_product.price = 2000
        valid_fba_product.is_fba = True

        result = product_filter.check_sales(valid_fba_product)
        assert result.passed is True
        assert result.estimated_monthly_revenue >= 20000

    def test_fba_sales_filter_fail(self, product_filter, valid_fba_product):
        """FBA月売上2万円未満は不通過"""
        # BSR 500000位 → 推定1-2個/月 × 1500円 < 2万円
        valid_fba_product.bsr = 500000
        valid_fba_product.price = 1500
        valid_fba_product.is_fba = True

        result = product_filter.check_sales(valid_fba_product)
        assert result.passed is False
        assert "FBA月売上" in result.reason

    def test_fba_sales_boundary(self, product_filter, valid_fba_product):
        """FBA月売上境界テスト"""
        # 月売上がちょうど2万円になるケースをテスト
        valid_fba_product.is_fba = True

        # 2万円ちょうど → 通過
        valid_fba_product.price = 2000
        valid_fba_product.bsr = 30000  # 推定30個/月 × 2000円 = 6万円

        result = product_filter.check_sales(valid_fba_product)
        assert result.passed is True

    # ============================================
    # FBM販売数フィルタテスト（FR-204）
    # ============================================

    def test_fbm_sales_filter_pass(self, product_filter, valid_fbm_product):
        """FBM月3個以上は通過"""
        # BSR 50000位 → 推定10個/月
        valid_fbm_product.bsr = 50000
        valid_fbm_product.is_fba = False

        result = product_filter.check_sales(valid_fbm_product)
        assert result.passed is True
        assert result.estimated_monthly_sales >= 3

    def test_fbm_sales_filter_fail(self, product_filter, valid_fbm_product):
        """FBM月3個未満は不通過"""
        # BSR 2000000位 → 推定1-2個/月（係数ベースでも3未満になる高ランキング）
        valid_fbm_product.bsr = 2000000
        valid_fbm_product.is_fba = False

        result = product_filter.check_sales(valid_fbm_product)
        assert result.passed is False
        assert "FBM月販売数" in result.reason

    def test_fbm_sales_boundary_2_3(self, product_filter, valid_fbm_product):
        """FBM月販売数境界テスト: 2個/3個"""
        valid_fbm_product.is_fba = False

        # 推定3個以上 → 通過
        valid_fbm_product.bsr = 100000  # 推定10個/月
        result = product_filter.check_sales(valid_fbm_product)
        assert result.passed is True

    # ============================================
    # BSR未取得テスト
    # ============================================

    def test_bsr_zero_fails(self, product_filter, valid_fba_product):
        """BSR 0の場合は不通過"""
        valid_fba_product.bsr = 0
        result = product_filter.check_sales(valid_fba_product)
        assert result.passed is False
        assert "BSR未取得" in result.reason

    # ============================================
    # 複合フィルタテスト
    # ============================================

    def test_check_all_pass(self, product_filter, valid_fba_product):
        """全条件を満たす商品は通過"""
        result = product_filter.check(valid_fba_product)
        assert result.passed is True

    def test_check_price_fail(self, product_filter, valid_fba_product):
        """価格フィルタで不通過"""
        valid_fba_product.price = 1000
        result = product_filter.check(valid_fba_product)
        assert result.passed is False
        assert "価格" in result.reason

    def test_check_reviews_fail(self, product_filter, valid_fba_product):
        """レビュー数フィルタで不通過"""
        valid_fba_product.review_count = 100
        result = product_filter.check(valid_fba_product)
        assert result.passed is False
        assert "レビュー数" in result.reason

    def test_check_sales_fail(self, product_filter, valid_fba_product):
        """BSRフィルタまたは販売数フィルタで不通過"""
        valid_fba_product.bsr = 900000
        result = product_filter.check(valid_fba_product)
        assert result.passed is False
        # BSRフィルタか販売数関連の理由
        assert "BSR" in result.reason or "FBA月売上" in result.reason or "FBM月販売数" in result.reason

    # ============================================
    # フィルタリングテスト
    # ============================================

    def test_filter_multiple_products(self, product_filter):
        """複数商品のフィルタリング"""
        products = [
            # 通過する商品
            ProductDetail(
                asin="B001", title="OK商品", price=2000,
                image_url="", bsr=5000, category="", review_count=20,
                is_fba=True, product_url="", rating=3.5,
            ),
            # 価格で不通過
            ProductDetail(
                asin="B002", title="安すぎ", price=1000,
                image_url="", bsr=5000, category="", review_count=20,
                is_fba=True, product_url="", rating=3.5,
            ),
            # レビューで不通過
            ProductDetail(
                asin="B003", title="レビュー多", price=2000,
                image_url="", bsr=5000, category="", review_count=100,
                is_fba=True, product_url="", rating=3.5,
            ),
            # 通過する商品
            ProductDetail(
                asin="B004", title="OK商品2", price=3000,
                image_url="", bsr=10000, category="", review_count=10,
                is_fba=True, product_url="", rating=3.8,
            ),
        ]

        filtered = product_filter.filter(products)

        # 2件通過
        assert len(filtered) == 2
        asins = [p.asin for p in filtered]
        assert "B001" in asins
        assert "B004" in asins

    def test_filter_with_details(self, product_filter, valid_fba_product):
        """フィルタリングと詳細結果の取得"""
        products = [valid_fba_product]
        results = product_filter.filter_with_details(products)

        assert len(results) == 1
        product, filter_result = results[0]
        assert product.asin == valid_fba_product.asin
        assert filter_result.passed is True
        assert filter_result.estimated_monthly_sales > 0
        assert filter_result.estimated_monthly_revenue > 0


class TestProductFilterRequirements:
    """要件定義に基づくテスト（FR-201〜FR-204）"""

    @pytest.fixture
    def product_filter(self):
        return ProductFilter()

    def test_fr201_price_filter(self, product_filter):
        """FR-201: 価格1,500円以上4,000円以下の商品のみ抽出"""
        product = ProductDetail(
            asin="TEST", title="", price=1500,
            image_url="", bsr=5000, category="",
            review_count=20, is_fba=True, product_url="", rating=3.5,
        )

        # 1500円 → 通過
        assert product_filter.check_min_price(product) is True

        # 1499円 → 不通過
        product.price = 1499
        assert product_filter.check_min_price(product) is False

        # 4000円 → 通過
        product.price = 4000
        assert product_filter.check_max_price(product) is True

        # 4001円 → 不通過
        product.price = 4001
        assert product_filter.check_max_price(product) is False

    def test_fr202_review_filter(self, product_filter):
        """FR-202: レビュー50件以下の商品のみ抽出"""
        product = ProductDetail(
            asin="TEST", title="", price=2000,
            image_url="", bsr=5000, category="",
            review_count=50, is_fba=True, product_url="", rating=3.5,
        )

        # 50件 → 通過
        assert product_filter.check_reviews(product) is True

        # 51件 → 不通過
        product.review_count = 51
        assert product_filter.check_reviews(product) is False

    def test_fr203_fba_sales_filter(self, product_filter):
        """FR-203: FBA月売上2万円以上の商品のみ抽出"""
        product = ProductDetail(
            asin="TEST", title="", price=2000,
            image_url="", bsr=5000, category="",
            review_count=20, is_fba=True, product_url="", rating=3.5,
        )

        result = product_filter.check_sales(product)
        assert result.estimated_monthly_revenue >= 20000

    def test_fr204_fbm_sales_filter(self, product_filter):
        """FR-204: FBM月3個以上の商品のみ抽出"""
        product = ProductDetail(
            asin="TEST", title="", price=2000,
            image_url="", bsr=30000, category="",
            review_count=20, is_fba=False, product_url="", rating=3.5,
        )

        result = product_filter.check_sales(product)
        assert result.estimated_monthly_sales >= 3


class TestCategoryKeywordFilter:
    """カテゴリ・キーワードフィルタのテストクラス"""

    @pytest.fixture
    def filter_config_with_exclusions(self):
        """除外カテゴリ・禁止キーワード付き設定"""
        return FilterConfig(
            min_price=1500,
            max_price=4000,
            max_reviews=50,
            max_rating=4.2,
            min_bsr=5000,
            max_bsr=50000,
            fba_min_monthly_sales=20000,
            fbm_min_monthly_units=3,
            excluded_categories=[
                "ファッション",
                "ビューティー",
                "食品",
                "おもちゃ",
                "ベビー&マタニティ",
            ],
            prohibited_keywords=[
                "ピアス",
                "ネックレス",
                "バッグ",
                "食器",
                "充電器",
                "コンセント",
            ],
        )

    @pytest.fixture
    def product_filter_with_exclusions(self, filter_config_with_exclusions):
        return ProductFilter(config=filter_config_with_exclusions)

    # ============================================
    # カテゴリフィルタテスト
    # ============================================

    def test_category_home_kitchen_passes(self, product_filter_with_exclusions):
        """ホーム＆キッチンカテゴリは通過"""
        product = ProductDetail(
            asin="B08OK001", title="キッチン収納ラック", price=2000,
            image_url="", bsr=5000, category="ホーム＆キッチン",
            review_count=20, is_fba=True, product_url="", rating=3.5,
        )
        passed, _ = product_filter_with_exclusions.check_category(product)
        assert passed is True

    def test_category_fashion_excluded(self, product_filter_with_exclusions):
        """ファッションカテゴリは除外"""
        product = ProductDetail(
            asin="B08NG001", title="おしゃれなTシャツ", price=2000,
            image_url="", bsr=5000, category="ファッション",
            review_count=20, is_fba=True, product_url="", rating=3.5,
        )
        passed, matched = product_filter_with_exclusions.check_category(product)
        assert passed is False
        assert "ファッション" in matched

    def test_category_beauty_excluded(self, product_filter_with_exclusions):
        """ビューティーカテゴリは除外"""
        product = ProductDetail(
            asin="B08NG002", title="化粧品セット", price=2500,
            image_url="", bsr=8000, category="ビューティー",
            review_count=15, is_fba=True, product_url="", rating=4.0,
        )
        passed, matched = product_filter_with_exclusions.check_category(product)
        assert passed is False
        assert "ビューティー" in matched

    def test_category_food_excluded(self, product_filter_with_exclusions):
        """食品カテゴリは除外"""
        product = ProductDetail(
            asin="B08NG003", title="おいしいお菓子", price=1800,
            image_url="", bsr=3000, category="食品・飲料・お酒",
            review_count=50, is_fba=True, product_url="", rating=4.0,
        )
        passed, matched = product_filter_with_exclusions.check_category(product)
        assert passed is False
        assert "食品" in matched

    def test_category_toys_excluded(self, product_filter_with_exclusions):
        """おもちゃカテゴリは除外（食品衛生法）"""
        product = ProductDetail(
            asin="B08NG004", title="子供用ブロック", price=2000,
            image_url="", bsr=5000, category="おもちゃ",
            review_count=30, is_fba=True, product_url="", rating=3.8,
        )
        passed, matched = product_filter_with_exclusions.check_category(product)
        assert passed is False
        assert "おもちゃ" in matched

    def test_category_baby_excluded(self, product_filter_with_exclusions):
        """ベビー＆マタニティカテゴリは除外"""
        product = ProductDetail(
            asin="B08NG005", title="ベビー用品", price=2500,
            image_url="", bsr=6000, category="ベビー&マタニティ",
            review_count=20, is_fba=True, product_url="", rating=3.5,
        )
        passed, matched = product_filter_with_exclusions.check_category(product)
        assert passed is False
        assert "ベビー&マタニティ" in matched

    def test_category_case_insensitive(self, product_filter_with_exclusions):
        """カテゴリチェックは大文字小文字を区別しない"""
        product = ProductDetail(
            asin="B08NG006", title="テスト", price=2000,
            image_url="", bsr=5000, category="ファッション小物",
            review_count=20, is_fba=True, product_url="", rating=3.5,
        )
        passed, _ = product_filter_with_exclusions.check_category(product)
        assert passed is False

    # ============================================
    # 禁止キーワードフィルタテスト
    # ============================================

    def test_keyword_normal_title_passes(self, product_filter_with_exclusions):
        """通常のタイトルは通過"""
        product = ProductDetail(
            asin="B08OK002", title="収納ボックス 折りたたみ式", price=2000,
            image_url="", bsr=5000, category="ホーム＆キッチン",
            review_count=20, is_fba=True, product_url="", rating=3.5,
        )
        passed, _ = product_filter_with_exclusions.check_prohibited_keywords(product)
        assert passed is True

    def test_keyword_earring_excluded(self, product_filter_with_exclusions):
        """ピアスを含むタイトルは除外"""
        product = ProductDetail(
            asin="B08NG007", title="シルバーピアス レディース", price=2000,
            image_url="", bsr=5000, category="ジュエリー",
            review_count=10, is_fba=True, product_url="", rating=4.0,
        )
        passed, matched = product_filter_with_exclusions.check_prohibited_keywords(product)
        assert passed is False
        assert "ピアス" in matched

    def test_keyword_necklace_excluded(self, product_filter_with_exclusions):
        """ネックレスを含むタイトルは除外"""
        product = ProductDetail(
            asin="B08NG008", title="パールネックレス 冠婚葬祭", price=3000,
            image_url="", bsr=8000, category="ジュエリー",
            review_count=15, is_fba=True, product_url="", rating=3.8,
        )
        passed, matched = product_filter_with_exclusions.check_prohibited_keywords(product)
        assert passed is False
        assert "ネックレス" in matched

    def test_keyword_bag_excluded(self, product_filter_with_exclusions):
        """バッグを含むタイトルは除外"""
        product = ProductDetail(
            asin="B08NG009", title="ショルダーバッグ レザー", price=3500,
            image_url="", bsr=10000, category="シューズ&バッグ",
            review_count=25, is_fba=True, product_url="", rating=4.0,
        )
        passed, matched = product_filter_with_exclusions.check_prohibited_keywords(product)
        assert passed is False
        assert "バッグ" in matched

    def test_keyword_tableware_excluded(self, product_filter_with_exclusions):
        """食器を含むタイトルは除外（食品衛生法）"""
        product = ProductDetail(
            asin="B08NG010", title="陶器食器セット 北欧風", price=2500,
            image_url="", bsr=6000, category="ホーム＆キッチン",
            review_count=20, is_fba=True, product_url="", rating=3.5,
        )
        passed, matched = product_filter_with_exclusions.check_prohibited_keywords(product)
        assert passed is False
        assert "食器" in matched

    def test_keyword_charger_excluded(self, product_filter_with_exclusions):
        """充電器を含むタイトルは除外（PSE対象）"""
        product = ProductDetail(
            asin="B08NG011", title="USB充電器 急速充電", price=1800,
            image_url="", bsr=3000, category="家電&カメラ",
            review_count=50, is_fba=True, product_url="", rating=4.0,
        )
        passed, matched = product_filter_with_exclusions.check_prohibited_keywords(product)
        assert passed is False
        assert "充電器" in matched

    def test_keyword_outlet_excluded(self, product_filter_with_exclusions):
        """コンセントを含むタイトルは除外（PSE対象）"""
        product = ProductDetail(
            asin="B08NG012", title="延長コード コンセント 4口", price=2000,
            image_url="", bsr=5000, category="家電&カメラ",
            review_count=30, is_fba=True, product_url="", rating=3.8,
        )
        passed, matched = product_filter_with_exclusions.check_prohibited_keywords(product)
        assert passed is False
        assert "コンセント" in matched

    def test_keyword_case_insensitive(self, product_filter_with_exclusions):
        """キーワードチェックは大文字小文字を区別しない"""
        product = ProductDetail(
            asin="B08NG013", title="USB CHARGER 充電器", price=2000,
            image_url="", bsr=5000, category="家電",
            review_count=20, is_fba=True, product_url="", rating=3.5,
        )
        passed, _ = product_filter_with_exclusions.check_prohibited_keywords(product)
        assert passed is False

    # ============================================
    # 複合フィルタテスト
    # ============================================

    def test_check_excludes_by_category(self, product_filter_with_exclusions):
        """全体checkでカテゴリ除外が機能する"""
        product = ProductDetail(
            asin="B08NG014", title="普通の商品名", price=2000,
            image_url="", bsr=5000, category="ビューティー",
            review_count=20, is_fba=True, product_url="", rating=3.5,
        )
        result = product_filter_with_exclusions.check(product)
        assert result.passed is False
        assert "除外カテゴリ" in result.reason

    def test_check_excludes_by_keyword(self, product_filter_with_exclusions):
        """全体checkで禁止キーワード除外が機能する"""
        product = ProductDetail(
            asin="B08NG015", title="おしゃれなネックレス", price=2000,
            image_url="", bsr=5000, category="ホーム＆キッチン",
            review_count=20, is_fba=True, product_url="", rating=3.5,
        )
        result = product_filter_with_exclusions.check(product)
        assert result.passed is False
        assert "禁止キーワード" in result.reason

    def test_filter_excludes_regulated_products(self, product_filter_with_exclusions):
        """フィルタリングで規制対象商品が除外される"""
        products = [
            # OK: ホームキッチン収納
            ProductDetail(
                asin="B001", title="収納ボックス", price=2000,
                image_url="", bsr=5000, category="ホーム＆キッチン",
                review_count=20, is_fba=True, product_url="", rating=3.5,
            ),
            # NG: ファッションカテゴリ
            ProductDetail(
                asin="B002", title="Tシャツ", price=2000,
                image_url="", bsr=5000, category="ファッション",
                review_count=20, is_fba=True, product_url="", rating=3.5,
            ),
            # NG: 禁止キーワード「ピアス」
            ProductDetail(
                asin="B003", title="シルバーピアス", price=2000,
                image_url="", bsr=5000, category="ホーム＆キッチン",
                review_count=20, is_fba=True, product_url="", rating=3.5,
            ),
            # NG: 禁止キーワード「充電器」
            ProductDetail(
                asin="B004", title="USB充電器", price=2000,
                image_url="", bsr=5000, category="ホーム＆キッチン",
                review_count=20, is_fba=True, product_url="", rating=3.5,
            ),
            # OK: スポーツ用品
            ProductDetail(
                asin="B005", title="ヨガマット", price=2500,
                image_url="", bsr=8000, category="スポーツ&アウトドア",
                review_count=15, is_fba=True, product_url="", rating=3.8,
            ),
        ]

        filtered = product_filter_with_exclusions.filter(products)

        assert len(filtered) == 2
        asins = [p.asin for p in filtered]
        assert "B001" in asins
        assert "B005" in asins
        assert "B002" not in asins  # ファッション除外
        assert "B003" not in asins  # ピアス除外
        assert "B004" not in asins  # 充電器除外


class TestLargeSizeFilter:
    """大型サイズフィルタのテストクラス"""

    @pytest.fixture
    def product_filter(self):
        return ProductFilter()

    @pytest.fixture
    def standard_size_product(self):
        """標準サイズの商品（フィルタ通過）"""
        return ProductDetail(
            asin="B08STANDARD",
            title="標準サイズ商品",
            price=2000,
            image_url="https://example.com/image.jpg",
            bsr=5000,
            category="ホーム＆キッチン",
            review_count=20,
            is_fba=True,
            product_url="https://www.amazon.co.jp/dp/B08STANDARD",
            rating=3.8,
            dimensions=(30.0, 25.0, 15.0),  # 合計70cm < 100cm
            weight_kg=2.0,  # 2kg < 9kg
        )

    @pytest.fixture
    def large_size_product_by_dimensions(self):
        """大型サイズの商品（寸法で判定）"""
        return ProductDetail(
            asin="B08LARGE01",
            title="大型商品（寸法）",
            price=2500,
            image_url="https://example.com/image.jpg",
            bsr=8000,
            category="ホーム＆キッチン",
            review_count=15,
            is_fba=True,
            product_url="https://www.amazon.co.jp/dp/B08LARGE01",
            rating=4.0,
            dimensions=(50.0, 40.0, 20.0),  # 合計110cm > 100cm
            weight_kg=3.0,  # 重量は問題なし
        )

    @pytest.fixture
    def large_size_product_by_weight(self):
        """大型サイズの商品（重量で判定）"""
        return ProductDetail(
            asin="B08LARGE02",
            title="大型商品（重量）",
            price=2500,
            image_url="https://example.com/image.jpg",
            bsr=8000,
            category="ホーム＆キッチン",
            review_count=15,
            is_fba=True,
            product_url="https://www.amazon.co.jp/dp/B08LARGE02",
            rating=4.0,
            dimensions=(30.0, 20.0, 10.0),  # 合計60cm 寸法は問題なし
            weight_kg=12.0,  # 12kg > 9kg
        )

    # ============================================
    # 大型サイズ判定テスト
    # ============================================

    def test_standard_size_passes_filter(self, product_filter, standard_size_product):
        """標準サイズ商品はフィルタを通過する"""
        assert product_filter.check_size(standard_size_product) is True

    def test_large_size_by_dimensions_fails_filter(self, product_filter, large_size_product_by_dimensions):
        """寸法が大型基準を超える商品はフィルタで除外"""
        assert product_filter.check_size(large_size_product_by_dimensions) is False

    def test_large_size_by_weight_fails_filter(self, product_filter, large_size_product_by_weight):
        """重量が大型基準を超える商品はフィルタで除外"""
        assert product_filter.check_size(large_size_product_by_weight) is False

    def test_dimensions_boundary_100cm(self, product_filter):
        """境界値テスト: 寸法合計100cmはOK、101cmはNG"""
        # 合計100cm（40+35+25）→ OK
        product_100 = ProductDetail(
            asin="B08BOUND100", title="境界100cm", price=2000,
            image_url="", bsr=5000, category="", review_count=20,
            is_fba=True, product_url="", rating=3.5,
            dimensions=(40.0, 35.0, 25.0),  # 合計100cm
            weight_kg=2.0,
        )
        assert product_filter.check_size(product_100) is True
        assert product_100.is_large_size is False

        # 合計100.1cm → NG
        product_101 = ProductDetail(
            asin="B08BOUND101", title="境界101cm", price=2000,
            image_url="", bsr=5000, category="", review_count=20,
            is_fba=True, product_url="", rating=3.5,
            dimensions=(40.0, 35.0, 25.1),  # 合計100.1cm
            weight_kg=2.0,
        )
        assert product_filter.check_size(product_101) is False
        assert product_101.is_large_size is True

    def test_weight_boundary_9kg(self, product_filter):
        """境界値テスト: 重量9kgはOK、9.1kgはNG"""
        # 9kg → OK
        product_9kg = ProductDetail(
            asin="B08BOUND9KG", title="境界9kg", price=2000,
            image_url="", bsr=5000, category="", review_count=20,
            is_fba=True, product_url="", rating=3.5,
            dimensions=(30.0, 20.0, 10.0),
            weight_kg=9.0,
        )
        assert product_filter.check_size(product_9kg) is True
        assert product_9kg.is_large_size is False

        # 9.1kg → NG
        product_over9kg = ProductDetail(
            asin="B08BOUND9KG2", title="境界9.1kg", price=2000,
            image_url="", bsr=5000, category="", review_count=20,
            is_fba=True, product_url="", rating=3.5,
            dimensions=(30.0, 20.0, 10.0),
            weight_kg=9.1,
        )
        assert product_filter.check_size(product_over9kg) is False
        assert product_over9kg.is_large_size is True

    def test_no_dimensions_no_weight_passes(self, product_filter):
        """寸法・重量が不明な場合は通過する（後でチェック可能）"""
        product_unknown = ProductDetail(
            asin="B08UNKNOWN", title="不明商品", price=2000,
            image_url="", bsr=5000, category="", review_count=20,
            is_fba=True, product_url="", rating=3.5,
            dimensions=None,  # 不明
            weight_kg=None,   # 不明
        )
        assert product_filter.check_size(product_unknown) is True
        assert product_unknown.is_large_size is False

    def test_only_dimensions_known_large(self, product_filter):
        """寸法のみ判明で大型の場合"""
        product = ProductDetail(
            asin="B08DIMONLY", title="寸法のみ大型", price=2000,
            image_url="", bsr=5000, category="", review_count=20,
            is_fba=True, product_url="", rating=3.5,
            dimensions=(50.0, 40.0, 20.0),  # 合計110cm > 100cm
            weight_kg=None,  # 重量不明
        )
        assert product_filter.check_size(product) is False
        assert product.is_large_size is True

    def test_only_weight_known_large(self, product_filter):
        """重量のみ判明で大型の場合"""
        product = ProductDetail(
            asin="B08WTONLY", title="重量のみ大型", price=2000,
            image_url="", bsr=5000, category="", review_count=20,
            is_fba=True, product_url="", rating=3.5,
            dimensions=None,  # 寸法不明
            weight_kg=15.0,  # 15kg > 9kg
        )
        assert product_filter.check_size(product) is False
        assert product.is_large_size is True

    # ============================================
    # 複合フィルタテスト（大型サイズ含む）
    # ============================================

    def test_check_rejects_large_size(self, product_filter, large_size_product_by_dimensions):
        """全体checkで大型商品が除外される"""
        result = product_filter.check(large_size_product_by_dimensions)
        assert result.passed is False
        assert "大型サイズ" in result.reason

    def test_filter_excludes_large_products(self, product_filter):
        """フィルタリングで大型商品が除外される"""
        products = [
            # 標準サイズ（通過）
            ProductDetail(
                asin="B001", title="標準サイズ", price=2000,
                image_url="", bsr=5000, category="", review_count=20,
                is_fba=True, product_url="", rating=3.5,
                dimensions=(30.0, 20.0, 15.0),  # 65cm
                weight_kg=2.0,
            ),
            # 大型サイズ（寸法で除外）
            ProductDetail(
                asin="B002", title="大型（寸法）", price=2000,
                image_url="", bsr=5000, category="", review_count=20,
                is_fba=True, product_url="", rating=3.5,
                dimensions=(60.0, 30.0, 20.0),  # 110cm > 100cm
                weight_kg=3.0,
            ),
            # 大型サイズ（重量で除外）
            ProductDetail(
                asin="B003", title="大型（重量）", price=2000,
                image_url="", bsr=5000, category="", review_count=20,
                is_fba=True, product_url="", rating=3.5,
                dimensions=(30.0, 20.0, 15.0),  # 65cm
                weight_kg=10.0,  # 10kg > 9kg
            ),
            # 標準サイズ（通過）
            ProductDetail(
                asin="B004", title="標準サイズ2", price=2500,
                image_url="", bsr=8000, category="", review_count=15,
                is_fba=True, product_url="", rating=3.8,
                dimensions=(25.0, 20.0, 10.0),  # 55cm
                weight_kg=1.5,
            ),
        ]

        filtered = product_filter.filter(products)

        # 2件通過（大型の2件が除外される）
        assert len(filtered) == 2
        asins = [p.asin for p in filtered]
        assert "B001" in asins
        assert "B004" in asins
        assert "B002" not in asins
        assert "B003" not in asins
