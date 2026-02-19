"""Async job queue with parallel workers."""
from __future__ import annotations

import asyncio
import logging
import time

from ..config import settings

logger = logging.getLogger(__name__)


class JobQueue:
    """In-process async job queue with configurable parallelism.

    - Up to MAX_CONCURRENT_JOBS jobs run in parallel.
    - Per-user concurrency limit: 1 active job per user.
    - Inter-job delay to avoid 1688 blocking.
    """

    def __init__(self):
        self._queue: asyncio.Queue[tuple[int, int]] = asyncio.Queue()  # (job_id, user_id)
        self._worker_tasks: list[asyncio.Task] = []
        self._running_users: set[int] = set()
        self._deferred: list[tuple[int, int]] = []
        self._lock = asyncio.Lock()  # protects _running_users and _deferred
        self._shutdown_event = asyncio.Event()
        self._last_job_end: dict[int, float] = {}  # user_id -> timestamp

    def start_worker(self) -> None:
        """Start background worker coroutines (one per concurrent slot)."""
        loop = asyncio.get_event_loop()
        n = max(settings.MAX_CONCURRENT_JOBS, 1)
        for i in range(n):
            task = loop.create_task(self._worker(worker_id=i))
            self._worker_tasks.append(task)
        logger.info(f"Started {n} job queue worker(s)")

    async def enqueue(self, job_id: int, user_id: int) -> None:
        """Add a job to the queue."""
        await self._queue.put((job_id, user_id))
        logger.info(f"Job {job_id} enqueued for user {user_id}")

    async def _apply_inter_job_delay(self, job_id: int, user_id: int) -> None:
        """Wait between jobs for the same user to avoid 1688 blocking."""
        delay = settings.BATCH_INTER_JOB_DELAY
        last_end = self._last_job_end.get(user_id)
        if last_end is None or delay <= 0:
            return

        elapsed = time.monotonic() - last_end
        remaining = delay - elapsed
        if remaining <= 0:
            return

        logger.info(f"Job {job_id}: waiting {remaining:.0f}s inter-job delay")

        # Write delay progress to the progress file
        try:
            from pathlib import Path
            progress_file = Path(settings.JOBS_OUTPUT_DIR) / str(job_id) / "progress.json"
            progress_file.parent.mkdir(parents=True, exist_ok=True)

            import json
            while remaining > 0:
                msg = f"次のリサーチまで {int(remaining)}秒 待機中..."
                progress_file.write_text(
                    json.dumps({"pct": 0, "message": msg}, ensure_ascii=False),
                    encoding="utf-8",
                )
                wait_step = min(remaining, 5.0)
                await asyncio.sleep(wait_step)
                remaining -= wait_step
        except Exception:
            # Fallback: just sleep the remaining time
            if remaining > 0:
                await asyncio.sleep(remaining)

    async def _worker(self, worker_id: int = 0) -> None:
        """Process jobs from the queue."""
        from .job_runner import run_research_job

        logger.info(f"Job queue worker-{worker_id} started")
        while not self._shutdown_event.is_set():
            try:
                # Get next job (with timeout so we can check shutdown)
                try:
                    job_id, user_id = await asyncio.wait_for(
                        self._queue.get(), timeout=2.0
                    )
                except asyncio.TimeoutError:
                    async with self._lock:
                        self._requeue_deferred()
                    continue

                # Per-user concurrency check (thread-safe with lock)
                async with self._lock:
                    if user_id in self._running_users:
                        self._deferred.append((job_id, user_id))
                        logger.info(f"Job {job_id} deferred (user {user_id} has active job)")
                        continue
                    self._running_users.add(user_id)

                try:
                    # Apply inter-job delay before starting
                    await self._apply_inter_job_delay(job_id, user_id)

                    logger.info(f"Worker-{worker_id} starting job {job_id}")
                    await run_research_job(job_id)
                except Exception:
                    logger.exception(f"Job {job_id} raised an exception")
                finally:
                    self._last_job_end[user_id] = time.monotonic()
                    async with self._lock:
                        self._running_users.discard(user_id)
                        self._requeue_deferred()

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception(f"Unexpected error in worker-{worker_id}")
                await asyncio.sleep(1)

        logger.info(f"Job queue worker-{worker_id} stopped")

    def _requeue_deferred(self) -> None:
        """Move deferred jobs back to the queue if the user slot is free."""
        still_deferred = []
        for job_id, user_id in self._deferred:
            if user_id not in self._running_users:
                self._queue.put_nowait((job_id, user_id))
            else:
                still_deferred.append((job_id, user_id))
        self._deferred = still_deferred

    async def shutdown(self) -> None:
        """Gracefully stop all workers."""
        self._shutdown_event.set()
        for task in self._worker_tasks:
            task.cancel()
        for task in self._worker_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._worker_tasks.clear()


# Singleton
job_queue = JobQueue()
