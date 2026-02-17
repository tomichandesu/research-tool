"""FastAPI dependencies for authentication."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User
from ..services.user_service import check_plan_active
from .session import get_session


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Return the logged-in user or None."""
    session_id = request.session.get("sid")
    if not session_id:
        return None

    sess = await get_session(db, session_id)
    if sess is None:
        request.session.clear()
        return None

    user = await db.get(User, sess.user_id)
    if user is None or not user.is_active:
        request.session.clear()
        return None

    return user


async def require_login(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency that requires an authenticated active user with an active plan."""
    user = await get_current_user(request, db)
    if user is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    if user.role != "admin" and not check_plan_active(user):
        raise HTTPException(status_code=303, headers={"Location": "/expired"})
    return user


async def require_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency that requires admin role. Redirects to /admin/login if not logged in or not admin."""
    user = await get_current_user(request, db)
    if user is None or user.role != "admin":
        raise HTTPException(status_code=303, headers={"Location": "/admin/login"})
    return user
