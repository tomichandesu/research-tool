"""Email sending service for password reset etc."""
from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

from ..config import settings

logger = logging.getLogger(__name__)


def send_password_reset_email(to_email: str, reset_url: str) -> bool:
    """Send a password reset email. Returns True if sent, False if SMTP not configured."""
    if not settings.SMTP_HOST or not settings.SMTP_FROM:
        logger.warning("SMTP not configured, skipping email send")
        return False

    body = f"""パスワードリセットのリクエストを受け付けました。

以下のリンクをクリックして、新しいパスワードを設定してください：

{reset_url}

このリンクは1時間有効です。

心当たりがない場合は、このメールを無視してください。
"""
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "パスワードリセット - Amazon-1688 リサーチツール"
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
        logger.info(f"Password reset email sent to {to_email}")
        return True
    except Exception:
        logger.exception(f"Failed to send password reset email to {to_email}")
        return False
