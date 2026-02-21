"""結果データモデル"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Iterator

from .product import ProductDetail, AlibabaProduct


@dataclass
class MatchResult:
    """マッチング結果

    Attributes:
        amazon_product: Amazon商品詳細
        alibaba_product: 1688商品情報（マッチした場合）
        is_matched: マッチしたかどうか
        hamming_distance: ハミング距離（画像類似度）
        match_confidence: マッチ信頼度（0.0〜1.0）
    """
    amazon_product: ProductDetail
    alibaba_product: Optional[AlibabaProduct] = None
    is_matched: bool = False
    hamming_distance: Optional[int] = None
    match_confidence: Optional[float] = None

    @property
    def similarity_percentage(self) -> Optional[float]:
        """類似度をパーセンテージで返す

        ORBマッチ時: match_confidence × 100
        pHash時: (64 - hamming_distance) / 64 × 100
        """
        if self.match_confidence is not None:
            return self.match_confidence * 100
        if self.hamming_distance is not None:
            return (64 - self.hamming_distance) / 64 * 100
        return None

    def to_dict(self) -> dict:
        """辞書に変換"""
        return {
            "amazon_product": self.amazon_product.to_dict(),
            "alibaba_product": self.alibaba_product.to_dict() if self.alibaba_product else None,
            "is_matched": self.is_matched,
            "hamming_distance": self.hamming_distance,
            "match_confidence": self.match_confidence,
        }


@dataclass
class ProfitResult:
    """利益計算結果

    Attributes:
        amazon_price: Amazon販売価格（円）
        cost_1688_jpy: 1688仕入れ価格（円換算後）
        shipping: 国際送料（円）
        customs: 関税（円）
        referral_fee: Amazon紹介料（円）
        fba_fee: FBA手数料（円）
        total_cost: 総コスト（円）
        profit: 利益（円）
        profit_rate: 利益率（0.0〜1.0）
        is_profitable: 利益が出るかどうか
    """
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

    @property
    def profit_rate_percentage(self) -> float:
        """利益率をパーセンテージで返す"""
        return self.profit_rate * 100

    @property
    def roi(self) -> float:
        """ROI（投資利益率）を計算"""
        if self.total_cost == 0:
            return 0.0
        return self.profit / self.total_cost

    def to_dict(self) -> dict:
        """辞書に変換"""
        return {
            "amazon_price": self.amazon_price,
            "cost_1688_jpy": self.cost_1688_jpy,
            "shipping": self.shipping,
            "customs": self.customs,
            "referral_fee": self.referral_fee,
            "fba_fee": self.fba_fee,
            "total_cost": self.total_cost,
            "profit": self.profit,
            "profit_rate": self.profit_rate,
            "is_profitable": self.is_profitable,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProfitResult:
        """辞書から生成"""
        return cls(
            amazon_price=data["amazon_price"],
            cost_1688_jpy=data["cost_1688_jpy"],
            shipping=data["shipping"],
            customs=data["customs"],
            referral_fee=data["referral_fee"],
            fba_fee=data["fba_fee"],
            total_cost=data["total_cost"],
            profit=data["profit"],
            profit_rate=data["profit_rate"],
            is_profitable=data["is_profitable"],
        )


@dataclass
class ResearchResult:
    """最終リサーチ結果

    Attributes:
        amazon_product: Amazon商品詳細
        alibaba_product: マッチした1688商品
        profit_result: 利益計算結果
        estimated_monthly_sales: 推定月間販売数
        estimated_monthly_revenue: 推定月間売上（円）
        match_result: マッチング結果
    """
    amazon_product: ProductDetail
    alibaba_product: AlibabaProduct
    profit_result: ProfitResult
    estimated_monthly_sales: int
    estimated_monthly_revenue: int
    match_result: Optional[MatchResult] = None

    @property
    def estimated_monthly_profit(self) -> int:
        """推定月間利益を計算"""
        return self.profit_result.profit * self.estimated_monthly_sales

    @property
    def score(self) -> float:
        """リサーチスコアを計算（利益率 × 販売数の重み付け）"""
        # 利益率 (0-1) × 販売数スコア（log10スケール）
        import math
        sales_score = min(math.log10(max(self.estimated_monthly_sales, 1) + 1), 3) / 3
        return self.profit_result.profit_rate * sales_score * 100

    def to_dict(self) -> dict:
        """辞書に変換"""
        return {
            "amazon_product": self.amazon_product.to_dict(),
            "alibaba_product": self.alibaba_product.to_dict(),
            "profit_result": self.profit_result.to_dict(),
            "estimated_monthly_sales": self.estimated_monthly_sales,
            "estimated_monthly_revenue": self.estimated_monthly_revenue,
            "estimated_monthly_profit": self.estimated_monthly_profit,
            "score": self.score,
        }

    def to_csv_row(self) -> dict:
        """CSV出力用の1行データを生成"""
        return {
            # Amazon情報
            "ASIN": self.amazon_product.asin,
            "商品タイトル": self.amazon_product.title,
            "Amazon価格（円）": self.amazon_product.price,
            "レビュー数": self.amazon_product.review_count,
            "評価": self.amazon_product.rating,
            "BSR": self.amazon_product.bsr,
            "カテゴリ": self.amazon_product.category,
            "FBA": "○" if self.amazon_product.is_fba else "×",
            "Amazon URL": self.amazon_product.amazon_url,

            # 1688情報
            "1688価格（元）": self.alibaba_product.price_cny,
            "1688価格（円）": self.alibaba_product.price_jpy,
            "1688店舗": self.alibaba_product.shop_name or "",
            "1688 URL": self.alibaba_product.product_url,

            # コスト明細
            "仕入原価（円）": self.profit_result.cost_1688_jpy,
            "国際送料（円）": self.profit_result.shipping,
            "関税（円）": self.profit_result.customs,
            "紹介料（円）": self.profit_result.referral_fee,
            "FBA手数料（円）": self.profit_result.fba_fee,
            "総コスト（円）": self.profit_result.total_cost,

            # 利益
            "利益（円）": self.profit_result.profit,
            "利益率（%）": round(self.profit_result.profit_rate_percentage, 1),

            # 販売予測
            "推定月間販売数": self.estimated_monthly_sales,
            "推定月間売上（円）": self.estimated_monthly_revenue,
            "推定月間利益（円）": self.estimated_monthly_profit,

            # スコア
            "リサーチスコア": round(self.score, 1),
        }


@dataclass
class KeywordResearchOutcome:
    """run_keyword_research() の戻り値ラッパー

    スコアベース優先探索のためのメタデータを保持しつつ、
    __len__ / __iter__ / __bool__ で後方互換性を維持する。

    Attributes:
        keyword: リサーチしたキーワード
        results: ResearchResultのリスト
        total_searched: Amazon検索結果数
        pass_count: フィルタ通過数
        products_with_candidates: HTML用の生データ（dict list）
    """
    keyword: str
    results: list[ResearchResult] = field(default_factory=list)
    total_searched: int = 0
    pass_count: int = 0
    products_with_candidates: list[dict] = field(default_factory=list)
    all_filtered_products: list[dict] = field(default_factory=list)
    filter_reasons: dict = field(default_factory=dict)
    alibaba_search_error: str = ""

    @property
    def score(self) -> float:
        """市場スコア: 通過率 + 候補数ボーナス"""
        if self.total_searched == 0:
            return 0.0
        hit_rate = (self.pass_count / self.total_searched) * 100
        candidate_bonus = len(self.products_with_candidates) * 5
        return round(hit_rate + candidate_bonus, 1)

    def __len__(self) -> int:
        return len(self.results)

    def __iter__(self) -> Iterator[ResearchResult]:
        return iter(self.results)

    def __bool__(self) -> bool:
        return len(self.results) > 0
