"""ブラウザ管理ユーティリティ"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, AsyncGenerator

from playwright.async_api import async_playwright, Browser, Page, BrowserContext

logger = logging.getLogger(__name__)


class BrowserManager:
    """Playwrightブラウザ管理クラス

    Attributes:
        headless: ヘッドレスモードで起動するかどうか
        timeout: タイムアウト（ミリ秒）
        request_delay: リクエスト間の待機時間（秒）
        use_auth: 1688認証を使用するかどうか
        user_data_dir: ユーザーデータディレクトリ（ログイン状態保持用）
    """

    # デフォルトのユーザーデータディレクトリ
    DEFAULT_USER_DATA_DIR = Path.home() / ".amazon-research" / "browser-data"

    def __init__(
        self,
        headless: bool = True,
        timeout: int = 30000,
        request_delay: float = 2.0,
        use_auth: bool = False,
        auth_storage_path: Optional[Path] = None,
        user_data_dir: Optional[Path] = None,
        use_persistent_context: bool = False,
    ):
        self.headless = headless
        self.timeout = timeout
        self.request_delay = request_delay
        self.use_auth = use_auth
        self.auth_storage_path = auth_storage_path
        self.user_data_dir = user_data_dir or self.DEFAULT_USER_DATA_DIR
        self.use_persistent_context = use_persistent_context
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    async def start(self) -> None:
        """ブラウザを起動する"""
        if self._context is not None:
            return

        logger.info("ブラウザを起動中...")
        self._playwright = await async_playwright().start()

        # 共通のコンテキストオプション
        context_options = {
            "viewport": {"width": 1920, "height": 1080},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "locale": "ja-JP",
            "timezone_id": "Asia/Tokyo",
        }

        # 永続コンテキストを使用する場合（セラーセントラルログイン用）
        if self.use_persistent_context:
            # ユーザーデータディレクトリを作成
            self.user_data_dir.mkdir(parents=True, exist_ok=True)

            logger.info(f"永続コンテキスト使用: {self.user_data_dir}")

            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.user_data_dir),
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
                **context_options,
            )
        else:
            # 通常のブラウザ起動
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
            )

            # 1688用の認証を使用する場合
            # ロケール/タイムゾーンはja-JPのまま維持（Amazon.co.jpのBSR抽出に必要）
            # 1688の認証はCookieベースなのでロケール変更は不要
            if self.use_auth and self.auth_storage_path and self.auth_storage_path.exists():
                logger.info("認証済みセッションを使用します")
                context_options["storage_state"] = str(self.auth_storage_path)

            # コンテキストを作成
            self._context = await self._browser.new_context(**context_options)

        # デフォルトタイムアウトを設定
        self._context.set_default_timeout(self.timeout)

        logger.info("ブラウザ起動完了")

    async def stop(self) -> None:
        """ブラウザを終了する"""
        if self._context:
            await self._context.close()
            self._context = None

        if self._browser:
            await self._browser.close()
            self._browser = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        logger.info("ブラウザ終了")

    async def new_page(self) -> Page:
        """新しいページを作成する"""
        if self._context is None:
            await self.start()
        return await self._context.new_page()

    async def navigate(self, page: Page, url: str) -> None:
        """ページに移動する（リクエスト間隔を考慮）"""
        await asyncio.sleep(self.request_delay)
        logger.debug(f"ページ移動: {url}")
        await page.goto(url, wait_until="domcontentloaded")

    async def wait_for_selector(
        self,
        page: Page,
        selector: str,
        timeout: Optional[int] = None,
    ) -> bool:
        """セレクタが表示されるまで待機"""
        try:
            await page.wait_for_selector(
                selector,
                timeout=timeout or self.timeout,
            )
            return True
        except Exception as e:
            logger.warning(f"セレクタ待機タイムアウト: {selector} - {e}")
            return False

    async def get_text(self, page: Page, selector: str) -> Optional[str]:
        """テキストを取得する"""
        try:
            element = await page.query_selector(selector)
            if element:
                return await element.inner_text()
        except Exception as e:
            logger.debug(f"テキスト取得失敗: {selector} - {e}")
        return None

    async def get_attribute(
        self,
        page: Page,
        selector: str,
        attribute: str,
    ) -> Optional[str]:
        """属性を取得する"""
        try:
            element = await page.query_selector(selector)
            if element:
                return await element.get_attribute(attribute)
        except Exception as e:
            logger.debug(f"属性取得失敗: {selector}[{attribute}] - {e}")
        return None

    async def click(self, page: Page, selector: str) -> bool:
        """要素をクリックする"""
        try:
            await page.click(selector)
            return True
        except Exception as e:
            logger.warning(f"クリック失敗: {selector} - {e}")
            return False

    async def type_text(
        self,
        page: Page,
        selector: str,
        text: str,
        delay: int = 50,
    ) -> bool:
        """テキストを入力する"""
        try:
            await page.fill(selector, text)
            return True
        except Exception as e:
            logger.warning(f"テキスト入力失敗: {selector} - {e}")
            return False

    async def scroll_to_bottom(self, page: Page, step: int = 300) -> None:
        """ページを下までスクロールする"""
        await page.evaluate("""
            async () => {
                await new Promise((resolve) => {
                    let totalHeight = 0;
                    const distance = %d;
                    const timer = setInterval(() => {
                        const scrollHeight = document.body.scrollHeight;
                        window.scrollBy(0, distance);
                        totalHeight += distance;
                        if (totalHeight >= scrollHeight) {
                            clearInterval(timer);
                            resolve();
                        }
                    }, 100);
                });
            }
        """ % step)

    async def take_screenshot(self, page: Page, path: str) -> None:
        """スクリーンショットを撮影する"""
        await page.screenshot(path=path)
        logger.info(f"スクリーンショット保存: {path}")

    @asynccontextmanager
    async def page_context(self) -> AsyncGenerator[Page, None]:
        """ページコンテキストマネージャー"""
        page = await self.new_page()
        try:
            yield page
        finally:
            await page.close()

    @asynccontextmanager
    async def browser_session(self) -> AsyncGenerator["BrowserManager", None]:
        """ブラウザセッションコンテキストマネージャー"""
        await self.start()
        try:
            yield self
        finally:
            await self.stop()


class RetryStrategy:
    """リトライ戦略"""

    MAX_RETRIES = 3
    BASE_DELAY = 2  # 秒

    @staticmethod
    async def with_retry(func, *args, **kwargs):
        """リトライ付きで関数を実行する"""
        last_exception = None

        for attempt in range(RetryStrategy.MAX_RETRIES):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                if attempt < RetryStrategy.MAX_RETRIES - 1:
                    delay = RetryStrategy.BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"リトライ {attempt + 1}/{RetryStrategy.MAX_RETRIES} "
                        f"({delay}秒後): {e}"
                    )
                    await asyncio.sleep(delay)

        raise last_exception
