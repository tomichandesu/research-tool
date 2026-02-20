"""Research job routes."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import aiohttp

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import require_login
from ..config import settings
from ..database import get_db
from ..models import ReferenceSeller, ResearchJob, SavedKeyword, User
from ..services.ai_keyword_service import stream_keyword_chat
from ..services.job_queue import job_queue
from ..services.job_runner import cancel_job, check_user_1688_session
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

    # Check per-user 1688 session status
    session_ok, session_msg = check_user_1688_session(user.id)

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
            "session_ok": session_ok,
            "session_msg": session_msg,
            "max_batch_size": settings.MAX_BATCH_SIZE,
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
    raw_keywords = (form.get("keyword") or "").strip()
    research_type = (form.get("research_type") or "batch").strip()

    err_ctx = {
        "request": request, "user": user,
        "usage_allowed": True, "usage_message": "",
        "session_ok": True, "session_msg": "",
        "max_batch_size": settings.MAX_BATCH_SIZE,
        "saved_keywords": [],
    }

    if not raw_keywords:
        return templates.TemplateResponse(
            "research/new.html",
            {**err_ctx, "error": "キーワードを入力してください"},
        )

    # Parse keywords based on research_type
    if research_type == "deep":
        # Deep mode: single keyword only
        keywords = [raw_keywords.splitlines()[0].strip()]
        keywords = [kw for kw in keywords if kw]
    else:
        # Batch mode: one per line, deduplicate, preserve order
        seen: set[str] = set()
        keywords = []
        for line in raw_keywords.splitlines():
            kw = line.strip()
            if kw and kw not in seen:
                seen.add(kw)
                keywords.append(kw)

    if not keywords:
        return templates.TemplateResponse(
            "research/new.html",
            {**err_ctx, "error": "キーワードを入力してください"},
        )

    # Enforce limits
    if research_type == "batch" and len(keywords) > settings.MAX_BATCH_SIZE:
        return templates.TemplateResponse(
            "research/new.html",
            {**err_ctx, "error": f"一度に登録できるキーワードは最大{settings.MAX_BATCH_SIZE}個です。"},
        )

    # Check per-user 1688 session before starting research
    session_ok, session_msg = check_user_1688_session(user.id)
    if not session_ok:
        return templates.TemplateResponse(
            "research/new.html",
            {**err_ctx, "error": session_msg},
        )

    # Check usage limit
    allowed, msg = await check_usage_limit(db, user)
    if not allowed:
        return templates.TemplateResponse(
            "research/new.html",
            {**err_ctx, "error": msg, "usage_allowed": False, "usage_message": msg},
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

    # For deep (single keyword) mode, check if user already has an active job
    if research_type == "deep":
        existing = await db.scalar(
            select(ResearchJob).where(
                ResearchJob.user_id == user.id,
                ResearchJob.status.in_(["pending", "running"]),
            )
        )
        if existing:
            return templates.TemplateResponse(
                "research/new.html",
                {**err_ctx, "error": "実行中のリサーチがあります。完了するまでお待ちください。"},
            )

    # Create job(s)
    is_batch = len(keywords) > 1
    batch_group_id = str(uuid.uuid4()) if is_batch else None
    default_max = 30 if research_type == "deep" else 10
    auto_max_kw = min(int(form.get("auto_max_keywords") or default_max), 100)
    created_jobs: list[ResearchJob] = []

    for pos, kw in enumerate(keywords, start=1):
        job = ResearchJob(
            user_id=user.id,
            keyword=kw,
            mode="auto",
            auto_max_keywords=auto_max_kw,
            auto_max_duration=60,
            batch_group_id=batch_group_id,
            batch_position=pos if is_batch else None,
        )
        db.add(job)
        created_jobs.append(job)

    await db.flush()

    # Increment usage for each keyword
    for job in created_jobs:
        await increment_usage(db, user)
        await log_action(db, user.id, "research_start",
                         json.dumps({"keyword": job.keyword, "job_id": job.id,
                                     "batch_group_id": batch_group_id}))

    await db.commit()

    # Enqueue all jobs
    for job in created_jobs:
        await job_queue.enqueue(job.id, user.id)

    # Redirect to the first job's detail page
    return RedirectResponse(f"/research/{created_jobs[0].id}", status_code=303)


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
    db: AsyncSession = Depends(get_db),
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

    # Load reference seller products
    reference_products: list[str] = []
    result = await db.execute(
        select(ReferenceSeller).where(ReferenceSeller.products_json.isnot(None))
    )
    for seller in result.scalars().all():
        try:
            titles = json.loads(seller.products_json)
            if isinstance(titles, list):
                reference_products.extend(titles)
        except (json.JSONDecodeError, TypeError):
            pass

    async def event_stream():
        async for chunk in stream_keyword_chat(
            messages, reference_products=reference_products or None
        ):
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


_logger = logging.getLogger(__name__)

AMAZON_SUGGEST_URL = (
    "https://completion.amazon.co.jp/api/2017/suggestions"
    "?mid=A1VC38T7YXB528&alias=aps&prefix={query}"
)


async def _fetch_amazon_suggestions(keyword: str) -> list[str]:
    """Fetch autocomplete suggestions from Amazon.co.jp."""
    url = AMAZON_SUGGEST_URL.format(query=quote(keyword + " "))
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json(content_type=None)
    except Exception:
        _logger.exception("Amazon suggest API error for keyword=%s", keyword)
        return []
    return [
        item["value"]
        for item in data.get("suggestions", [])
        if item.get("value", "").strip() and item["value"].strip() != keyword
    ]


@router.post("/discovery/keyword-expand")
async def discovery_keyword_expand(
    request: Request,
    user: User = Depends(require_login),
):
    """Return Amazon autocomplete suggestions for a keyword."""
    body = await request.json()
    keyword = (body.get("keyword") or "").strip()

    if not keyword:
        return JSONResponse({"suggestions": [], "error": "キーワードを指定してください"})

    suggestions = await _fetch_amazon_suggestions(keyword)
    return JSONResponse({"suggestions": suggestions})


@router.get("/{job_id}/batch-queue")
async def batch_queue_status(
    job_id: int,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """Return batch queue status for polling."""
    job = await db.get(ResearchJob, job_id)
    if not job or (job.user_id != user.id and user.role != "admin"):
        return {"error": "not_found"}

    if not job.batch_group_id:
        return {"batch": False}

    result = await db.execute(
        select(ResearchJob)
        .where(ResearchJob.batch_group_id == job.batch_group_id)
        .order_by(ResearchJob.batch_position)
    )
    batch_jobs = list(result.scalars().all())

    completed_count = sum(1 for j in batch_jobs if j.status in ("completed", "failed"))
    total = len(batch_jobs)

    # Find the currently running or next pending job for auto-navigation
    current_active_id = None
    for j in batch_jobs:
        if j.status in ("running", "pending"):
            current_active_id = j.id
            break

    jobs_data = []
    for j in batch_jobs:
        # Read progress from file for running jobs
        progress_pct = j.progress_pct
        progress_message = j.progress_message or ""
        if j.status == "running":
            progress_file = Path(settings.JOBS_OUTPUT_DIR) / str(j.id) / "progress.json"
            if progress_file.exists():
                try:
                    data = json.loads(progress_file.read_text(encoding="utf-8"))
                    progress_pct = data.get("pct", progress_pct)
                    progress_message = data.get("message", progress_message)
                except Exception:
                    pass

        jobs_data.append({
            "id": j.id,
            "keyword": j.keyword,
            "position": j.batch_position,
            "status": j.status,
            "progress_pct": progress_pct,
            "progress_message": progress_message,
        })

    return {
        "batch": True,
        "batch_group_id": job.batch_group_id,
        "total": total,
        "completed": completed_count,
        "current_active_id": current_active_id,
        "jobs": jobs_data,
    }


@router.post("/batch/{batch_group_id}/cancel-pending")
async def batch_cancel_pending(
    batch_group_id: str,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """Cancel all pending jobs in a batch."""
    result = await db.execute(
        select(ResearchJob).where(
            ResearchJob.batch_group_id == batch_group_id,
            ResearchJob.status == "pending",
        )
    )
    cancelled = 0
    for job in result.scalars().all():
        if job.user_id != user.id and user.role != "admin":
            continue
        job.status = "cancelled"
        job.completed_at = datetime.now(timezone.utc)
        job.error_message = "ユーザーによるキャンセル"
        cancelled += 1

    await db.commit()

    # Find any job from this batch to redirect to
    any_job = await db.scalar(
        select(ResearchJob).where(
            ResearchJob.batch_group_id == batch_group_id,
        )
    )
    if any_job:
        return RedirectResponse(f"/research/{any_job.id}", status_code=303)
    return RedirectResponse("/research/history", status_code=303)


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

    # Load batch info if applicable
    batch_jobs = []
    if job.batch_group_id:
        result = await db.execute(
            select(ResearchJob)
            .where(ResearchJob.batch_group_id == job.batch_group_id)
            .order_by(ResearchJob.batch_position)
        )
        batch_jobs = list(result.scalars().all())

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "research/detail.html",
        {
            "request": request,
            "user": user,
            "job": job,
            "summary": summary,
            "batch_jobs": batch_jobs,
        },
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
