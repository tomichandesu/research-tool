"""Research job routes."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import require_login
from ..database import get_db
from ..models import ResearchJob, SavedKeyword, User
from ..services.ai_keyword_service import stream_keyword_chat
from ..services.job_queue import job_queue
from ..services.job_runner import cancel_job, check_1688_session
from ..services.keyword_discovery import (
    get_all_categories,
    get_category_keywords,
    get_random_keyword,
    get_successful_keywords,
)
from ..services.usage_tracker import check_usage_limit, increment_usage, log_action

router = APIRouter(prefix="/research", tags=["research"])


@router.get("/new", response_class=HTMLResponse)
async def research_new(
    request: Request,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    allowed, msg = await check_usage_limit(db, user)

    # Load saved keywords
    result = await db.execute(
        select(SavedKeyword)
        .where(SavedKeyword.user_id == user.id)
        .order_by(SavedKeyword.created_at.desc())
    )
    saved_keywords = list(result.scalars().all())

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "research/new.html",
        {
            "request": request,
            "user": user,
            "usage_allowed": allowed,
            "usage_message": msg,
            "saved_keywords": saved_keywords,
        },
    )


@router.post("/new")
async def research_submit(
    request: Request,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    templates = request.app.state.templates
    form = await request.form()
    keyword = (form.get("keyword") or "").strip()

    if not keyword:
        return templates.TemplateResponse(
            "research/new.html",
            {"request": request, "user": user, "error": "Keyword required",
             "usage_allowed": True, "usage_message": "",
             "session_ok": True, "session_msg": ""},
        )

    # Check 1688 session before starting research
    session_ok, session_msg = check_1688_session()
    if not session_ok:
        return templates.TemplateResponse(
            "research/new.html",
            {"request": request, "user": user, "error": session_msg,
             "usage_allowed": True, "usage_message": ""},
        )

    # Check usage limit
    allowed, msg = await check_usage_limit(db, user)
    if not allowed:
        return templates.TemplateResponse(
            "research/new.html",
            {"request": request, "user": user, "error": msg,
             "usage_allowed": False, "usage_message": msg},
        )

    # Auto-cleanup stale jobs (running > 2 hours = definitely stuck)
    stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    stale_result = await db.execute(
        select(ResearchJob).where(
            ResearchJob.user_id == user.id,
            ResearchJob.status.in_(["pending", "running"]),
        )
    )
    for stale_job in stale_result.scalars().all():
        job_time = stale_job.started_at or stale_job.created_at
        if job_time and job_time.replace(tzinfo=timezone.utc) < stale_cutoff:
            stale_job.status = "failed"
            stale_job.error_message = "タイムアウト（2時間以上経過のため自動終了）"
            stale_job.completed_at = datetime.now(timezone.utc)

    await db.flush()

    # Check if user still has an active job after cleanup
    existing = await db.scalar(
        select(ResearchJob).where(
            ResearchJob.user_id == user.id,
            ResearchJob.status.in_(["pending", "running"]),
        )
    )
    if existing:
        return templates.TemplateResponse(
            "research/new.html",
            {"request": request, "user": user,
             "error": "実行中のリサーチがあります。完了するまでお待ちください。",
             "usage_allowed": True, "usage_message": ""},
        )

    # Create job
    mode = (form.get("mode") or "single").strip()
    if mode not in ("single", "auto"):
        mode = "single"

    job = ResearchJob(user_id=user.id, keyword=keyword, mode=mode)

    if mode == "auto":
        job.auto_max_keywords = min(int(form.get("auto_max_keywords") or 10), 100)
        job.auto_max_duration = 60  # 固定60分（セーフティタイムアウト）

    db.add(job)
    await db.flush()

    # Increment usage
    await increment_usage(db, user)
    await log_action(db, user.id, "research_start",
                     json.dumps({"keyword": keyword, "job_id": job.id}))
    await db.commit()

    # Enqueue
    await job_queue.enqueue(job.id, user.id)

    return RedirectResponse(f"/research/{job.id}", status_code=303)


@router.get("/history", response_class=HTMLResponse)
async def research_history(
    request: Request,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ResearchJob)
        .where(ResearchJob.user_id == user.id)
        .order_by(ResearchJob.created_at.desc())
        .limit(50)
    )
    jobs = list(result.scalars().all())

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "research/history.html",
        {"request": request, "user": user, "jobs": jobs},
    )


# --- Keyword Discovery ---


@router.get("/discovery/categories", response_class=HTMLResponse)
async def discovery_categories(
    request: Request,
    user: User = Depends(require_login),
):
    categories = get_all_categories()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "research/_discovery_categories.html",
        {"request": request, "categories": categories},
    )


@router.get("/discovery/categories/{category_id}", response_class=HTMLResponse)
async def discovery_category_keywords(
    category_id: str,
    request: Request,
    user: User = Depends(require_login),
):
    category = get_category_keywords(category_id)
    if not category:
        return HTMLResponse("<p>カテゴリが見つかりません。</p>")
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "research/_discovery_category_keywords.html",
        {"request": request, "category": category},
    )


@router.get("/discovery/random", response_class=HTMLResponse)
async def discovery_random(
    request: Request,
    user: User = Depends(require_login),
):
    kw = get_random_keyword()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "research/_discovery_random.html",
        {"request": request, "kw": kw},
    )


@router.get("/discovery/successful", response_class=HTMLResponse)
async def discovery_successful(
    request: Request,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    keywords = await get_successful_keywords(db)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "research/_discovery_successful.html",
        {"request": request, "keywords": keywords},
    )


@router.post("/discovery/ai-chat")
async def discovery_ai_chat(
    request: Request,
    user: User = Depends(require_login),
):
    """SSE endpoint for AI keyword discovery chat."""
    body = await request.json()
    message = (body.get("message") or "").strip()
    history = body.get("history") or []

    if not message:
        return StreamingResponse(
            iter(["data: {\"error\": \"メッセージを入力してください\"}\n\n"]),
            media_type="text/event-stream",
        )

    # Build messages for OpenAI
    messages = []
    for msg in history:
        role = msg.get("role")
        content = msg.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    async def event_stream():
        async for chunk in stream_keyword_chat(messages):
            escaped = json.dumps(chunk, ensure_ascii=False)
            yield f"data: {{\"chunk\": {escaped}}}\n\n"
        yield "data: {\"done\": true}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{job_id}", response_class=HTMLResponse)
async def research_detail(
    job_id: int,
    request: Request,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(ResearchJob, job_id)
    if not job:
        return RedirectResponse("/", status_code=303)

    # Members can only see their own jobs; admins see all
    if job.user_id != user.id and user.role != "admin":
        return RedirectResponse("/", status_code=303)

    summary = None
    if job.result_summary:
        try:
            summary = json.loads(job.result_summary)
        except json.JSONDecodeError:
            pass

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "research/detail.html",
        {"request": request, "user": user, "job": job, "summary": summary},
    )


@router.get("/{job_id}/status")
async def research_status_api(
    job_id: int,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """HTMX polling endpoint for job status."""
    job = await db.get(ResearchJob, job_id)
    if not job or (job.user_id != user.id and user.role != "admin"):
        return {"status": "not_found"}

    progress_pct = job.progress_pct
    progress_message = job.progress_message or ""

    # Read real-time progress from file written by subprocess
    if job.status == "running":
        from ..config import settings
        progress_file = Path(settings.JOBS_OUTPUT_DIR) / str(job_id) / "progress.json"
        if progress_file.exists():
            try:
                data = json.loads(progress_file.read_text(encoding="utf-8"))
                progress_pct = data.get("pct", progress_pct)
                progress_message = data.get("message", progress_message)
            except Exception:
                pass

    return {
        "status": job.status,
        "progress_pct": progress_pct,
        "progress_message": progress_message,
    }


@router.post("/{job_id}/cancel")
async def research_cancel(
    job_id: int,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a running or pending research job."""
    job = await db.get(ResearchJob, job_id)
    if not job or (job.user_id != user.id and user.role != "admin"):
        return RedirectResponse("/", status_code=303)

    await cancel_job(job_id)
    return RedirectResponse(f"/research/{job_id}", status_code=303)


@router.get("/{job_id}/download/{filetype}")
async def research_download(
    job_id: int,
    filetype: str,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(ResearchJob, job_id)
    if not job or (job.user_id != user.id and user.role != "admin"):
        return RedirectResponse("/", status_code=303)

    if filetype == "html" and job.result_html_path:
        path = Path(job.result_html_path)
    elif filetype == "excel" and job.result_excel_path:
        path = Path(job.result_excel_path)
    else:
        return RedirectResponse(f"/research/{job_id}", status_code=303)

    if not path.exists():
        return RedirectResponse(f"/research/{job_id}", status_code=303)

    return FileResponse(path, filename=path.name)


# --- Saved Keywords ---


@router.post("/keywords/save")
async def save_keyword(
    request: Request,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    keyword = (form.get("keyword") or "").strip()
    if not keyword:
        return RedirectResponse("/research/new", status_code=303)

    # Check if already saved
    existing = await db.scalar(
        select(SavedKeyword).where(
            SavedKeyword.user_id == user.id,
            SavedKeyword.keyword == keyword,
        )
    )
    if not existing:
        db.add(SavedKeyword(user_id=user.id, keyword=keyword))
        await db.commit()

    return RedirectResponse("/research/new", status_code=303)


@router.post("/keywords/{keyword_id}/delete")
async def delete_keyword(
    keyword_id: int,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    kw = await db.get(SavedKeyword, keyword_id)
    if kw and kw.user_id == user.id:
        await db.delete(kw)
        await db.commit()
    return RedirectResponse("/research/new", status_code=303)
