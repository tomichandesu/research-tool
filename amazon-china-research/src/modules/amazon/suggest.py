"""AmazonサジェストキーワードAPIモジュール

Amazonオートコンプリートから、入力キーワードに関連する
サジェストキーワードを取得する。
"""
from __future__ import annotations

import logging
from urllib.parse import quote

import aiohttp

logger = logging.getLogger(__name__)

# Amazon.co.jp オートコンプリートAPI
SUGGEST_URL = (
    "https://completion.amazon.co.jp/api/2017/suggestions"
    "?mid=A1VC38T7YXB528&alias=aps&prefix={query}"
)


async def fetch_suggest_keywords(keyword: str) -> list[str]:
    """Amazonサジェストキーワードを取得する

    Args:
        keyword: 元キーワード（例: "貯金箱"）

    Returns:
        サジェストキーワードのリスト（元キーワード含まず）
        例: ["貯金箱 かわいい", "貯金箱 大人", "貯金箱 動物", ...]
    """
    url = SUGGEST_URL.format(query=quote(keyword))

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    logger.warning(f"サジェストAPI応答エラー: {resp.status}")
                    return []

                data = await resp.json()

    except Exception as e:
        logger.warning(f"サジェストAPI取得失敗: {e}")
        return []

    # APIレスポンスからキーワードを抽出
    suggestions = []
    for item in data.get("suggestions", []):
        value = item.get("value", "").strip()
        if value and value != keyword:
            suggestions.append(value)

    logger.info(f"サジェスト取得: '{keyword}' → {len(suggestions)}件")
    return suggestions


async def expand_keyword(keyword: str) -> list[str]:
    """キーワードをサジェスト展開する

    元キーワード + サジェストキーワードのリストを返す。

    Args:
        keyword: 元キーワード

    Returns:
        [元キーワード, サジェスト1, サジェスト2, ...]
    """
    suggestions = await fetch_suggest_keywords(keyword)

    # 元キーワードを先頭に、重複なしで結合
    expanded = [keyword]
    seen = {keyword}
    for s in suggestions:
        if s not in seen:
            expanded.append(s)
            seen.add(s)

    return expanded


async def expand_keywords(keywords: list[str]) -> list[str]:
    """複数キーワードをまとめてサジェスト展開する

    Args:
        keywords: 元キーワードのリスト

    Returns:
        全展開済みキーワードのリスト（重複なし）
    """
    all_expanded = []
    seen = set()

    for keyword in keywords:
        expanded = await expand_keyword(keyword)
        for kw in expanded:
            if kw not in seen:
                all_expanded.append(kw)
                seen.add(kw)

    return all_expanded
