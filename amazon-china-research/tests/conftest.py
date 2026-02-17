"""pytest 共通設定・フィクスチャ"""
import pytest
import sys
from pathlib import Path

# srcディレクトリをパスに追加
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))


@pytest.fixture
def sample_asin():
    """テスト用ASIN"""
    return "B08TEST001"


@pytest.fixture
def sample_keyword():
    """テスト用キーワード"""
    return "貯金箱"


@pytest.fixture
def sample_cny_price():
    """テスト用1688価格（元）"""
    return 50.0


@pytest.fixture
def sample_amazon_price():
    """テスト用Amazon価格（円）"""
    return 3000


@pytest.fixture
def exchange_rate():
    """為替レート（1元 = X円）"""
    return 21.5


@pytest.fixture
def shipping_per_kg():
    """国際送料（円/kg）"""
    return 1300


# pytest-asyncio の設定
def pytest_configure(config):
    """pytest設定"""
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )


# カスタムマーカー
def pytest_collection_modifyitems(config, items):
    """テストアイテムの修正"""
    for item in items:
        # asyncioテストに自動的にマーカーを追加
        if "async" in item.name:
            item.add_marker(pytest.mark.asyncio)
