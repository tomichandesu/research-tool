"""Account settings routes: profile edit + 1688 account linking (SMS)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import require_login
from ..database import get_db
from ..models import User
from ..services.alibaba_login import get_user_storage_path, login_session_manager
from ..services.job_runner import check_user_1688_session

router = APIRouter(prefix="/account", tags=["account"])


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    user: User = Depends(require_login),
):
    # Check per-user 1688 session status
    alibaba_session_valid, alibaba_session_message = check_user_1688_session(user.id)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "account/settings.html",
        {
            "request": request,
            "user": user,
            "alibaba_session_valid": alibaba_session_valid,
            "alibaba_session_message": alibaba_session_message,
        },
    )


@router.post("/profile", response_class=HTMLResponse)
async def update_profile(
    request: Request,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    alibaba_session_valid, alibaba_session_message = check_user_1688_session(user.id)
    templates = request.app.state.templates
    form = await request.form()
    display_name = (form.get("display_name") or "").strip()
    email = (form.get("email") or "").strip().lower()

    ctx = {
        "request": request,
        "user": user,
        "alibaba_session_valid": alibaba_session_valid,
        "alibaba_session_message": alibaba_session_message,
    }

    if not display_name:
        return templates.TemplateResponse(
            "account/settings.html",
            {**ctx, "error": "表示名を入力してください。"},
        )

    if not email or "@" not in email:
        return templates.TemplateResponse(
            "account/settings.html",
            {**ctx, "error": "有効なメールアドレスを入力してください。"},
        )

    # Check email uniqueness (if changed)
    if email != user.email:
        existing = await db.scalar(select(User).where(User.email == email))
        if existing:
            return templates.TemplateResponse(
                "account/settings.html",
                {**ctx, "error": "このメールアドレスは既に使われています。"},
            )

    user.display_name = display_name
    user.email = email
    await db.commit()

    return templates.TemplateResponse(
        "account/settings.html",
        {**ctx, "success": "プロフィールを更新しました。"},
    )


# --- 1688 Account Linking Endpoints (SMS) ---


class PhoneSubmit(BaseModel):
    phone: str


class CodeSubmit(BaseModel):
    code: str


@router.post("/1688/login/start")
async def alibaba_login_start(
    user: User = Depends(require_login),
):
    """Start an SMS login session for the user's 1688 account."""
    try:
        session = await login_session_manager.start_sms_login(user.id)
        return JSONResponse({
            "status": session.status,
        })
    except ValueError as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=429)


@router.post("/1688/login/phone")
async def alibaba_login_phone(
    body: PhoneSubmit,
    user: User = Depends(require_login),
):
    """Submit phone number for SMS verification."""
    phone = body.phone.strip()
    if not phone:
        return JSONResponse({"status": "error", "message": "電話番号を入力してください。"}, status_code=400)

    ok = await login_session_manager.submit_phone(user.id, phone)
    if not ok:
        return JSONResponse({"status": "error", "message": "アクティブなログインセッションがありません。"}, status_code=400)

    return JSONResponse({"status": "ok"})


@router.post("/1688/login/code")
async def alibaba_login_code(
    body: CodeSubmit,
    user: User = Depends(require_login),
):
    """Submit SMS verification code."""
    code = body.code.strip()
    if not code:
        return JSONResponse({"status": "error", "message": "認証コードを入力してください。"}, status_code=400)

    ok = await login_session_manager.submit_sms_code(user.id, code)
    if not ok:
        return JSONResponse({"status": "error", "message": "アクティブなログインセッションがありません。"}, status_code=400)

    return JSONResponse({"status": "ok"})


@router.get("/1688/login/status")
async def alibaba_login_status(
    user: User = Depends(require_login),
):
    """Check the current status of a user's login session."""
    session = await login_session_manager.get_status(user.id)
    if not session:
        # No active session — check if already linked
        valid, _ = check_user_1688_session(user.id)
        if valid:
            return JSONResponse({"status": "logged_in"})
        return JSONResponse({"status": "none"})

    return JSONResponse({
        "status": session.status,
        "error": session.error_message,
    })


@router.post("/1688/login/cancel")
async def alibaba_login_cancel(
    user: User = Depends(require_login),
):
    """Cancel an in-progress login session."""
    cancelled = await login_session_manager.cancel_login(user.id)
    return JSONResponse({"cancelled": cancelled})


@router.post("/1688/disconnect")
async def alibaba_disconnect(
    user: User = Depends(require_login),
):
    """Remove the user's 1688 session (disconnect account)."""
    storage_path = get_user_storage_path(user.id)
    if storage_path.exists():
        storage_path.unlink()
    return JSONResponse({"disconnected": True})
