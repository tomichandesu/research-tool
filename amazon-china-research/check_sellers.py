import sqlite3, json
conn = sqlite3.connect("/app/data/app.db")
c = conn.cursor()
c.execute("SELECT id, name, product_count, scraped_at FROM reference_sellers ORDER BY id")
for row in c.fetchall():
    sid, name, cnt, scraped = row
    s = scraped if scraped else "未取得"
    print(f"ID={sid} | {name} | {cnt or 0}件 | {s}")

# Also check brands in scraped data
print("\n=== 取得済みデータのブランド一覧 ===")
c.execute("SELECT id, name, products_json FROM reference_sellers WHERE products_json IS NOT NULL AND product_count > 0")
import re
from collections import Counter
for sid, name, pj in c.fetchall():
    titles = json.loads(pj)
    brands = Counter()
    for t in titles:
        m = re.match(r"\[([^\]]+)\]", t)
        if m:
            brands[m.group(1)] += 1
        else:
            m2 = re.match(r"^([A-Z][A-Za-z0-9]+)\s", t)
            if m2:
                brands[m2.group(1)] += 1
    top = brands.most_common(1)
    brand_name = top[0][0] if top else "?"
    print(f"  ID={sid} {name} -> ブランド: {brand_name} ({len(titles)}件)")

conn.close()
