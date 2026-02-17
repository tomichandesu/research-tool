"""User management and invite token services."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import InviteToken, User, ResearchJob
from .usage_tracker import PLAN_LIMITS


def check_plan_active(user: User) -> bool:
    """Check if a user's plan is still active.

    Returns True if the plan has no expiry, hasn't expired yet, or user is admin.
    """
    if user.role == "admin":
        return True
    if user.plan_expires_at is None:
        return True
    return user.plan_expires_at > datetime.utcnow()


def days_until_expiry(user: User) -> int | None:
    """Return the number of days until plan expiry, or None if no expiry set."""
    if user.plan_expires_at is None:
        return None
    delta = user.plan_expires_at - datetime.utcnow()
    return max(0, delta.days)


# Default extension periods per plan context
_EXTEND_MONTHS = {
    "monthly": 6,
    "annual": 6,
}


async def extend_plan(
    db: AsyncSession,
    user_id: int,
    months: int | None = None,
) -> User | None:
    """Extend a user's plan expiry by the given number of months.

    If months is None, the default is determined by plan_billing:
      - monthly billing -> 6 months
      - annual billing -> 6 months
    If plan_expires_at is in the past, extension starts from today.
    """
    user = await db.get(User, user_id)
    if not user:
        return None

    if months is None:
        if user.plan_billing == "annual":
            months = _EXTEND_MONTHS["annual"]
        else:
            months = _EXTEND_MONTHS["monthly"]

    now = datetime.utcnow()
    base = user.plan_expires_at if (user.plan_expires_at and user.plan_expires_at > now) else now
    user.plan_expires_at = base + relativedelta(months=months)
    await db.commit()
    await db.refresh(user)
    return user


async def list_users(db: AsyncSession) -> list[User]:
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return list(result.scalars().all())


async def get_user(db: AsyncSession, user_id: int) -> User | None:
    return await db.get(User, user_id)


async def update_user(
    db: AsyncSession,
    user_id: int,
    *,
    is_active: bool | None = None,
    usage_limit_monthly: int | None = None,
    role: str | None = None,
    service_type: str | None = None,
    plan_type: str | None = None,
    plan_billing: str | None = None,
    plan_expires_at: datetime | None = ...,
    consul_expires_at: datetime | None = ...,
    candidate_limit_monthly: int | None = None,
) -> User | None:
    user = await db.get(User, user_id)
    if not user:
        return None
    if is_active is not None:
        user.is_active = is_active
    if usage_limit_monthly is not None:
        user.usage_limit_monthly = usage_limit_monthly
    if role is not None:
        user.role = role
    if service_type is not None:
        user.service_type = service_type
    if plan_type is not None:
        user.plan_type = plan_type
        # Auto-set candidate limit based on plan
        if candidate_limit_monthly is None:
            limit = PLAN_LIMITS.get(plan_type, 20)
            if limit is not None:
                user.candidate_limit_monthly = limit
    if plan_billing is not None:
        user.plan_billing = plan_billing
    if plan_expires_at is not ...:
        user.plan_expires_at = plan_expires_at
    if consul_expires_at is not ...:
        user.consul_expires_at = consul_expires_at
    if candidate_limit_monthly is not None:
        user.candidate_limit_monthly = candidate_limit_monthly
    await db.commit()
    await db.refresh(user)
    return user


async def reset_monthly_usage(db: AsyncSession, user_id: int) -> None:
    user = await db.get(User, user_id)
    if user:
        user.usage_count_monthly = 0
        user.usage_reset_at = datetime.utcnow()
        user.candidate_count_monthly = 0
        user.candidate_reset_at = datetime.utcnow()
        await db.commit()


# --- Invite tokens ---

async def create_invite(
    db: AsyncSession,
    created_by: int,
    email: str | None = None,
    expire_days: int | None = None,
) -> InviteToken:
    token = uuid.uuid4().hex
    days = expire_days or settings.INVITE_EXPIRE_DAYS
    invite = InviteToken(
        token=token,
        email=email.strip().lower() if email else None,
        created_by=created_by,
        expires_at=datetime.utcnow() + timedelta(days=days),
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)
    return invite


async def list_invites(db: AsyncSession) -> list[InviteToken]:
    result = await db.execute(
        select(InviteToken).order_by(InviteToken.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_invite(db: AsyncSession, invite_id: int) -> bool:
    invite = await db.get(InviteToken, invite_id)
    if not invite:
        return False
    await db.delete(invite)
    await db.commit()
    return True


# --- Stats ---

async def admin_stats(db: AsyncSession) -> dict:
    total_users = await db.scalar(select(sa_func.count()).select_from(User))
    active_users = await db.scalar(
        select(sa_func.count()).select_from(User).where(User.is_active == True)
    )
    today = datetime.utcnow().date()
    today_start = datetime(today.year, today.month, today.day)
    jobs_today = await db.scalar(
        select(sa_func.count())
        .select_from(ResearchJob)
        .where(ResearchJob.created_at >= today_start)
    )
    pending_jobs = await db.scalar(
        select(sa_func.count())
        .select_from(ResearchJob)
        .where(ResearchJob.status == "pending")
    )
    running_jobs = await db.scalar(
        select(sa_func.count())
        .select_from(ResearchJob)
        .where(ResearchJob.status == "running")
    )

    # Plan distribution
    plan_counts = {}
    for plan in ["lite", "standard", "pro"]:
        cnt = await db.scalar(
            select(sa_func.count())
            .select_from(User)
            .where(User.plan_type == plan, User.is_active == True)
        )
        plan_counts[plan] = cnt or 0

    return {
        "total_users": total_users or 0,
        "active_users": active_users or 0,
        "jobs_today": jobs_today or 0,
        "pending_jobs": pending_jobs or 0,
        "running_jobs": running_jobs or 0,
        "plan_counts": plan_counts,
    }
