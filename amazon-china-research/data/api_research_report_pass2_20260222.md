# Amazon商品リサーチ・中国輸入ツール強化 第二次深掘り調査レポート
作成日: 2026-02-22

---

## 調査概要

第一次レポート（`api_research_report_20260222.md`）で見落とされた情報を補完する。
重点調査対象: Keepa API（日本対応詳細）、Oxylabs MCP、スクレイピングサービス比較、
Apify 1688 Actors、Amazon無料代替API、asyncio最新ベストプラクティス。

---

## 1. Keepa API 詳細調査

### 1-1. 価格プラン（2025-2026年確認済み）

| トークン/分 | 月額（EUR） | 月額（USD概算） |
|-------------|------------|----------------|
| 20          | €49        | ~$54           |
| 60          | €129       | ~$142          |
| 250         | €459       | ~$505          |
| 500         | €879       | ~$967          |
| 1,000       | €1,499     | ~$1,650        |
| 2,000       | €2,499     | ~$2,750        |
| 3,000       | €3,499     | ~$3,850        |
| 4,000       | €4,499     | ~$4,950        |

出典: [Keepa Pricing - RevenueGeeks](https://revenuegeeks.com/keepa-pricing/)

**補足**: Keepa €19/月の一般サブスクリプション加入者は 1トークン/分（最小プラン）を無料利用可能。
APIの無料トライアルは存在しない。

### 1-2. トークン消費ルール

- 通常商品クエリ: 1トークン = 1商品の完全データセット
- Offersクエリ（セラー価格一覧付き）: 通常より多くのトークンを消費
- ライブデータ（0に設定）: 追加トークンが必要な場合あり
- バッチ上限: **100 ASINを同時送信可能**

出典: [keepa Python API Docs](https://keepaapi.readthedocs.io/en/latest/product_query.html)

### 1-3. amazon.co.jp（日本）対応

- **Domain ID = 5** が amazon.co.jp に対応
- 確認済みサポートドメイン: .com(1), .co.uk(2), .de(3), .fr(4), .co.jp(5), .ca(6), .cn(7), .it(8), .es(9), .in(10), .mx(11)
- BSR（売れ筋ランキング）の履歴データは日本を含む全対応ドメインで利用可能
- 精度: Keepa vs Helium 10 の比較テストで同等レベルの精度が確認されている

出典: [keepa.py GitHub](https://github.com/deuexpo/keepa/blob/master/keepa.py), [日本語Keepa APIガイド](https://tonokokko.com/keepa-api-reference-product-finder/)

### 1-4. MCP サーバー（新発見）

**cosjef/Keepa_MCP** が2025年12月14日に公開済み。

- GitHub: [cosjef/keepa_MCP](https://github.com/cosjef/Keepa_MCP)
- Smithery掲載: [Keepa MCP Server - LobeHub](https://lobehub.com/mcp/cosjef-keepa_mcp)
- ツール数: **11個**
  - `keepa_batch_product_lookup` - 最大100 ASIN同時処理
  - `keepa_price_history` - 価格推移
  - `keepa_product_finder` - 20+フィルターで商品発掘
  - `keepa_category_analysis` - カテゴリ市場分析
  - `keepa_search_deals` - ディール検索
  - `keepa_best_sellers` - ベストセラー追跡
  - `keepa_sales_velocity` - 販売速度計算
  - `keepa_inventory_analysis` - 在庫分析
  - `keepa_seller_lookup` - セラー情報
  - `keepa_token_status` - トークン残量確認
- 要件: Node.js v18+、KEEPA_API_KEY 環境変数
- **注意**: 現時点では US ドメイン（amazon.com）のカテゴリIDに最適化されており、
  amazon.co.jp の完全サポートは未確認。要検証。

### 1-5. Jungle Scout API / Helium 10 API との比較

| 項目 | Keepa API | Jungle Scout API | Helium 10 API |
|------|-----------|-----------------|---------------|
| アクセス形態 | 直接API | 要サブスク（$79/月〜） | エンタープライズのみ |
| API価格下限 | €49/月（20トークン/分） | $29/1,000コール | 非公開（要問合せ） |
| バッチ処理 | 100 ASIN/リクエスト | 制限あり | 不明 |
| 販売数推定 | BSRベース（間接推定） | 直接推定（精度84-86%） | ML推定 |
| 日本対応 | 対応（domain ID=5） | 限定的 | 主にUS市場 |
| 価格履歴 | 数年分 | 限定的 | 限定的 |
| MCP統合 | あり（サードパーティ） | なし | なし |

出典: [Jungle Scout API](https://www.junglescout.com/products/jungle-scout-api/), [Helium 10 API Guide](https://amztoolset.com/helium-10-api/)

**結論**: 価格追跡・履歴データ目的には Keepa が最適。販売数推定精度を重視するなら Jungle Scout API（ただし $29/1,000コール + サブスク費用が発生）。Helium 10 API はエンタープライズ専用で個人利用には不向き。

---

## 2. Oxylabs MCP Server 詳細

### 2-1. MCP サーバー基本情報

- GitHub: [oxylabs/oxylabs-mcp](https://github.com/oxylabs/oxylabs-mcp)
- Smithery: [Smithery - Oxylabs MCP](https://smithery.ai/server/@oxylabs/oxylabs-mcp)
- PyPI: [oxylabs-mcp](https://pypi.org/project/oxylabs-mcp/)
- Glama: [Oxylabs MCP Server](https://glama.ai/mcp/servers/@oxylabs/oxylabs-mcp)

### 2-2. 提供ツール一覧

| ツール名 | 機能 |
|---------|------|
| `universal_scraper` | 任意URLをスクレイプ（JS対応） |
| `google_search_scraper` | Google検索結果 |
| `amazon_search_scraper` | Amazon検索ページ |
| `amazon_product_scraper` | Amazon個別商品ページ |
| `ai_scraper` | JSON/Markdown形式でAI最適化抽出 |
| `ai_crawler` | 複数ページクロール |
| `ai_browser_agent` | ブラウザ制御型エージェント |
| `ai_search` | Webサーチ + コンテンツ抽出 |

### 2-3. amazon.co.jp 対応確認

- Oxylabs Web Scraper API ドキュメントには amazon.co.jp サポートが記載されているが詳細制限は未公開
- `geo_location`パラメータで日本IPを指定してアクセス可能
- `amazon_search_scraper` / `amazon_product_scraper` は amazon.com ベースの設計だが
  URLを amazon.co.jp に変更することで動作する可能性が高い（要検証）

### 2-4. 1688.com 対応

- **専用スクレイパー API が存在する**: [Oxylabs 1688 Scraper API](https://oxylabs.io/products/scraper-api/ecommerce/1688)
- GitHub: [oxylabs/1688-scraper](https://github.com/oxylabs/1688-scraper)
- 対応データ: 価格・商品画像・新着コレクション詳細
- 中国マーケットプレイス対応: JD.com、Taobao も別途専用APIあり

### 2-5. Oxylabs E-Commerce Scraper API 価格体系

| プラン | 月額 | 含まれる結果数 | 1,000件あたり |
|--------|------|--------------|-------------|
| Free Trial | $0 | 2,000件 | - |
| Micro | $49 | ~98,000件 | $0.40〜$1.35 |
| Starter | $99 | ~220,000件 | $0.40〜$1.30 |
| Advanced | $249 | ~622,500件 | $0.40〜$1.25 |

- Amazon: $0.40〜$0.50/1,000件
- 1688専用Scraper: $0.40〜$1.35/1,000件（JSレンダリング有無で変動）
- 2,000 URLを同時並列取得可能（最大5,000URL）
- レートリミット: 無料10 req/s、Micro以上50 req/s
- 低成功率時（5分間で40%以下）は自動的に1 req/sに制限

出典: [Oxylabs 1688 Scraper](https://oxylabs.io/products/scraper-api/ecommerce/1688), [Rate Limits](https://developers.oxylabs.io/scraping-solutions/web-scraper-api/usage-and-billing/rate-limits)

---

## 3. Amazon.co.jp スクレイピングサービス比較

### 3-1. 主要サービス比較表

| サービス | 月10K-50K req価格 | amazon.co.jp対応 | anti-bot強度 | 特徴 |
|---------|-----------------|-----------------|------------|------|
| Oxylabs | $49-$99 | 確認（geo_location=JP） | 最高クラス | 1688専用APIも持つ |
| Bright Data | $0.90/1K | 195カ国対応で日本含む | 最高クラス | 最大IPプール(150M+) |
| ScraperAPI | $2.45/1K（少量）、$0.475/1K（大量） | 150+GEO対応 | 高 | シンプルAPI |
| Scrape.do | 要公式確認 | 不明 | 中 | 低価格帯 |
| Rainforest API | $83/10K | 記載なし（要確認） | N/A | マネージドAPI |
| ScrapeOps | $9/月（Proxy集約） | 日本IP対応 | 集約で最適選択 | 20+プロバイダー集約 |

### 3-2. Rainforest API 詳細価格

| プラン | 月額 | 月間リクエスト | オーバー料金 |
|--------|------|-------------|------------|
| Hobbyist | $23 | 500 | $0.06/req |
| Starter | $83 | 10,000 | $0.0118/req |
| Production | $375 | 250,000 | $0.003/req |
| BigData | $1,000 | 1,000,000 | $0.002/req |

**注意**: Rainforest API は「主要Amazonマーケットプレイス」をサポートと記載しているが、
amazon.co.jp の明示的な確認は取れていない。問い合わせ推奨。

出典: [Rainforest API Pricing](https://trajectdata.com/pricing/rainforest-api)

### 3-3. Bright Data の日本対応

- 195カ国のIPネットワーク（日本含む）
- Amazon専用Web Scraperは構造化データ出力対応
- 価格: Web Scraper API $0.90/1K（フラット料金で予測しやすい）

### 3-4. ScrapeOps Proxy Aggregator（低コスト代替）

- URL: [ScrapeOps](https://scrapeops.io/proxy-aggregator/)
- 月$9から、25,000 API クレジット付き
- 20+プロバイダーを自動切り替え（Smartproxy含む、日本IP対応）
- Amazon専用の成功率モニタリング付き
- 1,000無料クレジットで試用可能

---

## 4. Apify 1688 Actors 詳細

### 4-1. 利用可能な 1688 関連 Actor 一覧

| Actor | 作者 | 特徴 |
|-------|------|------|
| [1688 Product Search Scraper](https://apify.com/ecomscrape/1688-product-search-scraper) | ecomscrape | キーワード検索、ページネーション、プロキシ対応 |
| [1688 Product Details Page Scraper](https://apify.com/ecomscrape/1688-product-details-page-scraper/api) | ecomscrape | URLベースで詳細データ取得。MCP対応 |
| [CN 1688 Scraper](https://apify.com/styleindexamerica/cn-1688-scraper) | styleindexamerica | キーワード検索・価格・セラーデータ |
| [1688.com Search Scraper](https://apify.com/songd/1688-search-scraper) | songd | B2B価格・大量データ抽出 |

### 4-2. ecomscrape/1688-product-details-page-scraper 詳細

- 価格: **$20/月（固定）+ 従量課金**
- 評価: 4.8/5 （ユーザーレビュー）
- 取得データ: タイトル・ラベル・価格・属性・**画像URL**・バリアントスペック・サプライヤー情報
- MCP対応: あり（[MCP endpoint](https://apify.com/ecomscrape/1688-product-details-page-scraper/api/mcp)）
- Python MCP: [Python API](https://apify.com/ecomscrape/1688-product-details-page-scraper/api/python)

### 4-3. 画像検索（Image Search）の対応状況

**重要な発見**: Apify の標準 1688 Actor は**テキストキーワード検索**のみ対応。
画像検索（逆引き）には以下の代替手段を使用する必要がある:

1. **TMAPI 1688 Image Search API**:
   - URL: [tmapi.top](https://tmapi.top/docs/ali/search/search-items-by-image-url/)
   - 機能: 画像URLで1688商品を検索
   - 制約: **Alibaba系プラットフォームの画像URLのみ受け付け**（外部画像は変換ツールが必要）
   - 認証: apiTokenが必要
   - ページネーション: デフォルト20件、最大20件/ページ
   - ソート: default / sales / price_up / price_down
   - フィルター: 価格帯・ドロップシッピング・工場認証・送料無料・新着

2. **OtaAPI（RapidAPI経由）**:
   - 第一次レポートで確認済み
   - 画像URLから1688を検索する機能あり

3. **1688.com の公式機能**:
   - 2025年5月に海外向け画像検索機能が正式強化
   - 出典: [FinancialContent記事](https://markets.financialcontent.com/stocks/article/abnewswire-2025-5-30-overseas-1688-and-taobao-image-search-reshape-product-sourcing-for-global-sellers)
   - Taobao と連携した商品ソーシング向け逆画像検索

### 4-4. Apify MCP サーバー統合

- ホスト型: `https://mcp.apify.com`（OAuth認証）
- ローカル型: APIトークンを環境変数で設定
- 対応クライアント: Claude Desktop、VS Code
- 重要変更: SSE(Server-Sent Events)は**2026年4月1日廃止予定**、Streamable HTTPに移行
- 任意のActorをMCP経由で呼び出し可能 → 1688 Actorも Claude から直接実行可能

出典: [Apify MCP Documentation](https://docs.apify.com/platform/integrations/mcp), [GitHub apify-mcp-server](https://github.com/apify/apify-mcp-server)

---

## 5. Amazon 商品データ 無料・低コスト代替

### 5-1. Amazon PA-API 5.0 廃止スケジュール（重要）

- **Offers V1**: 2026年1月31日に廃止済み（既に廃止）
- **PA-API 5.0 全体**: 廃止予定（移行先: Creators API）
- **新API**: Amazon Creators API（OAuth 2.0、新認証情報が必要）
- 移行注意: AWSアクセスキー/シークレットキーは Creators API では使用不可

出典: [Amazon PA-API Deprecation](https://advertising.amazon.com/API/docs/en-us/release-notes/deprecations), [WordPress記事](https://wordpress.org/support/topic/pa-api-deprecation-by-jan-31-2026/)

### 5-2. Amazon SP-API（Selling Partner API）

- URL: [developer-docs.amazon.com/sp-api](https://developer-docs.amazon.com/sp-api)
- Catalog Items API v2022-04-01でAmazonカタログ商品を検索可能
- 用途: セラーとして出品している商品の管理用API（競合商品の無制限取得には向かない）
- **重要変更**: 2026年1月31日から全サードパーティ開発者に**年間$1,400 USDの登録料**が発生
- 実質的に無料での利用が困難になった

出典: [SP-API Developer Docs](https://developer-docs.amazon.com/sp-api), [Amazon API Guide](https://www.sarasanalytics.com/blog/amazon-api)

### 5-3. オープンソース Amazon スクレイパー（2025-2026年動作確認済み）

| プロジェクト | 特徴 | 状態 |
|------------|------|------|
| [amzpy](https://github.com/theonlyanil/amzpy) | curl_cffiベース、軽量 | アクティブ |
| [Scrapling](https://github.com/D4Vinci/Scrapling) | フル機能フレームワーク | アクティブ（推奨） |
| [tducret/amazon-scraper-python](https://github.com/tducret/amazon-scraper-python) | 軽量クライアント | メンテナンス状況不明 |

**amzpy の特徴**:
- `curl_cffi` を使用したTLSフィンガープリントスプーフィング
- 軽量設計でシンプルな商品情報取得
- pip install amzpy

**Scrapling の特徴**（詳細は下記セクション6参照）:
- 3種類のFetcher（Standard/Stealth/Dynamic）
- asyncio完全対応
- 内蔵MCPサーバー
- 92%テストカバレッジ

---

## 6. Python asyncio スクレイピング 2025-2026年 ベストプラクティス

### 6-1. ブラウザ偽装・フィンガープリント回避

#### Camoufox（最推奨・新発見）

- URL: [camoufox.com](https://camoufox.com/), [GitHub](https://github.com/daijro/camoufox)
- 種別: **Firefoxベース**のアンチ検出ブラウザ（Python対応）
- 仕組み: C++実装レベルでブラウザを改変 → JavaScriptから検出不可能
- 精度: CreepJS等主要テストで**0%検出スコア**（Playwright/Patchrightより優れる）
- 特徴:
  - Playwright と完全互換API（既存コードをほぼそのまま移植可能）
  - GeoIP + プロキシサポート内蔵
  - フィンガープリントスプーフィング
- インストール: `pip install camoufox`

出典: [ScrapingBee Camoufox Guide](https://www.scrapingbee.com/blog/how-to-scrape-with-camoufox-to-bypass-antibot-technology/), [ZenRows](https://www.zenrows.com/blog/web-scraping-with-camoufox)

#### Patchright（中程度の対策）

- Playwright の改良版（Python/Node.js両対応）
- CreepJS での検出率: 67%（通常Playwrightの100%から改善）
- 出典: [ZenRows Patchright](https://www.zenrows.com/blog/patchright)

#### Scrapling フレームワーク（包括的ソリューション）

- GitHub: [D4Vinci/Scrapling](https://github.com/D4Vinci/Scrapling)
- 3つのFetcherクラス:
  - `Fetcher`: curl_cffiベース、TLSフィンガープリントスプーフィング
  - `StealthyFetcher`: Cloudflare Turnstile対応の高度なアンチボット回避
  - `DynamicFetcher`: Playwright統合、フルブラウザ自動化
- セッション variant: `FetcherSession`, `StealthySession`, `DynamicSession`
- **asyncio完全対応**: 全Fetcherで非同期セッションクラスを提供
- 内蔵MCP server（AI支援スクレイピング）
- Smart Element Tracking: サイト構造変更後も要素を自動再特定
- ドメイン別スロットリング内蔵
- 92%テストカバレッジ、型ヒント完備

```python
# Scrapling使用例（asyncio + Stealth）
from scrapling.fetchers import StealthyFetcher

async def scrape_amazon_japan():
    fetcher = StealthyFetcher()
    page = await fetcher.async_fetch("https://www.amazon.co.jp/dp/ASIN")
    title = page.find("span#productTitle")
    return title.text
```

### 6-2. curl_cffi（軽量ブラウザ偽装）

- Python binding for curl-impersonate
- TLS/JA3/HTTP2フィンガープリントをブラウザに偽装
- asyncio対応: `AsyncSession` を使用

```python
from curl_cffi.requests import AsyncSession

async def fetch(url: str) -> str:
    async with AsyncSession() as session:
        resp = await session.get(url, impersonate="chrome")
        return resp.text
```

出典: [BrightData curl_cffi Guide](https://brightdata.com/blog/web-data/web-scraping-with-curl-cffi)

### 6-3. レートリミット・プロキシローテーション パターン

#### 推奨ライブラリ

| ライブラリ | 用途 | PyPI |
|-----------|------|------|
| `aiolimiter` | AsyncLimiter（トークンバケット） | aiolimiter |
| `asyncio-throttle` | Throttlerクラス | asyncio-throttle |
| `aiohttp-ratelimiter` | aiohttp統合型 | aiohttp-ratelimiter |

```python
# 推奨パターン: aiolimiter + aiohttp
from aiolimiter import AsyncLimiter
import aiohttp

rate_limiter = AsyncLimiter(20, 1)  # 20 req/sec

async def fetch_with_rate_limit(session, url, proxy):
    async with rate_limiter:
        async with session.get(url, proxy=proxy) as response:
            return await response.text()

# TCPConnector でコネクション数制御
connector = aiohttp.TCPConnector(limit_per_host=5)
```

#### プロキシローテーション戦略

1. **スマートプロキシAPI**: Oxylabs / Bright Data の自動ローテーション型
2. **ScrapeOps集約**: 20+プロバイダーを単一エンドポイントで利用
3. **自前ローテーション**: リスト管理 + バン検出 + 指数バックオフ

```python
# 指数バックオフ + ジッター
import asyncio, random

async def fetch_with_retry(url, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await fetch(url)
        except Exception:
            wait = (2 ** attempt) + random.uniform(0, 1)
            await asyncio.sleep(wait)
    raise Exception("Max retries exceeded")
```

出典:
- [ScrapeOps aiohttp Proxy Rotation](https://scrapeops.io/python-web-scraping-playbook/python-aiohttp-proxy-rotation/)
- [ProxiesAPI Rate Limiting](https://proxiesapi.com/articles/effective-strategies-for-rate-limiting-asynchronous-requests-in-python)
- [asyncio-throttle PyPI](https://pypi.org/project/asyncio-throttle/)

### 6-4. セッション管理ベストプラクティス

```python
# 長期稼働スクレイピングのセッション管理
class ScrapingSession:
    def __init__(self, proxy_list: list, rate: int = 10):
        self.proxies = proxy_list
        self.limiter = AsyncLimiter(rate, 1)
        self.connector = aiohttp.TCPConnector(
            limit_per_host=3,
            ttl_dns_cache=300,  # DNSキャッシュ300秒
            ssl=False
        )

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            connector=self.connector,
            headers={"User-Agent": random.choice(USER_AGENTS)}
        )
        return self

    async def __aexit__(self, *args):
        await self.session.close()
        await self.connector.close()
```

### 6-5. 最新アンチボット対策サービス（マネージド）

| サービス | 価格帯 | Cloudflare対応 | Amazon対応 |
|---------|------|--------------|----------|
| Camoufox（OSS） | 無料 | 高い | 要プロキシ |
| Scrapling（OSS） | 無料 | `StealthyFetcher`で対応 | 対応 |
| Oxylabs Web API | $49/月〜 | 対応 | 対応（日本含む） |
| ScrapeOps集約 | $9/月〜 | 部分対応 | 対応 |
| ZenRows | $49/月〜 | 対応 | 対応 |

---

## 7. 新発見の重要ツール・サービス

### 7-1. TMAPI（1688画像検索専用API）

- URL: [tmapi.top](https://tmapi.top/docs/ali/search/search-items-by-image-url/)
- 機能: 画像URLから1688商品を検索（逆画像検索）
- 制約: Alibaba系画像URL限定（外部画像は変換ツール必要）
- 用途: 現行ツールの phash/ORB マッチング後の1688サプライヤー特定に活用可能
- 評価: **第一次レポートの Otapi と合わせて検討価値高**

### 7-2. Amazon Creators API（PA-API後継）

- PA-API 5.0の後継として Amazon が推進する新API
- OAuth 2.0ベース（AWSキー方式は廃止）
- SearchItems/GetItems等の基本操作は継続
- Associates（アフィリエイト）アカウントが必要
- 出典: [Amazon Associates Help](https://affiliate-program.amazon.com/help/node/topic/GUVFJTV7MGMMNY94)

### 7-3. Scrapling MCP Server（内蔵）

- Scrapling フレームワークに内蔵のMCPサーバー
- AI支援スクレイピングを Claude 等から直接実行可能
- 追加インストール不要

---

## 8. 統合優先度 マトリックス（第二次調査反映版）

| 優先度 | ツール/API | 用途 | コスト | 難易度 |
|--------|-----------|------|--------|--------|
| 最高 | Camoufox + asyncio | Amazon.co.jp ブラウザスクレイピング | 無料 | 中 |
| 最高 | Scrapling StealthyFetcher | 汎用スクレイピング強化 | 無料 | 低 |
| 最高 | Keepa API（€49/月, domain=5） | 日本BSR・価格履歴 | €49/月 | 低 |
| 高 | Oxylabs 1688 Scraper | 1688大量取得 | $49/月〜 | 低 |
| 高 | Apify 1688 MCP | Claude連携1688取得 | $20/月〜 | 低 |
| 高 | TMAPI 1688画像検索 | 逆画像検索（1688） | 要確認 | 中 |
| 中 | Rainforest API（Starter $83） | Amazon構造化データ | $83/月 | 低 |
| 中 | ScrapeOps（$9/月） | プロキシ集約 | $9/月 | 低 |
| 低 | Keepa MCP（cosjef） | Claude連携Keepa | €49/月〜 | 低 |
| 低 | Amazon Creators API | 公式商品データ | 無料（要Associates） | 高 |

---

## 9. 未解決・追加調査が必要な項目

1. **Rainforest API の amazon.co.jp 明示的サポート確認**: 公式に日本対応かを問い合わせ必要
2. **Keepa MCP の amazon.co.jp 動作確認**: cosjef/Keepa_MCP で domain=5 が機能するか実証が必要
3. **TMAPI 1688画像検索の価格**: サインアップして価格体系を確認必要
4. **Oxylabs amazon.co.jp のパース品質**: 日本語ページのパース精度を実際にテスト必要
5. **Camoufox + 日本語Amazon**: 日本のIPでのCamoufox動作確認
6. **Amazon Creators API の jp 対応**: amazon.co.jp のアフィリエイトアカウントで Creators API が使えるか
7. **SP-API 年間$1,400費用の詳細**: 2026年1月31日から発生する開発者費用の対象範囲確認

---

## 10. 結論

### 最適スタック提案（2026年2月時点）

**コスト最小・機能充足パターン**:
```
Amazon.co.jp データ取得:
  - Camoufox（無料）+ aiolimiter + ScrapeOps Proxy（$9/月）
  - または Keepa API（€49/月）でBSR・価格履歴を高速取得

1688 データ取得:
  - TMAPI 1688画像検索 API（逆引き）
  - Oxylabs 1688 Scraper（$49/月・テキスト検索）
  - または Apify 1688 Actor（$20/月）

開発フレームワーク:
  - Scrapling（StealthyFetcher + asyncio）
  - curl_cffi（軽量HTTPリクエスト）
```

**APIファースト・高信頼パターン**:
```
- Keepa API €49/月（Amazon.co.jp domain=5 対応、バッチ100 ASIN）
- Oxylabs E-Commerce Scraper $49/月（Amazon+1688両対応）
- Apify MCP + 1688 Actor（$20/月）
合計: 約$120〜$130/月
```

出典一覧:
- [Keepa API Docs](https://keepaapi.readthedocs.io/en/latest/)
- [Keepa MCP GitHub](https://github.com/cosjef/Keepa_MCP)
- [Oxylabs MCP](https://github.com/oxylabs/oxylabs-mcp)
- [Oxylabs 1688 Scraper](https://oxylabs.io/products/scraper-api/ecommerce/1688)
- [Apify 1688 Details Scraper](https://apify.com/ecomscrape/1688-product-details-page-scraper/api)
- [Apify MCP Server](https://docs.apify.com/platform/integrations/mcp)
- [Rainforest API Pricing](https://trajectdata.com/pricing/rainforest-api)
- [Camoufox](https://camoufox.com/)
- [Scrapling](https://github.com/D4Vinci/Scrapling)
- [TMAPI 1688 Image Search](https://tmapi.top/docs/ali/search/search-items-by-image-url/)
- [Amazon PA-API Deprecation](https://advertising.amazon.com/API/docs/en-us/release-notes/deprecations)
- [SP-API Developer Docs](https://developer-docs.amazon.com/sp-api)
- [ScrapeOps](https://scrapeops.io/proxy-aggregator/)
- [Jungle Scout API](https://www.junglescout.com/products/jungle-scout-api/)
