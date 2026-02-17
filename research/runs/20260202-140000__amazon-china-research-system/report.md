# Amazon中国製品リサーチシステム 技術調査レポート

**調査日**: 2026-02-02
**目的**: Claude Codeを活用した中国製品リサーチ・利益計算システムの構築

---

## 要約

1. **Amazon SP-API + Keepa API** の組み合わせが最も現実的なデータソース
2. **1688画像検索API**（TMAPI/DajiAPI）で完全一致商品を自動検索可能
3. **画像品質判定**はLQS（Listing Quality Score）+ 独自ML判定で実現可能
4. **既存MCP/スキル**を活用すれば開発工数を大幅削減可能
5. **利幅計算**はFBA手数料API + 為替API + 国際送料テーブルで自動化可能

---

## 1. Amazon商品データ取得

### 1.1 Amazon SP-API（公式）

| 項目 | 内容 |
|------|------|
| 機能 | 商品データ、価格、在庫、レビュー、FBA/FBM判定 |
| 料金（2026年〜） | 年間$1,400 + 従量課金（$0.40/1000コール超過） |
| 制限 | セラーアカウント必須、レート制限あり |

**取得可能データ**:
- `FulfillmentChannel`: FBA/FBM判定
- 価格情報、レビュー数
- 販売数は直接取得不可（BSRから推定必要）

**出典**: [Amazon SP-API Documentation](https://developer-docs.amazon.com/sp-api/)

### 1.2 Keepa API（推奨）

| 項目 | 内容 |
|------|------|
| 機能 | 価格履歴、BSR履歴、販売推定、40億商品追跡 |
| 料金 | €19/月（約3,000円） |
| 強み | BSR→販売数変換データ保有 |

**取得可能データ**:
```python
# Keepa APIレスポンス例
{
  "csv": [
    # [0] Amazon価格履歴
    # [3] Sales Rank履歴
    # [16] 評価履歴
  ],
  "salesRanks": {},  # カテゴリ別BSR
  "offers": []       # 出品者情報（FBA/FBM判定可能）
}
```

**出典**: [Keepa API Documentation](https://keepaapi.readthedocs.io/)

### 1.3 BSR → 月間販売数の推定

```
推定式: Sales = A × BSR^(-B)
- A, B はカテゴリごとに異なる係数
- 精度: 80-85%（±15-20%の誤差）
```

| BSRランク帯 | 精度 |
|------------|------|
| 1-1,000 | ±10-15% |
| 1,000-10,000 | ±15-20% |
| 10,000-100,000 | ±20-25% |

**出典**: [BSR Monthly Sales Estimation](https://easyparser.com/blog/amazon-bsr-monthly-sales-estimation/)

---

## 2. 1688（Alibaba中国）連携

### 2.1 画像検索API

| プロバイダー | 機能 | 言語対応 |
|-------------|------|---------|
| [TMAPI](https://tmapi.top/) | 画像URL検索、商品詳細、ショップ情報 | 多言語 |
| [DajiAPI](https://dajiapi.cn/) | 画像検索、キーワード検索、店舗検索 | 12言語（日本語含む） |
| [AliPrice](https://api.aliprice.com/) | 1688/Taobao横断検索 | 多言語 |

### 2.2 TMAPI 画像検索エンドポイント

```bash
GET https://api.tmapi.top/ali/search/items-by-image
?apiToken=YOUR_TOKEN
&imageUrl=https://example.com/product.jpg
&sort=default
&page=1
```

**レスポンス**: 類似商品リスト（価格、販売数、ショップ情報含む）

**出典**: [TMAPI 1688 Image Search](https://tmapi.top/docs/ali/search/search-items-by-image-url/)

### 2.3 代行業者API連携

| サービス | 特徴 |
|---------|------|
| [NETSEA](https://ecnomikata.com/ecnews/44625/) | 2024年9月〜1688とAPI連携開始 |
| [誠（Makoto）](https://makoto1688.com/) | Amazon/楽天とAPI連携システム |
| [桜トレード](https://sakuratrade.jp/research_1688/) | 2025年2月〜日本語リサーチツール提供 |

---

## 3. 画像品質判定（作り込み度検出）

### 3.1 Listing Quality Score (LQS)

Jungle Scoutの **LQS** アルゴリズムで評価:

| スコア | 品質レベル | リサーチ対象 |
|--------|-----------|-------------|
| 1-3 | 非常に低品質 | ✅ 狙い目 |
| 4-6 | 中品質 | △ 検討 |
| 7-10 | 高品質 | ✗ 競合強い |

**評価要素**:
- 画像枚数（7枚未満は減点）
- 画像解像度
- メイン画像の品質
- A+コンテンツ有無

**出典**: [Jungle Scout LQS](https://support.junglescout.com/hc/en-us/articles/360008617394-Listing-Quality-Score-LQS)

### 3.2 独自ML判定（推奨実装）

```python
# 画像品質スコアリング要素
quality_factors = {
    "image_count": len(images) < 5,      # 画像5枚未満
    "white_background": not is_pure_white(main_image),  # 白背景でない
    "text_overlay": has_text_overlay(images),  # テキスト少ない
    "lifestyle_images": count_lifestyle(images) < 2,  # ライフスタイル画像少
    "infographics": count_infographics(images) == 0,  # インフォグラフィックなし
}
low_effort_score = sum(quality_factors.values()) / len(quality_factors)
```

---

## 4. 既存MCP/スキルの活用

### 4.1 MCPMarket.com で利用可能なMCP

| MCP名 | 機能 | URL |
|-------|------|-----|
| **Amazon Shopping** | 商品検索・購入 | [MCPMarket](https://mcpmarket.com/server/amazon-shopping) |
| **Amazon Marketplace Data** | セラーデータ取得（CData連携） | [MCPMarket](https://mcpmarket.com/server/amazon-marketplace) |
| **rigwild/mcp-server-amazon** | オープンソース、商品検索・カート | [GitHub](https://github.com/rigwild/mcp-server-amazon) |
| **Fewsats Amazon MCP** | 安全な購入機能付き | [GitHub](https://github.com/Fewsats/amazon-mcp) |

### 4.2 SkillsMP.com で利用可能なスキル

[SkillsMP](https://skillsmp.com/) には **87,000+** のClaude Codeスキルが登録されています。

**関連カテゴリ**:
- ecommerce / amazon-seller
- web-scraping / data-extraction
- api-integration
- image-analysis

### 4.3 既存システムの Amazon Marketplace MCP

現在のプロジェクトには既に **amazon-marketplace** MCPが接続済み:

```sql
-- 利用可能なテーブル
SELECT * FROM Orders LIMIT 10;
SELECT * FROM ListingsItems;
SELECT * FROM InventorySupply;
SELECT * FROM CompetitivePricing;
```

---

## 5. 利幅計算ロジック

### 5.1 コスト構成

```
利益 = Amazon販売価格 - (1688仕入価格 + 国際送料 + 関税 + FBA手数料 + 紹介料)
```

### 5.2 各コストの取得方法

| コスト項目 | 取得方法 |
|-----------|---------|
| 1688仕入価格 | TMAPI/DajiAPI |
| 国際送料 | Freightos API / 固定テーブル（$6-7/kg DHL） |
| 関税 | HSコードから計算（中国→日本: 約0-10%） |
| FBA手数料 | Amazon Revenue Calculator API |
| 紹介料 | カテゴリ別（8-15%） |

### 5.3 為替レート

```python
# 為替API例
import requests
rate = requests.get("https://api.exchangerate-api.com/v4/latest/CNY").json()
jpy_per_cny = rate["rates"]["JPY"]  # 約21円/元（2026年）
```

**出典**: [AMZ Prep FBA Calculator](https://amzprep.com/amazon-fba-profit-margin-calculator/)

---

## 6. システム設計提案

### 6.1 アーキテクチャ

```
┌─────────────────────────────────────────────────────────────┐
│                    Claude Code + MCP                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Amazon MCP   │  │ 1688 API     │  │ 為替/送料API │      │
│  │ (既存接続済) │  │ (TMAPI)      │  │              │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                 │                 │               │
│         ▼                 ▼                 ▼               │
│  ┌──────────────────────────────────────────────────┐      │
│  │            リサーチエンジン (Python)              │      │
│  │  - フィルタリング（レビュー/価格/販売数）         │      │
│  │  - 画像品質判定                                   │      │
│  │  - 1688画像検索                                   │      │
│  │  - 利幅計算                                       │      │
│  └──────────────────────────────────────────────────┘      │
│                          │                                  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────┐      │
│  │            結果出力 (CSV/Notion/Dashboard)        │      │
│  └──────────────────────────────────────────────────┘      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 必要なAPI/サービス

| サービス | 用途 | 月額目安 |
|---------|------|---------|
| Keepa API | BSR/価格履歴 | €19（約3,000円） |
| TMAPI | 1688画像検索 | 従量課金 |
| Amazon SP-API | 商品詳細 | $1,400/年（2026年〜） |
| 為替API | レート取得 | 無料〜 |

### 6.3 フィルタリングSQL例

```sql
-- 条件に合う商品を抽出（既存Amazon MCP使用）
SELECT
    o.AmazonOrderId,
    o.OrderTotalAmount,
    o.FulfillmentChannel,
    o.NumberOfItemsShipped
FROM Orders o
WHERE o.OrderTotalAmount >= 1500
  AND o.FulfillmentChannel = 'MFN'  -- FBM
LIMIT 100;
```

---

## 7. 実装ロードマップ

### Phase 1: データ収集基盤（1-2週間）
- [ ] Keepa API連携
- [ ] 既存Amazon MCPの拡張
- [ ] 1688 TMAPI連携

### Phase 2: フィルタリングエンジン（1週間）
- [ ] レビュー数/価格フィルタ
- [ ] BSR→販売数推定ロジック
- [ ] FBA/FBM判定

### Phase 3: 画像品質判定（1週間）
- [ ] LQSスコア取得
- [ ] 独自ML判定実装

### Phase 4: 利幅計算（1週間）
- [ ] 1688画像検索→仕入価格取得
- [ ] FBA手数料計算
- [ ] 総合利益計算

### Phase 5: UI/レポート（1週間）
- [ ] ダッシュボード構築
- [ ] CSVエクスポート
- [ ] 通知システム

---

## 8. 未解決・要追加調査

1. **TMAPI料金体系**: 具体的な従量課金レートは要問い合わせ
2. **1688認証**: 一部APIは1688アカウント連携が必要な可能性
3. **画像検索精度**: 完全一致vs類似商品の判定精度は実装テストが必要
4. **Amazon TOS**: 自動ツールによるスクレイピングはTOS違反リスクあり（API推奨）

---

## 出典一覧

1. [Amazon SP-API Documentation](https://developer-docs.amazon.com/sp-api/)
2. [Keepa API Documentation](https://keepaapi.readthedocs.io/)
3. [TMAPI 1688 API](https://tmapi.top/)
4. [DajiAPI](https://dajiapi.cn/)
5. [AliPrice API](https://api.aliprice.com/)
6. [MCPMarket.com](https://mcpmarket.com/)
7. [SkillsMP.com](https://skillsmp.com/)
8. [Jungle Scout LQS](https://support.junglescout.com/hc/en-us/articles/360008617394-Listing-Quality-Score-LQS)
9. [BSR Sales Estimation](https://easyparser.com/blog/amazon-bsr-monthly-sales-estimation/)
10. [AMZ Prep FBA Calculator](https://amzprep.com/amazon-fba-profit-margin-calculator/)
11. [NETSEA-1688連携](https://ecnomikata.com/ecnews/44625/)
12. [桜トレード1688ツール](https://sakuratrade.jp/research_1688/)
13. [rigwild/mcp-server-amazon](https://github.com/rigwild/mcp-server-amazon)
14. [Helium 10 vs Keepa](https://revenuegeeks.com/helium10-vs-keepa/)
15. [Freightos FBA Calculator](https://www.freightos.com/freight-resources/amazon-fba-freight-rate-calculator-free-freight-tool/)
