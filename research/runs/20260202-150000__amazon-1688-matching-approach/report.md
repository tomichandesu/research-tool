# Amazon vs 1688 画像マッチング 最適アプローチ調査レポート

**調査日**: 2026-02-02
**目的**: キーワード検索で「Amazon → 1688」と「1688 → Amazon」のどちらが画像一致抽出に効率的か

---

## 結論（推奨アプローチ）

### 🏆 推奨: **Amazon → 1688** の順序

```
┌─────────────────────────────────────────────────────────────┐
│  1. Amazonでキーワード検索（例：「貯金箱」）                │
│  2. 条件フィルタリング（レビュー≤40、価格≥1500円等）       │
│  3. 各商品の画像URLを取得                                   │
│  4. 1688の画像検索機能で完全一致を探す                      │
│  5. マッチした商品の利幅を計算                              │
└─────────────────────────────────────────────────────────────┘
```

### 理由

| 比較項目 | Amazon → 1688 | 1688 → Amazon |
|---------|---------------|---------------|
| **検索結果数** | 数百〜数千件 | 最大2000件（制限あり） |
| **画像検索精度** | 1688の画像検索は高精度 ✅ | Amazonの画像検索は弱い ❌ |
| **フィルタリング** | Amazonで条件絞り込み可能 ✅ | 1688では日本向け条件が困難 |
| **自動化難易度** | 容易（1688画像検索が優秀） | 困難（Amazon画像検索が貧弱） |
| **コスト** | 無料で実現可能 | 同様 |

---

## 主要な発見

### 発見1: 1688の画像検索は高精度

1688の画像検索機能は「完全一致」を見つけるのに非常に優れています。

> "Upload a picture and get product matches in seconds."
> "deep learning-trained algorithms that ensure high search accuracy"

**特徴**:
- 画像URLを入力するだけで同一商品を検索可能
- アカウント登録なしで使用可能（2021年12月以降）
- 複数の無料Chrome拡張機能が利用可能

**出典**: [AliPrice 1688 Search](https://www.aliprice.com/information/alibabaCnInformation.html)

### 発見2: Amazonの画像検索は「逆引き」に不向き

Amazon Lensは「商品を探す」機能であり、「1688商品がAmazonにあるか」を探すのには適していません。

**Amazon Lensの制限**:
- モバイルアプリ専用（自動化困難）
- 類似商品を表示（完全一致ではない）
- API提供なし

**出典**: [Amazon Lens](https://www.amazon.com/visual-search/help/stylesnap)

### 発見3: 1688の検索結果は最大2000件まで

1688のキーワード検索には制限があります。

> "1688.com limits search results to a maximum of 2000 items per query."

**対策**:
- 価格帯で絞り込み（priceStart/priceEnd）
- より具体的なキーワードを使用
- カテゴリを指定

**出典**: [Apify 1688 Scraper](https://apify.com/songd/1688-search-scraper)

### 発見4: 画像ハッシュで完全一致を高速判定可能

pHash（Perceptual Hash）を使えば、画像の完全一致を高速に判定できます。

```python
from imagehash import phash
from PIL import Image

# 2つの画像のハッシュを比較
hash1 = phash(Image.open("amazon_product.jpg"))
hash2 = phash(Image.open("1688_product.jpg"))

# 差分が小さいほど類似度が高い
difference = hash1 - hash2
is_match = difference < 10  # 閾値10以下で一致と判定
```

**出典**: [PyImageSearch - Image Hashing](https://pyimagesearch.com/2017/11/27/image-hashing-opencv-python/)

### 発見5: 既存のワークフローが「Amazon → 1688」を推奨

プロのソーシング業者も同じフローを推奨しています。

> "With just one click, search images across multiple platforms to find suppliers and compare prices"
> "95% of the products on Alibaba.com and Aliexpress.com are sourced from 1688.com"

**出典**: [Sourcing Nova 1688 Guide](https://sourcingnova.com/blog/1688-com-sourcing-guide/)

---

## 比較表: 2つのアプローチ

### パターンA: Amazon → 1688（推奨）

```
メリット:
✅ Amazonで売れている商品から始められる
✅ 1688の画像検索が高精度
✅ 条件フィルタリング（レビュー、価格、FBA/FBM）が容易
✅ 既存の手動ワークフローと同じ流れ
✅ 処理する商品数が少ない（フィルタ後）

デメリット:
❌ Amazon商品画像が加工されている場合、1688で見つからない可能性
```

### パターンB: 1688 → Amazon（非推奨）

```
メリット:
✅ 1688の全商品をカバーできる

デメリット:
❌ 1688の検索結果が2000件制限
❌ Amazonの画像検索が貧弱（自動化困難）
❌ 日本で売れる商品かどうか事前に判断できない
❌ 処理する商品数が膨大
```

---

## 推奨する実装フロー

```
┌─────────────────────────────────────────────────────────────┐
│ Step 1: ユーザーがキーワード入力（例：「貯金箱」）          │
└─────────────────────┬───────────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 2: Amazonでキーワード検索                              │
│   - Playwrightで商品一覧を取得                              │
│   - 1ページ48件 × 数ページ = 数百件                         │
└─────────────────────┬───────────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 3: 条件フィルタリング                                  │
│   - レビュー ≤ 40                                           │
│   - 価格 ≥ 1500円                                           │
│   - BSRから販売数推定                                       │
│   → 対象商品を絞り込み（例：50件に）                        │
└─────────────────────┬───────────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 4: 1688で画像検索                                      │
│   - 各商品の画像URLで1688を検索                             │
│   - 完全一致商品を取得                                      │
│   - 1688価格を記録                                          │
└─────────────────────┬───────────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 5: 画像ハッシュで完全一致を確認                        │
│   - pHashで類似度計算                                       │
│   - 閾値以下（差分 < 10）のみ採用                           │
└─────────────────────┬───────────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 6: 利幅計算・結果出力                                  │
│   - Amazon価格 - (1688価格 + 送料 + 手数料)                 │
│   - 利益率・利幅を計算                                      │
│   - CSVで出力                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 必要なツール（すべて無料）

| ツール | 用途 | コスト |
|--------|------|--------|
| **Playwright** | Amazon/1688のブラウザ自動化 | 無料 |
| **Python imagehash** | 画像の完全一致判定 | 無料 |
| **1688画像検索** | 公式機能を自動操作 | 無料 |
| **BeautifulSoup** | HTMLパース | 無料 |

---

## 処理時間の見積もり

| ステップ | 処理時間/件 | 100件の場合 |
|---------|------------|-------------|
| Amazon商品取得 | 1秒 | 約2分 |
| 1688画像検索 | 3秒 | 約5分 |
| 画像ハッシュ計算 | 0.1秒 | 約10秒 |
| **合計** | - | **約7-10分** |

---

## 未解決・要追加調査

1. **1688のCAPTCHA対策**: 大量アクセス時にCAPTCHAが出る可能性
2. **画像加工への対応**: Amazonで加工された画像は1688で見つからない場合あり
3. **レート制限**: 1688の連続アクセス制限の確認が必要

---

## 出典一覧

1. [AliPrice 1688 Search by Image](https://www.aliprice.com/information/alibabaCnInformation.html)
2. [Amazon Lens - Visual Search](https://www.amazon.com/visual-search/help/stylesnap)
3. [Apify 1688 Scraper](https://apify.com/songd/1688-search-scraper)
4. [PyImageSearch - Image Hashing](https://pyimagesearch.com/2017/11/27/image-hashing-opencv-python/)
5. [Sourcing Nova - 1688 Guide](https://sourcingnova.com/blog/1688-com-sourcing-guide/)
6. [Python imagehash Library](https://pypi.org/project/ImageHash/)
7. [Playwright Web Scraping](https://oxylabs.io/blog/playwright-web-scraping)
8. [1688 Search by Image Chrome Extension](https://chromewebstore.google.com/detail/1688-search-by-image/dbjldigbjceebginhcnmjnigbocicokh)
