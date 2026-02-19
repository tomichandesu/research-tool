"""Amazon seller page scraper for reference product titles."""
from __future__ import annotations

import asyncio
import logging
import re

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Common user-agent to avoid immediate blocks
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_HEADERS = {
    "User-Agent": _UA,
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_REQUEST_INTERVAL = 2.0  # seconds between requests
_TIMEOUT = 10.0  # per-page timeout
_MAX_PAGES = 20


def extract_seller_id(url: str) -> str | None:
    """Extract Amazon seller ID from various URL formats.

    Supported:
      - https://www.amazon.co.jp/s?me=SELLER_ID
      - https://www.amazon.co.jp/s?seller=SELLER_ID
      - https://www.amazon.co.jp/stores/SELLER_ID
      - https://www.amazon.co.jp/sp?seller=SELLER_ID
    """
    # ?me= or &me=
    m = re.search(r'[?&]me=([A-Z0-9]+)', url)
    if m:
        return m.group(1)

    # ?seller= or &seller=
    m = re.search(r'[?&]seller=([A-Z0-9]+)', url)
    if m:
        return m.group(1)

    # /stores/<seller_id> or /stores/page/<seller_id>
    m = re.search(r'/stores/(?:page/)?([A-Z0-9]+)', url)
    if m:
        return m.group(1)

    return None


def _parse_product_titles(html: str) -> list[str]:
    """Parse product titles from Amazon search results HTML."""
    soup = BeautifulSoup(html, "html.parser")
    titles: list[str] = []

    # Primary selectors for Amazon JP product titles
    selectors = [
        "h2 a span",                              # standard search result
        "[data-component-type='s-search-result'] h2 span",
        ".s-result-item h2 span",
        "span.a-text-normal",
    ]

    for sel in selectors:
        for el in soup.select(sel):
            text = el.get_text(strip=True)
            if text and len(text) > 3 and text not in titles:
                titles.append(text)
        if titles:
            break

    return titles


def _has_next_page(html: str, current_page: int) -> bool:
    """Check if there's a next page in search results."""
    soup = BeautifulSoup(html, "html.parser")
    next_link = soup.select_one("a.s-pagination-next")
    if next_link and not next_link.get("aria-disabled"):
        return True
    # Also check for page number links
    page_links = soup.select("span.s-pagination-item")
    for link in page_links:
        try:
            if int(link.get_text(strip=True)) > current_page:
                return True
        except (ValueError, TypeError):
            pass
    return False


def _is_product_url(url: str) -> bool:
    """Check if URL is an Amazon product page (not a seller page)."""
    return bool(re.search(r'/dp/[A-Z0-9]{10}', url))


async def resolve_seller_from_page(url: str) -> tuple[str, str]:
    """Fetch any Amazon page and extract the seller ID and store URL.

    Works with product pages (/dp/), brand stores, seller storefronts,
    and any other Amazon page that contains seller links.

    Args:
        url: Any Amazon URL

    Returns:
        Tuple of (seller_id, seller_store_url)

    Raises:
        ValueError: If seller info cannot be found on the page
    """
    async with httpx.AsyncClient(
        headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Look for seller link in multiple locations on the page
    seller_patterns = [
        r'[?&]seller=([A-Z0-9]{10,})',
        r'[?&]me=([A-Z0-9]{10,})',
        r'/stores/([A-Z0-9]{10,})',
    ]

    # Collect all links on the page
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        for pattern in seller_patterns:
            m = re.search(pattern, href)
            if m:
                seller_id = m.group(1)
                store_url = f"https://www.amazon.co.jp/s?me={seller_id}"
                logger.info("Found seller %s from page %s", seller_id, url)
                return seller_id, store_url

    # Fallback: check merchant ID in page HTML
    m = re.search(r'"merchantId"\s*:\s*"([A-Z0-9]+)"', resp.text)
    if m:
        seller_id = m.group(1)
        store_url = f"https://www.amazon.co.jp/s?me={seller_id}"
        logger.info("Found seller %s from merchantId in page %s", seller_id, url)
        return seller_id, store_url

    raise ValueError(
        f"ページからセラー情報を取得できませんでした: {url}"
    )


# Keep backward-compatible alias
resolve_seller_from_product = resolve_seller_from_page


# Countries that indicate a foreign (non-Japanese) seller
_FOREIGN_INDICATORS = [
    "CN", "China", "中国", "中華",
    "US", "United States", "アメリカ",
    "HK", "Hong Kong", "香港",
    "TW", "Taiwan", "台湾",
    "KR", "Korea", "韓国",
    "SG", "Singapore", "シンガポール",
    "TH", "Thailand", "タイ王国",
    "VN", "Vietnam", "ベトナム",
    "Shenzhen", "深圳", "Guangzhou", "広州", "Shanghai", "上海",
    "Beijing", "北京", "Hangzhou", "杭州", "Yiwu", "義烏",
]


def _is_foreign_seller_name(name: str) -> bool:
    """Check if seller name contains 'jp', 'JP', 'japan' etc.

    On Amazon Japan, sellers with 'JP'/'jp' in their name are
    virtually always foreign (Chinese) sellers trying to look Japanese.
    Genuine Japanese sellers use their company name (株式会社xxx etc).

    Examples: "wonderful jp", "KIYOUMI-JP", "HomRain.jp", "AIOKEY-jp"
    """
    name_lower = name.lower().strip()

    # Any "jp" in the seller name = foreign seller
    if 'jp' in name_lower:
        return True

    # "japan" in seller name = foreign seller
    if 'japan' in name_lower:
        return True

    return False


# Foreign country indicators for address text
_FOREIGN_ADDRESS_INDICATORS = [
    ("中国", "CN"), ("China", "CN"), ("Shenzhen", "CN"), ("深圳", "CN"),
    ("Guangzhou", "CN"), ("広州", "CN"), ("Shanghai", "CN"), ("上海", "CN"),
    ("Beijing", "CN"), ("北京", "CN"), ("Hangzhou", "CN"), ("杭州", "CN"),
    ("Yiwu", "CN"), ("義烏", "CN"), ("Fujian", "CN"), ("福建", "CN"),
    ("Zhejiang", "CN"), ("浙江", "CN"), ("Guangdong", "CN"), ("広東", "CN"),
    ("Dongguan", "CN"), ("東莞", "CN"), ("Xiamen", "CN"), ("厦門", "CN"),
    ("Ningbo", "CN"), ("寧波", "CN"), ("Chengdu", "CN"), ("成都", "CN"),
    ("Wuhan", "CN"), ("武漢", "CN"), ("Suzhou", "CN"), ("蘇州", "CN"),
    ("United States", "US"), ("アメリカ", "US"),
    ("Hong Kong", "HK"), ("香港", "HK"),
    ("Taiwan", "TW"), ("台湾", "TW"),
    ("Korea", "KR"), ("韓国", "KR"),
]

# Japanese address indicators (only used in address section, NOT full page)
_JP_ADDRESS_INDICATORS = [
    "日本", "Japan", "東京", "大阪", "神奈川", "愛知", "福岡", "北海道",
    "千葉", "埼玉", "京都", "兵庫", "奈良", "滋賀", "三重", "岐阜",
    "静岡", "長野", "新潟", "群馬", "栃木", "茨城", "山梨", "富山",
    "石川", "福井", "岡山", "広島", "山口", "鳥取", "島根", "香川",
    "徳島", "愛媛", "高知", "佐賀", "長崎", "熊本", "大分", "宮崎",
    "鹿児島", "沖縄", "宮城", "岩手", "秋田", "山形", "青森", "福島",
]


def _detect_foreign_from_text(text: str) -> str | None:
    """Detect foreign (non-JP) country from text. Returns code or None."""
    # Check 2-letter country codes at address boundaries: "518000, CN"
    for code in ["CN", "US", "HK", "TW", "KR", "SG", "TH", "VN"]:
        if re.search(rf'[,\s]{code}(?:\s|$|[,.\n])', text):
            return code
    # Check text indicators for foreign countries
    for indicator, result in _FOREIGN_ADDRESS_INDICATORS:
        if indicator in text:
            return result
    return None


def _detect_jp_from_address(text: str) -> bool:
    """Detect if address section indicates Japan. Only for address sections."""
    # Check ", JP" pattern
    if re.search(r'[,\s]JP(?:\s|$|[,.\n])', text):
        return True
    for indicator in _JP_ADDRESS_INDICATORS:
        if indicator in text:
            return True
    return False


async def check_seller_location(seller_id: str) -> str:
    """Check seller's business location by fetching their profile page.

    Detection priority:
    1. Seller name pattern ("xxx jp", "xxx.jp") → CN (foreign)
    2. Address section foreign indicators (CN, HK, US, etc.) → foreign
    3. Address section JP indicators → JP
    4. Full page foreign indicators → foreign
    5. Nothing found → 不明

    Args:
        seller_id: Amazon seller ID

    Returns:
        Location string: "JP", "CN", "US", etc. or "不明"
    """
    profile_url = f"https://www.amazon.co.jp/sp?seller={seller_id}"

    try:
        async with httpx.AsyncClient(
            headers=_HEADERS, timeout=15.0, follow_redirects=True
        ) as client:
            resp = await client.get(profile_url)
            resp.raise_for_status()
    except Exception:
        logger.warning("Could not fetch seller profile for %s", seller_id)
        return "不明"

    soup = BeautifulSoup(resp.text, "html.parser")
    page_text = soup.get_text()
    logger.info(
        "Seller %s profile page length: %d chars", seller_id, len(page_text)
    )

    # Step 1: Extract seller display name and check for foreign name patterns
    seller_name = ""
    name_el = soup.select_one("#sellerName, .page-header-text span")
    if name_el:
        seller_name = name_el.get_text(strip=True)
        logger.info("Seller %s display name: '%s'", seller_id, seller_name)
        if _is_foreign_seller_name(seller_name):
            logger.info("Seller %s: foreign name pattern '%s' → CN", seller_id, seller_name)
            return "CN"

    # Step 2: Find address section
    address_section = ""
    section_labels = [
        "ビジネス所在地", "事業所の住所", "Business Address",
        "特定商取引法に基づく表記", "特定商取引法",
        "住所", "所在地", "事業者の住所",
    ]
    for label_text in section_labels:
        idx = page_text.find(label_text)
        if idx != -1:
            address_section = page_text[idx:idx + 500]
            logger.info(
                "Seller %s: found '%s', text: %.200s",
                seller_id, label_text, address_section,
            )
            break

    if address_section:
        # Step 3a: Check for foreign indicators in address (priority)
        foreign = _detect_foreign_from_text(address_section)
        if foreign:
            logger.info("Seller %s: address → %s", seller_id, foreign)
            return foreign

        # Step 3b: Check for JP indicators in address
        if _detect_jp_from_address(address_section):
            logger.info("Seller %s: address → JP", seller_id)
            return "JP"

    # Step 4: Full page scan for FOREIGN indicators only (NOT JP — amazon.co.jp always has "日本")
    foreign = _detect_foreign_from_text(page_text)
    if foreign:
        logger.info("Seller %s: full page → %s", seller_id, foreign)
        return foreign

    # Step 5: Nothing found
    logger.warning("Seller %s: could not determine location → 不明", seller_id)
    return "不明"


async def scrape_seller_products(url: str) -> list[str]:
    """Scrape all product titles from an Amazon seller's storefront.

    Args:
        url: Amazon seller URL

    Returns:
        List of product title strings

    Raises:
        ValueError: If seller ID cannot be extracted from URL
        httpx.HTTPError: On network failures
    """
    seller_id = extract_seller_id(url)
    if not seller_id:
        raise ValueError(
            f"セラーIDを抽出できませんでした。URLを確認してください: {url}"
        )

    all_titles: list[str] = []

    async with httpx.AsyncClient(
        headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True
    ) as client:
        for page in range(1, _MAX_PAGES + 1):
            search_url = (
                f"https://www.amazon.co.jp/s?me={seller_id}&page={page}"
            )
            logger.info("Scraping page %d: %s", page, search_url)

            resp = await client.get(search_url)
            resp.raise_for_status()

            titles = _parse_product_titles(resp.text)
            if not titles:
                logger.info("No titles found on page %d, stopping.", page)
                break

            for t in titles:
                if t not in all_titles:
                    all_titles.append(t)

            if not _has_next_page(resp.text, page):
                logger.info("No next page after page %d.", page)
                break

            # Polite delay between requests
            await asyncio.sleep(_REQUEST_INTERVAL)

    logger.info("Scraped %d unique titles for seller %s", len(all_titles), seller_id)
    return all_titles
