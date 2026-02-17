#!/usr/bin/env python
"""モジュール動作テストスクリプト

各モジュールを個別にテストして動作確認する。
ログイン不要で実行可能。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.utils.browser import BrowserManager
from src.modules.amazon.searcher import AmazonSearcher
from src.modules.amazon.scraper import AmazonScraper
from src.modules.amazon.filter import ProductFilter
from src.modules.alibaba.image_search import AlibabaImageSearcher
from src.modules.matcher.phash import ImageMatcher
from src.modules.calculator.profit import ProfitCalculator
from src.config import get_config


async def test_amazon_search():
    """Amazon検索テスト"""
    print("\n" + "=" * 60)
    print("1. Amazon検索テスト")
    print("=" * 60)

    browser = BrowserManager(headless=False, timeout=30000, request_delay=2.0)

    try:
        async with browser.browser_session():
            searcher = AmazonSearcher(browser)
            results = await searcher.search("収納ボックス", max_pages=1)

            print(f"\n検索結果: {len(results)}件")

            for i, r in enumerate(results[:5], 1):
                print(f"\n{i}. {r['asin']}")
                print(f"   タイトル: {r['title'][:40]}...")
                print(f"   価格: ¥{r['price']}")
                print(f"   レビュー: {r['review_count']}")

            return results
    except Exception as e:
        print(f"エラー: {e}")
        return []


async def test_amazon_scraper(asin: str):
    """Amazon商品詳細取得テスト"""
    print("\n" + "=" * 60)
    print(f"2. Amazon商品詳細テスト: {asin}")
    print("=" * 60)

    browser = BrowserManager(headless=False, timeout=30000, request_delay=2.0)

    try:
        async with browser.browser_session():
            scraper = AmazonScraper(browser, use_fba_simulator=False)
            product = await scraper.get_product_detail(asin)

            if product:
                print(f"\nASIN: {product.asin}")
                print(f"タイトル: {product.title[:50]}...")
                print(f"価格: ¥{product.price}")
                print(f"BSR: {product.bsr} ({product.category})")
                print(f"レビュー: {product.review_count}")
                print(f"評価: {product.rating}")
                print(f"FBA: {'Yes' if product.is_fba else 'No'}")
                print(f"バリエーション: {product.variation_count}")
                print(f"寸法: {product.dimensions}")
                print(f"重量: {product.weight_kg}kg")
                return product
            else:
                print("商品情報を取得できませんでした")
                return None
    except Exception as e:
        print(f"エラー: {e}")
        return None


async def test_filter(product):
    """フィルタテスト"""
    print("\n" + "=" * 60)
    print("3. フィルタテスト")
    print("=" * 60)

    if not product:
        print("商品データがありません")
        return

    product_filter = ProductFilter()
    result = product_filter.check(product)

    print(f"\nフィルタ結果: {'通過' if result.is_valid else '除外'}")
    if not result.is_valid:
        print(f"除外理由: {result.rejection_reason}")
    else:
        print(f"推定月間販売数: {result.estimated_monthly_sales}")
        print(f"推定月間売上: ¥{result.estimated_monthly_revenue}")


async def test_1688_search(image_url: str):
    """1688画像検索テスト"""
    print("\n" + "=" * 60)
    print("4. 1688画像検索テスト")
    print("=" * 60)

    browser = BrowserManager(headless=False, timeout=60000, request_delay=3.0)

    try:
        async with browser.browser_session():
            searcher = AlibabaImageSearcher(browser, max_results=5)
            results = await searcher.search_by_image(image_url)

            print(f"\n検索結果: {len(results)}件")

            for i, r in enumerate(results[:3], 1):
                print(f"\n{i}. 価格: ¥{r.price_cny}元")
                print(f"   タイトル: {r.title[:30] if r.title else 'N/A'}...")
                print(f"   URL: {r.product_url[:50]}...")
                print(f"   店舗URL: {r.shop_url or 'N/A'}")

            return results
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        return []


async def test_image_matcher(amazon_url: str, alibaba_urls: list[str]):
    """画像マッチングテスト"""
    print("\n" + "=" * 60)
    print("5. 画像マッチングテスト")
    print("=" * 60)

    matcher = ImageMatcher(threshold=5)

    try:
        result = await matcher.find_best_match(amazon_url, alibaba_urls)

        if result:
            index, distance = result
            print(f"\nベストマッチ: インデックス {index}")
            print(f"ハミング距離: {distance}")
            print(f"類似度: {matcher.similarity_percentage(distance):.1f}%")
            print(f"判定: {matcher.is_likely_same_product(distance)}")
        else:
            print("\nマッチする商品が見つかりませんでした")

        await matcher.close()
        return result
    except Exception as e:
        print(f"エラー: {e}")
        await matcher.close()
        return None


def test_profit_calculator():
    """利益計算テスト"""
    print("\n" + "=" * 60)
    print("6. 利益計算テスト")
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

    print(f"\n販売価格: ¥{result.amazon_price}")
    print(f"仕入原価: ¥{result.cost_1688_jpy}")
    print(f"国際送料: ¥{result.shipping}")
    print(f"関税: ¥{result.customs}")
    print(f"紹介料: ¥{result.referral_fee}")
    print(f"FBA手数料: ¥{result.fba_fee}")
    print(f"総コスト: ¥{result.total_cost}")
    print(f"利益: ¥{result.profit}")
    print(f"利益率: {result.profit_rate_percentage:.1f}%")


async def main():
    """メインテスト"""
    print("=" * 60)
    print("Amazon-1688 リサーチツール モジュールテスト")
    print("=" * 60)

    # テスト選択
    print("\nテスト項目:")
    print("1. Amazon検索")
    print("2. Amazon商品詳細（ASIN指定）")
    print("3. フィルタ")
    print("4. 1688画像検索")
    print("5. 画像マッチング")
    print("6. 利益計算")
    print("7. 全テスト実行")
    print("0. 終了")

    while True:
        try:
            choice = input("\n選択 (0-7): ").strip()
        except EOFError:
            # 非対話モードの場合は利益計算テストのみ実行
            print("\n非対話モード: 利益計算テストのみ実行")
            test_profit_calculator()
            break

        if choice == "0":
            break
        elif choice == "1":
            await test_amazon_search()
        elif choice == "2":
            asin = input("ASIN: ").strip() or "B08XYZ1234"
            await test_amazon_scraper(asin)
        elif choice == "3":
            asin = input("ASIN: ").strip() or "B08XYZ1234"
            product = await test_amazon_scraper(asin)
            await test_filter(product)
        elif choice == "4":
            url = input("画像URL: ").strip()
            if url:
                await test_1688_search(url)
            else:
                print("URLを入力してください")
        elif choice == "5":
            print("（画像URLを入力してマッチングテスト）")
        elif choice == "6":
            test_profit_calculator()
        elif choice == "7":
            # 全テスト
            results = await test_amazon_search()
            if results:
                asin = results[0]["asin"]
                product = await test_amazon_scraper(asin)
                if product:
                    await test_filter(product)
                    if product.image_url:
                        alibaba_results = await test_1688_search(product.image_url)
                        if alibaba_results:
                            alibaba_urls = [r.image_url for r in alibaba_results if r.image_url]
                            if alibaba_urls:
                                await test_image_matcher(product.image_url, alibaba_urls)
            test_profit_calculator()


if __name__ == "__main__":
    asyncio.run(main())
