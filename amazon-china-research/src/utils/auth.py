"""1688/Taobao認証管理モジュール"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)

# デフォルトの認証データ保存先
DEFAULT_AUTH_DIR = Path(__file__).parent.parent.parent / "config" / "auth"


class AuthManager:
    """1688/Taobaoの認証を管理する

    ブラウザのストレージ状態（Cookie、LocalStorage）を保存・復元し、
    ログインセッションを維持する。

    使用方法:
        1. 初回: setup_login() で手動ログイン → セッション保存
        2. 以降: get_authenticated_context() で認証済みコンテキスト取得
    """

    STORAGE_FILE = "1688_storage.json"
    LOGIN_CHECK_URL = "https://www.1688.com"
    LOGIN_SUCCESS_INDICATOR = "member"  # ログイン後のURLに含まれる文字列

    def __init__(self, auth_dir: Optional[Path] = None):
        self.auth_dir = auth_dir or DEFAULT_AUTH_DIR
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        self.storage_path = self.auth_dir / self.STORAGE_FILE

    def is_logged_in(self) -> bool:
        """保存済みセッションがあるかチェック"""
        return self.storage_path.exists()

    async def setup_login(self, timeout_minutes: int = 5) -> bool:
        """手動ログインのセットアップ

        ブラウザを表示モードで起動し、ユーザーに手動ログインを促す。
        ログイン完了後、セッションを保存する。

        Args:
            timeout_minutes: ログイン待機タイムアウト（分）

        Returns:
            True: ログイン成功
            False: タイムアウトまたはキャンセル
        """
        logger.info("=" * 50)
        logger.info("1688/Taobao ログインセットアップを開始します")
        logger.info("=" * 50)
        logger.info("")
        logger.info("ブラウザが開きます。以下の手順でログインしてください:")
        logger.info("1. 1688.com または Taobao のログインページが表示されます")
        logger.info("2. QRコード、SMS、またはパスワードでログインしてください")
        logger.info("3. ログイン完了後、自動的にセッションが保存されます")
        logger.info("")
        logger.info(f"タイムアウト: {timeout_minutes}分")
        logger.info("=" * 50)

        async with async_playwright() as p:
            # 表示モードでブラウザを起動
            browser = await p.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                ],
            )

            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )

            page = await context.new_page()

            try:
                # 1688トップページにアクセス
                await page.goto(self.LOGIN_CHECK_URL)

                # ログイン完了を待機
                logged_in = await self._wait_for_login(
                    page,
                    timeout_seconds=timeout_minutes * 60,
                )

                if logged_in:
                    # セッションを保存
                    await self._save_storage(context)
                    logger.info("ログインセッションを保存しました")
                    return True
                else:
                    logger.warning("ログインがタイムアウトしました")
                    return False

            finally:
                await browser.close()

    async def _wait_for_login(
        self,
        page: Page,
        timeout_seconds: int,
        check_interval: int = 3,
    ) -> bool:
        """ログイン完了を待機する"""
        elapsed = 0

        while elapsed < timeout_seconds:
            # 現在のURLをチェック
            current_url = page.url

            # ログインページではなくなったかチェック
            if "login" not in current_url.lower():
                # 1688のメインページに戻っているか確認
                if "1688.com" in current_url:
                    # ユーザー情報が表示されているか確認
                    user_element = await page.query_selector(
                        'a[href*="member"], '
                        'div.user-name, '
                        'span.login-info, '
                        'div.mypersonal-name'
                    )
                    if user_element:
                        logger.info("ログイン完了を検出しました")
                        return True

            await asyncio.sleep(check_interval)
            elapsed += check_interval

            # 進捗表示
            if elapsed % 30 == 0:
                remaining = (timeout_seconds - elapsed) // 60
                logger.info(f"ログイン待機中... 残り約{remaining}分")

        return False

    async def _save_storage(self, context: BrowserContext) -> None:
        """ストレージ状態を保存"""
        storage = await context.storage_state()
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(storage, f, ensure_ascii=False, indent=2)
        logger.info(f"認証データ保存: {self.storage_path}")

    async def get_authenticated_context(
        self,
        playwright,
        headless: bool = True,
    ) -> Optional[BrowserContext]:
        """認証済みブラウザコンテキストを取得

        Args:
            playwright: Playwrightインスタンス
            headless: ヘッドレスモード

        Returns:
            認証済みBrowserContext、または認証データがない場合はNone
        """
        if not self.is_logged_in():
            logger.warning("認証データがありません。setup_login()を実行してください")
            return None

        browser = await playwright.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )

        context = await browser.new_context(
            storage_state=str(self.storage_path),
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )

        return context

    async def verify_login(self) -> bool:
        """保存済みセッションが有効かチェック

        Returns:
            True: セッション有効
            False: セッション無効または期限切れ
        """
        if not self.is_logged_in():
            return False

        async with async_playwright() as p:
            context = await self.get_authenticated_context(p, headless=True)
            if not context:
                return False

            try:
                page = await context.new_page()
                await page.goto(self.LOGIN_CHECK_URL)
                await asyncio.sleep(3)

                # ログインページにリダイレクトされていないか確認
                if "login" in page.url.lower():
                    logger.warning("セッションが期限切れです")
                    return False

                # ユーザー情報が表示されているか確認
                user_element = await page.query_selector(
                    'a[href*="member"], '
                    'div.user-name, '
                    'span.login-info'
                )

                if user_element:
                    logger.info("セッションは有効です")
                    return True

                return False

            finally:
                await context.close()

    def clear_session(self) -> None:
        """保存済みセッションを削除"""
        if self.storage_path.exists():
            self.storage_path.unlink()
            logger.info("認証データを削除しました")


async def setup_1688_login():
    """1688ログインセットアップのエントリーポイント"""
    auth_manager = AuthManager()

    if auth_manager.is_logged_in():
        print("既存の認証データが見つかりました。")
        print("1. 既存のセッションを使用")
        print("2. 再ログイン")
        choice = input("選択 (1/2): ").strip()

        if choice == "1":
            # セッションの有効性を確認
            print("セッションを確認中...")
            if await auth_manager.verify_login():
                print("セッションは有効です。")
                return True
            else:
                print("セッションが無効です。再ログインが必要です。")

    # ログインセットアップ
    success = await auth_manager.setup_login(timeout_minutes=5)

    if success:
        print("\nログイン成功！")
        print("これで1688の画像検索が使用できます。")
    else:
        print("\nログインに失敗しました。")
        print("再度お試しください。")

    return success


if __name__ == "__main__":
    import asyncio
    asyncio.run(setup_1688_login())
