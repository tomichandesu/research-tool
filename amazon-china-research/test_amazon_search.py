"""Amazon検索のテスト"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.utils.browser import BrowserManager
from src.modules.amazon.searcher import AmazonSearcher


async def test_amazon_search():
    """Amazon検索をテスト"""
    print("=" * 60)
    print("Amazon Search Test")
    print("=" * 60)

    browser = BrowserManager(
        headless=False,
        timeout=60000,
        request_delay=2.0,
    )

    try:
        await browser.start()
        print("Browser started")

        searcher = AmazonSearcher(browser)
        print("Searching for: piggy bank")

        results = await searcher.search(
            keyword="貯金箱",
            max_pages=1,
        )

        print(f"\nResults found: {len(results)}")

        for i, item in enumerate(results[:5], 1):
            asin = item.get('asin', 'N/A')
            title = item.get('title', 'N/A')[:50] if item.get('title') else 'N/A'
            price = item.get('price', 'N/A')
            print(f"  [{i}] ASIN: {asin}, Price: {price}")
            print(f"       Title: {title}...")

        if results:
            print("\n" + "=" * 60)
            print("SUCCESS!")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("WARNING: No results found")
            print("=" * 60)

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await browser.stop()
        print("Browser stopped")


if __name__ == "__main__":
    asyncio.run(test_amazon_search())
