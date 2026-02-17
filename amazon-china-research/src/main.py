"""Amazon-1688 中国製品リサーチシステム メインモジュール"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

from .config import get_config, reload_config
from .models.product import ProductDetail, AlibabaProduct
from .models.result import MatchResult, ProfitResult, ResearchResult
from .modules.amazon.searcher import AmazonSearcher
from .modules.amazon.scraper import AmazonScraper
from .modules.amazon.filter import ProductFilter
from .modules.alibaba.image_search import AlibabaImageSearcher
from .modules.matcher.phash import ImageMatcher
from .modules.calculator.sales_estimator import SalesEstimator
from .modules.calculator.profit import ProfitCalculator
from .output.csv_exporter import CsvExporter
from .output.logger import setup_logger, ProgressReporter, ResearchStats
from .utils.browser import BrowserManager
from .utils.auth import AuthManager

logger = logging.getLogger(__name__)

# デフォルトの認証データパス
DEFAULT_AUTH_PATH = Path(__file__).parent.parent / "config" / "auth" / "1688_storage.json"


class Orchestrator:
    """リサーチワークフローを制御するオーケストレーター

    ワークフロー:
    1. Amazonでキーワード検索
    2. 各商品の詳細を取得
    3. フィルタリング（価格、レビュー数、販売数）
    4. 1688で画像検索
    5. pHashでマッチング
    6. 利益計算
    7. CSV出力
    """

    def __init__(
        self,
        config_path: Optional[str | Path] = None,
        headless: bool = True,
        use_auth: bool = True,
    ):
        # 設定を読み込み
        if config_path:
            reload_config(config_path)
        self.config = get_config()

        # ブラウザ設定
        self.headless = headless
        self.use_auth = use_auth

        # 認証マネージャー
        self.auth_manager = AuthManager()

        # 統計
        self.stats = ResearchStats()

    async def run(
        self,
        keyword: str,
        max_pages: int = 3,
        output_dir: Optional[str | Path] = None,
    ) -> list[ResearchResult]:
        """リサーチを実行

        Args:
            keyword: 検索キーワード
            max_pages: 検索ページ数
            output_dir: 出力ディレクトリ

        Returns:
            リサーチ結果リスト
        """
        logger.info(f"=== リサーチ開始: '{keyword}' ===")
        self.stats.start()

        results: list[ResearchResult] = []

        # 認証チェック（1688検索を使用する場合）
        if self.use_auth and not self.auth_manager.is_logged_in():
            logger.warning("1688認証データがありません。Amazon検索のみ実行します。")
            logger.warning("1688検索を有効にするには: python -m src.utils.auth")
            self.use_auth = False

        # Amazon用ブラウザを起動
        browser = BrowserManager(
            headless=self.headless,
            timeout=self.config.browser.timeout,
            request_delay=self.config.browser.request_delay,
        )

        # 1688用ブラウザ（認証済み）
        alibaba_browser = None
        if self.use_auth:
            alibaba_browser = BrowserManager(
                headless=self.headless,
                timeout=self.config.browser.timeout,
                request_delay=self.config.browser.request_delay,
                use_auth=True,
                auth_storage_path=DEFAULT_AUTH_PATH,
            )

        try:
            await browser.start()

            # 1688用ブラウザを起動（認証が有効な場合）
            if alibaba_browser:
                await alibaba_browser.start()

            # モジュールを初期化
            amazon_searcher = AmazonSearcher(browser)
            amazon_scraper = AmazonScraper(browser)
            product_filter = ProductFilter()
            # 1688検索は認証済みブラウザを使用（なければ通常ブラウザ）
            alibaba_searcher = AlibabaImageSearcher(alibaba_browser or browser)
            image_matcher = ImageMatcher()
            sales_estimator = SalesEstimator()
            profit_calculator = ProfitCalculator()

            # 1. Amazon検索
            logger.info("Step 1/6: Amazon検索中...")
            search_results = await amazon_searcher.search(
                keyword=keyword,
                max_pages=max_pages,
            )
            self.stats.total_searched = len(search_results)
            logger.info(f"検索結果: {len(search_results)}件")

            if not search_results:
                logger.warning("検索結果がありません")
                return []

            # 2. 商品詳細を取得
            logger.info("Step 2/6: 商品詳細取得中...")
            progress = ProgressReporter(
                total=len(search_results),
                description="商品詳細取得",
            )

            products: list[ProductDetail] = []
            for i, item in enumerate(search_results):
                try:
                    product = await amazon_scraper.get_product_detail(item["asin"])
                    if product:
                        products.append(product)
                    progress.update(message=item["asin"])
                except Exception as e:
                    logger.warning(f"詳細取得失敗: {item['asin']} - {e}")
                    self.stats.errors += 1

            progress.complete()
            logger.info(f"詳細取得完了: {len(products)}件")

            # 3. フィルタリング
            logger.info("Step 3/6: フィルタリング中...")
            filtered_products = product_filter.filter_with_details(products)
            self.stats.total_filtered = len(filtered_products)
            logger.info(f"フィルタ通過: {len(filtered_products)}件")

            if not filtered_products:
                logger.warning("フィルタを通過した商品がありません")
                return []

            # 4-6. 1688検索 → マッチング → 利益計算
            logger.info("Step 4-6/6: 1688検索・マッチング・利益計算中...")
            progress = ProgressReporter(
                total=len(filtered_products),
                description="1688マッチング",
            )

            for product, filter_result in filtered_products:
                try:
                    # 1688で画像検索
                    alibaba_products = await alibaba_searcher.search_by_image(
                        image_url=product.image_url,
                        max_results=self.config.search.alibaba_results,
                    )

                    if not alibaba_products:
                        progress.update(message=f"{product.asin}: マッチなし")
                        continue

                    # pHashでマッチング
                    best_match = await self._find_best_match(
                        image_matcher,
                        product.image_url,
                        alibaba_products,
                    )

                    if not best_match:
                        progress.update(message=f"{product.asin}: 類似画像なし")
                        continue

                    alibaba_product, hamming_distance = best_match
                    self.stats.total_matched += 1

                    # 利益計算
                    profit_result = profit_calculator.calculate(
                        amazon_price=product.price,
                        cny_price=alibaba_product.price_cny,
                        is_fba=product.is_fba,
                        category=self._normalize_category(product.category),
                    )

                    if profit_result.is_profitable:
                        self.stats.total_profitable += 1

                    # 結果を追加
                    result = ResearchResult(
                        amazon_product=product,
                        alibaba_product=alibaba_product,
                        profit_result=profit_result,
                        estimated_monthly_sales=filter_result.estimated_monthly_sales,
                        estimated_monthly_revenue=filter_result.estimated_monthly_revenue,
                        match_result=MatchResult(
                            amazon_product=product,
                            alibaba_product=alibaba_product,
                            is_matched=True,
                            hamming_distance=hamming_distance,
                        ),
                    )
                    results.append(result)

                    progress.update(
                        message=f"{product.asin}: ¥{profit_result.profit:,}"
                    )

                except Exception as e:
                    logger.warning(f"処理失敗: {product.asin} - {e}")
                    self.stats.errors += 1
                    progress.update(message=f"{product.asin}: エラー")

            progress.complete()

            # 結果をスコア順にソート
            results.sort(key=lambda x: x.score, reverse=True)

            # CSV出力
            if results:
                exporter = CsvExporter(output_dir=output_dir)
                csv_path = exporter.export(results, keyword)
                logger.info(f"CSV出力: {csv_path}")

            # 統計表示
            self.stats.finish()
            logger.info("\n" + self.stats.summary())

            return results

        finally:
            await browser.stop()
            if alibaba_browser:
                await alibaba_browser.stop()
            await image_matcher.close()

    async def _find_best_match(
        self,
        matcher: ImageMatcher,
        amazon_image_url: str,
        alibaba_products: list[AlibabaProduct],
    ) -> Optional[tuple[AlibabaProduct, int]]:
        """最もマッチする1688商品を見つける"""
        candidate_urls = [p.image_url for p in alibaba_products if p.image_url]

        if not candidate_urls:
            return None

        result = await matcher.find_best_match(amazon_image_url, candidate_urls)

        if result:
            index, distance = result
            return (alibaba_products[index], distance)

        return None

    def _normalize_category(self, category: str) -> str:
        """カテゴリー名を正規化"""
        category_mapping = {
            "ホーム＆キッチン": "home_kitchen",
            "ホーム&キッチン": "home_kitchen",
            "おもちゃ": "toys",
            "ビューティー": "beauty",
            "家電": "electronics",
            "PC・周辺機器": "electronics",
        }
        return category_mapping.get(category, "default")


def parse_args() -> argparse.Namespace:
    """コマンドライン引数をパース"""
    parser = argparse.ArgumentParser(
        description="Amazon-1688 中国製品リサーチシステム",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # 初回: 1688にログイン
  python -m src.main --login

  # リサーチ実行
  python -m src.main --keyword "貯金箱"
  python -m src.main --keyword "貯金箱" --max-pages 5
  python -m src.main --keyword "貯金箱" --output ./results/
        """,
    )

    parser.add_argument(
        "--login",
        action="store_true",
        help="1688ログインセットアップを実行",
    )

    parser.add_argument(
        "--keyword", "-k",
        type=str,
        required=False,  # --login の場合は不要
        help="検索キーワード",
    )

    parser.add_argument(
        "--max-pages", "-p",
        type=int,
        default=3,
        help="検索ページ数（デフォルト: 3）",
    )

    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="出力ディレクトリ",
    )

    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="設定ファイルパス",
    )

    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="ヘッドレスモードで実行（デフォルト: True）",
    )

    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="ブラウザを表示して実行",
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="詳細ログを出力",
    )

    return parser.parse_args()


async def main():
    """メイン関数"""
    args = parse_args()

    # ロガーをセットアップ
    log_level = "DEBUG" if args.verbose else "INFO"
    setup_logger(log_level=log_level)

    # ログインモード
    if args.login:
        print("=" * 50)
        print("1688/Taobao ログインセットアップ")
        print("=" * 50)
        auth_manager = AuthManager()
        success = await auth_manager.setup_login(timeout_minutes=5)
        if success:
            print("\nログイン成功！1688検索が使用できます。")
            return 0
        else:
            print("\nログインに失敗しました。")
            return 1

    # キーワードが必要
    if not args.keyword:
        print("エラー: --keyword オプションが必要です")
        print("使用方法: python -m src.main --keyword '検索キーワード'")
        print("初回ログイン: python -m src.main --login")
        return 1

    # ヘッドレス設定
    headless = not args.no_headless

    # オーケストレーターを作成
    orchestrator = Orchestrator(
        config_path=args.config,
        headless=headless,
    )

    # リサーチを実行
    results = await orchestrator.run(
        keyword=args.keyword,
        max_pages=args.max_pages,
        output_dir=args.output,
    )

    # 結果サマリー
    if results:
        print(f"\n=== リサーチ完了: {len(results)}件の有望商品を発見 ===")
        print("\nトップ5商品:")
        for i, result in enumerate(results[:5], 1):
            print(
                f"{i}. {result.amazon_product.title[:40]}... "
                f"利益: Y{result.profit_result.profit:,} "
                f"({result.profit_result.profit_rate_percentage:.1f}%)"
            )
    else:
        print("\n有望な商品は見つかりませんでした")

    return 0 if results else 1


def run():
    """エントリーポイント"""
    sys.exit(asyncio.run(main()))


if __name__ == "__main__":
    run()
