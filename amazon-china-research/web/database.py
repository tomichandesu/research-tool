"""Async SQLAlchemy database setup."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

logger = logging.getLogger(__name__)

# Ensure the directory for the SQLite file exists
_db_path = settings.DB_PATH
Path(_db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)

async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    """Create all tables if they don't exist, then run migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _migrate_add_plan_columns()


async def _migrate_add_plan_columns() -> None:
    """Add plan-related columns to existing tables (idempotent)."""
    migrations = [
        # Users table - plan fields
        ("users", "plan_type", "TEXT NOT NULL DEFAULT 'consul'"),
        ("users", "plan_billing", "TEXT NOT NULL DEFAULT 'none'"),
        ("users", "plan_expires_at", "DATETIME"),
        ("users", "consul_expires_at", "DATETIME"),
        ("users", "candidate_limit_monthly", "INTEGER DEFAULT 20"),
        ("users", "candidate_count_monthly", "INTEGER DEFAULT 0"),
        ("users", "candidate_reset_at", "DATETIME"),
        # Consul request fields
        ("users", "consul_request_status", "TEXT"),
        ("users", "consul_requested_at", "DATETIME"),
        # Stripe integration fields
        ("users", "stripe_customer_id", "TEXT"),
        ("users", "stripe_subscription_id", "TEXT"),
        ("users", "stripe_subscription_status", "TEXT"),
        # Research jobs table - auto mode fields
        ("research_jobs", "auto_max_keywords", "INTEGER DEFAULT 10"),
        ("research_jobs", "auto_max_duration", "INTEGER DEFAULT 60"),
    ]
    async with engine.begin() as conn:
        for table, col_name, col_def in migrations:
            try:
                await conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                )
                logger.info(f"Migration: added column {table}.{col_name}")
            except Exception:
                pass  # Column already exists


async def get_db() -> AsyncSession:
    """Dependency that yields an async DB session."""
    async with async_session_factory() as session:
        yield session
