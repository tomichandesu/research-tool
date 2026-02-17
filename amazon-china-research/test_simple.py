#!/usr/bin/env python
"""シンプルモジュールテスト（非対話・エンコーディング対応）"""
from __future__ import annotations

import asyncio
import sys
import os
from pathlib import Path

# UTF-8出力を強制
if sys.platform == 'win32':
    os.system('chcp 65001 >nul 2>&1')
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent))


def test_profit_calculator():
    """利益計算テスト"""
    from src.modules.calculator.profit import ProfitCalculator

    print("\n" + "=" * 60)
    print("利益計算テスト")
    print("=" * 60)

    calc = ProfitCalculator()

    # サンプル計算（販売価格2500円、仕入れ50元）
    result = calc.calculate(
        amazon_price=2500,
        cny_price=50.0,
        is_fba=True,
        category="home_kitchen",
        weight_kg=0.5,
        dimensions=(20, 15, 10),
    )

    print(f"\n販売価格: {result.amazon_price}円")
    print(f"仕入原価: {result.cost_1688_jpy}円")
    print(f"国際送料: {result.shipping}円")
    print(f"関税: {result.customs}円")
    print(f"紹介料: {result.referral_fee}円")
    print(f"FBA手数料: {result.fba_fee}円")
    print(f"総コスト: {result.total_cost}円")
    print(f"利益: {result.profit}円")
    print(f"利益率: {result.profit_rate_percentage:.1f}%")
    print(f"収益性: {'あり' if result.is_profitable else 'なし'}")

    return result


def test_filter():
    """フィルタテスト"""
    from src.modules.amazon.filter import ProductFilter
    from src.models.product import ProductDetail

    print("\n" + "=" * 60)
    print("フィルタテスト")
    print("=" * 60)

    # テスト用商品データ
    good_product = ProductDetail(
        asin="B001234567",
        title="収納ボックス 折りたたみ式",
        price=2500,
        image_url="https://example.com/image.jpg",
        bsr=15000,
        category="ホーム&キッチン",
        review_count=30,
        is_fba=True,
        product_url="https://amazon.co.jp/dp/B001234567",
        rating=3.8,
        variation_count=3,
        dimensions=(30, 20, 15),
        weight_kg=0.8,
    )

    bad_product_fashion = ProductDetail(
        asin="B009999999",
        title="おしゃれバッグ レディース",
        price=3000,
        image_url="https://example.com/bag.jpg",
        bsr=5000,
        category="ファッション",
        review_count=10,
        is_fba=True,
        product_url="https://amazon.co.jp/dp/B009999999",
        variation_count=2,
    )

    bad_product_large = ProductDetail(
        asin="B008888888",
        title="大型収納ケース",
        price=3500,
        image_url="https://example.com/large.jpg",
        bsr=8000,
        category="ホーム&キッチン",
        review_count=20,
        is_fba=True,
        product_url="https://amazon.co.jp/dp/B008888888",
        variation_count=1,
        dimensions=(50, 40, 30),  # 合計120cm > 100cm
        weight_kg=5.0,
    )

    product_filter = ProductFilter()

    print("\n--- 正常商品 ---")
    result1 = product_filter.check(good_product)
    print(f"商品: {good_product.title[:20]}...")
    print(f"結果: {'通過' if result1.passed else '除外'}")
    if result1.passed:
        print(f"推定月間販売: {result1.estimated_monthly_sales}個")

    print("\n--- ファッション商品（除外対象） ---")
    result2 = product_filter.check(bad_product_fashion)
    print(f"商品: {bad_product_fashion.title[:20]}...")
    print(f"結果: {'通過' if result2.passed else '除外'}")
    if not result2.passed:
        print(f"除外理由: {result2.reason}")

    print("\n--- 大型商品（除外対象） ---")
    result3 = product_filter.check(bad_product_large)
    print(f"商品: {bad_product_large.title[:20]}...")
    print(f"結果: {'通過' if result3.passed else '除外'}")
    if not result3.passed:
        print(f"除外理由: {result3.reason}")


async def test_amazon_search():
    """Amazon検索テスト（ブラウザ表示）"""
    from src.utils.browser import BrowserManager
    from src.modules.amazon.searcher import AmazonSearcher

    print("\n" + "=" * 60)
    print("Amazon検索テスト")
    print("=" * 60)

    browser = BrowserManager(headless=False, timeout=30000, request_delay=2.0)

    try:
        async with browser.browser_session():
            searcher = AmazonSearcher(browser)
            results = await searcher.search("収納ボックス", max_pages=1)

            print(f"\n検索結果: {len(results)}件")

            for i, r in enumerate(results[:5], 1):
                title = r['title'][:35] if r['title'] else 'N/A'
                print(f"{i}. [{r['asin']}] {title}... - {r['price']}円")

            return results
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return []


async def main():
    """メイン"""
    print("=" * 60)
    print("Amazon-1688 リサーチツール モジュールテスト")
    print("=" * 60)

    # 1. 利益計算テスト（ブラウザ不要）
    test_profit_calculator()

    # 2. フィルタテスト（ブラウザ不要）
    test_filter()

    # 3. Amazon検索テスト（ブラウザ必要）
    print("\n" + "=" * 60)
    print("Amazon検索テストを実行しますか？（ブラウザが起動します）")
    print("自動でスキップします...")
    print("=" * 60)

    # 非対話モードでは検索テストをスキップ
    # await test_amazon_search()

    print("\n" + "=" * 60)
    print("テスト完了!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
