"""Server-side session management."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Session


async def create_session(db: AsyncSession, user_id: int) -> str:
    """Create a new session row and return the session id."""
    session_id = uuid.uuid4().hex
    expires = datetime.utcnow() + timedelta(hours=settings.SESSION_MAX_AGE_HOURS)
    row = Session(id=session_id, user_id=user_id, expires_at=expires)
    db.add(row)
    await db.commit()
    return session_id


async def get_session(db: AsyncSession, session_id: str) -> Session | None:
    """Return the session if it exists and is not expired."""
    stmt = select(Session).where(
        Session.id == session_id,
        Session.expires_at > datetime.utcnow(),
    )
    return await db.scalar(stmt)


async def delete_session(db: AsyncSession, session_id: str) -> None:
    """Delete a session (logout)."""
    await db.execute(delete(Session).where(Session.id == session_id))
    await db.commit()


async def cleanup_expired(db: AsyncSession) -> int:
    """Remove expired sessions. Returns count deleted."""
    result = await db.execute(
        delete(Session).where(Session.expires_at <= datetime.utcnow())
    )
    await db.commit()
    return result.rowcount  # type: ignore[return-value]
