"""ORB特徴量マッチングによる商品同定モジュール

OpenCV ORB (Oriented FAST and Rotated BRIEF) を使用して、
Amazon商品画像と1688商品画像の視覚的類似度を計算する。

pHashは「同一写真」検出用（閾値5でハミング距離28-38は全て弾かれる）のに対し、
ORBは回転・スケール不変の特徴点マッチングで、
異なる角度・背景・照明でも同一商品を検出できる。
"""
from __future__ import annotations

import logging
from io import BytesIO
from typing import Optional

import aiohttp
import cv2
import numpy as np

from ...config import get_config, MatcherConfig
from ...models.product import AlibabaProduct
from ...models.result import ProfitResult

logger = logging.getLogger(__name__)


class SmartMatcher:
    """ORB特徴量ベースの商品画像マッチャー

    ORBアルゴリズム:
    1. 画像をグレースケールに変換
    2. 300x300にリサイズ（統一比較）
    3. ORB検出器で特徴点（最大500個）とdescriptorを抽出
    4. BFMatcher (Hamming距離) でdescriptor同士をkNN照合
    5. Lowe's ratio test (0.75) で曖昧なマッチを除外
    6. 類似度 = good_matches / min(kp1数, kp2数)
    """

    RESIZE_DIM = 300  # 統一リサイズサイズ

    def __init__(
        self,
        min_similarity: float = 0.10,
        n_features: int = 500,
        ratio_threshold: float = 0.75,
        min_price_cny: float = 0.5,
        config: Optional[MatcherConfig] = None,
    ):
        if config is None:
            config = get_config().matcher

        self.min_similarity = min_similarity or config.orb_min_similarity
        self.n_features = n_features or config.orb_n_features
        self.ratio_threshold = ratio_threshold or config.orb_ratio_threshold
        self.min_price_cny = min_price_cny or config.min_price_cny

        self._orb = cv2.ORB_create(nfeatures=self.n_features)
        self._bf = cv2.BFMatcher(cv2.NORM_HAMMING)
        self._session: Optional[aiohttp.ClientSession] = None

        # DINOv2 利用可能チェック
        self._dino_available = False
        try:
            from .dino import is_available
            self._dino_available = is_available()
        except ImportError:
            pass

    async def _get_session(self) -> aiohttp.ClientSession:
        """HTTPセッションを取得（遅延初期化）"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                },
            )
        return self._session

    async def close(self):
        """セッションを閉じる"""
        if self._session and not self._session.closed:
            await self._session.close()

    async def prepare_image_dino(self, url: str) -> Optional[np.ndarray]:
        """DINOv2特徴ベクトルを準備（384次元）

        Args:
            url: 画像URL

        Returns:
            384次元L2正規化numpy配列、またはNone
        """
        if not self._dino_available:
            return None
        img_bytes = await self._download_image(url)
        if img_bytes is None:
            return None
        try:
            from .dino import extract_features
            return extract_features(img_bytes)
        except Exception as e:
            logger.warning(f"DINOv2特徴量抽出エラー: {e}")
            return None

    @staticmethod
    def dino_similarity(feat1: np.ndarray, feat2: np.ndarray) -> float:
        """DINOv2コサイン類似度

        Args:
            feat1: DINOv2特徴ベクトル1
            feat2: DINOv2特徴ベクトル2

        Returns:
            コサイン類似度 (0.0-1.0)
        """
        from .dino import cosine_similarity
        return cosine_similarity(feat1, feat2)

    async def _download_image(self, url: str) -> Optional[bytes]:
        """画像をダウンロードしてバイト列を返す"""
        try:
            session = await self._get_session()
            async with session.get(url) as response:
                if response.status != 200:
                    logger.warning(f"画像DL失敗: {url} (status={response.status})")
                    return None
                return await response.read()
        except Exception as e:
            logger.warning(f"画像DLエラー: {url} - {e}")
            return None

    def _bytes_to_gray(self, img_bytes: bytes) -> Optional[np.ndarray]:
        """バイト列をグレースケールnumpy配列に変換（300x300リサイズ）"""
        try:
            arr = np.frombuffer(img_bytes, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
            if img is None:
                return None
            return cv2.resize(img, (self.RESIZE_DIM, self.RESIZE_DIM))
        except Exception as e:
            logger.warning(f"画像変換エラー: {e}")
            return None

    def _bytes_to_color(self, img_bytes: bytes) -> Optional[np.ndarray]:
        """バイト列をカラーnumpy配列に変換（300x300リサイズ）"""
        try:
            arr = np.frombuffer(img_bytes, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is None:
                return None
            return cv2.resize(img, (self.RESIZE_DIM, self.RESIZE_DIM))
        except Exception as e:
            logger.warning(f"カラー画像変換エラー: {e}")
            return None

    @staticmethod
    def histogram_similarity(img1_color: np.ndarray, img2_color: np.ndarray) -> float:
        """2つのカラー画像のヒストグラム相関を計算

        HSV色空間のH(色相)とS(彩度)チャネルで比較。
        同じ商品なら色分布が似る（相関0.5以上）。
        全く別の商品（黒ゴム vs 金属ラック）なら相関が低い。

        Returns:
            相関値 (-1.0〜1.0)。1.0が完全一致。
        """
        hsv1 = cv2.cvtColor(img1_color, cv2.COLOR_BGR2HSV)
        hsv2 = cv2.cvtColor(img2_color, cv2.COLOR_BGR2HSV)

        # H: 0-180, S: 0-256 の2Dヒストグラム
        h_bins, s_bins = 50, 60
        hist_size = [h_bins, s_bins]
        ranges = [0, 180, 0, 256]
        channels = [0, 1]

        hist1 = cv2.calcHist([hsv1], channels, None, hist_size, ranges)
        cv2.normalize(hist1, hist1, 0, 1, cv2.NORM_MINMAX)

        hist2 = cv2.calcHist([hsv2], channels, None, hist_size, ranges)
        cv2.normalize(hist2, hist2, 0, 1, cv2.NORM_MINMAX)

        return cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)

    def _compute_orb_similarity(
        self,
        img1: np.ndarray,
        img2: np.ndarray,
    ) -> float:
        """2つのグレースケール画像間のORB類似度を計算

        Returns:
            類似度 (0.0-1.0)。特徴点が見つからない場合は0.0
        """
        kp1, des1 = self._orb.detectAndCompute(img1, None)
        kp2, des2 = self._orb.detectAndCompute(img2, None)

        if des1 is None or des2 is None:
            return 0.0
        if len(kp1) < 2 or len(kp2) < 2:
            return 0.0

        # kNN照合（k=2でLowe's ratio test）
        try:
            matches = self._bf.knnMatch(des1, des2, k=2)
        except cv2.error:
            return 0.0

        # Lowe's ratio test: 最近傍と次近傍の距離比で曖昧なマッチを除外
        good_matches = []
        for match in matches:
            if len(match) == 2:
                m, n = match
                if m.distance < self.ratio_threshold * n.distance:
                    good_matches.append(m)

        # 類似度 = good_matches / min(特徴点数)
        denominator = min(len(kp1), len(kp2))
        if denominator == 0:
            return 0.0

        return len(good_matches) / denominator

    async def prepare_image(self, url: str) -> Optional[np.ndarray]:
        """画像URLからグレースケール配列を準備する（ORB比較用）

        Args:
            url: 画像URL

        Returns:
            300x300グレースケールnumpy配列、またはNone
        """
        img_bytes = await self._download_image(url)
        if img_bytes is None:
            return None
        return self._bytes_to_gray(img_bytes)

    async def prepare_image_color(self, url: str) -> Optional[np.ndarray]:
        """画像URLからカラー配列を準備する（ヒストグラム比較用）

        Args:
            url: 画像URL

        Returns:
            300x300カラーnumpy配列、またはNone
        """
        img_bytes = await self._download_image(url)
        if img_bytes is None:
            return None
        return self._bytes_to_color(img_bytes)

    def similarity(self, img1: np.ndarray, img2: np.ndarray) -> float:
        """2つのグレースケール画像のORB類似度を返す

        Args:
            img1: グレースケール画像1（prepare_imageの戻り値）
            img2: グレースケール画像2（prepare_imageの戻り値）

        Returns:
            類似度 (0.0-1.0)
        """
        return self._compute_orb_similarity(img1, img2)

    async def compute_similarity(self, url1: str, url2: str) -> float:
        """2つの画像URLからORB類似度を計算

        Args:
            url1: 画像URL 1
            url2: 画像URL 2

        Returns:
            類似度 (0.0-1.0)
        """
        bytes1 = await self._download_image(url1)
        bytes2 = await self._download_image(url2)

        if bytes1 is None or bytes2 is None:
            return 0.0

        gray1 = self._bytes_to_gray(bytes1)
        gray2 = self._bytes_to_gray(bytes2)

        if gray1 is None or gray2 is None:
            return 0.0

        return self._compute_orb_similarity(gray1, gray2)

    async def find_best_match(
        self,
        amazon_image_url: str,
        alibaba_products: list[AlibabaProduct],
        amazon_price: int,
        profit_calc,
        is_fba: bool = True,
        category: str = "default",
        weight_kg: Optional[float] = None,
        dimensions: Optional[tuple] = None,
        diagnose: bool = False,
        tag: str = "",
    ) -> Optional[tuple[AlibabaProduct, float, ProfitResult, list[dict]]]:
        """1688候補の中から最良マッチを検索

        フロー:
        1. Amazon画像を1回だけDL → ORB特徴点を計算
        2. 各1688候補について:
           - price_cny < min_price_cny → スキップ（価格サニティ）
           - 画像DL → ORB類似度を計算
           - 類似度 < min_similarity → スキップ
           - 利益計算
        3. 通過した候補の中から最高利益率を返す

        Args:
            amazon_image_url: Amazon商品画像URL
            alibaba_products: 1688商品リスト
            amazon_price: Amazon販売価格（円）
            profit_calc: ProfitCalculator インスタンス
            is_fba: FBA出品か
            category: カテゴリ
            weight_kg: 重量(kg)
            dimensions: 寸法(L,W,H) cm
            diagnose: 診断モード
            tag: ログタグ

        Returns:
            (best_alibaba, similarity, profit_result, diagnostics) or None
        """
        # Amazon画像をDL＆ORB特徴点を事前計算
        amazon_bytes = await self._download_image(amazon_image_url)
        if amazon_bytes is None:
            logger.warning(f"Amazon画像DL失敗: {amazon_image_url}")
            return None

        amazon_gray = self._bytes_to_gray(amazon_bytes)
        if amazon_gray is None:
            logger.warning(f"Amazon画像変換失敗")
            return None

        amazon_kp, amazon_des = self._orb.detectAndCompute(amazon_gray, None)
        if amazon_des is None or len(amazon_kp) < 2:
            logger.warning(f"Amazon画像の特徴点が不足")
            return None

        best_alibaba: Optional[AlibabaProduct] = None
        best_similarity: float = 0.0
        best_profit: Optional[ProfitResult] = None
        best_rate: float = -1.0
        diagnostics: list[dict] = []

        for i, ap in enumerate(alibaba_products):
            diag_entry = {
                "index": i + 1,
                "price_cny": ap.price_cny,
                "title": (ap.title or "")[:30],
                "similarity": 0.0,
                "profit_rate": None,
                "status": "skipped",
                "reason": "",
            }

            # 価格サニティチェック
            if ap.price_cny < self.min_price_cny:
                diag_entry["reason"] = f"価格{ap.price_cny}元 < {self.min_price_cny}元"
                diagnostics.append(diag_entry)
                if diagnose:
                    print(f"{tag}       {i+1}. [SKIP] {ap.price_cny}元 < "
                          f"{self.min_price_cny}元（価格サニティ）")
                continue

            # 画像がない場合はスキップ
            if not ap.image_url:
                diag_entry["reason"] = "画像URLなし"
                diagnostics.append(diag_entry)
                continue

            # 1688画像をDL＆グレースケール変換
            ali_bytes = await self._download_image(ap.image_url)
            if ali_bytes is None:
                diag_entry["reason"] = "画像DL失敗"
                diagnostics.append(diag_entry)
                continue

            ali_gray = self._bytes_to_gray(ali_bytes)
            if ali_gray is None:
                diag_entry["reason"] = "画像変換失敗"
                diagnostics.append(diag_entry)
                continue

            # ORB類似度計算（Amazon特徴点を再利用）
            ali_kp, ali_des = self._orb.detectAndCompute(ali_gray, None)
            if ali_des is None or len(ali_kp) < 2:
                diag_entry["reason"] = "特徴点不足"
                diagnostics.append(diag_entry)
                continue

            try:
                matches = self._bf.knnMatch(amazon_des, ali_des, k=2)
            except cv2.error:
                diag_entry["reason"] = "kNN照合エラー"
                diagnostics.append(diag_entry)
                continue

            good_matches = []
            for match in matches:
                if len(match) == 2:
                    m, n = match
                    if m.distance < self.ratio_threshold * n.distance:
                        good_matches.append(m)

            denominator = min(len(amazon_kp), len(ali_kp))
            similarity = len(good_matches) / denominator if denominator > 0 else 0.0

            diag_entry["similarity"] = round(similarity, 4)

            # 類似度チェック
            if similarity < self.min_similarity:
                diag_entry["status"] = "rejected"
                diag_entry["reason"] = f"類似度{similarity:.2%} < {self.min_similarity:.0%}"
                diagnostics.append(diag_entry)
                if diagnose:
                    print(f"{tag}       {i+1}. [NG] {ap.price_cny}元 | "
                          f"類似度{similarity:.2%} < {self.min_similarity:.0%} | "
                          f"{(ap.title or '')[:25]}")
                continue

            # 利益計算
            pr = profit_calc.calculate(
                amazon_price=amazon_price,
                cny_price=ap.price_cny,
                is_fba=is_fba,
                category=category,
                weight_kg=weight_kg,
                dimensions=dimensions,
            )

            diag_entry["profit_rate"] = round(pr.profit_rate_percentage, 1)
            diag_entry["status"] = "passed"
            diag_entry["reason"] = ""
            diagnostics.append(diag_entry)

            if diagnose:
                print(f"{tag}       {i+1}. [OK] {ap.price_cny}元 | "
                      f"類似度{similarity:.2%} | "
                      f"利益率{pr.profit_rate_percentage:.1f}% | "
                      f"{(ap.title or '')[:25]}")

            # 最高利益率の商品を選択
            if pr.profit_rate_percentage > best_rate:
                best_rate = pr.profit_rate_percentage
                best_profit = pr
                best_alibaba = ap
                best_similarity = similarity

        if best_alibaba is None or best_profit is None:
            return None

        return (best_alibaba, best_similarity, best_profit, diagnostics)
