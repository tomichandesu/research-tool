"""1688 session monitoring.

Periodically checks 1688 cookie expiry and logs warnings when session
is about to expire. Admin must manually re-login via
`python run_research.py --login` when cookies expire.

Note: 1688 does NOT extend cookie expiry on page visits; cookies have a
fixed lifetime set at login time.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from .job_runner import _AUTH_STORAGE_PATH, _REQUIRED_COOKIE_NAMES

logger = logging.getLogger(__name__)

# How often to check session status (6 hours)
CHECK_INTERVAL_SECONDS = 6 * 60 * 60

# Threshold for "expiring soon" warnings (24 hours)
EARLY_REFRESH_SECONDS = 24 * 60 * 60


def get_session_status() -> dict:
    """Return 1688 session status with remaining time.

    Returns dict with keys:
        valid (bool): Whether the session is currently valid
        message (str): Human-readable status
        min_expires_at (float|None): Earliest cookie expiry as Unix timestamp
        remaining_seconds (float|None): Seconds until earliest expiry
        remaining_hours (float|None): Hours until earliest expiry
    """
    if not _AUTH_STORAGE_PATH.exists():
        return {
            "valid": False,
            "message": "認証データなし",
            "min_expires_at": None,
            "remaining_seconds": None,
            "remaining_hours": None,
        }

    try:
        data = json.loads(_AUTH_STORAGE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "valid": False,
            "message": "認証データ破損",
            "min_expires_at": None,
            "remaining_seconds": None,
            "remaining_hours": None,
        }

    cookies = data.get("cookies", [])
    if not cookies:
        return {
            "valid": False,
            "message": "Cookieなし",
            "min_expires_at": None,
            "remaining_seconds": None,
            "remaining_hours": None,
        }

    now = time.time()
    # Find the earliest expiry among REQUIRED 1688 cookies (cookie2, csg)
    # Ignore other minor cookies that may expire earlier
    min_expiry = None
    for c in cookies:
        domain = c.get("domain", "")
        name = c.get("name", "")
        if ".1688.com" not in domain:
            continue
        if name not in _REQUIRED_COOKIE_NAMES:
            continue
        exp = c.get("expires", -1)
        if exp == -1:
            continue  # Session cookie, no fixed expiry
        if min_expiry is None or exp < min_expiry:
            min_expiry = exp

    if min_expiry is None:
        return {
            "valid": True,
            "message": "有効（期限なし）",
            "min_expires_at": None,
            "remaining_seconds": None,
            "remaining_hours": None,
        }

    remaining = min_expiry - now
    if remaining <= 0:
        return {
            "valid": False,
            "message": "セッション期限切れ",
            "min_expires_at": min_expiry,
            "remaining_seconds": 0,
            "remaining_hours": 0,
        }

    hours = remaining / 3600
    if hours < 24:
        msg = f"残り{hours:.1f}時間（要注意）"
    else:
        days = remaining / 86400
        msg = f"残り{days:.1f}日"

    return {
        "valid": True,
        "message": msg,
        "min_expires_at": min_expiry,
        "remaining_seconds": remaining,
        "remaining_hours": hours,
    }


async def session_keeper_loop():
    """Background loop that monitors 1688 session status.

    Checks every CHECK_INTERVAL_SECONDS and logs warnings when session
    is about to expire. Does NOT attempt auto-refresh (1688 cookies have
    fixed expiry and cannot be extended by page visits).
    """
    # Wait 60 seconds after startup before first check
    await asyncio.sleep(60)

    while True:
        try:
            status = get_session_status()
            remaining = status.get("remaining_seconds")
            hours = status.get("remaining_hours")

            if not status["valid"]:
                logger.error(
                    "1688 SESSION EXPIRED! "
                    "Run `python run_research.py --login` to re-login. "
                    f"Status: {status['message']}"
                )
            elif remaining is not None and hours is not None:
                if hours < 6:
                    logger.error(
                        f"1688 session expiring in {hours:.1f} hours! "
                        "Run `python run_research.py --login` NOW."
                    )
                elif hours < 24:
                    logger.warning(
                        f"1688 session expiring in {hours:.1f} hours. "
                        "Plan to re-login soon."
                    )
                elif hours < 48:
                    logger.info(
                        f"1688 session OK: {hours:.0f} hours remaining "
                        "(re-login recommended within 24h)"
                    )
                else:
                    logger.info(f"1688 session OK: {status['message']}")
            else:
                logger.info("1688 session valid (no fixed expiry)")

        except Exception:
            logger.exception("Error in session keeper loop")

        # Check more frequently as expiry approaches
        status = get_session_status()
        remaining = status.get("remaining_seconds")
        if remaining is not None and remaining < 6 * 3600:
            sleep_time = 600  # Every 10 minutes when < 6 hours
        elif remaining is not None and remaining < EARLY_REFRESH_SECONDS:
            sleep_time = 3600  # Every 1 hour when < 24 hours
        else:
            sleep_time = CHECK_INTERVAL_SECONDS

        await asyncio.sleep(sleep_time)
