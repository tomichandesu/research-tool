"""Authentication routes: login, logout, register."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..auth.service import hash_password, verify_password
from ..auth.session import create_session, delete_session
from ..config import settings
from ..database import get_db
from ..models import InviteToken, User, UsageLog

router = APIRouter(tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)
    if user:
        return RedirectResponse("/", status_code=303)
    templates = request.app.state.templates
    return templates.TemplateResponse("auth/login.html", {"request": request})


@router.post("/login")
async def login_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    password = form.get("password") or ""
    templates = request.app.state.templates

    # Find user
    user = await db.scalar(select(User).where(User.email == email))

    # Brute-force lockout check
    if user and user.locked_until and user.locked_until > datetime.utcnow():
        remaining = int((user.locked_until - datetime.utcnow()).total_seconds() // 60) + 1
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": f"アカウントがロックされています。{remaining}分後にお試しください。"},
            status_code=429,
        )

    if not user or not verify_password(password, user.password_hash):
        # Increment failed count
        if user:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.MAX_LOGIN_ATTEMPTS:
                user.locked_until = datetime.utcnow() + timedelta(
                    minutes=settings.LOGIN_LOCKOUT_MINUTES
                )
            await db.commit()
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "メールアドレスまたはパスワードが正しくありません。"},
            status_code=401,
        )

    if not user.is_active:
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "このアカウントは無効化されています。管理者にお問い合わせください。"},
            status_code=403,
        )

    # Reset failed login count on success
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = datetime.utcnow()

    session_id = await create_session(db, user.id)
    request.session["sid"] = session_id

    # Usage log
    db.add(UsageLog(user_id=user.id, action="login"))
    await db.commit()

    return RedirectResponse("/", status_code=303)


@router.get("/logout")
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    session_id = request.session.get("sid")
    if session_id:
        await delete_session(db, session_id)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/register/{token}", response_class=HTMLResponse)
async def register_page(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    templates = request.app.state.templates

    invite = await db.scalar(
        select(InviteToken).where(
            InviteToken.token == token,
            InviteToken.used_by.is_(None),
            InviteToken.expires_at > datetime.utcnow(),
        )
    )
    if not invite:
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "error": "この招待リンクは無効または期限切れです。", "token": token, "invalid": True},
        )

    return templates.TemplateResponse(
        "auth/register.html",
        {"request": request, "token": token, "invite_email": invite.email or ""},
    )


@router.post("/register/{token}")
async def register_submit(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    templates = request.app.state.templates
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    password = form.get("password") or ""
    display_name = (form.get("display_name") or "").strip()

    # Validate invite
    invite = await db.scalar(
        select(InviteToken).where(
            InviteToken.token == token,
            InviteToken.used_by.is_(None),
            InviteToken.expires_at > datetime.utcnow(),
        )
    )
    if not invite:
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "error": "この招待リンクは無効または期限切れです。", "token": token, "invalid": True},
        )

    # If invite is email-restricted, enforce it
    if invite.email and invite.email.lower() != email:
        return templates.TemplateResponse(
            "auth/register.html",
            {
                "request": request,
                "error": f"この招待リンクは {invite.email} 専用です。",
                "token": token,
                "invite_email": invite.email,
            },
        )

    # Validation
    errors = []
    if not email or "@" not in email:
        errors.append("有効なメールアドレスを入力してください。")
    if len(password) < 8:
        errors.append("パスワードは8文字以上にしてください。")
    if not display_name:
        errors.append("表示名を入力してください。")

    # Check uniqueness
    existing = await db.scalar(select(User).where(User.email == email))
    if existing:
        errors.append("このメールアドレスは既に登録されています。")

    if errors:
        return templates.TemplateResponse(
            "auth/register.html",
            {
                "request": request,
                "errors": errors,
                "token": token,
                "invite_email": invite.email or "",
                "form_email": email,
                "form_display_name": display_name,
            },
        )

    # Create user
    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
        role="member",
    )
    db.add(user)
    await db.flush()

    # Mark invite as used
    invite.used_by = user.id
    await db.commit()

    # Auto-login
    session_id = await create_session(db, user.id)
    request.session["sid"] = session_id

    return RedirectResponse("/", status_code=303)
