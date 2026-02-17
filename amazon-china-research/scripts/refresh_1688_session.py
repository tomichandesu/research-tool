"""1688セッション自動リフレッシュスクリプト.

定期的に1688にアクセスしてCookieを更新し、セッションを延長する。
cronジョブで12時間ごとに実行する想定。

使い方:
    python scripts/refresh_1688_session.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

AUTH_STORAGE_PATH = Path(__file__).parent.parent / "config" / "auth" / "1688_storage.json"
REQUIRED_COOKIE_NAMES = {"cookie2", "csg"}


def check_current_session() -> tuple[bool, float | None]:
    """現在のセッション状態をチェック。(有効かどうか, 残り時間h)"""
    if not AUTH_STORAGE_PATH.exists():
        return False, None

    data = json.loads(AUTH_STORAGE_PATH.read_text(encoding="utf-8"))
    cookies = data.get("cookies", [])
    now = time.time()

    min_remaining = None
    for c in cookies:
        if c.get("name") not in REQUIRED_COOKIE_NAMES:
            continue
        if ".1688.com" not in c.get("domain", ""):
            continue
        exp = c.get("expires", -1)
        if exp <= 0:
            continue
        remaining = (exp - now) / 3600
        if min_remaining is None or remaining < min_remaining:
            min_remaining = remaining

    if min_remaining is None:
        return False, None
    return min_remaining > 0, min_remaining


async def refresh_session() -> bool:
    """1688にアクセスしてセッションをリフレッシュ。"""
    from playwright.async_api import async_playwright

    if not AUTH_STORAGE_PATH.exists():
        logger.error("認証データがありません。手動ログインが必要です。")
        return False

    valid, remaining_h = check_current_session()
    if not valid:
        logger.error("セッションが既に期限切れです。手動ログインが必要です。")
        return False

    logger.info(f"現在のセッション残り: {remaining_h:.1f}時間")
    logger.info("1688にアクセスしてセッションをリフレッシュ中...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )

        try:
            context = await browser.new_context(
                storage_state=str(AUTH_STORAGE_PATH),
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )

            page = await context.new_page()

            # 1688トップページにアクセス
            await page.goto("https://www.1688.com", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(3)

            # ログイン状態を確認
            current_url = page.url
            if "login" in current_url.lower():
                logger.error("ログインページにリダイレクトされました。セッション無効。")
                await browser.close()
                return False

            # ユーザー情報の確認
            user_element = await page.query_selector(
                'a[href*="member"], div.user-name, span.login-info, div.mypersonal-name'
            )

            if not user_element:
                logger.warning("ユーザー要素が見つかりません。追加ページにアクセス中...")
                # いくつかのページにアクセスしてCookie更新を促す
                try:
                    await page.goto("https://work.1688.com/home/index.htm", wait_until="networkidle", timeout=30000)
                    await asyncio.sleep(2)
                except Exception:
                    pass

            # 更新されたストレージ状態を保存
            storage = await context.storage_state()
            with open(AUTH_STORAGE_PATH, "w", encoding="utf-8") as f:
                json.dump(storage, f, ensure_ascii=False, indent=2)
            logger.info("ストレージ状態を保存しました。")

            await context.close()

        finally:
            await browser.close()

    # リフレッシュ後のセッション状態を確認
    valid_after, remaining_after = check_current_session()
    if valid_after:
        logger.info(f"リフレッシュ完了。セッション残り: {remaining_after:.1f}時間")
        if remaining_h and remaining_after and remaining_after > remaining_h:
            logger.info(f"セッションが延長されました！ ({remaining_h:.1f}h → {remaining_after:.1f}h)")
        elif remaining_h and remaining_after and abs(remaining_after - remaining_h) < 0.1:
            logger.warning("Cookie期限は変わりませんでした（固定期限の可能性）")
        return True
    else:
        logger.error("リフレッシュ後もセッションが無効です。")
        return False


def main():
    valid, remaining_h = check_current_session()

    if not valid:
        logger.error("セッションが無効です。手動で再ログインしてください:")
        logger.error("  python run_research.py --login")
        sys.exit(1)

    logger.info(f"セッション有効。残り: {remaining_h:.1f}時間")

    success = asyncio.run(refresh_session())

    if success:
        logger.info("セッションリフレッシュ成功")
        sys.exit(0)
    else:
        logger.error("セッションリフレッシュ失敗")
        sys.exit(1)


if __name__ == "__main__":
    main()
