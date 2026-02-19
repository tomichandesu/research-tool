"""Keyword discovery service for the keyword assistant feature."""
from __future__ import annotations

import json
import random
from functools import lru_cache
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "discovery_keywords.json"


@lru_cache(maxsize=1)
def _load_data() -> dict:
    with open(_DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_all_categories() -> list[dict]:
    """Return all categories with basic info (no keywords)."""
    data = _load_data()
    return [
        {
            "id": cat["id"],
            "name": cat["name"],
            "icon": cat["icon"],
            "description": cat["description"],
            "keyword_count": len(cat["keywords"]),
        }
        for cat in data["categories"]
    ]


def get_category_keywords(category_id: str) -> dict | None:
    """Return a single category with its keywords, or None if not found."""
    data = _load_data()
    for cat in data["categories"]:
        if cat["id"] == category_id:
            return cat
    return None


def get_random_keyword() -> dict:
    """Return a random keyword entry with its category info."""
    data = _load_data()
    all_kws: list[tuple[dict, dict]] = []
    for cat in data["categories"]:
        for kw in cat["keywords"]:
            all_kws.append((cat, kw))

    cat, kw = random.choice(all_kws)
    return {
        "keyword": kw["keyword"],
        "difficulty": kw["difficulty"],
        "description": kw["description"],
        "tags": kw["tags"],
        "category_name": cat["name"],
        "category_icon": cat["icon"],
    }


async def get_successful_keywords(db: AsyncSession, limit: int = 20) -> list[dict]:
    """Return keywords from completed ResearchJobs that found candidates, ranked by count."""
    query = text("""
        SELECT
            keyword,
            COUNT(*) as job_count,
            MAX(completed_at) as last_used
        FROM research_jobs
        WHERE status = 'completed'
          AND result_summary IS NOT NULL
          AND json_extract(result_summary, '$.candidate_count') > 0
        GROUP BY keyword
        ORDER BY job_count DESC
        LIMIT :limit
    """)
    result = await db.execute(query, {"limit": limit})
    rows = result.fetchall()
    return [
        {
            "keyword": row[0],
            "job_count": row[1],
            "last_used": row[2],
        }
        for row in rows
    ]
