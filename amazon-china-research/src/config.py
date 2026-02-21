"""設定管理モジュール"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class FilterConfig:
    """フィルタ設定"""
    min_price: int = 1500
    max_price: int = 4000
    max_reviews: int = 50
    max_rating: float = 4.2
    min_bsr: int = 5000
    max_bsr: int = 50000
    max_variations: int = 5  # バリエーション5個以下のみ
    min_profit_rate: float = 20.0  # 最低利益率（%）
    fba_min_monthly_sales: int = 20000
    fbm_min_monthly_units: int = 3
    category_bsr_thresholds: dict[str, dict[str, int]] = field(default_factory=dict)  # カテゴリ別BSR閾値
    excluded_categories: list[str] = field(default_factory=list)  # 除外カテゴリ
    prohibited_keywords: list[str] = field(default_factory=list)  # 禁止キーワード
    excluded_brands: list[str] = field(default_factory=list)  # 除外ブランド


@dataclass
class MatcherConfig:
    """画像マッチング設定"""
    phash_threshold: int = 5
    orb_min_similarity: float = 0.10       # ORB最低類似度 (0.0-1.0)
    orb_garbage_threshold: float = 0.02    # ORBゴミ除去閾値（これ未満は明らかに別商品）
    orb_n_features: int = 500              # ORB特徴点数
    orb_ratio_threshold: float = 0.75      # Lowe's ratio test閾値
    min_price_cny: float = 0.5             # 1688最低価格（元）
    max_profit_rate: float = 50.0          # これ以上の利益率は別商品とみなす（%）
    max_candidates: int = 5                # HTML候補表示数
    # DINOv2
    use_dino: bool = True                    # DINOv2使用有無
    dino_garbage_threshold: float = 0.25     # これ未満は別商品
    dino_model_name: str = "dinov2_vits14"   # モデル名


@dataclass
class DefaultDimensions:
    """デフォルト寸法"""
    length: int = 20
    width: int = 15
    height: int = 10


@dataclass
class ProfitConfig:
    """利益計算設定"""
    exchange_rate: float = 23.0               # 1元 = X円（現在レート+1円）
    china_domestic_shipping: float = 2.0      # 中国国内送料（元）
    agent_fee_rate: float = 0.03              # 代行手数料率（3%）
    international_shipping_per_kg: float = 10.0  # 国際送料（元/kg）
    customs_rate: float = 0.10                # 関税率（10%）
    default_dimensions: DefaultDimensions = field(default_factory=DefaultDimensions)
    default_weight: float = 0.5               # デフォルト重量（kg）


@dataclass
class BrowserConfig:
    """ブラウザ設定"""
    headless: bool = True
    request_delay: float = 2.0
    timeout: int = 30000


@dataclass
class OutputConfig:
    """出力設定"""
    csv_encoding: str = "utf-8-sig"
    log_level: str = "INFO"


@dataclass
class SearchConfig:
    """検索設定"""
    max_pages: int = 3
    alibaba_results: int = 10
    max_concurrent_keywords: int = 5  # 並列キーワード数
    organic_only: bool = True  # スポンサー広告を除外


@dataclass
class SalesEstimationEntry:
    """BSR→販売数推定テーブルエントリ"""
    bsr_max: int
    units_min: int


@dataclass
class CategoryCoefficient:
    """カテゴリ別係数"""
    a: float
    b: float


@dataclass
class SalesEstimationConfig:
    """販売数推定設定"""
    table: list[SalesEstimationEntry] = field(default_factory=list)
    category_coefficients: dict[str, CategoryCoefficient] = field(default_factory=dict)


@dataclass
class FbaFeeRange:
    """FBA手数料範囲（価格ベース - 後方互換用）"""
    price_max: int
    fee: int


@dataclass
class FbaSizeTier:
    """FBA手数料サイズ区分"""
    name: str
    max_dimensions_sum: int  # 縦+横+高さの合計(cm)
    max_weight: float        # kg
    fee: int


@dataclass
class FbaSmallConfig:
    """小型サイズ設定"""
    max_dimensions_sum: int = 45
    max_weight: float = 0.25
    fee: int = 288


@dataclass
class FbaFeesConfig:
    """FBA手数料設定"""
    small: FbaSmallConfig = field(default_factory=FbaSmallConfig)
    standard: list[FbaSizeTier] = field(default_factory=list)
    large: list[FbaSizeTier] = field(default_factory=list)
    default_fee: int = 434
    # 後方互換用
    ranges: list[FbaFeeRange] = field(default_factory=list)


@dataclass
class AutoConfig:
    """自動リサーチ設定"""
    state_file: str = "output/auto_state.json"
    max_depth: int = 3
    max_suggests_per_seed: int = 10
    max_big_keywords_per_expand: int = 5
    keyword_cooldown_days: int = 7
    max_keywords: int = 0              # 最大KW数（0=無制限）
    max_duration_minutes: int = 0      # 最大時間（0=無制限）
    max_candidates: int = 0            # 最大候補商品数（0=無制限）
    dry_run_threshold: int = 5         # 連続N回ゼロヒットで枝刈り
    max_title_keywords: int = 3        # タイトルから抽出する新シードの上限


@dataclass
class Config:
    """全体設定"""
    filter: FilterConfig = field(default_factory=FilterConfig)
    matcher: MatcherConfig = field(default_factory=MatcherConfig)
    profit: ProfitConfig = field(default_factory=ProfitConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    sales_estimation: SalesEstimationConfig = field(default_factory=SalesEstimationConfig)
    fba_fees: FbaFeesConfig = field(default_factory=FbaFeesConfig)
    auto: AutoConfig = field(default_factory=AutoConfig)
    referral_rates: dict[str, float] = field(default_factory=dict)

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> Config:
        """設定ファイルを読み込む"""
        if config_path is None:
            # デフォルトパスを使用
            base_dir = Path(__file__).parent.parent
            config_path = base_dir / "config" / "config.yaml"

        config_path = Path(config_path)

        if not config_path.exists():
            # 設定ファイルがない場合はデフォルト設定を返す
            return cls()

        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> Config:
        """辞書から設定を生成"""
        config = cls()

        # Filter
        if "filter" in data:
            f = data["filter"]
            config.filter = FilterConfig(
                min_price=f.get("min_price", 1500),
                max_price=f.get("max_price", 4000),
                max_reviews=f.get("max_reviews", 50),
                max_rating=f.get("max_rating", 4.9),
                min_bsr=f.get("min_bsr", 5000),
                max_bsr=f.get("max_bsr", 50000),
                max_variations=f.get("max_variations", 5),
                min_profit_rate=f.get("min_profit_rate", 20.0),
                fba_min_monthly_sales=f.get("fba", {}).get("min_monthly_sales", 20000),
                fbm_min_monthly_units=f.get("fbm", {}).get("min_monthly_units", 3),
                category_bsr_thresholds=f.get("category_bsr_thresholds", {}),
                excluded_categories=f.get("excluded_categories", []),
                prohibited_keywords=f.get("prohibited_keywords", []),
                excluded_brands=f.get("excluded_brands", []),
            )

        # Matcher
        if "matcher" in data:
            m = data["matcher"]
            config.matcher = MatcherConfig(
                phash_threshold=m.get("phash_threshold", 5),
                orb_min_similarity=m.get("orb_min_similarity", 0.10),
                orb_garbage_threshold=m.get("orb_garbage_threshold", 0.02),
                orb_n_features=m.get("orb_n_features", 500),
                orb_ratio_threshold=m.get("orb_ratio_threshold", 0.75),
                min_price_cny=m.get("min_price_cny", 0.5),
                max_profit_rate=m.get("max_profit_rate", 50.0),
                max_candidates=m.get("max_candidates", 5),
                use_dino=m.get("use_dino", True),
                dino_garbage_threshold=m.get("dino_garbage_threshold", 0.25),
                dino_model_name=m.get("dino_model_name", "dinov2_vits14"),
            )

        # Profit
        if "profit" in data:
            p = data["profit"]
            dims = p.get("default_dimensions", {})
            default_dims = DefaultDimensions(
                length=dims.get("length", 20),
                width=dims.get("width", 15),
                height=dims.get("height", 10),
            )
            config.profit = ProfitConfig(
                exchange_rate=p.get("exchange_rate", 23.0),
                china_domestic_shipping=p.get("china_domestic_shipping", 2.0),
                agent_fee_rate=p.get("agent_fee_rate", 0.03),
                international_shipping_per_kg=p.get("international_shipping_per_kg", 10.0),
                customs_rate=p.get("customs_rate", 0.10),
                default_dimensions=default_dims,
                default_weight=p.get("default_weight", 0.5),
            )

        # Browser
        if "browser" in data:
            b = data["browser"]
            config.browser = BrowserConfig(
                headless=b.get("headless", True),
                request_delay=b.get("request_delay", 2.0),
                timeout=b.get("timeout", 30000),
            )

        # Output
        if "output" in data:
            o = data["output"]
            config.output = OutputConfig(
                csv_encoding=o.get("csv_encoding", "utf-8-sig"),
                log_level=o.get("log_level", "INFO"),
            )

        # Search
        if "search" in data:
            s = data["search"]
            config.search = SearchConfig(
                max_pages=s.get("max_pages", 3),
                alibaba_results=s.get("alibaba_results", 10),
                max_concurrent_keywords=s.get("max_concurrent_keywords", 5),
                organic_only=s.get("organic_only", True),
            )

        # Sales Estimation
        if "sales_estimation" in data:
            se = data["sales_estimation"]
            table = [
                SalesEstimationEntry(bsr_max=e["bsr_max"], units_min=e["units_min"])
                for e in se.get("table", [])
            ]
            coefficients = {
                k: CategoryCoefficient(a=v["a"], b=v["b"])
                for k, v in se.get("category_coefficients", {}).items()
            }
            config.sales_estimation = SalesEstimationConfig(
                table=table,
                category_coefficients=coefficients,
            )

        # FBA Fees
        if "fba_fees" in data:
            ff = data["fba_fees"]

            # 小型サイズ
            small_data = ff.get("small", {})
            small_config = FbaSmallConfig(
                max_dimensions_sum=small_data.get("max_dimensions_sum", 45),
                max_weight=small_data.get("max_weight", 0.25),
                fee=small_data.get("fee", 288),
            )

            # 標準サイズ（リスト）
            standard_list = []
            for tier in ff.get("standard", []):
                standard_list.append(FbaSizeTier(
                    name=tier.get("name", ""),
                    max_dimensions_sum=tier.get("max_dimensions_sum", 0),
                    max_weight=tier.get("max_weight", 0),
                    fee=tier.get("fee", 0),
                ))

            # 大型サイズ（リスト）
            large_list = []
            for tier in ff.get("large", []):
                large_list.append(FbaSizeTier(
                    name=tier.get("name", ""),
                    max_dimensions_sum=tier.get("max_dimensions_sum", 0),
                    max_weight=tier.get("max_weight", 0),
                    fee=tier.get("fee", 0),
                ))

            config.fba_fees = FbaFeesConfig(
                small=small_config,
                standard=standard_list,
                large=large_list,
                default_fee=ff.get("default", 434),
            )

        # Auto
        if "auto" in data:
            a = data["auto"]
            config.auto = AutoConfig(
                state_file=a.get("state_file", "output/auto_state.json"),
                max_depth=a.get("max_depth", 3),
                max_suggests_per_seed=a.get("max_suggests_per_seed", 10),
                max_big_keywords_per_expand=a.get("max_big_keywords_per_expand", 5),
                keyword_cooldown_days=a.get("keyword_cooldown_days", 7),
                max_keywords=a.get("max_keywords", 0),
                max_duration_minutes=a.get("max_duration_minutes", 0),
                max_candidates=a.get("max_candidates", 0),
                dry_run_threshold=a.get("dry_run_threshold", 5),
                max_title_keywords=a.get("max_title_keywords", 3),
            )

        # Referral Rates
        if "referral_rates" in data:
            config.referral_rates = data["referral_rates"]

        return config


# グローバル設定インスタンス
_config: Config | None = None


def get_config(config_path: str | Path | None = None) -> Config:
    """設定を取得する（シングルトン）"""
    global _config
    if _config is None:
        _config = Config.load(config_path)
    return _config


def reload_config(config_path: str | Path | None = None) -> Config:
    """設定を再読み込みする"""
    global _config
    _config = Config.load(config_path)
    return _config
