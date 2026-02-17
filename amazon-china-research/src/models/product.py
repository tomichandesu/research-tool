"""商品データモデル"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProductDetail:
    """Amazon商品詳細

    Attributes:
        asin: Amazon商品ID
        title: 商品タイトル
        price: 価格（円）
        image_url: メイン画像URL
        bsr: 大カテゴリーランキング (Best Seller Rank)
        category: 大カテゴリー名
        review_count: レビュー数
        is_fba: FBA出品かどうか（出荷元=Amazon、販売元=第三者セラー）
        is_amazon_direct: Amazon直販かどうか（出荷元・販売元ともにAmazon）
        product_url: 商品ページURL
        rating: 評価（星）
        seller_name: 出品者名
        variation_count: バリエーション数
        dimensions: 商品寸法 (長さ, 幅, 高さ) cm
        weight_kg: 商品重量 (kg)
    """
    asin: str
    title: str
    price: int
    image_url: str
    bsr: int
    category: str
    review_count: int
    is_fba: bool
    product_url: str
    rating: Optional[float] = None
    is_amazon_direct: bool = False
    seller_name: Optional[str] = None
    variation_count: int = 1
    dimensions: Optional[tuple[float, float, float]] = None  # (長さ, 幅, 高さ) cm
    weight_kg: Optional[float] = None  # 重量 kg

    @property
    def dimensions_sum(self) -> Optional[float]:
        """寸法の合計（縦+横+高さ）を返す"""
        if self.dimensions is None:
            return None
        return sum(self.dimensions)

    @property
    def is_large_size(self) -> bool:
        """大型サイズかどうかを判定

        Amazon大型基準:
        - 寸法合計 > 100cm または
        - 重量 > 9kg
        """
        # 寸法による判定
        if self.dimensions is not None:
            if sum(self.dimensions) > 100:
                return True
        # 重量による判定
        if self.weight_kg is not None:
            if self.weight_kg > 9.0:
                return True
        return False

    @property
    def amazon_url(self) -> str:
        """Amazon商品ページURLを生成"""
        if self.product_url:
            return self.product_url
        return f"https://www.amazon.co.jp/dp/{self.asin}"

    def to_dict(self) -> dict:
        """辞書に変換"""
        return {
            "asin": self.asin,
            "title": self.title,
            "price": self.price,
            "image_url": self.image_url,
            "bsr": self.bsr,
            "category": self.category,
            "review_count": self.review_count,
            "is_fba": self.is_fba,
            "is_amazon_direct": self.is_amazon_direct,
            "product_url": self.product_url,
            "rating": self.rating,
            "seller_name": self.seller_name,
            "variation_count": self.variation_count,
            "dimensions": self.dimensions,
            "weight_kg": self.weight_kg,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProductDetail:
        """辞書から生成"""
        dimensions = data.get("dimensions")
        if dimensions is not None and isinstance(dimensions, (list, tuple)):
            dimensions = tuple(dimensions)
        return cls(
            asin=data["asin"],
            title=data["title"],
            price=data["price"],
            image_url=data["image_url"],
            bsr=data["bsr"],
            category=data["category"],
            review_count=data["review_count"],
            is_fba=data["is_fba"],
            product_url=data.get("product_url", ""),
            rating=data.get("rating"),
            is_amazon_direct=data.get("is_amazon_direct", False),
            seller_name=data.get("seller_name"),
            variation_count=data.get("variation_count", 1),
            dimensions=dimensions,
            weight_kg=data.get("weight_kg"),
        )


@dataclass
class AlibabaProduct:
    """1688商品情報

    Attributes:
        price_cny: 価格（元）
        image_url: 商品画像URL
        product_url: 商品ページURL
        shop_name: ショップ名
        shop_url: ショップページURL
        min_order: 最小注文数
        title: 商品タイトル
    """
    price_cny: float
    image_url: str
    product_url: str
    shop_name: Optional[str] = None
    shop_url: Optional[str] = None
    min_order: Optional[int] = None
    title: Optional[str] = None

    @property
    def price_jpy(self) -> int:
        """日本円に換算（デフォルトレート: 21.5円/元）"""
        return int(self.price_cny * 21.5)

    def to_dict(self) -> dict:
        """辞書に変換"""
        return {
            "price_cny": self.price_cny,
            "image_url": self.image_url,
            "product_url": self.product_url,
            "shop_name": self.shop_name,
            "shop_url": self.shop_url,
            "min_order": self.min_order,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AlibabaProduct:
        """辞書から生成"""
        return cls(
            price_cny=data["price_cny"],
            image_url=data["image_url"],
            product_url=data["product_url"],
            shop_name=data.get("shop_name"),
            shop_url=data.get("shop_url"),
            min_order=data.get("min_order"),
            title=data.get("title"),
        )
