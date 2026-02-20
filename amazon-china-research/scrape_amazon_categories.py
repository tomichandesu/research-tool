#!/usr/bin/env python3
"""
Amazon Japan ベストセラー カテゴリツリー スクレイパー

指定した10カテゴリのベストセラーページから、
左サイドバーのカテゴリナビゲーションを再帰的にスクレイピングし、
最大3階層深さまでカテゴリツリーをJSON形式で保存する。

Usage:
    python scrape_amazon_categories.py
"""

import json
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

BASE_URL = "https://www.amazon.co.jp"

# スクレイピング対象の10メインカテゴリ
MAIN_CATEGORIES = [
    {"name": "DIY・工具・ガーデン", "url": "/gp/bestsellers/diy/"},
    {"name": "おもちゃ", "url": "/gp/bestsellers/toys/"},
    {"name": "スポーツ＆アウトドア", "url": "/gp/bestsellers/sports/"},
    {"name": "ペット用品", "url": "/gp/bestsellers/pet-supplies/"},
    {"name": "ベビー＆マタニティ", "url": "/gp/bestsellers/baby/"},
    {"name": "ホーム＆キッチン", "url": "/gp/bestsellers/kitchen/"},
    {"name": "ホビー", "url": "/gp/bestsellers/hobby/"},
    {"name": "文房具・オフィス用品", "url": "/gp/bestsellers/office-products/"},
    {"name": "産業・研究開発用品", "url": "/gp/bestsellers/industrial/"},
    {"name": "車＆バイク", "url": "/gp/bestsellers/automotive/"},
]

# 出力先パス
SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "web" / "static" / "data"
OUTPUT_FILE = OUTPUT_DIR / "amazon_categories.json"

# 再帰の最大深さ (メイン=0, sub=1, sub-sub=2, sub-sub-sub=3)
MAX_DEPTH = 3

# リクエスト間隔 (秒)
DELAY_MIN = 2.0
DELAY_MAX = 3.0

# HTTPヘッダー
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

# ---------------------------------------------------------------------------
# 統計カウンター
# ---------------------------------------------------------------------------

stats = {
    "total_requests": 0,
    "successful_requests": 0,
    "failed_requests": 0,
    "total_categories": 0,
}


# ---------------------------------------------------------------------------
# HTTP取得
# ---------------------------------------------------------------------------


def fetch_page(client: httpx.Client, url: str) -> str | None:
    """URLからHTMLを取得する。失敗時はNoneを返す。"""
    full_url = url if url.startswith("http") else BASE_URL + url
    stats["total_requests"] += 1

    try:
        response = client.get(full_url, follow_redirects=True, timeout=30.0)
        response.raise_for_status()
        stats["successful_requests"] += 1
        return response.text
    except httpx.HTTPStatusError as e:
        print(f"  [ERROR] HTTP {e.response.status_code} for {full_url}")
        stats["failed_requests"] += 1
        return None
    except httpx.RequestError as e:
        print(f"  [ERROR] Request failed for {full_url}: {e}")
        stats["failed_requests"] += 1
        return None


def wait_between_requests() -> None:
    """リクエスト間のランダムな待機。"""
    delay = random.uniform(DELAY_MIN, DELAY_MAX)
    time.sleep(delay)


# ---------------------------------------------------------------------------
# HTMLパース: サイドバーからサブカテゴリリンクを抽出
# ---------------------------------------------------------------------------


def extract_subcategories(
    html: str, parent_url: str, visited_urls: set | None = None,
    root_url_prefix: str | None = None,
) -> list[dict]:
    """
    ベストセラーページのHTMLからサイドバーのサブカテゴリリンクを抽出する。

    Amazon Japanのベストセラーページでは、左サイドバーに
    role="group" 内に子カテゴリリンクが表示される。
    visited_urls により親・兄弟カテゴリを除外する。
    root_url_prefix により他カテゴリドメインへのクロスリンクを除外する。
    """
    soup = BeautifulSoup(html, "lxml")
    subcategories = []
    seen_urls = set()
    exclude_urls = visited_urls or set()

    # role="group" 内のリンクを抽出（Amazon現行レイアウト）
    groups = soup.find_all(attrs={"role": "group"})
    for group in groups:
        links = group.find_all("a", href=True)
        for link in links:
            href = link.get("href", "")
            name = link.get_text(strip=True)
            if _is_valid_subcategory(href, name, parent_url, seen_urls, exclude_urls, root_url_prefix):
                normalized = _normalize_url(href)
                seen_urls.add(normalized)
                subcategories.append({"name": name, "url": normalized, "children": []})

    if subcategories:
        return subcategories

    # フォールバック: /gp/bestsellers/ パターンのリンクを全ページから探す
    all_links = soup.find_all("a", href=re.compile(r"/gp/bestsellers/"))
    for link in all_links:
        href = link.get("href", "")
        name = link.get_text(strip=True)
        if _is_valid_subcategory(href, name, parent_url, seen_urls, exclude_urls, root_url_prefix):
            normalized = _normalize_url(href)
            seen_urls.add(normalized)
            subcategories.append({"name": name, "url": normalized, "children": []})

    return subcategories


def _is_valid_subcategory(
    href: str, name: str, parent_url: str, seen_urls: set, visited_urls: set,
    root_url_prefix: str | None = None,
) -> bool:
    """サブカテゴリリンクとして有効かどうかを判定する。"""
    if not name or len(name) < 1:
        return False
    if not href:
        return False

    # /gp/bestsellers/ を含むURLのみ
    if "/gp/bestsellers/" not in href:
        return False

    normalized = _normalize_url(href)

    # クロスカテゴリリンクを除外（例: DIY内からkitchenへのリンク）
    if root_url_prefix and not normalized.startswith(root_url_prefix):
        return False

    # 既にこのページ内で見たURLは除外
    if normalized in seen_urls:
        return False

    # 再帰全体で既に訪問済みのURL（親・兄弟）は除外
    if normalized in visited_urls:
        return False

    # 親URLと同一なら除外
    parent_normalized = _normalize_url(parent_url)
    if normalized == parent_normalized:
        return False

    # トップレベルの /gp/bestsellers/ (末尾スラッシュのみ) は除外
    if normalized == "/gp/bestsellers/":
        return False

    # 「すべてのカテゴリー」等の汎用リンクを除外
    skip_names = {"すべてのカテゴリー", "すべて", "Amazon ランキング", "ランキング"}
    if name in skip_names:
        return False

    # ref= 以降にページネーション情報があるものは除外
    if "pg=" in href or "ie=" in href.split("/gp/bestsellers/")[0]:
        return False

    return True


def _normalize_url(url: str) -> str:
    """URLを正規化して比較可能にする。"""
    # クエリパラメータやref=部分を除去し、パス部分だけ取り出す
    if url.startswith("http"):
        parsed = urlparse(url)
        path = parsed.path
    else:
        path = url.split("?")[0].split("#")[0]

    # ref= を含む場合はそこで切る
    if "/ref=" in path:
        path = path.split("/ref=")[0]

    # 末尾スラッシュを正規化
    if not path.endswith("/"):
        path = path + "/"

    return path


# ---------------------------------------------------------------------------
# 再帰スクレイピング
# ---------------------------------------------------------------------------


def scrape_category_tree(
    client: httpx.Client,
    name: str,
    url: str,
    depth: int = 0,
    max_depth: int = MAX_DEPTH,
    visited_urls: set | None = None,
    root_url_prefix: str | None = None,
) -> dict:
    """
    カテゴリページを再帰的にスクレイピングし、ツリー構造を構築する。

    visited_urls を再帰全体で共有し、親・兄弟カテゴリへの逆走を防止する。
    root_url_prefix により他カテゴリドメインへのクロスリンクを除外する。
    """
    if visited_urls is None:
        visited_urls = set()

    # depth 0 ではroot_url_prefixを自動設定
    # 例: /gp/bestsellers/diy/ → /gp/bestsellers/diy/
    if root_url_prefix is None and depth == 0:
        root_url_prefix = _normalize_url(url)

    indent = "  " * depth
    try:
        print(f"{indent}[Depth {depth}] Scraping: {name} ({url})")
    except UnicodeEncodeError:
        print(f"{indent}[Depth {depth}] Scraping: (name={url})")

    # 自分のURLを訪問済みに追加
    visited_urls.add(_normalize_url(url))

    node = {
        "name": name,
        "url": url,
        "children": [],
    }

    # 最大深さに達していたら子カテゴリは取得しない
    if depth >= max_depth:
        print(f"{indent}  -> Max depth reached, skipping children")
        return node

    # ページを取得
    html = fetch_page(client, url)
    if html is None:
        print(f"{indent}  -> Failed to fetch page, skipping children")
        return node

    # サブカテゴリを抽出（visited_urlsで親・兄弟を除外、root_url_prefixでクロスカテゴリを除外）
    subcats = extract_subcategories(html, url, visited_urls, root_url_prefix)
    print(f"{indent}  -> Found {len(subcats)} subcategories")
    stats["total_categories"] += len(subcats)

    # 兄弟URL同士もvisitedに追加（先に全部追加してから再帰）
    for subcat in subcats:
        visited_urls.add(_normalize_url(subcat["url"]))

    # 各サブカテゴリを再帰的にスクレイピング
    for i, subcat in enumerate(subcats):
        try:
            print(f"{indent}  [{i + 1}/{len(subcats)}] {subcat['name']}")
        except UnicodeEncodeError:
            print(f"{indent}  [{i + 1}/{len(subcats)}] {subcat['url']}")
        try:
            wait_between_requests()
            child_node = scrape_category_tree(
                client=client,
                name=subcat["name"],
                url=subcat["url"],
                depth=depth + 1,
                max_depth=max_depth,
                visited_urls=visited_urls,
                root_url_prefix=root_url_prefix,
            )
            node["children"].append(child_node)
        except Exception as e:
            print(f"{indent}  [ERROR] Failed to scrape {subcat['url']}: {e}")
            # Still add a stub node so we don't lose the category name
            node["children"].append({
                "name": subcat["name"],
                "url": subcat["url"],
                "children": [],
            })

    return node


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------


def main() -> None:
    """メイン処理: 全カテゴリをスクレイピングしてJSON保存。"""
    print("=" * 70)
    print("Amazon Japan bestseller category tree scraper")
    print(f"Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Categories: {len(MAIN_CATEGORIES)}")
    print(f"Max depth: {MAX_DEPTH}")
    print(f"Output: {OUTPUT_FILE}")
    print("=" * 70)

    # 出力ディレクトリを作成
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # レジューム: 既存の中間保存データを読み込む
    results = []
    completed_urls = set()
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if isinstance(existing, list):
                for item in existing:
                    completed_urls.add(item.get("url", ""))
                    results.append(item)
                if results:
                    print(f"\nResuming: {len(results)} categories already completed")
                    for r in results:
                        print(f"  - {r.get('name', '?')}")
        except (json.JSONDecodeError, OSError):
            pass

    # httpx クライアントを作成 (接続プール再利用)
    with httpx.Client(headers=HEADERS, http2=False) as client:
        for idx, cat in enumerate(MAIN_CATEGORIES):
            # 既にスクレイプ済みならスキップ
            if cat["url"] in completed_urls:
                print(f"\n[{idx + 1}/{len(MAIN_CATEGORIES)}] SKIP (already done): {cat['name']}")
                continue

            print(f"\n{'=' * 60}")
            print(f"[{idx + 1}/{len(MAIN_CATEGORIES)}] Main category: {cat['name']}")
            print(f"{'=' * 60}")

            try:
                tree = scrape_category_tree(
                    client=client,
                    name=cat["name"],
                    url=cat["url"],
                    depth=0,
                    max_depth=MAX_DEPTH,
                    visited_urls=None,  # 各メインカテゴリごとにリセット
                )
                results.append(tree)
            except Exception as e:
                print(f"\n  [CRITICAL ERROR] Category {cat['name']} failed: {e}")
                import traceback
                traceback.print_exc()
                # Save a stub so resume skips this category
                results.append({
                    "name": cat["name"],
                    "url": cat["url"],
                    "children": [],
                    "error": str(e),
                })

            # 中間保存 (途中でエラーが起きてもデータが残るように)
            _save_json(results, OUTPUT_FILE)
            print(f"\n  -> Saved ({len(results)}/{len(MAIN_CATEGORIES)} categories)")

            # カテゴリ間の待機
            if idx < len(MAIN_CATEGORIES) - 1:
                wait_between_requests()

    # 最終保存
    _save_json(results, OUTPUT_FILE)

    # 統計表示
    print("\n" + "=" * 70)
    print("Scraping complete!")
    print(f"End: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Total requests: {stats['total_requests']}")
    print(f"Success: {stats['successful_requests']}")
    print(f"Failed: {stats['failed_requests']}")
    print(f"Total categories found: {stats['total_categories']}")
    print(f"Output: {OUTPUT_FILE}")
    print("=" * 70)

    # ツリーのサマリーを表示
    print("\nCategory tree summary:")
    for cat in results:
        _print_tree_summary(cat, depth=0)


def _save_json(data: list, filepath: Path) -> None:
    """JSON形式でファイルに保存する。"""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _print_tree_summary(node: dict, depth: int = 0) -> None:
    """ツリーのサマリーを再帰的に表示する。"""
    indent = "  " * depth
    children_count = len(node.get("children", []))
    total = _count_descendants(node)
    name = node.get("name", "?")
    try:
        if depth == 0:
            print(f"{indent}{name} (direct: {children_count}, total: {total})")
        else:
            print(f"{indent}- {name} ({children_count})")
    except UnicodeEncodeError:
        # Windows cp932 can't encode some kanji
        safe_name = name.encode("ascii", errors="replace").decode("ascii")
        if depth == 0:
            print(f"{indent}{safe_name} (direct: {children_count}, total: {total})")
        else:
            print(f"{indent}- {safe_name} ({children_count})")

    # depth 0 と 1 のみ子を表示 (サマリーなので深く表示しない)
    if depth < 1:
        for child in node.get("children", []):
            _print_tree_summary(child, depth + 1)


def _count_descendants(node: dict) -> int:
    """ノード以下の全子孫数を数える。"""
    count = len(node.get("children", []))
    for child in node.get("children", []):
        count += _count_descendants(child)
    return count


if __name__ == "__main__":
    main()
