"""ログインヘルパー

セラーセントラルへのログインをサポートするユーティリティ。
初回起動時にログインし、以降はログイン状態を保持する。
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from playwright.async_api import async_playwright, Page

logger = logging.getLogger(__name__)


class SellerCentralLogin:
    """セラーセントラルログインヘルパー

    ユーザーが手動でログインするためのブラウザを起動し、
    ログイン完了後にセッションを保存する。
    """

    SELLER_CENTRAL_URL = "https://sellercentral.amazon.co.jp"
    FBA_SIMULATOR_URL = "https://sellercentral.amazon.co.jp/fba/profitabilitycalculator/index"
    USER_DATA_DIR = Path.home() / ".amazon-research" / "browser-data"

    @classmethod
    async def setup_login(cls) -> bool:
        """ログインセットアップを実行

        ブラウザを起動し、ユーザーにログインを促す。
        ログイン完了後、Enterキーで続行。

        Returns:
            True: ログイン成功
            False: ログイン失敗またはキャンセル
        """
        print("\n" + "=" * 60)
        print("セラーセントラル ログインセットアップ")
        print("=" * 60)
        print("\n1. ブラウザが起動します")
        print("2. セラーセントラルにログインしてください")
        print("3. ログイン完了後、このウィンドウに戻ってEnterキーを押してください")
        print("\n※ ログイン情報はローカルに保存され、次回以降は自動でログイン状態になります")
        print("=" * 60 + "\n")

        # ユーザーデータディレクトリを作成
        cls.USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

        playwright = await async_playwright().start()

        try:
            # 永続コンテキストでブラウザを起動（非ヘッドレス）
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(cls.USER_DATA_DIR),
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                ],
                viewport={"width": 1920, "height": 1080},
                locale="ja-JP",
            )

            # ページを作成してセラーセントラルに移動
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(cls.SELLER_CENTRAL_URL)

            print("ブラウザが起動しました。セラーセントラルにログインしてください...")

            # ユーザーがログインするのを待つ
            input("\nログイン完了後、Enterキーを押してください: ")

            # ログイン確認
            is_logged_in = await cls._check_login_status(page)

            if is_logged_in:
                print("\n✓ ログイン成功！セッションを保存しました。")
                print(f"  保存先: {cls.USER_DATA_DIR}")

                # FBAシミュレーターへのアクセス確認
                print("\nFBAシミュレーターへのアクセスを確認中...")
                await page.goto(cls.FBA_SIMULATOR_URL)
                await page.wait_for_timeout(3000)

                if "signin" not in page.url.lower():
                    print("✓ FBAシミュレーターにアクセスできます")
                else:
                    print("⚠ FBAシミュレーターへのアクセス権限がない可能性があります")

                return True
            else:
                print("\n✗ ログインが確認できませんでした。")
                return False

        except Exception as e:
            logger.error(f"ログインセットアップエラー: {e}")
            print(f"\n✗ エラーが発生しました: {e}")
            return False

        finally:
            await context.close()
            await playwright.stop()

    @classmethod
    async def _check_login_status(cls, page: Page) -> bool:
        """ログイン状態を確認"""
        try:
            # 現在のURLを確認（既にセラーセントラルにいる可能性）
            current_url = page.url.lower()

            # 既にログインページでなければ、ダッシュボードにいる可能性が高い
            if "sellercentral" in current_url and "signin" not in current_url and "ap/signin" not in current_url:
                return True

            # セラーセントラルに移動してリダイレクト先を確認
            response = await page.goto(cls.SELLER_CENTRAL_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            final_url = page.url.lower()

            # ログインページにリダイレクトされていないか確認
            if "signin" in final_url or "ap/signin" in final_url:
                return False

            # ダッシュボードの要素を確認
            dashboard_indicators = [
                "#sc-content-container",
                ".dashboard",
                "#navbar",
                "[data-testid='navigation']",
            ]

            for selector in dashboard_indicators:
                element = await page.query_selector(selector)
                if element:
                    return True

            # URLがセラーセントラルのままならログイン成功とみなす
            return "sellercentral" in final_url

        except Exception as e:
            # ナビゲーション中断エラーの場合、リダイレクト先URLを確認
            logger.debug(f"ナビゲーションエラー（リダイレクト確認中）: {e}")
            await page.wait_for_timeout(3000)
            final_url = page.url.lower()
            if "signin" in final_url or "ap/signin" in final_url:
                return False
            return "sellercentral" in final_url

    @classmethod
    async def is_logged_in(cls) -> bool:
        """現在ログイン済みかどうかを確認

        Returns:
            True: ログイン済み
            False: 未ログイン
        """
        if not cls.USER_DATA_DIR.exists():
            return False

        playwright = await async_playwright().start()

        try:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(cls.USER_DATA_DIR),
                headless=True,
                viewport={"width": 1920, "height": 1080},
            )

            page = context.pages[0] if context.pages else await context.new_page()
            is_logged_in = await cls._check_login_status(page)

            await context.close()
            return is_logged_in

        except Exception as e:
            logger.error(f"ログイン確認エラー: {e}")
            return False

        finally:
            await playwright.stop()

    @classmethod
    def clear_session(cls) -> None:
        """保存されたセッションをクリア"""
        import shutil

        if cls.USER_DATA_DIR.exists():
            shutil.rmtree(cls.USER_DATA_DIR)
            print(f"セッションをクリアしました: {cls.USER_DATA_DIR}")
        else:
            print("クリアするセッションがありません")


async def main():
    """コマンドラインからの実行用"""
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--clear":
        SellerCentralLogin.clear_session()
    else:
        success = await SellerCentralLogin.setup_login()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
