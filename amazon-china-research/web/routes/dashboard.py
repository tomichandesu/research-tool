"""Dashboard route (member landing page)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user, require_login
from ..database import get_db
from ..models import ResearchJob, User

router = APIRouter(tags=["dashboard"])

# Plan display info
PLAN_DISPLAY = {
    "lite": {"label": "ライト", "color": "badge-member"},
    "standard": {"label": "スタンダード", "color": "badge-active"},
    "pro": {"label": "プロ", "color": "badge-admin"},
}

SERVICE_TYPE_DISPLAY = {
    "none": "",
    "ai_automate": "AI自動物販",
    "alumni": "卒業生アフターフォロー",
}


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    # Recent jobs for this user
    result = await db.execute(
        select(ResearchJob)
        .where(ResearchJob.user_id == user.id)
        .order_by(ResearchJob.created_at.desc())
        .limit(10)
    )
    recent_jobs = list(result.scalars().all())

    plan_info = PLAN_DISPLAY.get(user.plan_type, PLAN_DISPLAY["lite"])
    service_label = SERVICE_TYPE_DISPLAY.get(user.service_type, "")

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "recent_jobs": recent_jobs,
            "plan_info": plan_info,
            "service_label": service_label,
        },
    )


@router.get("/help", response_class=HTMLResponse)
async def help_page(
    request: Request,
    user: User = Depends(require_login),
):
    templates = request.app.state.templates
    return templates.TemplateResponse("help.html", {"request": request, "user": user})


@router.get("/keyword-guide", response_class=HTMLResponse)
async def keyword_guide_page(
    request: Request,
    user: User = Depends(require_login),
):
    templates = request.app.state.templates
    return templates.TemplateResponse("keyword_guide.html", {"request": request, "user": user})


@router.get("/expired", response_class=HTMLResponse)
async def plan_expired(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "expired.html",
        {"request": request, "user": user},
    )
