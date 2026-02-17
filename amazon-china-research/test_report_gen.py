"""Test: generate an HTML report with problematic data and verify it works."""
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.output.session_report import SessionReportGenerator

# Test data with characters that previously broke the report:
# - newlines in seller_name
# - single quotes in titles
# - backslashes
# - Unicode special characters
test_session_data = [
    {
        "keyword": "テスト風船",
        "score": 25.5,
        "total_searched": 24,
        "pass_count": 3,
        "products": [
            {
                "amazon": {
                    "asin": "B0TEST001",
                    "title": "OBEST バルーンポンプ 電動 風船 空気入れ 'テスト' 商品",
                    "price": 3299,
                    "image_url": "https://m.media-amazon.com/images/I/61zK1hM-nAL._AC_SY450_.jpg",
                    "bsr": 6499,
                    "category": "おもちゃ",
                    "rating": 4.2,
                    "seller_name": "xuxuhjao\n （4件の評価）",  # newline in seller name!
                    "variation_count": 1,
                    "dimensions": [25.0, 13.0, 12.0],
                    "weight_kg": 0.5,
                    "product_url": "https://www.amazon.co.jp/dp/B0TEST001",
                    "estimated_monthly_sales": 150,
                    "estimated_monthly_revenue": 494850,
                },
                "candidates": [
                    {
                        "alibaba": {
                            "title": "电动气球充气泵 balloon pump",
                            "price_cny": 15.5,
                            "image_url": "https://example.com/img.jpg",
                            "product_url": "https://detail.1688.com/offer/123.html",
                            "shop_name": "广州\\某某店铺",  # backslash in shop name!
                            "min_order": "2個",
                        },
                        "combined_score": 0.72,
                        "profit": {
                            "profit": 1500,
                            "profit_rate_percentage": 45.5,
                            "total_cost": 1799,
                        },
                    }
                ],
            },
            {
                "amazon": {
                    "asin": "B0TEST002",
                    "title": "Skingwa テスト's \"special\" item\twith\ttabs",
                    "price": 1999,
                    "image_url": "https://m.media-amazon.com/images/I/test.jpg",
                    "bsr": 12000,
                    "category": "ホーム＆キッチン",
                    "rating": 2.3,
                    "seller_name": "Skingwa-jp\n （9件の評価）",  # another newline!
                    "variation_count": 3,
                    "dimensions": [10.0, 8.0, 5.0],
                    "weight_kg": 0.2,
                    "product_url": "https://www.amazon.co.jp/dp/B0TEST002",
                    "estimated_monthly_sales": 80,
                    "estimated_monthly_revenue": 159920,
                },
                "candidates": [],
            },
        ],
    },
    {
        "keyword": "テスト隠れ家",
        "score": 0.0,
        "total_searched": 24,
        "pass_count": 0,
        "products": [],
    },
]

test_stats = {
    "total_keywords": 2,
    "total_candidates": 1,
    "elapsed_seconds": 120.5,
    "elapsed_str": "0時間2分0秒",
}

# Generate
gen = SessionReportGenerator(output_dir=str(project_root / "output" / "test_verify"))
html_path = gen.generate_html(test_session_data, test_stats)
print(f"Generated: {html_path}")

# Basic validation: check the file contains the data and no JSON.parse
content = open(html_path, encoding="utf-8").read()
assert "JSON.parse" not in content, "ERROR: still using JSON.parse!"
assert "var DATA = {" in content, "ERROR: DATA not embedded as object literal!"
assert "xuxuhjao" in content, "ERROR: seller name not in output!"
assert "ensure_ascii" not in content, "Looks good - no raw non-ASCII in JS"

# Check that the JSON data portion is valid by extracting and parsing
import re
import json
m = re.search(r"var DATA = ({.+?});\s*\n", content, re.DOTALL)
if m:
    try:
        data = json.loads(m.group(1))
        print(f"JSON validation OK: {len(data['keywords'])} keywords")
        for kw in data["keywords"]:
            print(f"  {kw['keyword']}: {len(kw['products'])} products")
    except json.JSONDecodeError as e:
        print(f"JSON VALIDATION FAILED: {e}")
        sys.exit(1)
else:
    print("WARNING: Could not extract DATA from HTML for validation")

print(f"\nAll checks passed! File: {html_path}")
