"""1688 login session management for per-user authentication (SMS + QR)."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from ..config import settings

logger = logging.getLogger(__name__)

# Per-user auth storage base directory
_USER_DATA_BASE = Path(__file__).parent.parent.parent / "output" / "users"
_DEBUG_DIR = Path(__file__).parent.parent.parent / "output" / "debug"


def _log(msg: str) -> None:
    """Print + logger.info for guaranteed visibility in Docker logs."""
    print(f"[1688-LOGIN] {msg}", flush=True)
    logger.info(msg)


def get_user_storage_path(user_id: int) -> Path:
    """Return the path to a user's 1688 storage state file."""
    return _USER_DATA_BASE / str(user_id) / "1688_storage.json"


@dataclass
class LoginSession:
    user_id: int
    mode: str = "sms"  # "sms" | "qr"
    status: str = "starting"
    # Statuses: "starting" | "waiting_scan" | "waiting_phone" |
    #           "waiting_code" | "logged_in" | "failed"
    qr_image_b64: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    error_message: Optional[str] = None
    _pw: object = field(default=None, repr=False)
    _task: Optional[asyncio.Task] = field(default=None, repr=False)
    _browser: Optional[Browser] = field(default=None, repr=False)
    _context: Optional[BrowserContext] = field(default=None, repr=False)
    _page: Optional[Page] = field(default=None, repr=False)
    # SMS flow: events for coordinating between API and browser
    _phone_number: Optional[str] = field(default=None, repr=False)
    _sms_code: Optional[str] = field(default=None, repr=False)
    _phone_event: Optional[asyncio.Event] = field(default=None, repr=False)
    _code_event: Optional[asyncio.Event] = field(default=None, repr=False)


class LoginSessionManager:
    """Manages concurrent login sessions for 1688 (SMS and QR)."""

    LOGIN_URL = "https://login.1688.com/member/signin.htm"
    LOGIN_TIMEOUT = settings.LOGIN_TIMEOUT_SECONDS
    MAX_CONCURRENT = settings.MAX_CONCURRENT_LOGINS

    # Selectors that indicate a logged-in user (from src/utils/auth.py)
    _USER_SELECTORS = (
        'a[href*="member"], '
        'div.user-name, '
        'span.login-info, '
        'div.mypersonal-name'
    )

    def __init__(self) -> None:
        self._sessions: dict[int, LoginSession] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # SMS Login Flow
    # ------------------------------------------------------------------

    async def start_sms_login(self, user_id: int) -> LoginSession:
        """Start an SMS login session. Opens browser and waits for phone number."""
        async with self._lock:
            existing = self._sessions.get(user_id)
            if existing and existing.status not in ("failed", "logged_in"):
                _log(f"User {user_id}: returning existing session (status={existing.status})")
                return existing

            active = sum(
                1 for s in self._sessions.values()
                if s.status not in ("failed", "logged_in")
            )
            if active >= self.MAX_CONCURRENT:
                raise ValueError(
                    "ログインセッションが上限に達しています。しばらくお待ちください。"
                )

            session = LoginSession(
                user_id=user_id,
                mode="sms",
                _phone_event=asyncio.Event(),
                _code_event=asyncio.Event(),
            )
            self._sessions[user_id] = session

        _log(f"User {user_id}: starting SMS login session")
        session._task = asyncio.create_task(self._sms_login_worker(session))
        return session

    async def submit_phone(self, user_id: int, phone: str) -> bool:
        """Submit phone number for SMS login."""
        session = self._sessions.get(user_id)
        if not session or session.mode != "sms":
            _log(f"User {user_id}: submit_phone failed - no session or wrong mode")
            return False
        session._phone_number = phone
        if session._phone_event:
            session._phone_event.set()
        _log(f"User {user_id}: phone number submitted")
        return True

    async def submit_sms_code(self, user_id: int, code: str) -> bool:
        """Submit SMS verification code."""
        session = self._sessions.get(user_id)
        if not session or session.mode != "sms":
            _log(f"User {user_id}: submit_code failed - no session or wrong mode")
            return False
        session._sms_code = code
        if session._code_event:
            session._code_event.set()
        _log(f"User {user_id}: SMS code submitted")
        return True

    async def _save_debug_screenshot(self, page: Page, user_id: int, step: str) -> None:
        """Save a debug screenshot for troubleshooting."""
        try:
            _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            path = _DEBUG_DIR / f"user_{user_id}_{step}.png"
            await page.screenshot(path=str(path), full_page=True)
            _log(f"User {user_id}: debug screenshot saved: {path}")
        except Exception as e:
            _log(f"User {user_id}: failed to save screenshot: {e}")

    async def _sms_login_worker(self, session: LoginSession) -> None:
        """Background task for SMS login flow."""
        try:
            _log(f"User {session.user_id}: worker starting - launching browser")
            pw = await async_playwright().start()
            session._pw = pw
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
            )
            session._browser = browser
            _log(f"User {session.user_id}: browser launched OK")

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
            session._context = context
            page = await context.new_page()
            session._page = page

            # Navigate to login page
            _log(f"User {session.user_id}: navigating to {self.LOGIN_URL}")
            await page.goto(self.LOGIN_URL, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            current_url = page.url
            _log(f"User {session.user_id}: landed on {current_url}")
            await self._save_debug_screenshot(page, session.user_id, "01_login_page")

            # Get page HTML for debugging
            page_title = await page.title()
            _log(f"User {session.user_id}: page title = {page_title}")

            # Click "短信登录" tab to switch to SMS mode
            sms_tab_selectors = [
                'div:text("短信登录")',
                'span:text("短信登录")',
                'a:text("短信登录")',
                'li:text("短信登录")',
                'div.tab-item:has-text("短信")',
                ':text("短信验证码登录")',
                ':text("手机验证码")',
            ]
            sms_tab_clicked = False
            for sel in sms_tab_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        await el.click()
                        _log(f"User {session.user_id}: clicked SMS tab ({sel})")
                        sms_tab_clicked = True
                        await asyncio.sleep(1)
                        break
                except Exception as e:
                    _log(f"User {session.user_id}: SMS tab selector {sel} failed: {e}")
                    continue

            if not sms_tab_clicked:
                _log(f"User {session.user_id}: WARNING - could not find SMS tab, continuing anyway")

            await self._save_debug_screenshot(page, session.user_id, "02_after_sms_tab")

            session.status = "waiting_phone"
            _log(f"User {session.user_id}: SMS login ready, waiting for phone")

            # Wait for phone number from user (max 5 minutes)
            try:
                await asyncio.wait_for(session._phone_event.wait(), timeout=self.LOGIN_TIMEOUT)
            except asyncio.TimeoutError:
                session.status = "failed"
                session.error_message = "タイムアウトしました。再度お試しください。"
                _log(f"User {session.user_id}: phone wait timed out")
                return

            phone = session._phone_number
            _log(f"User {session.user_id}: phone received, entering number")

            # Find and fill phone input
            phone_selectors = [
                'input[id*="phone"]',
                'input[name*="phone"]',
                'input[placeholder*="手机"]',
                'input[placeholder*="号码"]',
                'input[type="tel"]',
                '#fm-sms-login-id',
                'input.China_Login_Input_2n6',
            ]
            phone_filled = False
            for sel in phone_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        await el.click()
                        await el.fill(phone)
                        phone_filled = True
                        _log(f"User {session.user_id}: phone filled via {sel}")
                        break
                except Exception as e:
                    _log(f"User {session.user_id}: phone selector {sel} failed: {e}")

            if not phone_filled:
                # Fallback: try all visible inputs
                _log(f"User {session.user_id}: trying fallback input search")
                inputs = await page.query_selector_all('input[type="text"], input[type="tel"], input:not([type])')
                for i, inp in enumerate(inputs):
                    try:
                        if await inp.is_visible():
                            await inp.click()
                            await inp.fill(phone)
                            phone_filled = True
                            _log(f"User {session.user_id}: phone filled via fallback input #{i}")
                            break
                    except Exception:
                        pass

            if not phone_filled:
                await self._save_debug_screenshot(page, session.user_id, "03_phone_not_found")
                session.status = "failed"
                session.error_message = "電話番号の入力欄が見つかりませんでした。"
                _log(f"User {session.user_id}: FAILED - phone input not found")
                return

            await asyncio.sleep(0.5)
            await self._save_debug_screenshot(page, session.user_id, "03_phone_filled")

            # Click "get code" button
            code_btn_selectors = [
                'button:has-text("获取验证码")',
                'button:has-text("验证码")',
                'button:has-text("获取")',
                'a:has-text("获取验证码")',
                '#China_Login_GetCode_2m1',
                'button.China_Login_Button_2n8',
            ]
            code_sent = False
            for sel in code_btn_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        await el.click()
                        code_sent = True
                        _log(f"User {session.user_id}: clicked send code ({sel})")
                        break
                except Exception as e:
                    _log(f"User {session.user_id}: send code selector {sel} failed: {e}")
                    continue

            if not code_sent:
                await self._save_debug_screenshot(page, session.user_id, "04_send_code_not_found")
                session.status = "failed"
                session.error_message = "認証コード送信ボタンが見つかりませんでした。"
                _log(f"User {session.user_id}: FAILED - send code button not found")
                return

            await asyncio.sleep(1)
            await self._save_debug_screenshot(page, session.user_id, "04_code_sent")
            session.status = "waiting_code"
            _log(f"User {session.user_id}: SMS code request sent, waiting for user code")

            # Wait for SMS code from user
            try:
                await asyncio.wait_for(session._code_event.wait(), timeout=self.LOGIN_TIMEOUT)
            except asyncio.TimeoutError:
                session.status = "failed"
                session.error_message = "タイムアウトしました。再度お試しください。"
                _log(f"User {session.user_id}: code wait timed out")
                return

            code = session._sms_code
            _log(f"User {session.user_id}: code received, entering")

            # Fill verification code
            code_selectors = [
                'input[id*="code"]',
                'input[name*="code"]',
                'input[placeholder*="验证码"]',
                'input[placeholder*="输入"]',
                '#China_Login_SmsPwdInput_2m2',
            ]
            code_filled = False
            for sel in code_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        await el.click()
                        await el.fill(code)
                        code_filled = True
                        _log(f"User {session.user_id}: code filled via {sel}")
                        break
                except Exception as e:
                    _log(f"User {session.user_id}: code selector {sel} failed: {e}")

            if not code_filled:
                # Fallback: find the second visible input (first is phone)
                _log(f"User {session.user_id}: trying fallback code input search")
                inputs = await page.query_selector_all('input[type="text"], input[type="tel"], input[type="password"], input:not([type])')
                visible_inputs = []
                for inp in inputs:
                    try:
                        if await inp.is_visible():
                            visible_inputs.append(inp)
                    except Exception:
                        pass
                _log(f"User {session.user_id}: found {len(visible_inputs)} visible inputs")
                if len(visible_inputs) >= 2:
                    await visible_inputs[1].click()
                    await visible_inputs[1].fill(code)
                    code_filled = True
                    _log(f"User {session.user_id}: code filled via fallback (2nd input)")

            if not code_filled:
                await self._save_debug_screenshot(page, session.user_id, "05_code_not_found")
                session.status = "failed"
                session.error_message = "認証コード入力欄が見つかりませんでした。"
                _log(f"User {session.user_id}: FAILED - code input not found")
                return

            await asyncio.sleep(0.5)
            await self._save_debug_screenshot(page, session.user_id, "05_code_filled")

            # Click login button
            login_btn_selectors = [
                'button:has-text("登录")',
                'button[type="submit"]',
                'input[type="submit"]',
                '#China_Login_Submit_2m3',
                'button.China_Login_Submit_2n9',
            ]
            login_clicked = False
            for sel in login_btn_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        await el.click()
                        login_clicked = True
                        _log(f"User {session.user_id}: clicked login button ({sel})")
                        break
                except Exception as e:
                    _log(f"User {session.user_id}: login button selector {sel} failed: {e}")
                    continue

            if not login_clicked:
                _log(f"User {session.user_id}: WARNING - login button not found, trying Enter key")
                await page.keyboard.press("Enter")

            # Wait for navigation / login to complete
            _log(f"User {session.user_id}: waiting for login result...")
            await asyncio.sleep(5)

            current_url = page.url
            _log(f"User {session.user_id}: after login, url={current_url}")
            await self._save_debug_screenshot(page, session.user_id, "06_after_login")

            # Handle intermediate pages (security check, "知道了" button, etc.)
            await self._handle_intermediate_pages(page, session)

            # Check login success
            if await self._check_login_success(page):
                await self._save_storage(session)
                session.status = "logged_in"
                _log(f"User {session.user_id}: SMS login successful!")
                return

            # Retry login check (might need time for redirect)
            for i in range(10):
                await asyncio.sleep(3)
                # Handle any new intermediate pages that appear
                await self._handle_intermediate_pages(page, session)
                current_url = page.url
                _log(f"User {session.user_id}: retry {i+1}/10, url={current_url}")
                if await self._check_login_success(page):
                    await self._save_storage(session)
                    session.status = "logged_in"
                    _log(f"User {session.user_id}: SMS login successful (retry {i+1})")
                    return

            await self._save_debug_screenshot(page, session.user_id, "07_login_failed")
            session.status = "failed"
            session.error_message = "ログインに失敗しました。認証コードが正しいか確認してください。"
            _log(f"User {session.user_id}: FAILED - login not detected after retries")

        except asyncio.CancelledError:
            session.status = "failed"
            session.error_message = "ログインがキャンセルされました。"
            _log(f"User {session.user_id}: login cancelled")
            raise
        except Exception as e:
            session.status = "failed"
            session.error_message = f"ログインエラー: {e}"
            _log(f"User {session.user_id}: EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
        finally:
            _log(f"User {session.user_id}: worker cleanup (status={session.status})")
            await self._cleanup_browser(session)
            if session.status in ("failed", "logged_in"):
                self._sessions.pop(session.user_id, None)

    # ------------------------------------------------------------------
    # QR Login Flow (kept as alternative)
    # ------------------------------------------------------------------

    async def start_qr_login(self, user_id: int) -> LoginSession:
        """Start a QR-code login session for a user."""
        async with self._lock:
            existing = self._sessions.get(user_id)
            if existing and existing.status not in ("failed", "logged_in"):
                return existing

            active = sum(
                1 for s in self._sessions.values()
                if s.status not in ("failed", "logged_in")
            )
            if active >= self.MAX_CONCURRENT:
                raise ValueError(
                    "ログインセッションが上限に達しています。しばらくお待ちください。"
                )

            session = LoginSession(user_id=user_id, mode="qr")
            self._sessions[user_id] = session

        session._task = asyncio.create_task(self._qr_login_worker(session))
        return session

    async def _qr_login_worker(self, session: LoginSession) -> None:
        """Background task: launch browser, capture QR, poll for login."""
        try:
            pw = await async_playwright().start()
            session._pw = pw
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
            )
            session._browser = browser

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
            session._context = context
            page = await context.new_page()
            session._page = page

            await page.goto(self.LOGIN_URL, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            await self._capture_qr(page, session=session)
            session.status = "waiting_scan"

            elapsed = 0
            last_qr_refresh = 0
            while elapsed < self.LOGIN_TIMEOUT:
                await asyncio.sleep(3)
                elapsed += 3

                if await self._check_login_success(page):
                    await self._save_storage(session)
                    session.status = "logged_in"
                    return

                last_qr_refresh += 3
                if last_qr_refresh >= 10:
                    last_qr_refresh = 0
                    try:
                        await self._capture_qr(page, session=session)
                    except Exception:
                        pass

            session.status = "failed"
            session.error_message = "ログインがタイムアウトしました（5分経過）。再度お試しください。"

        except asyncio.CancelledError:
            session.status = "failed"
            session.error_message = "ログインがキャンセルされました。"
            raise
        except Exception as e:
            session.status = "failed"
            session.error_message = f"ログインエラー: {e}"
        finally:
            await self._cleanup_browser(session)
            if session.status in ("failed", "logged_in"):
                self._sessions.pop(session.user_id, None)

    # ------------------------------------------------------------------
    # Common
    # ------------------------------------------------------------------

    async def get_status(self, user_id: int) -> Optional[LoginSession]:
        return self._sessions.get(user_id)

    async def cancel_login(self, user_id: int) -> bool:
        session = self._sessions.pop(user_id, None)
        if not session:
            return False
        await self._close_session(session)
        return True

    async def cleanup_all(self) -> None:
        async with self._lock:
            user_ids = list(self._sessions.keys())
        for uid in user_ids:
            await self.cancel_login(uid)

    async def _close_session(self, session: LoginSession) -> None:
        if session._task and not session._task.done():
            session._task.cancel()
            try:
                await session._task
            except (asyncio.CancelledError, Exception):
                pass
        await self._cleanup_browser(session)

    async def _cleanup_browser(self, session: LoginSession) -> None:
        if session._browser:
            try:
                await session._browser.close()
            except Exception:
                pass
            session._browser = None
        if session._pw:
            try:
                await session._pw.stop()
            except Exception:
                pass
            session._pw = None
        session._context = None
        session._page = None

    async def _handle_intermediate_pages(self, page: Page, session: LoginSession) -> None:
        """Handle intermediate pages like security checks, 知道了 buttons, etc."""
        current_url = page.url

        # Handle login_unusual.htm - security verification page
        # The page shows "知道了" (Got it) button when environment is safe
        if "login_unusual" in current_url or "unusual" in current_url:
            _log(f"User {session.user_id}: detected unusual login page, looking for 知道了 button")
            confirm_selectors = [
                'button:has-text("知道了")',
                'a:has-text("知道了")',
                'input[value*="知道"]',
                'button:has-text("确定")',
                'a:has-text("确定")',
                'button:has-text("继续")',
                'a:has-text("继续")',
                ':text("知道了")',
            ]
            for sel in confirm_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        await el.click()
                        _log(f"User {session.user_id}: clicked confirmation button ({sel})")
                        await asyncio.sleep(3)
                        await self._save_debug_screenshot(page, session.user_id, "07_after_confirm")
                        new_url = page.url
                        _log(f"User {session.user_id}: after confirm, url={new_url}")
                        return
                except Exception as e:
                    _log(f"User {session.user_id}: confirm selector {sel} failed: {e}")
                    continue
            _log(f"User {session.user_id}: could not find confirm button on unusual page")

        # Handle other potential intermediate pages
        # Some pages have a simple "next step" or "continue" link
        try:
            next_selectors = [
                'a:has-text("下一步")',
                'button:has-text("下一步")',
                'a:has-text("进入")',
            ]
            for sel in next_selectors:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.click()
                    _log(f"User {session.user_id}: clicked next step ({sel})")
                    await asyncio.sleep(3)
                    return
        except Exception:
            pass

    async def _check_login_success(self, page: Page) -> bool:
        """Check if login succeeded via URL change or session cookies."""
        current_url = page.url

        # Skip intermediate pages (these still have login-related URLs but aren't login pages)
        if "login_unusual" in current_url:
            return False

        # URL no longer on login page
        if "login" not in current_url.lower() and "signin" not in current_url.lower():
            _log(f"Login detected: URL changed to {current_url}")
            return True

        # Check session cookies - cookie2 is the primary session cookie
        cookies = await page.context.cookies()
        has_cookie2 = any(
            c.get("name") == "cookie2"
            and (".1688.com" in (c.get("domain") or "") or ".taobao.com" in (c.get("domain") or ""))
            for c in cookies
        )
        # Also check __cn_logon__ which is a 1688-specific login indicator
        has_cn_logon = any(
            c.get("name") == "__cn_logon__" and ".1688.com" in (c.get("domain") or "")
            for c in cookies
        )
        if has_cookie2 and has_cn_logon:
            _log(f"Login detected: cookie2 + __cn_logon__ found")
            return True
        return False

    async def _capture_qr(self, page: Page, session: LoginSession | None = None) -> bytes:
        """Capture QR code screenshot."""
        qr_selectors = [
            'img[id*="qrcode"]', 'img[src*="qrcode"]',
            'div.qrcode-img img', 'div.qr-code img',
            'canvas.qrcode', '#China_Login_QR_498 img',
        ]
        screenshot_bytes = None
        for sel in qr_selectors:
            el = await page.query_selector(sel)
            if el:
                try:
                    screenshot_bytes = await el.screenshot(type="png")
                    break
                except Exception:
                    continue
        if not screenshot_bytes:
            screenshot_bytes = await page.screenshot(type="png")
        b64 = "data:image/png;base64," + base64.b64encode(screenshot_bytes).decode()
        if session:
            session.qr_image_b64 = b64
        return screenshot_bytes

    async def _save_storage(self, session: LoginSession) -> None:
        if not session._context:
            return
        storage = await session._context.storage_state()
        storage_path = get_user_storage_path(session.user_id)
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_text(
            json.dumps(storage, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _log(f"User {session.user_id}: storage saved to {storage_path}")


# Singleton instance
login_session_manager = LoginSessionManager()
