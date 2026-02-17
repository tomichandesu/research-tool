"""ImageMatcher ユニットテスト"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import imagehash
from PIL import Image
import io

from src.modules.matcher.phash import ImageMatcher


class TestImageMatcher:
    """ImageMatcherのテストクラス"""

    @pytest.fixture
    def matcher(self):
        """ImageMatcherインスタンスを生成"""
        return ImageMatcher(threshold=5)

    @pytest.fixture
    def matcher_strict(self):
        """厳格な閾値のImageMatcher"""
        return ImageMatcher(threshold=3)

    @pytest.fixture
    def matcher_loose(self):
        """緩い閾値のImageMatcher"""
        return ImageMatcher(threshold=10)

    # ============================================
    # 閾値設定テスト
    # ============================================

    def test_default_threshold(self):
        """デフォルト閾値が5であること"""
        matcher = ImageMatcher()
        assert matcher.threshold == 5

    def test_custom_threshold(self):
        """カスタム閾値が設定できること"""
        matcher = ImageMatcher(threshold=10)
        assert matcher.threshold == 10

    # ============================================
    # ハミング距離計算テスト
    # ============================================

    def test_hamming_distance_identical(self, matcher):
        """同一ハッシュのハミング距離は0"""
        # 同じ画像データからハッシュを生成
        img = Image.new('RGB', (64, 64), color='red')
        hash1 = imagehash.phash(img)
        hash2 = imagehash.phash(img)

        distance = matcher.hamming_distance(hash1, hash2)
        assert distance == 0

    def test_hamming_distance_different(self, matcher):
        """異なるハッシュのハミング距離は>0"""
        # pHashは輝度ベースなので、パターンの異なる画像を使用
        img1 = Image.new('RGB', (64, 64), color='white')
        # チェッカーパターンの画像を作成
        img2 = Image.new('RGB', (64, 64), color='black')
        for x in range(64):
            for y in range(64):
                if (x + y) % 2 == 0:
                    img2.putpixel((x, y), (255, 255, 255))
        hash1 = imagehash.phash(img1)
        hash2 = imagehash.phash(img2)

        distance = matcher.hamming_distance(hash1, hash2)
        assert distance > 0

    def test_hamming_distance_max(self, matcher):
        """ハミング距離の最大値は64"""
        img1 = Image.new('RGB', (64, 64), color='white')
        img2 = Image.new('RGB', (64, 64), color='black')
        hash1 = imagehash.phash(img1)
        hash2 = imagehash.phash(img2)

        distance = matcher.hamming_distance(hash1, hash2)
        assert 0 <= distance <= 64

    # ============================================
    # 類似度パーセンテージテスト
    # ============================================

    def test_similarity_percentage_identical(self, matcher):
        """距離0 = 100%類似"""
        percentage = matcher.similarity_percentage(0)
        assert percentage == 100.0

    def test_similarity_percentage_completely_different(self, matcher):
        """距離64 = 0%類似"""
        percentage = matcher.similarity_percentage(64)
        assert percentage == 0.0

    def test_similarity_percentage_half(self, matcher):
        """距離32 = 50%類似"""
        percentage = matcher.similarity_percentage(32)
        assert percentage == 50.0

    @pytest.mark.parametrize("distance,expected", [
        (0, 100.0),
        (5, 92.1875),
        (10, 84.375),
        (32, 50.0),
        (64, 0.0),
    ])
    def test_similarity_percentage_various(self, matcher, distance, expected):
        """様々な距離での類似度"""
        percentage = matcher.similarity_percentage(distance)
        assert abs(percentage - expected) < 0.01

    # ============================================
    # 判定結果テスト
    # ============================================

    @pytest.mark.parametrize("distance,expected", [
        (0, "完全一致"),
        (1, "ほぼ同一"),
        (3, "ほぼ同一"),
        (4, "同一商品の可能性高"),
        (5, "同一商品の可能性高"),
        (6, "類似（要確認）"),
        (10, "類似（要確認）"),
        (11, "異なる商品"),
        (30, "異なる商品"),
    ])
    def test_is_likely_same_product(self, matcher, distance, expected):
        """ハミング距離からの判定結果"""
        result = matcher.is_likely_same_product(distance)
        assert result == expected

    # ============================================
    # マッチング判定テスト（FR-302）
    # ============================================

    @pytest.mark.asyncio
    async def test_is_match_threshold_boundary(self, matcher):
        """閾値境界でのマッチング判定"""
        # モックを使用してテスト
        with patch.object(matcher, 'get_hamming_distance', new_callable=AsyncMock) as mock_distance:
            # 閾値5以下 → True
            mock_distance.return_value = 5
            assert await matcher.is_match("url1", "url2") is True

            # 閾値5超 → False
            mock_distance.return_value = 6
            assert await matcher.is_match("url1", "url2") is False

    @pytest.mark.asyncio
    async def test_is_match_error_handling(self, matcher):
        """エラー時はFalseを返す"""
        with patch.object(matcher, 'get_hamming_distance', new_callable=AsyncMock) as mock_distance:
            mock_distance.return_value = None
            assert await matcher.is_match("url1", "url2") is False


class TestImageMatcherAsync:
    """ImageMatcherの非同期テスト"""

    @pytest.fixture
    def matcher(self):
        return ImageMatcher(threshold=5)

    @pytest.mark.asyncio
    async def test_get_hash_with_mock(self, matcher):
        """画像ハッシュ取得のモックテスト"""
        # 画像ダウンロードをモック
        test_image = Image.new('RGB', (100, 100), color='red')

        with patch.object(matcher, '_download_image', new_callable=AsyncMock) as mock_download:
            mock_download.return_value = test_image

            hash_result = await matcher.get_hash("https://example.com/image.jpg")

            assert hash_result is not None
            mock_download.assert_called_once_with("https://example.com/image.jpg")

    @pytest.mark.asyncio
    async def test_get_hash_download_failure(self, matcher):
        """画像ダウンロード失敗時はNoneを返す"""
        with patch.object(matcher, '_download_image', new_callable=AsyncMock) as mock_download:
            mock_download.return_value = None

            hash_result = await matcher.get_hash("https://example.com/invalid.jpg")

            assert hash_result is None

    @pytest.mark.asyncio
    async def test_find_best_match(self, matcher):
        """最良マッチを見つける"""
        # テスト用画像を生成（pHashはパターンで区別するため、異なるパターンを使用）
        source_img = Image.new('RGB', (100, 100), color='white')
        similar_img = Image.new('RGB', (100, 100), color='white')  # 同じ

        # チェッカーパターンで明確に異なる画像
        different_img = Image.new('RGB', (100, 100), color='black')
        for x in range(100):
            for y in range(100):
                if (x + y) % 2 == 0:
                    different_img.putpixel((x, y), (255, 255, 255))

        async def mock_get_hash(url):
            if "source" in url:
                return imagehash.phash(source_img)
            elif "similar" in url:
                return imagehash.phash(similar_img)
            else:
                return imagehash.phash(different_img)

        with patch.object(matcher, 'get_hash', side_effect=mock_get_hash):
            result = await matcher.find_best_match(
                "https://example.com/source.jpg",
                [
                    "https://example.com/different.jpg",
                    "https://example.com/similar.jpg",
                ]
            )

            # similar.jpg (index 1) がベストマッチ
            assert result is not None
            assert result[0] == 1  # インデックス
            assert result[1] == 0  # 距離0（同一画像）

    @pytest.mark.asyncio
    async def test_find_best_match_no_match(self, matcher):
        """マッチなしの場合はNoneを返す"""
        # pHashは輝度ベースなので、パターンの異なる画像を使用
        source_img = Image.new('RGB', (100, 100), color='white')

        # チェッカーパターンで明確に異なる画像
        different_img = Image.new('RGB', (100, 100), color='black')
        for x in range(100):
            for y in range(100):
                if (x + y) % 2 == 0:
                    different_img.putpixel((x, y), (255, 255, 255))

        # 全く異なる画像のハッシュを返す
        async def mock_get_hash(url):
            if "source" in url:
                return imagehash.phash(source_img)
            else:
                # 閾値を超える距離になるよう異なるパターンの画像を使用
                return imagehash.phash(different_img)

        with patch.object(matcher, 'get_hash', side_effect=mock_get_hash):
            # 閾値を0にして、完全一致以外はマッチしないようにする
            matcher.threshold = 0

            result = await matcher.find_best_match(
                "https://example.com/source.jpg",
                ["https://example.com/different.jpg"]
            )

            # 異なる画像なのでマッチなし
            assert result is None

    @pytest.mark.asyncio
    async def test_find_all_matches(self, matcher):
        """閾値以下の全マッチを見つける"""
        source_img = Image.new('RGB', (100, 100), color='red')

        async def mock_get_hash(url):
            return imagehash.phash(source_img)

        with patch.object(matcher, 'get_hash', side_effect=mock_get_hash):
            results = await matcher.find_all_matches(
                "https://example.com/source.jpg",
                [
                    "https://example.com/img1.jpg",
                    "https://example.com/img2.jpg",
                ]
            )

            # 全て同一画像なので全てマッチ
            assert len(results) == 2
            # 距離順にソートされている
            assert all(r[1] == 0 for r in results)

    @pytest.mark.asyncio
    async def test_close_session(self, matcher):
        """セッションのクローズ"""
        # セッションがない状態でクローズしてもエラーにならない
        await matcher.close()


class TestImageMatcherRequirements:
    """要件定義に基づくテスト（FR-302）"""

    @pytest.fixture
    def matcher(self):
        return ImageMatcher(threshold=5)

    def test_fr302_threshold_5(self, matcher):
        """FR-302: pHashの閾値が5であること"""
        assert matcher.threshold == 5

    @pytest.mark.asyncio
    async def test_fr302_match_criteria(self, matcher):
        """FR-302: ハミング距離5以下でマッチと判定されること"""
        with patch.object(matcher, 'get_hamming_distance', new_callable=AsyncMock) as mock:
            # 距離5以下 → マッチ
            for distance in [0, 1, 2, 3, 4, 5]:
                mock.return_value = distance
                result = await matcher.is_match("url1", "url2")
                assert result is True, f"距離{distance}でマッチすべき"

            # 距離6以上 → 不一致
            for distance in [6, 7, 10, 20, 64]:
                mock.return_value = distance
                result = await matcher.is_match("url1", "url2")
                assert result is False, f"距離{distance}で不一致とすべき"
