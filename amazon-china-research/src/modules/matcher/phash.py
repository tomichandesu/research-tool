"""pHash画像マッチングモジュール"""
from __future__ import annotations

import logging
from io import BytesIO
from typing import Optional
import asyncio

import aiohttp
from PIL import Image
import imagehash

from ...config import get_config, MatcherConfig

logger = logging.getLogger(__name__)


class ImageMatcher:
    """pHashを使用した画像マッチング

    pHash（Perceptual Hash）は、画像の視覚的特徴を64ビットのハッシュ値に変換する。
    2つのハッシュ間のハミング距離が小さいほど、画像は類似している。

    閾値:
    - 0: 完全一致
    - 1-5: 非常に類似（同一商品と見なせる）
    - 6-10: 類似（要確認）
    - 11以上: 異なる画像
    """

    def __init__(
        self,
        threshold: Optional[int] = None,
        config: Optional[MatcherConfig] = None,
    ):
        if config is None:
            config = get_config().matcher
        if threshold is None:
            threshold = config.phash_threshold

        self.threshold = threshold
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """HTTP セッションを取得"""
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

    async def is_match(
        self,
        image_url_1: str,
        image_url_2: str,
    ) -> bool:
        """2つの画像が一致するか判定

        Args:
            image_url_1: 比較元画像URL
            image_url_2: 比較先画像URL

        Returns:
            True: ハミング距離 <= threshold
            False: ハミング距離 > threshold
        """
        distance = await self.get_hamming_distance(image_url_1, image_url_2)
        if distance is None:
            return False
        return distance <= self.threshold

    async def get_hamming_distance(
        self,
        image_url_1: str,
        image_url_2: str,
    ) -> Optional[int]:
        """2つの画像間のハミング距離を計算

        Args:
            image_url_1: 比較元画像URL
            image_url_2: 比較先画像URL

        Returns:
            ハミング距離（0-64）、エラー時はNone
        """
        try:
            hash1 = await self.get_hash(image_url_1)
            hash2 = await self.get_hash(image_url_2)

            if hash1 is None or hash2 is None:
                return None

            distance = self.hamming_distance(hash1, hash2)
            logger.debug(
                f"ハミング距離: {distance} "
                f"(閾値: {self.threshold})"
            )
            return distance

        except Exception as e:
            logger.warning(f"ハミング距離計算失敗: {e}")
            return None

    async def get_hash(self, image_url: str) -> Optional[imagehash.ImageHash]:
        """画像のpHashを取得

        Args:
            image_url: 画像URL

        Returns:
            pHashオブジェクト、エラー時はNone
        """
        try:
            image = await self._download_image(image_url)
            if image is None:
                return None

            # pHashを計算
            hash_value = imagehash.phash(image)
            logger.debug(f"pHash計算: {hash_value}")
            return hash_value

        except Exception as e:
            logger.warning(f"pHash計算失敗: {image_url} - {e}")
            return None

    async def _download_image(self, url: str) -> Optional[Image.Image]:
        """画像をダウンロードする

        Args:
            url: 画像URL

        Returns:
            PILイメージオブジェクト、エラー時はNone
        """
        try:
            session = await self._get_session()
            async with session.get(url) as response:
                if response.status != 200:
                    logger.warning(f"画像ダウンロード失敗: {url} (status={response.status})")
                    return None

                content = await response.read()
                image = Image.open(BytesIO(content))

                # RGBに変換（アルファチャンネルを除去）
                if image.mode in ("RGBA", "LA", "P"):
                    image = image.convert("RGB")

                return image

        except Exception as e:
            logger.warning(f"画像ダウンロードエラー: {url} - {e}")
            return None

    def hamming_distance(
        self,
        hash1: imagehash.ImageHash,
        hash2: imagehash.ImageHash,
    ) -> int:
        """ハミング距離を計算

        Args:
            hash1: pHash 1
            hash2: pHash 2

        Returns:
            ハミング距離（0-64）
        """
        return hash1 - hash2

    async def find_best_match(
        self,
        source_url: str,
        candidate_urls: list[str],
    ) -> Optional[tuple[int, int]]:
        """最も類似した画像を見つける

        Args:
            source_url: 比較元画像URL
            candidate_urls: 候補画像URLリスト

        Returns:
            (最もマッチしたインデックス, ハミング距離) のタプル
            マッチなしの場合はNone
        """
        source_hash = await self.get_hash(source_url)
        if source_hash is None:
            return None

        best_match = None
        best_distance = float('inf')

        for i, candidate_url in enumerate(candidate_urls):
            candidate_hash = await self.get_hash(candidate_url)
            if candidate_hash is None:
                continue

            distance = self.hamming_distance(source_hash, candidate_hash)

            if distance < best_distance:
                best_distance = distance
                best_match = i

            # 完全一致の場合は即座に返す
            if distance == 0:
                return (i, 0)

        if best_match is not None and best_distance <= self.threshold:
            return (best_match, best_distance)

        return None

    async def find_all_matches(
        self,
        source_url: str,
        candidate_urls: list[str],
    ) -> list[tuple[int, int]]:
        """閾値以下の全ての類似画像を見つける

        Args:
            source_url: 比較元画像URL
            candidate_urls: 候補画像URLリスト

        Returns:
            (インデックス, ハミング距離) のタプルリスト（距離順）
        """
        source_hash = await self.get_hash(source_url)
        if source_hash is None:
            return []

        matches = []

        for i, candidate_url in enumerate(candidate_urls):
            candidate_hash = await self.get_hash(candidate_url)
            if candidate_hash is None:
                continue

            distance = self.hamming_distance(source_hash, candidate_hash)

            if distance <= self.threshold:
                matches.append((i, distance))

        # 距離でソート
        matches.sort(key=lambda x: x[1])
        return matches

    def similarity_percentage(self, distance: int) -> float:
        """ハミング距離を類似度パーセンテージに変換

        Args:
            distance: ハミング距離（0-64）

        Returns:
            類似度（0.0-100.0%）
        """
        return (64 - distance) / 64 * 100

    def is_likely_same_product(self, distance: int) -> str:
        """ハミング距離から判定結果を返す

        Args:
            distance: ハミング距離

        Returns:
            判定結果の文字列
        """
        if distance == 0:
            return "完全一致"
        elif distance <= 3:
            return "ほぼ同一"
        elif distance <= 5:
            return "同一商品の可能性高"
        elif distance <= 10:
            return "類似（要確認）"
        else:
            return "異なる商品"
