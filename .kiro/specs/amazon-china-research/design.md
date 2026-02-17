# Amazon-1688 中国製品リサーチシステム 設計書

**Spec ID**: `amazon-china-research`
**Version**: 1.0.0
**Created**: 2026-02-02

---

## 1. System Architecture（システムアーキテクチャ）

### 1.1 全体構成図

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Claude Code Environment                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    Orchestrator (main.py)                     │  │
│  │  - CLI Interface                                              │  │
│  │  - Workflow Coordination                                      │  │
│  │  - Progress Reporting                                         │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                       │
│         ┌────────────────────┼────────────────────┐                 │
│         ▼                    ▼                    ▼                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │   Amazon     │    │   Alibaba    │    │   Profit     │          │
│  │   Module     │    │   Module     │    │   Module     │          │
│  │              │    │              │    │              │          │
│  │ - search()   │    │ - search()   │    │ - calculate()│          │
│  │ - detail()   │    │ - match()    │    │ - export()   │          │
│  │ - filter()   │    │              │    │              │          │
│  └──────┬───────┘    └──────┬───────┘    └──────────────┘          │
│         │                   │                                        │
│         ▼                   ▼                                        │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    Playwright MCP                             │  │
│  │  - Browser Automation                                         │  │
│  │  - Page Navigation                                            │  │
│  │  - Data Extraction                                            │  │
│  └──────────────────────────────────────────────────────────────┘  │
│         │                   │                                        │
│         ▼                   ▼                                        │
│  ┌──────────────┐    ┌──────────────┐                               │
│  │  Amazon.co.jp │    │   1688.com   │                               │
│  └──────────────┘    └──────────────┘                               │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    Image Matcher                              │  │
│  │  - pHash Generation                                           │  │
│  │  - Hamming Distance Calculation                               │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 モジュール構成

```
src/
├── main.py                    # エントリーポイント
├── config.py                  # 設定管理
├── models/
│   ├── __init__.py
│   ├── product.py             # 商品データモデル
│   └── result.py              # 結果データモデル
├── modules/
│   ├── __init__.py
│   ├── amazon/
│   │   ├── __init__.py
│   │   ├── searcher.py        # Amazon検索
│   │   ├── scraper.py         # 商品詳細取得
│   │   └── filter.py          # フィルタリング
│   ├── alibaba/
│   │   ├── __init__.py
│   │   ├── image_search.py    # 1688画像検索
│   │   └── product_parser.py  # 商品情報パース
│   ├── matcher/
│   │   ├── __init__.py
│   │   └── phash.py           # pHash画像マッチング
│   └── calculator/
│       ├── __init__.py
│       ├── sales_estimator.py # 販売数推定
│       └── profit.py          # 利益計算
├── output/
│   ├── __init__.py
│   ├── csv_exporter.py        # CSV出力
│   └── logger.py              # ログ出力
└── utils/
    ├── __init__.py
    └── browser.py             # ブラウザユーティリティ
```

---

## 2. Module Design（モジュール設計）

### 2.1 Amazon Module

#### 2.1.1 AmazonSearcher

```python
class AmazonSearcher:
    """
    Amazon.co.jpでキーワード検索を実行する

    Attributes:
        page: Playwrightのページオブジェクト
        base_url: Amazon.co.jpのベースURL
    """

    async def search(self, keyword: str, max_pages: int = 3) -> list[dict]:
        """
        キーワードで商品を検索

        Args:
            keyword: 検索キーワード
            max_pages: 取得するページ数

        Returns:
            商品リスト（ASIN, タイトル, 価格, 画像URL）
        """
        pass
```

#### 2.1.2 AmazonScraper

```python
class AmazonScraper:
    """
    商品詳細ページから情報を取得する
    """

    async def get_product_detail(self, asin: str) -> ProductDetail:
        """
        商品詳細を取得

        Args:
            asin: Amazon商品ID

        Returns:
            ProductDetail: BSR, レビュー数, FBA/FBM等を含む
        """
        pass
```

#### 2.1.3 ProductFilter

```python
class ProductFilter:
    """
    商品フィルタリングを行う
    """

    def __init__(self, config: FilterConfig):
        self.min_price = config.min_price          # 1500
        self.max_reviews = config.max_reviews      # 40
        self.fba_min_monthly_sales = config.fba_min_monthly_sales  # 20000
        self.fbm_min_monthly_units = config.fbm_min_monthly_units  # 3

    def filter(self, products: list[ProductDetail]) -> list[ProductDetail]:
        """
        条件に合う商品のみを抽出
        """
        pass
```

### 2.2 Alibaba Module

#### 2.2.1 AlibabaImageSearcher

```python
class AlibabaImageSearcher:
    """
    1688で画像検索を実行する
    """

    async def search_by_image(self, image_url: str) -> list[dict]:
        """
        画像URLで1688を検索

        Args:
            image_url: 検索する画像のURL

        Returns:
            類似商品リスト（価格, 画像URL, 商品URL）
        """
        pass
```

### 2.3 Matcher Module

#### 2.3.1 ImageMatcher

```python
class ImageMatcher:
    """
    pHashを使用した画像マッチング
    """

    def __init__(self, threshold: int = 5):
        self.threshold = threshold

    def is_match(self, image_url_1: str, image_url_2: str) -> bool:
        """
        2つの画像が一致するか判定

        Returns:
            True: ハミング距離 <= threshold
            False: ハミング距離 > threshold
        """
        pass

    def get_hash(self, image_url: str) -> str:
        """
        画像のpHashを取得
        """
        pass

    def hamming_distance(self, hash1: str, hash2: str) -> int:
        """
        ハミング距離を計算
        """
        pass
```

### 2.4 Calculator Module

#### 2.4.1 SalesEstimator

```python
class SalesEstimator:
    """
    BSRから月間販売数を推定する
    """

    # カテゴリ別係数
    CATEGORY_COEFFICIENTS = {
        "home_kitchen": (5000, 0.75),
        "toys": (3500, 0.80),
        "beauty": (8000, 0.70),
        "electronics": (2500, 0.85),
        "default": (4000, 0.78)
    }

    def estimate(self, bsr: int, category: str = "default") -> int:
        """
        月間販売数を推定

        Args:
            bsr: 大カテゴリーランキング
            category: カテゴリ名

        Returns:
            推定月間販売数
        """
        a, b = self.CATEGORY_COEFFICIENTS.get(category, self.CATEGORY_COEFFICIENTS["default"])
        return max(1, int(a * (bsr ** (-b)) * 30))
```

#### 2.4.2 ProfitCalculator

```python
class ProfitCalculator:
    """
    利益を計算する
    """

    # 定数
    JPY_PER_CNY = 21.5              # 為替レート
    SHIPPING_PER_KG = 1300          # 国際送料（円/kg）
    DEFAULT_WEIGHT = 0.5            # デフォルト重量（kg）

    # カテゴリ別紹介料
    REFERRAL_RATES = {
        "home_kitchen": 0.15,
        "toys": 0.15,
        "beauty": 0.10,
        "electronics": 0.08,
        "default": 0.15
    }

    # FBA手数料
    FBA_FEES = {
        1000: 290,   # 1000円未満
        2000: 420,   # 1000-2000円
        float('inf'): 530  # 2000円以上
    }

    def calculate(
        self,
        amazon_price: int,
        cny_price: float,
        is_fba: bool,
        category: str = "default",
        weight_kg: float = None
    ) -> ProfitResult:
        """
        利益を計算

        Returns:
            ProfitResult: 利益、利益率、コスト明細
        """
        pass
```

---

## 3. Data Models（データモデル）

### 3.1 ProductDetail

```python
@dataclass
class ProductDetail:
    """Amazon商品詳細"""
    asin: str
    title: str
    price: int                    # 円
    image_url: str
    bsr: int                      # 大カテゴリーランキング
    category: str                 # 大カテゴリー名
    review_count: int
    is_fba: bool
    product_url: str
```

### 3.2 AlibabaProduct

```python
@dataclass
class AlibabaProduct:
    """1688商品情報"""
    price_cny: float              # 元
    image_url: str
    product_url: str
    shop_name: str | None = None
    min_order: int | None = None
```

### 3.3 MatchResult

```python
@dataclass
class MatchResult:
    """マッチング結果"""
    amazon_product: ProductDetail
    alibaba_product: AlibabaProduct | None
    is_matched: bool
    hamming_distance: int | None
```

### 3.4 ProfitResult

```python
@dataclass
class ProfitResult:
    """利益計算結果"""
    amazon_price: int
    cost_1688_jpy: int
    shipping: int
    customs: int
    referral_fee: int
    fba_fee: int
    total_cost: int
    profit: int
    profit_rate: float
    is_profitable: bool
```

### 3.5 ResearchResult

```python
@dataclass
class ResearchResult:
    """最終リサーチ結果"""
    amazon_product: ProductDetail
    alibaba_product: AlibabaProduct
    profit_result: ProfitResult
    estimated_monthly_sales: int
    estimated_monthly_revenue: int
```

---

## 4. Configuration（設定）

### 4.1 設定ファイル構造（config.yaml）

```yaml
# フィルタ設定
filter:
  min_price: 1500              # 最低価格（円）
  max_reviews: 40              # 最大レビュー数
  fba:
    min_monthly_sales: 20000   # 最低月売上（円）
  fbm:
    min_monthly_units: 3       # 最低月販売数

# 画像マッチング設定
matcher:
  phash_threshold: 5           # pHashの許容差分

# 利益計算設定
profit:
  exchange_rate: 21.5          # 1元 = X円
  shipping_per_kg: 1300        # 国際送料（円/kg）
  default_weight: 0.5          # デフォルト重量（kg）
  customs_rate: 0.05           # 関税率（5%）
  customs_threshold: 10000     # 関税発生閾値（円）

# ブラウザ設定
browser:
  headless: true               # ヘッドレスモード
  request_delay: 2.0           # リクエスト間隔（秒）
  timeout: 30000               # タイムアウト（ミリ秒）

# 出力設定
output:
  csv_encoding: "utf-8-sig"    # CSV文字コード（Excel対応）
  log_level: "INFO"
```

---

## 5. Sequence Diagrams（シーケンス図）

### 5.1 基本リサーチフロー

```
User          Orchestrator       Amazon         1688          Matcher      Calculator
  │                │                │              │              │              │
  │ keyword        │                │              │              │              │
  ├───────────────>│                │              │              │              │
  │                │ search(kw)     │              │              │              │
  │                ├───────────────>│              │              │              │
  │                │    products[]  │              │              │              │
  │                │<───────────────┤              │              │              │
  │                │                │              │              │              │
  │                │ loop: each product            │              │              │
  │                │──────────────────────────────────────────────────────────────│
  │                │ │ get_detail(asin)            │              │              │
  │                │ ├─────────────>│              │              │              │
  │                │ │   detail     │              │              │              │
  │                │ │<─────────────┤              │              │              │
  │                │ │              │              │              │              │
  │                │ │ filter()     │              │              │              │
  │                │ │──────────────│              │              │              │
  │                │ │ [if passed]  │              │              │              │
  │                │ │ search_image(url)           │              │              │
  │                │ │ ├────────────────────────-->│              │              │
  │                │ │ │   alibaba_products[]      │              │              │
  │                │ │ │<──────────────────────────┤              │              │
  │                │ │ │              │              │              │              │
  │                │ │ │ loop: each alibaba_product│              │              │
  │                │ │ │──────────────────────────────────────────│              │
  │                │ │ │ │ is_match(img1, img2)    │              │              │
  │                │ │ │ ├─────────────────────────────────────-->│              │
  │                │ │ │ │   matched: bool         │              │              │
  │                │ │ │ │<────────────────────────────────────────│              │
  │                │ │ │ │             │              │              │              │
  │                │ │ │ │ [if matched]│              │              │              │
  │                │ │ │ │ calculate_profit()       │              │              │
  │                │ │ │ ├──────────────────────────────────────────────────────>│
  │                │ │ │ │   profit_result          │              │              │
  │                │ │ │ │<──────────────────────────────────────────────────────┤
  │                │ │ │──────────────────────────────────────────│              │
  │                │──────────────────────────────────────────────────────────────│
  │                │                │              │              │              │
  │                │ export_csv()   │              │              │              │
  │ result.csv     │                │              │              │              │
  │<───────────────┤                │              │              │              │
```

---

## 6. Error Handling（エラーハンドリング）

### 6.1 エラー種別

| エラーコード | エラー種別 | 対処 |
|-------------|-----------|------|
| E001 | ネットワークエラー | 3回リトライ後スキップ |
| E002 | 商品ページ404 | スキップ、ログ記録 |
| E003 | BSR取得失敗 | スキップ、ログ記録 |
| E004 | 1688検索タイムアウト | スキップ、ログ記録 |
| E005 | 画像ダウンロード失敗 | スキップ、ログ記録 |
| E006 | CAPTCHA検出 | 一時停止、ユーザー通知 |

### 6.2 リトライ戦略

```python
class RetryStrategy:
    MAX_RETRIES = 3
    BASE_DELAY = 2  # 秒

    @staticmethod
    async def with_retry(func, *args, **kwargs):
        for attempt in range(RetryStrategy.MAX_RETRIES):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                if attempt == RetryStrategy.MAX_RETRIES - 1:
                    raise
                delay = RetryStrategy.BASE_DELAY * (2 ** attempt)
                await asyncio.sleep(delay)
```

---

## 7. Testing Strategy（テスト戦略）

### 7.1 テストレベル

| レベル | 対象 | ツール |
|--------|------|--------|
| Unit | 個別関数 | pytest |
| Integration | モジュール間連携 | pytest |
| E2E | 全体フロー | pytest + Playwright |

### 7.2 テストケース構成

```
tests/
├── unit/
│   ├── test_sales_estimator.py
│   ├── test_profit_calculator.py
│   ├── test_image_matcher.py
│   └── test_filter.py
├── integration/
│   ├── test_amazon_module.py
│   ├── test_alibaba_module.py
│   └── test_workflow.py
└── e2e/
    └── test_full_research.py
```

### 7.3 モックデータ

```python
# tests/fixtures/mock_data.py

MOCK_AMAZON_PRODUCT = ProductDetail(
    asin="B08XXXXXX",
    title="テスト貯金箱",
    price=2000,
    image_url="https://images-na.ssl-images-amazon.com/...",
    bsr=5000,
    category="ホーム&キッチン",
    review_count=25,
    is_fba=True,
    product_url="https://www.amazon.co.jp/dp/B08XXXXXX"
)

MOCK_ALIBABA_PRODUCT = AlibabaProduct(
    price_cny=30.0,
    image_url="https://cbu01.alicdn.com/...",
    product_url="https://detail.1688.com/...",
    shop_name="テストショップ"
)
```

---

## 8. Deployment（デプロイメント）

### 8.1 必要環境

```bash
# Python環境
Python 3.10+
pip install playwright imagehash pillow pyyaml

# Playwright ブラウザインストール
playwright install chromium
```

### 8.2 ディレクトリ構成（実行時）

```
amazon-china-research/
├── src/                       # ソースコード
├── config/
│   └── config.yaml            # 設定ファイル
├── output/
│   ├── results/               # 結果CSV
│   └── logs/                  # ログファイル
├── tests/                     # テストコード
├── requirements.txt           # 依存ライブラリ
└── README.md                  # 使用方法
```

### 8.3 実行コマンド

```bash
# 基本実行
python src/main.py --keyword "貯金箱"

# オプション付き
python src/main.py --keyword "貯金箱" --max-pages 5 --output ./output/results/

# 設定ファイル指定
python src/main.py --keyword "貯金箱" --config ./config/custom.yaml
```

---

## 9. Mapping: Requirements → Design

| 要件ID | 設計要素 |
|--------|---------|
| FR-101 | AmazonSearcher.search() |
| FR-102 | AmazonScraper.get_product_detail() |
| FR-103 | AmazonScraper.get_product_detail() |
| FR-201 | ProductFilter.filter() |
| FR-202 | ProductFilter.filter() |
| FR-203 | ProductFilter.filter() + SalesEstimator |
| FR-204 | ProductFilter.filter() + SalesEstimator |
| FR-205 | SalesEstimator.estimate() |
| FR-301 | AlibabaImageSearcher.search_by_image() |
| FR-302 | ImageMatcher.is_match() |
| FR-303 | AlibabaImageSearcher.search_by_image() |
| FR-401 | ProfitCalculator.calculate() |
| FR-402 | ProfitCalculator.JPY_PER_CNY |
| FR-403 | ProfitCalculator.SHIPPING_PER_KG |
| FR-404 | ProfitCalculator.REFERRAL_RATES, FBA_FEES |
| FR-501 | CsvExporter.export() |
| FR-502 | Orchestrator.report_progress() |
