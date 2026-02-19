"""Web application configuration."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
_project_root = Path(__file__).parent.parent
load_dotenv(_project_root / ".env")


class WebConfig:
    """Web application settings loaded from environment variables."""

    SECRET_KEY: str = os.getenv("SECRET_KEY", secrets.token_hex(32))
    DB_PATH: str = os.getenv("DB_PATH", str(_project_root / "data" / "app.db"))
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        f"sqlite+aiosqlite:///{os.getenv('DB_PATH', str(_project_root / 'data' / 'app.db'))}",
    )

    # Session
    SESSION_MAX_AGE_HOURS: int = int(os.getenv("SESSION_MAX_AGE_HOURS", "72"))

    # Invite
    INVITE_EXPIRE_DAYS: int = int(os.getenv("INVITE_EXPIRE_DAYS", "7"))

    # Admin seed
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "admin@example.com")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "changeme123")
    ADMIN_DISPLAY_NAME: str = os.getenv("ADMIN_DISPLAY_NAME", "Admin")

    # Job queue
    MAX_CONCURRENT_JOBS: int = int(os.getenv("MAX_CONCURRENT_JOBS", "1"))
    JOB_TIMEOUT_MINUTES: int = int(os.getenv("JOB_TIMEOUT_MINUTES", "30"))
    STALE_JOB_MINUTES: int = int(os.getenv("STALE_JOB_MINUTES", "45"))

    # Output
    JOBS_OUTPUT_DIR: str = os.getenv(
        "JOBS_OUTPUT_DIR", str(_project_root / "output" / "jobs")
    )

    # Server
    HOST: str = os.getenv("WEB_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("WEB_PORT", "8000"))

    # Login brute force protection
    MAX_LOGIN_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15

    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    # Stripe
    STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY: str = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_PRICE_LITE_MONTHLY: str = os.getenv("STRIPE_PRICE_LITE_MONTHLY", "")
    STRIPE_PRICE_LITE_ANNUAL: str = os.getenv("STRIPE_PRICE_LITE_ANNUAL", "")
    STRIPE_PRICE_STANDARD_MONTHLY: str = os.getenv("STRIPE_PRICE_STANDARD_MONTHLY", "")
    STRIPE_PRICE_STANDARD_ANNUAL: str = os.getenv("STRIPE_PRICE_STANDARD_ANNUAL", "")
    STRIPE_PRICE_PRO_ANNUAL: str = os.getenv("STRIPE_PRICE_PRO_ANNUAL", "")


settings = WebConfig()
