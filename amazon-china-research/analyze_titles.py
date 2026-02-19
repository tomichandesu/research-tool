"""Analyze scraped product titles from reference sellers."""
import sqlite3
import json
import re
from collections import Counter

conn = sqlite3.connect("/app/data/app.db")
c = conn.cursor()

c.execute("SELECT products_json FROM reference_sellers WHERE products_json IS NOT NULL")
all_titles = []
for (pj,) in c.fetchall():
    try:
        titles = json.loads(pj)
        all_titles.extend(titles)
    except:
        pass

# Category analysis
categories = {
    "お香立て/香炉": ["お香立て", "香炉", "インセンス", "線香立て", "倒流香", "お香たて"],
    "置物/オブジェ": ["置物", "オブジェ", "置き物", "フィギュア"],
    "インテリア雑貨(北欧/韓国)": ["インテリア雑貨", "北欧雑貨", "韓国雑貨", "北欧インテリア"],
    "花瓶/フラワーベース": ["花瓶", "フラワーベース", "一輪挿し"],
    "ガーデニング": ["ガーデン", "オーナメント", "ガーデニング"],
    "アクセサリー収納/トレイ": ["アクセサリートレイ", "ジュエリートレイ", "ジュエリーボックス"],
    "バッグ類": ["痛バ", "マザーズバッグ", "リュック", "ナップサック", "トートバッグ", "ショルダーバッグ"],
    "推し活グッズ": ["推し活", "痛バ", "ぬいポーチ", "オタ活", "ぬいぐるみポーチ"],
    "ペット用品": ["ペット", "爬虫類", "水槽", "アクアリウム", "インコ", "ハムスター"],
    "カチューシャ/ヘアアクセ": ["カチューシャ", "ヘアバンド", "ヘアアクセ", "ヘアリボン"],
    "キャンドル/照明": ["キャンドル", "ナイトライト", "ランプ", "照明", "LEDキャンドル"],
    "鍋敷き/キッチン雑貨": ["鍋敷き", "トリベット", "キッチン雑貨"],
    "木製トレー/プレート": ["ウッドプレート", "ウッドトレイ", "木製トレー", "カッティングボード"],
    "サバゲー/ミリタリー": ["サバゲー", "ミリタリー", "ホルスター", "タクティカル", "エアガン"],
    "壁掛け/タペストリー": ["壁掛け", "タペストリー", "フラッグ", "ウォール"],
    "アロマ/リラックス": ["アロマ", "アロマストーン", "ディフューザー"],
    "収納/整理": ["収納", "ボックス", "整理"],
    "文具/デスク": ["ペン立て", "ブックエンド", "しおり", "ブックマーク"],
}

cat_counts = {}
for cat, kws in categories.items():
    count = 0
    for t in all_titles:
        for kw in kws:
            if kw in t:
                count += 1
                break
    if count > 0:
        cat_counts[cat] = count

print("=== ジャンル別商品数 ===")
for cat, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]):
    pct = cnt / len(all_titles) * 100
    bar = "#" * int(pct / 2)
    print(f"  {cat}: {cnt}件 ({pct:.1f}%) {bar}")

print()
print(f"総タイトル数: {len(all_titles)}")
unique = len(set(all_titles))
print(f"ユニークタイトル数: {unique}")

# Brand distribution
brands = Counter()
for t in all_titles:
    m = re.match(r"\[([^\]]+)\]", t)
    if m:
        brands[m.group(1)] += 1
    else:
        m2 = re.match(r"^([A-Z][A-Za-z0-9]+)\s", t)
        if m2:
            brands[m2.group(1)] += 1

print()
print("=== ブランド/セラー名 TOP 20 ===")
for brand, cnt in brands.most_common(20):
    print(f"  {brand}: {cnt}件")

# Price range keywords
print()
print("=== よく出るキーワード TOP 30 ===")
word_counter = Counter()
for t in all_titles:
    words = re.findall(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\uFF00-\uFFEF]{2,}", t)
    for w in words:
        if len(w) >= 2 and w not in ("おしゃれ", "可愛い", "かわいい", "インテリア", "北欧", "韓国"):
            word_counter[w] += 1

for word, cnt in word_counter.most_common(30):
    print(f"  {word}: {cnt}回")

conn.close()
