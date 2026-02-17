"""Usage tracking based on monthly candidate product count."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User, UsageLog

# Plan limits: plan_type -> monthly candidate limit
PLAN_LIMITS = {
    "lite": 20,
    "standard": 40,
    "pro": 100,
}


def get_candidate_limit(user: User) -> int:
    """Return monthly candidate limit for the user's plan."""
    return user.candidate_limit_monthly


async def check_candidate_limit(db: AsyncSession, user: User) -> tuple[bool, str]:
    """Check if user can start a new research based on candidate count.

    Returns (allowed, message). Resets counter if new month.
    """
    now = datetime.utcnow()

    # Auto-reset if new month
    if user.candidate_reset_at is None or user.candidate_reset_at.month != now.month or user.candidate_reset_at.year != now.year:
        user.candidate_count_monthly = 0
        user.candidate_reset_at = now
        await db.commit()

    limit = get_candidate_limit(user)
    if user.candidate_count_monthly >= limit:
        return False, f"月間候補商品上限に達しました ({user.candidate_count_monthly}/{limit})"

    return True, ""


async def add_candidates(db: AsyncSession, user: User, count: int) -> None:
    """Add candidate count from a completed research to the user's monthly total."""
    if count <= 0:
        return
    user.candidate_count_monthly += count
    await db.commit()


async def get_usage_display(user: User) -> dict:
    """Return display info for the user's usage."""
    limit = get_candidate_limit(user)
    return {
        "count": user.candidate_count_monthly,
        "limit": limit,
        "limit_display": str(limit),
        "is_unlimited": False,
        "remaining": limit - user.candidate_count_monthly,
    }


# Legacy compat wrappers (called from existing code)
async def check_usage_limit(db: AsyncSession, user: User) -> tuple[bool, str]:
    return await check_candidate_limit(db, user)


async def increment_usage(db: AsyncSession, user: User) -> None:
    """No-op: usage is now tracked by candidate count on job completion."""
    pass


async def log_action(
    db: AsyncSession,
    user_id: int,
    action: str,
    metadata: str | None = None,
) -> None:
    db.add(UsageLog(user_id=user_id, action=action, metadata_json=metadata))
    await db.commit()
