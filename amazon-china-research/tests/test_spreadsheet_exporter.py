"""SpreadsheetExporter のテスト"""
import csv
import tempfile
from pathlib import Path

import pytest

from src.output.spreadsheet_exporter import SpreadsheetExporter
from src.models.product import ProductDetail, AlibabaProduct
from src.models.result import ProfitResult, ResearchResult


@pytest.fixture
def sample_results():
    """テスト用のリサーチ結果リスト"""
    # Amazon商品
    amazon_product = ProductDetail(
        asin="B0TEST001",
        title="テスト商品1 - キッチン用品",
        price=2500,  # ライバル価格
        image_url="https://images-na.ssl-images-amazon.com/images/I/test1.jpg",
        bsr=5000,
        category="ホーム＆キッチン",
        review_count=30,
        is_fba=True,
        product_url="https://www.amazon.co.jp/dp/B0TEST001",
        rating=3.5,
        variation_count=3,
    )

    # アリババ商品
    alibaba_product = AlibabaProduct(
        price_cny=35.0,
        image_url="https://cbu01.alicdn.com/img/test1.jpg",
        product_url="https://detail.1688.com/offer/123456.html",
        shop_name="テストショップ",
        shop_url="https://shop1688.1688.com/page/index.htm",
    )

    # 利益計算結果
    # 総コスト: 仕入805 + 送料115 + 関税92 + 紹介料375 + FBA434 = 1821円
    profit_result = ProfitResult(
        amazon_price=2500,
        cost_1688_jpy=805,  # 35元 × 23円/元
        shipping=115,
        customs=92,
        referral_fee=375,  # 2500 × 0.15
        fba_fee=434,
        total_cost=1821,
        profit=679,  # 2500 - 1821
        profit_rate=0.2716,  # 679/2500
        is_profitable=True,
    )

    # リサーチ結果
    result = ResearchResult(
        amazon_product=amazon_product,
        alibaba_product=alibaba_product,
        profit_result=profit_result,
        estimated_monthly_sales=50,
        estimated_monthly_revenue=125000,  # 2500 × 50
    )

    return [result]


@pytest.fixture
def temp_output_dir():
    """一時出力ディレクトリ"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestSpreadsheetExporter:
    """SpreadsheetExporter のテスト"""

    def test_export_creates_csv_file(self, sample_results, temp_output_dir):
        """CSVファイルが作成されること"""
        exporter = SpreadsheetExporter(output_dir=temp_output_dir)
        filepath = exporter.export(sample_results, keyword="テスト")

        assert filepath.exists()
        assert filepath.suffix == ".csv"
        assert "spreadsheet_" in filepath.name

    def test_export_headers(self, sample_results, temp_output_dir):
        """正しいヘッダーが出力されること"""
        exporter = SpreadsheetExporter(output_dir=temp_output_dir)
        filepath = exporter.export(sample_results, keyword="テスト")

        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames

        expected_headers = [
            "No.",
            "Amazon商品画像",
            "商品ページURL",
            "1688ショップURL",
            "販売価格（円）",
            "アリババ原単価（円）",
            "利益率（%）",
            "利幅（円）",
        ]
        assert headers == expected_headers

    def test_export_selling_price_minus_10(self, sample_results, temp_output_dir):
        """販売価格がライバル価格-10円になっていること"""
        exporter = SpreadsheetExporter(output_dir=temp_output_dir)
        filepath = exporter.export(sample_results, keyword="テスト")

        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            row = next(reader)

        # ライバル価格2500円 - 10円 = 2490円
        assert int(row["販売価格（円）"]) == 2490

    def test_export_alibaba_price_jpy(self, sample_results, temp_output_dir):
        """アリババ原単価（円）が正しく変換されていること"""
        exporter = SpreadsheetExporter(output_dir=temp_output_dir)
        filepath = exporter.export(sample_results, keyword="テスト")

        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            row = next(reader)

        # 35元 × 23円/元 = 805円
        assert int(row["アリババ原単価（円）"]) == 805

    def test_export_profit_calculation_with_adjustment(self, sample_results, temp_output_dir):
        """利幅と利益率が販売価格-10円で計算されていること"""
        exporter = SpreadsheetExporter(output_dir=temp_output_dir)
        filepath = exporter.export(sample_results, keyword="テスト")

        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            row = next(reader)

        selling_price = 2490  # 2500 - 10
        total_cost = 1821
        expected_profit_margin = selling_price - total_cost  # 669円
        expected_profit_rate = expected_profit_margin / selling_price * 100  # 26.9%

        assert int(row["利幅（円）"]) == expected_profit_margin
        assert float(row["利益率（%）"]) == pytest.approx(expected_profit_rate, rel=0.01)

    def test_export_image_url(self, sample_results, temp_output_dir):
        """Amazon商品画像URLが正しく出力されること"""
        exporter = SpreadsheetExporter(output_dir=temp_output_dir)
        filepath = exporter.export(sample_results, keyword="テスト")

        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            row = next(reader)

        assert row["Amazon商品画像"] == "https://images-na.ssl-images-amazon.com/images/I/test1.jpg"

    def test_export_product_url(self, sample_results, temp_output_dir):
        """商品ページURLが正しく出力されること"""
        exporter = SpreadsheetExporter(output_dir=temp_output_dir)
        filepath = exporter.export(sample_results, keyword="テスト")

        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            row = next(reader)

        assert row["商品ページURL"] == "https://www.amazon.co.jp/dp/B0TEST001"

    def test_export_shop_url(self, sample_results, temp_output_dir):
        """1688ショップURLが正しく出力されること"""
        exporter = SpreadsheetExporter(output_dir=temp_output_dir)
        filepath = exporter.export(sample_results, keyword="テスト")

        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            row = next(reader)

        assert row["1688ショップURL"] == "https://shop1688.1688.com/page/index.htm"

    def test_export_custom_price_adjustment(self, sample_results, temp_output_dir):
        """カスタム価格調整が適用されること"""
        # -20円の調整
        exporter = SpreadsheetExporter(output_dir=temp_output_dir, price_adjustment=-20)
        filepath = exporter.export(sample_results, keyword="テスト")

        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            row = next(reader)

        # 2500 - 20 = 2480
        assert int(row["販売価格（円）"]) == 2480

    def test_export_multiple_results(self, temp_output_dir):
        """複数の結果が正しく出力されること"""
        results = []
        for i in range(3):
            amazon_product = ProductDetail(
                asin=f"B0TEST00{i}",
                title=f"テスト商品{i}",
                price=2000 + i * 500,
                image_url=f"https://images.amazon.com/test{i}.jpg",
                bsr=5000,
                category="ホーム＆キッチン",
                review_count=10,
                is_fba=True,
                product_url=f"https://www.amazon.co.jp/dp/B0TEST00{i}",
                rating=4.0,
            )
            alibaba_product = AlibabaProduct(
                price_cny=30.0 + i * 5,
                image_url=f"https://cbu01.alicdn.com/img/test{i}.jpg",
                product_url=f"https://detail.1688.com/offer/{i}.html",
                shop_url=f"https://shop{i}.1688.com",
            )
            profit_result = ProfitResult(
                amazon_price=2000 + i * 500,
                cost_1688_jpy=690 + i * 115,
                shipping=115,
                customs=80,
                referral_fee=300 + i * 75,
                fba_fee=434,
                total_cost=1619 + i * 190,
                profit=381 + i * 310,
                profit_rate=0.19 + i * 0.05,
                is_profitable=True,
            )
            results.append(ResearchResult(
                amazon_product=amazon_product,
                alibaba_product=alibaba_product,
                profit_result=profit_result,
                estimated_monthly_sales=50,
                estimated_monthly_revenue=(2000 + i * 500) * 50,
            ))

        exporter = SpreadsheetExporter(output_dir=temp_output_dir)
        filepath = exporter.export(results, keyword="複数テスト")

        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 3
        assert rows[0]["No."] == "1"
        assert rows[1]["No."] == "2"
        assert rows[2]["No."] == "3"

    def test_export_detailed(self, sample_results, temp_output_dir):
        """詳細版出力が正しく動作すること"""
        exporter = SpreadsheetExporter(output_dir=temp_output_dir)
        filepath = exporter.export_detailed(sample_results, keyword="詳細テスト")

        assert filepath.exists()
        assert "detailed_" in filepath.name

        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            row = next(reader)

        # 詳細版のヘッダーを確認
        assert "ASIN" in headers
        assert "商品タイトル" in headers
        assert "ライバル価格（円）" in headers
        assert "総コスト（円）" in headers
        assert "レビュー数" in headers
        assert "バリエーション数" in headers

        # 値を確認
        assert row["ASIN"] == "B0TEST001"
        assert int(row["ライバル価格（円）"]) == 2500
        assert int(row["販売価格（円）"]) == 2490

    def test_export_empty_shop_url(self, temp_output_dir):
        """shop_urlがNoneの場合でも正しく出力されること"""
        amazon_product = ProductDetail(
            asin="B0TEST002",
            title="テスト商品2",
            price=3000,
            image_url="https://images.amazon.com/test2.jpg",
            bsr=10000,
            category="おもちゃ",
            review_count=20,
            is_fba=True,
            product_url="https://www.amazon.co.jp/dp/B0TEST002",
            rating=4.0,
        )
        alibaba_product = AlibabaProduct(
            price_cny=40.0,
            image_url="https://cbu01.alicdn.com/img/test2.jpg",
            product_url="https://detail.1688.com/offer/654321.html",
            shop_url=None,  # ショップURLなし
        )
        profit_result = ProfitResult(
            amazon_price=3000,
            cost_1688_jpy=920,
            shipping=115,
            customs=104,
            referral_fee=300,
            fba_fee=434,
            total_cost=1873,
            profit=1127,
            profit_rate=0.376,
            is_profitable=True,
        )
        result = ResearchResult(
            amazon_product=amazon_product,
            alibaba_product=alibaba_product,
            profit_result=profit_result,
            estimated_monthly_sales=30,
            estimated_monthly_revenue=90000,
        )

        exporter = SpreadsheetExporter(output_dir=temp_output_dir)
        filepath = exporter.export([result], keyword="空URL")

        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            row = next(reader)

        assert row["1688ショップURL"] == ""
