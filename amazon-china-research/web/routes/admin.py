"""Admin routes."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user, require_admin
from ..auth.service import hash_password, verify_password
from ..auth.session import create_session, delete_session
from ..config import settings
from ..database import get_db
from ..models import ExcludedKeyword, ReferenceSeller, ResearchJob, User, UsageLog
from ..services.session_keeper import get_session_status
from ..services.usage_tracker import PLAN_LIMITS
from ..services.user_service import (
    admin_stats,
    create_invite,
    delete_invite,
    extend_plan,
    list_invites,
    list_users,
    get_user,
    reset_monthly_usage,
    update_user,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# Plan display info
PLAN_DISPLAY = {
    "lite": {"label": "ライト", "color": "badge-member"},
    "standard": {"label": "スタンダード", "color": "badge-active"},
    "pro": {"label": "プロ", "color": "badge-admin"},
}


@router.get("/login", response_class=HTMLResponse)
async def admin_login_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)
    if user and user.role == "admin":
        return RedirectResponse("/admin/", status_code=303)
    templates = request.app.state.templates
    return templates.TemplateResponse("admin/login.html", {"request": request})


@router.post("/login")
async def admin_login_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    password = form.get("password") or ""
    templates = request.app.state.templates

    user = await db.scalar(select(User).where(User.email == email))

    # Lockout check
    if user and user.locked_until and user.locked_until > datetime.utcnow():
        remaining = int((user.locked_until - datetime.utcnow()).total_seconds() // 60) + 1
        return templates.TemplateResponse(
            "admin/login.html",
            {"request": request, "error": f"アカウントがロックされています。{remaining}分後にお試しください。"},
            status_code=429,
        )

    if not user or not verify_password(password, user.password_hash):
        if user:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.MAX_LOGIN_ATTEMPTS:
                user.locked_until = datetime.utcnow() + timedelta(
                    minutes=settings.LOGIN_LOCKOUT_MINUTES
                )
            await db.commit()
        return templates.TemplateResponse(
            "admin/login.html",
            {"request": request, "error": "メールアドレスまたはパスワードが正しくありません。"},
            status_code=401,
        )

    if not user.is_active:
        return templates.TemplateResponse(
            "admin/login.html",
            {"request": request, "error": "このアカウントは無効化されています。"},
            status_code=403,
        )

    if user.role != "admin":
        return templates.TemplateResponse(
            "admin/login.html",
            {"request": request, "error": "管理者権限がありません。"},
            status_code=403,
        )

    # Login success
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = datetime.utcnow()
    session_id = await create_session(db, user.id)
    request.session["sid"] = session_id
    db.add(UsageLog(user_id=user.id, action="admin_login"))
    await db.commit()

    return RedirectResponse("/admin/", status_code=303)


@router.get("/logout")
async def admin_logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    session_id = request.session.get("sid")
    if session_id:
        await delete_session(db, session_id)
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stats = await admin_stats(db)
    session_status = get_session_status()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "admin/dashboard.html",
        {"request": request, "user": user, "stats": stats,
         "plan_display": PLAN_DISPLAY, "session_status": session_status},
    )


@router.get("/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    users = await list_users(db)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "admin/users.html",
        {"request": request, "user": user, "users": users,
         "plan_display": PLAN_DISPLAY, "plan_limits": PLAN_LIMITS},
    )


@router.post("/users/create")
async def admin_create_user(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    display_name = (form.get("display_name") or "").strip()
    password = form.get("password") or ""
    plan_type = form.get("plan_type") or "lite"
    templates = request.app.state.templates

    errors = []
    if not email or "@" not in email:
        errors.append("Valid email required.")
    if not display_name:
        errors.append("Display name required.")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if plan_type not in PLAN_LIMITS:
        errors.append("Invalid plan type.")

    # Check uniqueness
    existing = await db.scalar(select(User).where(User.email == email))
    if existing:
        errors.append("This email is already registered.")

    if errors:
        users = await list_users(db)
        return templates.TemplateResponse(
            "admin/users.html",
            {"request": request, "user": user, "users": users, "errors": errors,
             "form_email": email, "form_display_name": display_name,
             "plan_display": PLAN_DISPLAY, "plan_limits": PLAN_LIMITS},
        )

    candidate_limit = PLAN_LIMITS.get(plan_type, 20)
    service_type = form.get("service_type") or "none"

    # Determine billing based on service type
    if service_type == "alumni":
        plan_billing = "annual"
    else:
        plan_billing = "none"

    # 全プラン共通: 6ヶ月間
    now = datetime.utcnow()
    plan_expires_at = now + relativedelta(months=6)

    new_user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
        role="member",
        is_active=True,
        service_type=service_type,
        plan_type=plan_type,
        plan_billing=plan_billing,
        plan_expires_at=plan_expires_at,
        candidate_limit_monthly=candidate_limit,
    )
    db.add(new_user)
    await db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def admin_user_detail(
    user_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    target = await get_user(db, user_id)
    if not target:
        return RedirectResponse("/admin/users", status_code=303)

    # Recent jobs
    result = await db.execute(
        select(ResearchJob)
        .where(ResearchJob.user_id == user_id)
        .order_by(ResearchJob.created_at.desc())
        .limit(20)
    )
    jobs = list(result.scalars().all())

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "admin/user_detail.html",
        {"request": request, "user": user, "target": target, "jobs": jobs,
         "plan_display": PLAN_DISPLAY, "plan_limits": PLAN_LIMITS},
    )


@router.post("/users/{user_id}")
async def admin_user_update(
    user_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    action = form.get("action")

    if action == "toggle_active":
        target = await get_user(db, user_id)
        if target and target.id != user.id:
            await update_user(db, user_id, is_active=not target.is_active)

    elif action == "update_plan":
        service_type = form.get("service_type", "none")
        plan_type = form.get("plan_type", "lite")
        if plan_type in PLAN_LIMITS:
            # Determine billing based on service type
            if service_type == "alumni":
                plan_billing = "annual"
            elif service_type == "ai_automate":
                plan_billing = "none"  # manual admin management
            else:
                plan_billing = "none"

            # 全プラン共通: 6ヶ月間
            now = datetime.utcnow()
            plan_expires_at = now + relativedelta(months=6)

            await update_user(
                db, user_id,
                service_type=service_type,
                plan_type=plan_type,
                plan_billing=plan_billing,
                plan_expires_at=plan_expires_at,
            )

    elif action == "update_candidate_limit":
        limit = int(form.get("candidate_limit_monthly", 20))
        await update_user(db, user_id, candidate_limit_monthly=max(0, limit))

    elif action == "reset_usage":
        await reset_monthly_usage(db, user_id)

    elif action == "change_role":
        role = form.get("role", "member")
        if role in ("admin", "member") and user_id != user.id:
            await update_user(db, user_id, role=role)

    elif action == "set_expiry":
        expiry_str = form.get("plan_expires_at", "").strip()
        if expiry_str:
            plan_expires_at = datetime.strptime(expiry_str, "%Y-%m-%d")
        else:
            plan_expires_at = None
        await update_user(db, user_id, plan_expires_at=plan_expires_at)

    elif action == "extend_plan":
        months_str = form.get("months", "")
        months = int(months_str) if months_str else None
        await extend_plan(db, user_id, months=months)

    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


@router.get("/invites", response_class=HTMLResponse)
async def admin_invites(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    invites = await list_invites(db)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "admin/invites.html",
        {"request": request, "user": user, "invites": invites},
    )


@router.post("/invites")
async def admin_create_invite(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    email = (form.get("email") or "").strip() or None
    invite = await create_invite(db, created_by=user.id, email=email)
    return RedirectResponse("/admin/invites", status_code=303)


@router.post("/invites/{invite_id}/delete")
async def admin_delete_invite(
    invite_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await delete_invite(db, invite_id)
    return RedirectResponse("/admin/invites", status_code=303)


@router.get("/jobs", response_class=HTMLResponse)
async def admin_jobs(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ResearchJob).order_by(ResearchJob.created_at.desc()).limit(100)
    )
    jobs = list(result.scalars().all())

    # Eagerly load user display names
    user_ids = {j.user_id for j in jobs}
    users_map = {}
    if user_ids:
        users_result = await db.execute(
            select(User).where(User.id.in_(user_ids))
        )
        for u in users_result.scalars():
            users_map[u.id] = u.display_name

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "admin/jobs.html",
        {"request": request, "user": user, "jobs": jobs, "users_map": users_map},
    )


# --- Excluded Keywords ---

@router.get("/excluded-keywords", response_class=HTMLResponse)
async def admin_excluded_keywords(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ExcludedKeyword).order_by(ExcludedKeyword.created_at.desc())
    )
    keywords = list(result.scalars().all())
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "admin/excluded_keywords.html",
        {"request": request, "user": user, "keywords": keywords},
    )


@router.post("/excluded-keywords")
async def admin_add_excluded_keyword(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    raw = (form.get("keywords") or "").strip()
    match_type = "phrase"
    reason = (form.get("reason") or "").strip() or None

    # Support bulk add: one keyword per line or comma-separated
    lines = [k.strip() for k in raw.replace(",", "\n").split("\n") if k.strip()]

    # Check for duplicates
    existing = await db.execute(select(ExcludedKeyword.keyword))
    existing_set = {row[0].lower() for row in existing.all()}

    added = 0
    for kw in lines:
        if kw.lower() not in existing_set:
            db.add(ExcludedKeyword(keyword=kw, match_type=match_type, reason=reason))
            existing_set.add(kw.lower())
            added += 1

    if added:
        await db.commit()

    return RedirectResponse("/admin/excluded-keywords", status_code=303)


@router.post("/excluded-keywords/{kw_id}/delete")
async def admin_delete_excluded_keyword(
    kw_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    kw = await db.get(ExcludedKeyword, kw_id)
    if kw:
        await db.delete(kw)
        await db.commit()
    return RedirectResponse("/admin/excluded-keywords", status_code=303)


# --- Reference Sellers ---

@router.get("/reference-sellers", response_class=HTMLResponse)
async def admin_reference_sellers(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ReferenceSeller).order_by(ReferenceSeller.created_at.desc())
    )
    sellers = list(result.scalars().all())
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "admin/reference_sellers.html",
        {"request": request, "user": user, "sellers": sellers},
    )


@router.post("/reference-sellers")
async def admin_add_reference_seller(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    import asyncio
    from ..services.seller_scraper import (
        extract_seller_id,
        check_seller_location, resolve_seller_from_page,
    )

    form = await request.form()
    raw = (form.get("urls") or "").strip()
    urls = [u.strip() for u in raw.split("\n") if u.strip()]

    if not urls:
        result = await db.execute(
            select(ReferenceSeller).order_by(ReferenceSeller.created_at.desc())
        )
        sellers = list(result.scalars().all())
        templates = request.app.state.templates
        return templates.TemplateResponse(
            "admin/reference_sellers.html",
            {"request": request, "user": user, "sellers": sellers,
             "error": "URLを入力してください。"},
        )

    # Check for duplicates (by seller ID)
    existing_result = await db.execute(select(ReferenceSeller.url))
    existing_urls = {row[0] for row in existing_result.all()}
    existing_seller_ids: set[str] = set()
    for eu in existing_urls:
        sid = extract_seller_id(eu)
        if sid:
            existing_seller_ids.add(sid)

    # Phase 1: Separate URLs — extract seller ID directly, or queue for HTTP resolution
    seller_id_urls: list[str] = []  # already have seller ID
    pages_to_resolve: list[str] = []  # need HTTP to resolve (product pages, brand stores, etc.)
    skipped_non_jp_url = 0
    errors: list[str] = []

    for url in urls:
        if "amazon.co.jp" not in url:
            skipped_non_jp_url += 1
            continue
        sid = extract_seller_id(url)
        if sid:
            if sid not in existing_seller_ids and sid not in seller_id_urls:
                seller_id_urls.append(sid)
        else:
            # Any Amazon URL (product page, brand store, storefront, etc.)
            pages_to_resolve.append(url)

    # Phase 2: Resolve unknown URLs → seller IDs by fetching pages (parallel, max 5)
    sem = asyncio.Semaphore(5)

    if pages_to_resolve:
        async def resolve_one(purl: str) -> tuple[str, str | None]:
            async with sem:
                try:
                    sid, _ = await resolve_seller_from_page(purl)
                    return purl, sid
                except Exception as e:
                    return purl, None

        resolve_results = await asyncio.gather(
            *(resolve_one(u) for u in pages_to_resolve),
            return_exceptions=True,
        )
        for res in resolve_results:
            if isinstance(res, Exception):
                errors.append(str(res))
                continue
            purl, sid = res
            if not sid:
                errors.append(f"セラー特定失敗: {purl[:80]}")
                continue
            if sid not in existing_seller_ids and sid not in seller_id_urls:
                seller_id_urls.append(sid)

    # Phase 3: Check locations in parallel (max 5 concurrent)
    candidates = seller_id_urls
    added = 0
    skipped_foreign = 0
    skipped_foreign_names: list[str] = []

    if candidates:
        async def check_one(sid: str) -> tuple[str, str]:
            async with sem:
                loc = await check_seller_location(sid)
                return sid, loc

        results = await asyncio.gather(
            *(check_one(sid) for sid in candidates),
            return_exceptions=True,
        )

        for res in results:
            if isinstance(res, Exception):
                errors.append(str(res))
                continue
            sid, location = res
            if location not in ("JP", "不明"):
                skipped_foreign += 1
                skipped_foreign_names.append(f"{sid}({location})")
                logger.info("Skipped foreign seller %s (%s)", sid, location)
                continue

            name = f"セラー {sid} [{location}]"
            seller_url = f"https://www.amazon.co.jp/s?me={sid}"
            db.add(ReferenceSeller(name=name, url=seller_url))
            existing_seller_ids.add(sid)
            added += 1

    if added:
        await db.commit()

    result = await db.execute(
        select(ReferenceSeller).order_by(ReferenceSeller.created_at.desc())
    )
    sellers = list(result.scalars().all())
    templates = request.app.state.templates

    success_msg = f"{added}件のセラーを追加しました。" if added else "新規セラーはありませんでした（重複）。"
    if skipped_foreign:
        foreign_detail = "、".join(skipped_foreign_names[:5])
        if len(skipped_foreign_names) > 5:
            foreign_detail += f" 他{len(skipped_foreign_names) - 5}件"
        success_msg += f" （海外セラー {skipped_foreign}件を除外: {foreign_detail}）"
    if skipped_non_jp_url:
        success_msg += f" （日本以外のURL {skipped_non_jp_url}件を除外）"

    return templates.TemplateResponse(
        "admin/reference_sellers.html",
        {"request": request, "user": user, "sellers": sellers,
         "success": success_msg,
         "error": " / ".join(errors) if errors else None},
    )


@router.post("/reference-sellers/{seller_id}/scrape")
async def admin_scrape_reference_seller(
    seller_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    import json

    seller = await db.get(ReferenceSeller, seller_id)
    if not seller:
        return RedirectResponse("/admin/reference-sellers", status_code=303)

    try:
        from ..services.seller_scraper import (
            scrape_seller_products,
            resolve_seller_from_page,
            check_seller_location,
            extract_seller_id,
        )

        # If URL doesn't have a seller ID, resolve from the page
        sid = extract_seller_id(seller.url)
        if not sid:
            resolved_sid, seller_url = await resolve_seller_from_page(seller.url)
            seller.url = seller_url
            seller.name = f"セラー {resolved_sid}"

        # Check location - auto-delete foreign sellers
        sid = extract_seller_id(seller.url)
        if sid:
            location = await check_seller_location(sid)
            logger.info("Seller %s location: %s", sid, location)

            # Non-JP sellers are auto-deleted
            if location not in ("JP", "不明"):
                seller_name = seller.name
                await db.delete(seller)
                await db.commit()

                result = await db.execute(
                    select(ReferenceSeller).order_by(ReferenceSeller.created_at.desc())
                )
                sellers = list(result.scalars().all())
                templates = request.app.state.templates
                return templates.TemplateResponse(
                    "admin/reference_sellers.html",
                    {"request": request, "user": user, "sellers": sellers,
                     "error": f"「{seller_name}」は日本以外のセラー（{location}）のため自動削除しました。"},
                )

            seller.name = f"セラー {sid} [{location}]"

        titles = await scrape_seller_products(seller.url)

        seller.products_json = json.dumps(titles, ensure_ascii=False)
        seller.product_count = len(titles)
        seller.scraped_at = datetime.utcnow()
        await db.commit()

        result = await db.execute(
            select(ReferenceSeller).order_by(ReferenceSeller.created_at.desc())
        )
        sellers = list(result.scalars().all())
        templates = request.app.state.templates
        return templates.TemplateResponse(
            "admin/reference_sellers.html",
            {"request": request, "user": user, "sellers": sellers,
             "success": f"「{seller.name}」から{len(titles)}件の商品タイトルを取得しました。"},
        )

    except Exception as e:
        logger.exception("Scraping failed for seller %d", seller_id)
        result = await db.execute(
            select(ReferenceSeller).order_by(ReferenceSeller.created_at.desc())
        )
        sellers = list(result.scalars().all())
        templates = request.app.state.templates
        return templates.TemplateResponse(
            "admin/reference_sellers.html",
            {"request": request, "user": user, "sellers": sellers,
             "error": f"スクレイピング失敗: {e}。手動入力をお試しください。"},
        )


@router.post("/reference-sellers/{seller_id}/manual")
async def admin_manual_reference_seller(
    seller_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    import json

    seller = await db.get(ReferenceSeller, seller_id)
    if not seller:
        return RedirectResponse("/admin/reference-sellers", status_code=303)

    form = await request.form()
    raw = (form.get("titles") or "").strip()
    titles = [t.strip() for t in raw.split("\n") if t.strip()]

    seller.products_json = json.dumps(titles, ensure_ascii=False)
    seller.product_count = len(titles)
    seller.scraped_at = datetime.utcnow()
    await db.commit()

    return RedirectResponse("/admin/reference-sellers", status_code=303)


@router.post("/reference-sellers/bulk-delete")
async def admin_bulk_delete_reference_sellers(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    ids = form.getlist("ids")
    deleted = 0
    for sid in ids:
        try:
            seller = await db.get(ReferenceSeller, int(sid))
            if seller:
                await db.delete(seller)
                deleted += 1
        except (ValueError, TypeError):
            pass
    if deleted:
        await db.commit()

    result = await db.execute(
        select(ReferenceSeller).order_by(ReferenceSeller.created_at.desc())
    )
    sellers = list(result.scalars().all())
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "admin/reference_sellers.html",
        {"request": request, "user": user, "sellers": sellers,
         "success": f"{deleted}件のセラーを削除しました。"},
    )


@router.post("/reference-sellers/{seller_id}/delete")
async def admin_delete_reference_seller(
    seller_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    seller = await db.get(ReferenceSeller, seller_id)
    if seller:
        await db.delete(seller)
        await db.commit()
    return RedirectResponse("/admin/reference-sellers", status_code=303)
