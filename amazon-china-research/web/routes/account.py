"""Account settings routes: profile edit."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import require_login
from ..database import get_db
from ..models import User

router = APIRouter(prefix="/account", tags=["account"])


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    user: User = Depends(require_login),
):
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "account/settings.html", {"request": request, "user": user}
    )


@router.post("/profile", response_class=HTMLResponse)
async def update_profile(
    request: Request,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    templates = request.app.state.templates
    form = await request.form()
    display_name = (form.get("display_name") or "").strip()
    email = (form.get("email") or "").strip().lower()

    if not display_name:
        return templates.TemplateResponse(
            "account/settings.html",
            {"request": request, "user": user, "error": "表示名を入力してください。"},
        )

    if not email or "@" not in email:
        return templates.TemplateResponse(
            "account/settings.html",
            {"request": request, "user": user, "error": "有効なメールアドレスを入力してください。"},
        )

    # Check email uniqueness (if changed)
    if email != user.email:
        existing = await db.scalar(select(User).where(User.email == email))
        if existing:
            return templates.TemplateResponse(
                "account/settings.html",
                {"request": request, "user": user, "error": "このメールアドレスは既に使われています。"},
            )

    user.display_name = display_name
    user.email = email
    await db.commit()

    return templates.TemplateResponse(
        "account/settings.html",
        {"request": request, "user": user, "success": "プロフィールを更新しました。"},
    )
