"""Bridge between the web job queue and the existing research pipeline.

Playwright requires its own event loop with subprocess support.
On Windows (Python 3.14+), uvicorn's loop doesn't support subprocess_exec.
Solution: run the entire research in a separate process via ProcessPoolExecutor.
"""
from __future__ import annotations

import asyncio
import json
import logging
import multiprocessing
import shutil
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

from ..config import settings
from ..database import async_session_factory
from ..models import ExcludedKeyword, ResearchJob, User
from .usage_tracker import add_candidates, log_action

logger = logging.getLogger(__name__)

# Spawn context for subprocess isolation (Playwright needs its own event loop)
_mp_context = multiprocessing.get_context("spawn")


# ---------------------------------------------------------------------------
# Progress tracking helpers (used by subprocess to report progress)
# ---------------------------------------------------------------------------

def _write_progress(progress_file: str, pct: int, message: str) -> None:
    """Write progress to a JSON file for the status endpoint to read."""
    import json as _json
    from pathlib import Path as _Path
    try:
        p = _Path(progress_file)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_json.dumps({"pct": pct, "message": message}), encoding="utf-8")
    except Exception:
        pass  # Non-critical


class _ProgressWriter:
    """Wraps stdout to capture [N/6] and [AUTO] messages and write progress."""

    _STEP_MAP = {
        "[1/6]": (20, "Amazon検索中..."),
        "[2/6]": (30, "フィルタリング中..."),
        "[3/6]": (45, "商品詳細取得中..."),
        "[4/6]": (60, "最終フィルタリング中..."),
        "[5/6]": (75, "1688画像検索中..."),
        "[6/6]": (90, "レポート生成中..."),
    }

    def __init__(self, original_stdout, progress_file: str,
                 mode: str = "single", max_keywords: int = 1):
        self._original = original_stdout
        self._progress_file = progress_file
        self._mode = mode
        self._max_keywords = max(max_keywords, 1)

    def write(self, text):
        result = self._original.write(text)
        self._extract_progress(text)
        return result

    def flush(self):
        return self._original.flush()

    def fileno(self):
        return self._original.fileno()

    def _extract_progress(self, text: str):
        if self._mode == "single":
            for marker, (pct, msg) in self._STEP_MAP.items():
                if marker in text:
                    _write_progress(self._progress_file, pct, msg)
                    return
        elif self._mode == "auto":
            # Track per-keyword progress from [AUTO] [N] "keyword" pattern
            if "[AUTO]" in text and "リサーチ中..." in text:
                import re
                m = re.search(r'\[AUTO\]\s*\[(\d+)\]', text)
                if m:
                    kw_num = int(m.group(1))
                    pct = 10 + int(kw_num / self._max_keywords * 80)
                    pct = min(pct, 90)
                    _write_progress(
                        self._progress_file, pct,
                        f"リサーチ中... ({kw_num}/{self._max_keywords}キーワード)",
                    )

    def __getattr__(self, name):
        return getattr(self._original, name)

# Path to 1688 auth storage
_AUTH_STORAGE_PATH = Path(__file__).parent.parent.parent / "config" / "auth" / "1688_storage.json"

# Key cookies that must be valid for 1688 to work
_REQUIRED_COOKIE_NAMES = {"cookie2", "csg"}


def check_1688_session() -> tuple[bool, str]:
    """Check if the 1688 auth session is valid by inspecting cookie expiry.

    Returns:
        (is_valid, message) tuple.
    """
    if not _AUTH_STORAGE_PATH.exists():
        return False, "1688の認証データがありません。管理者が `python run_research.py --login` を実行してください。"

    try:
        data = json.loads(_AUTH_STORAGE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False, "1688の認証データが破損しています。管理者に連絡してください。"

    cookies = data.get("cookies", [])
    if not cookies:
        return False, "1688の認証Cookieが空です。管理者が再ログインしてください。"

    now = time.time()

    # Check that required cookies exist and at least one is not expired
    for name in _REQUIRED_COOKIE_NAMES:
        matching = [c for c in cookies if c.get("name") == name and ".1688.com" in (c.get("domain") or "")]
        if not matching:
            # Also check .taobao.com domain
            matching = [c for c in cookies if c.get("name") == name and ".taobao.com" in (c.get("domain") or "")]
        if not matching:
            return False, f"1688の認証Cookie ({name}) が見つかりません。管理者が再ログインしてください。"

        # Check if at least one is still valid
        valid = [c for c in matching if c.get("expires", -1) == -1 or c.get("expires", 0) > now]
        if not valid:
            return False, "1688のセッションが期限切れです。管理者が `python run_research.py --login` で再ログインしてください。"

    return True, ""


def _friendly_error(raw: str) -> str:
    """Convert raw error messages to user-friendly Japanese messages."""
    if not raw:
        return "予期しないエラーが発生しました。しばらく時間をおいて再度お試しください。"

    low = raw.lower()

    # Already in Japanese (user cancel, our timeout messages)
    if "ユーザーにより" in raw or "タイムアウト" in raw:
        return raw

    # Network / connection errors
    if "timeout" in low or "timed out" in low:
        return f"通信タイムアウトが発生しました。インターネット接続やAmazon/1688の応答が遅い可能性があります。\n\n詳細: {raw}"
    if "connection" in low and ("refused" in low or "reset" in low or "error" in low):
        return f"接続エラーが発生しました。サーバーとの通信に問題がある可能性があります。\n\n詳細: {raw}"

    # Browser / Playwright errors
    if "browser" in low or "playwright" in low or "chromium" in low:
        return f"ブラウザの起動または操作に失敗しました。サーバーの負荷が高い可能性があります。しばらく時間をおいて再度お試しください。\n\n詳細: {raw}"

    # 1688 auth errors
    if "1688" in low or "alibaba" in low or "cookie" in low or "auth" in low or "login" in low:
        return f"1688へのアクセスに失敗しました。認証セッションが期限切れの可能性があります。管理者にお問い合わせください。\n\n詳細: {raw}"

    # Memory / resource errors
    if "memory" in low or "oom" in low or "killed" in low:
        return f"サーバーのリソース不足により処理が中断されました。しばらく時間をおいて再度お試しください。\n\n詳細: {raw}"

    # Generic with original message
    return f"リサーチ中にエラーが発生しました。しばらく時間をおいて再度お試しください。\n\n詳細: {raw}"


# Track running job executors and futures for cancellation
_running_executors: dict[int, ProcessPoolExecutor] = {}
_running_futures: dict[int, asyncio.Future] = {}
# Track jobs explicitly cancelled by the user (vs server restart)
_user_cancelled_jobs: set[int] = {}


async def cancel_job(job_id: int) -> bool:
    """Cancel a running or pending job.

    Kills the subprocess executor and marks job as cancelled in DB.
    Also releases the user's queue slot so the next job starts immediately.
    Returns True if successfully cancelled.
    """
    # Mark as user-initiated cancel before cancelling future
    _user_cancelled_jobs.add(job_id)

    # Cancel the asyncio future first (unblocks the worker)
    fut = _running_futures.pop(job_id, None)
    if fut and not fut.done():
        fut.cancel()

    # Kill the subprocess executor
    executor = _running_executors.pop(job_id, None)
    if executor:
        executor.shutdown(wait=False, cancel_futures=True)

    async with async_session_factory() as db:
        job = await db.get(ResearchJob, job_id)
        if not job:
            return False
        if job.status not in ("pending", "running"):
            return False
        user_id = job.user_id
        job.status = "failed"
        job.progress_message = "ユーザーにより停止されました"
        job.error_message = "ユーザーにより停止されました"
        job.completed_at = datetime.utcnow()
        await db.commit()

    # Release user slot in queue so next job can start immediately
    from .job_queue import job_queue
    async with job_queue._lock:
        job_queue._running_users.discard(user_id)
        job_queue._requeue_deferred()

    return True


def _run_in_subprocess(job_id: int, keyword: str, jobs_output_dir: str, user_id: int = 0, extra_excluded_keywords: list[str] | None = None) -> dict:
    """Run research in a separate process where Playwright works.

    This function runs in a child process with its own event loop.
    Returns a dict with results or error info.
    """
    import asyncio
    import sys
    import json
    import shutil
    import traceback
    from pathlib import Path

    project_root = Path(__file__).parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    # Set up progress tracking
    progress_file = str(Path(jobs_output_dir) / str(job_id) / "progress.json")
    Path(jobs_output_dir, str(job_id)).mkdir(parents=True, exist_ok=True)
    _write_progress(progress_file, 15, "ブラウザ起動中...")
    old_stdout = sys.stdout
    sys.stdout = _ProgressWriter(old_stdout, progress_file, mode="single")

    async def _do_research():
        import time as _time
        from src.config import get_config
        from src.utils.browser import BrowserManager
        from run_research import run_keyword_research

        config = get_config()

        # Merge admin-managed excluded keywords into config
        if extra_excluded_keywords:
            existing = set(k.lower() for k in config.filter.prohibited_keywords)
            for kw in extra_excluded_keywords:
                if kw.lower() not in existing:
                    config.filter.prohibited_keywords.append(kw)

        job_output_dir = Path(jobs_output_dir) / str(job_id)
        job_output_dir.mkdir(parents=True, exist_ok=True)

        # Record start time BEFORE research to filter old files
        start_epoch = _time.time() - 5  # 5s buffer

        browser = BrowserManager(
            headless=True,
            timeout=config.browser.timeout,
            request_delay=config.browser.request_delay,
            use_auth=True,
            auth_storage_path=project_root / "config" / "auth" / "1688_storage.json",
        )

        try:
            await browser.start()
            outcome = await run_keyword_research(
                browser=browser,
                keyword=keyword,
                config=config,
            )
        finally:
            await browser.stop()

        # Collect result files (only files created AFTER this job started)
        # Search recursively to catch output/results/ subdirectory too
        result_html = None
        result_excel = None
        default_output = project_root / "output"
        for f in default_output.rglob(f"*{keyword}*"):
            if f.is_file() and f.stat().st_mtime >= start_epoch:
                dest = job_output_dir / f.name
                shutil.copy2(f, dest)
                if f.suffix == ".html" and not result_html:
                    result_html = str(dest)
                elif f.suffix in (".xlsx", ".xls") and not result_excel:
                    result_excel = str(dest)

        return {
            "success": True,
            "result_html_path": result_html,
            "result_excel_path": result_excel,
            "summary": {
                "keyword": outcome.keyword,
                "total_searched": outcome.total_searched,
                "pass_count": outcome.pass_count,
                "results_count": len(outcome.results),
                "candidates_count": len(outcome.products_with_candidates),
                "score": outcome.score,
                "filter_reasons": _do_categorize(outcome),
            },
        }

    def _do_categorize(outcome):
        if not hasattr(outcome, 'filter_reasons') or not outcome.filter_reasons:
            return []
        from run_research import _categorize_filter_reasons
        return _categorize_filter_reasons(outcome.filter_reasons)

    try:
        # 15-minute timeout for single-keyword research
        return asyncio.run(asyncio.wait_for(_do_research(), timeout=900))
    except asyncio.TimeoutError:
        return {
            "success": False,
            "error": "リサーチがタイムアウトしました（15分超過）。キーワードを変えてお試しください。",
            "traceback": "",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }
    finally:
        sys.stdout = old_stdout


def _run_auto_in_subprocess(
    job_id: int, seed_keyword: str, max_keywords: int, max_duration: int,
    jobs_output_dir: str, max_candidates: int = 0, user_id: int = 0,
    extra_excluded_keywords: list[str] | None = None,
) -> dict:
    """Run auto-research in a separate process.

    Returns a dict with aggregated results across all keywords.
    """
    import asyncio
    import sys
    import json
    import shutil
    import traceback
    from pathlib import Path

    project_root = Path(__file__).parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    # Set up progress tracking
    progress_file = str(Path(jobs_output_dir) / str(job_id) / "progress.json")
    Path(jobs_output_dir, str(job_id)).mkdir(parents=True, exist_ok=True)
    _write_progress(progress_file, 15, f"オートリサーチ準備中...")
    old_stdout = sys.stdout
    sys.stdout = _ProgressWriter(
        old_stdout, progress_file, mode="auto", max_keywords=max_keywords,
    )

    async def _do_auto():
        import time as _time
        from src.config import get_config
        from src.utils.browser import BrowserManager
        from src.modules.amazon.auto_researcher import AutoResearcher, AutoState

        config = get_config()
        config.auto.max_keywords = max_keywords
        config.auto.max_duration_minutes = max_duration
        if max_candidates > 0:
            config.auto.max_candidates = max_candidates

        # Merge admin-managed excluded keywords into config
        if extra_excluded_keywords:
            existing = set(k.lower() for k in config.filter.prohibited_keywords)
            for kw in extra_excluded_keywords:
                if kw.lower() not in existing:
                    config.filter.prohibited_keywords.append(kw)

        job_output_dir = Path(jobs_output_dir) / str(job_id)
        job_output_dir.mkdir(parents=True, exist_ok=True)

        # Per-user state directory (auto_state + known_asins)
        user_data_dir = project_root / "output" / "users" / str(user_id)
        user_data_dir.mkdir(parents=True, exist_ok=True)

        # Use per-user auto_state.json for cooldown tracking
        user_state_file = user_data_dir / "auto_state.json"
        config.auto.state_file = str(user_state_file)

        # Web jobs always start fresh: delete old state so AutoResearcher.__init__
        # doesn't load stale total_researched / researched_keywords counts.
        if user_state_file.exists():
            user_state_file.unlink()

        # Record start time BEFORE research to filter old files
        start_epoch = _time.time() - 5  # 5s buffer

        browser = BrowserManager(
            headless=True,
            timeout=config.browser.timeout,
            request_delay=config.browser.request_delay,
            use_auth=True,
            auth_storage_path=project_root / "config" / "auth" / "1688_storage.json",
        )

        try:
            await browser.start()
            researcher = AutoResearcher(browser, config)
            # Override known_asins path to per-user
            researcher._known_asins_path = user_data_dir / "known_asins.json"
            from src.modules.amazon.auto_researcher import _load_known_asins
            researcher._known_asins = _load_known_asins(researcher._known_asins_path)
            # Web jobs always start fresh (resume=False).
            # Each job is independent; we don't carry over
            # keywords from a previous job's state file.
            await researcher.run(
                seed_keywords=[seed_keyword],
                diagnose=False,
                resume=False,
            )
        finally:
            await browser.stop()

        # Collect results from session data
        total_candidates = 0
        total_searched = 0
        total_pass = 0
        keywords_researched = researcher.state.total_researched

        # Aggregate filter reasons across all keywords
        agg_filter_reasons = {
            "price_low": 0, "price_high": 0, "reviews": 0,
            "prohibited": 0, "brand": 0, "price_zero": 0,
            "prohibited_detail": {},
            "brand_detail": {},
            "final_filter": {},
        }

        for data in researcher._session_data:
            total_candidates += len(data.get("products", []))
            total_searched += data.get("total_searched", 0)
            total_pass += data.get("pass_count", 0)
            fr = data.get("filter_reasons", {})
            for key in ("price_low", "price_high", "reviews", "prohibited", "brand", "price_zero"):
                agg_filter_reasons[key] += fr.get(key, 0)
            for kw, cnt in fr.get("prohibited_detail", {}).items():
                agg_filter_reasons["prohibited_detail"][kw] = agg_filter_reasons["prohibited_detail"].get(kw, 0) + cnt
            for brand, cnt in fr.get("brand_detail", {}).items():
                agg_filter_reasons["brand_detail"][brand] = agg_filter_reasons["brand_detail"].get(brand, 0) + cnt
            for reason, cnt in fr.get("final_filter", {}).items():
                agg_filter_reasons["final_filter"][reason] = agg_filter_reasons["final_filter"].get(reason, 0) + cnt

        # Convert to categorized educational format
        from run_research import _categorize_filter_reasons
        categorized_reasons = _categorize_filter_reasons(agg_filter_reasons)

        # Generate session report directly into job output dir
        # (AutoResearcher writes to src/output/ which is wrong for web jobs)
        result_html = None
        result_excel = None
        if researcher._session_data:
            try:
                from src.output.session_report import SessionReportGenerator
                elapsed = _time.time() - start_epoch
                stats = {
                    "total_keywords": keywords_researched,
                    "total_candidates": total_candidates,
                    "elapsed_seconds": elapsed,
                    "elapsed_str": f"{int(elapsed//3600)}時間{int((elapsed%3600)//60)}分{int(elapsed%60)}秒",
                }
                gen = SessionReportGenerator(output_dir=str(job_output_dir))
                html_path = gen.generate_html(researcher._session_data, stats)
                excel_path = gen.generate_excel(researcher._session_data, stats)
                if html_path:
                    result_html = html_path
                if excel_path:
                    result_excel = excel_path
            except Exception:
                pass

        # Also copy individual keyword results (only new files)
        default_output = project_root / "output"
        for f in default_output.rglob(f"*{seed_keyword}*"):
            if f.is_file() and f.stat().st_mtime >= start_epoch:
                dest = job_output_dir / f.name
                if not dest.exists():
                    shutil.copy2(f, dest)
                    if not result_html and f.suffix == ".html":
                        result_html = str(dest)
                    if not result_excel and f.suffix in (".xlsx", ".xls"):
                        result_excel = str(dest)

        return {
            "success": True,
            "result_html_path": result_html,
            "result_excel_path": result_excel,
            "summary": {
                "keyword": seed_keyword,
                "mode": "auto",
                "keywords_researched": keywords_researched,
                "total_searched": total_searched,
                "pass_count": total_pass,
                "candidates_count": total_candidates,
                "score": round(
                    sum(d.get("score", 0) for d in researcher._session_data)
                    / max(len(researcher._session_data), 1), 1
                ),
                "filter_reasons": categorized_reasons,
            },
        }

    try:
        # Timeout = max_duration + 5 min buffer (for startup/report generation)
        timeout_sec = (max_duration + 5) * 60
        return asyncio.run(asyncio.wait_for(_do_auto(), timeout=timeout_sec))
    except asyncio.TimeoutError:
        return {
            "success": False,
            "error": f"自動リサーチがタイムアウトしました（{max_duration + 5}分超過）。キーワードを変えてお試しください。",
            "traceback": "",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }
    finally:
        sys.stdout = old_stdout


async def run_research_job(job_id: int) -> None:
    """Execute a single research job by offloading to a subprocess."""

    # Mark as running + compute remaining candidate quota
    async with async_session_factory() as db:
        job = await db.get(ResearchJob, job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return

        keyword = job.keyword
        mode = job.mode
        user_id = job.user_id
        auto_max_keywords = job.auto_max_keywords or 10
        auto_max_duration = job.auto_max_duration or 60

        # Calculate remaining candidate quota for this user
        remaining_candidates = 0  # 0 = unlimited
        user = await db.get(User, job.user_id)
        if user:
            from .usage_tracker import get_candidate_limit
            limit = get_candidate_limit(user)
            if limit is not None:
                remaining_candidates = max(limit - user.candidate_count_monthly, 0)

        # Load admin-managed excluded keywords from DB
        from sqlalchemy import select as sa_select
        ek_result = await db.execute(sa_select(ExcludedKeyword.keyword))
        extra_excluded_keywords = [row[0] for row in ek_result.all()]

        job.status = "running"
        job.started_at = datetime.utcnow()
        job.progress_pct = 10
        job.progress_message = (
            f"Starting auto-research ({auto_max_keywords} keywords max)..."
            if mode == "auto"
            else "Starting research process..."
        )
        await db.commit()

    try:
        loop = asyncio.get_event_loop()
        timeout_seconds = settings.JOB_TIMEOUT_MINUTES * 60

        # Create a fresh executor per job so the worker process always
        # imports the latest code from disk (no stale module cache).
        executor = ProcessPoolExecutor(max_workers=1, mp_context=_mp_context)
        _running_executors[job_id] = executor
        try:
            if mode == "auto":
                future = loop.run_in_executor(
                    executor,
                    _run_auto_in_subprocess,
                    job_id,
                    keyword,
                    auto_max_keywords,
                    auto_max_duration,
                    settings.JOBS_OUTPUT_DIR,
                    remaining_candidates,
                    user_id,
                    extra_excluded_keywords,
                )
            else:
                future = loop.run_in_executor(
                    executor,
                    _run_in_subprocess,
                    job_id,
                    keyword,
                    settings.JOBS_OUTPUT_DIR,
                    user_id,
                    extra_excluded_keywords,
                )

            _running_futures[job_id] = future
            result = await asyncio.wait_for(future, timeout=timeout_seconds)
        except asyncio.CancelledError:
            if job_id in _user_cancelled_jobs:
                # User explicitly cancelled via cancel button
                _user_cancelled_jobs.discard(job_id)
                logger.info(f"Job {job_id} was cancelled by user")
                result = {
                    "success": False,
                    "error": "ユーザーにより停止されました",
                    "traceback": "",
                }
            else:
                # Server restart/shutdown — don't save to DB.
                # Job stays as "running" and _recover_stale_jobs will
                # reset it to "pending" on next startup for auto-retry.
                logger.info(f"Job {job_id} interrupted by server shutdown, will auto-retry on restart")
                return
        except asyncio.TimeoutError:
            logger.error(f"Job {job_id} timed out after {settings.JOB_TIMEOUT_MINUTES} minutes")
            result = {
                "success": False,
                "error": f"リサーチがタイムアウトしました（{settings.JOB_TIMEOUT_MINUTES}分超過）。キーワードを変えてお試しください。",
                "traceback": "",
            }
        finally:
            _running_executors.pop(job_id, None)
            _running_futures.pop(job_id, None)
            executor.shutdown(wait=False)

        async with async_session_factory() as db:
            job = await db.get(ResearchJob, job_id)
            if not job:
                return

            if result["success"]:
                total_searched = result["summary"].get("total_searched", 0)
                candidates = result["summary"].get("candidates_count", 0)
                keywords_researched = result["summary"].get("keywords_researched", 0)

                # Mark as completed — even if candidates=0, the research ran successfully.
                # Only mark as "failed" if an exception was raised (handled in except block).
                if True:
                    job.status = "completed"
                    job.progress_pct = 100
                    job.progress_message = "Complete"
                    job.result_html_path = result.get("result_html_path")
                    job.result_excel_path = result.get("result_excel_path")
                    job.result_summary = json.dumps(result["summary"], ensure_ascii=False)
                    job.completed_at = datetime.utcnow()
                    logger.info(f"Job {job_id} completed: {result['summary']}")

                    # Add candidate count to user's monthly usage
                    if candidates > 0:
                        user = await db.get(User, job.user_id)
                        if user:
                            await add_candidates(db, user, candidates)
                            await log_action(
                                db, user.id, "candidates_added",
                                json.dumps({"job_id": job_id, "candidates": candidates}),
                            )
                            logger.info(f"Job {job_id}: added {candidates} candidates to user {user.id}")
            else:
                job.status = "failed"
                job.progress_pct = 0
                job.progress_message = "エラーが発生しました"
                job.error_message = _friendly_error(result.get("error", ""))
                job.completed_at = datetime.utcnow()
                logger.error(f"Job {job_id} failed: {result.get('error')}\n{result.get('traceback', '')}")

            await db.commit()

    except Exception as e:
        logger.error(f"Job {job_id} executor error: {e}\n{traceback.format_exc()}")
        async with async_session_factory() as db:
            job = await db.get(ResearchJob, job_id)
            if job:
                job.status = "failed"
                job.progress_pct = 0
                job.progress_message = "エラーが発生しました"
                job.error_message = _friendly_error(str(e))
                job.completed_at = datetime.utcnow()
                await db.commit()
