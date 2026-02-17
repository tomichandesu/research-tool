"""Full pipeline test with detailed logging"""
import asyncio
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

from src.utils.browser import BrowserManager
from src.utils.auth import AuthManager
from src.modules.amazon.searcher import AmazonSearcher
from src.modules.amazon.scraper import AmazonScraper
from src.modules.amazon.filter import ProductFilter
from src.modules.alibaba.image_search import AlibabaImageSearcher

AUTH_PATH = Path(__file__).parent / "config" / "auth" / "1688_storage.json"


async def test_pipeline():
    """Full pipeline test"""
    print("=" * 60)
    print("Full Pipeline Test")
    print("=" * 60)

    # Check auth
    auth_manager = AuthManager()
    has_auth = auth_manager.is_logged_in()
    print(f"1688 Auth: {'OK' if has_auth else 'NOT FOUND'}")

    # Amazon browser
    amazon_browser = BrowserManager(
        headless=False,
        timeout=60000,
        request_delay=2.0,
    )

    # 1688 browser (with auth if available)
    alibaba_browser = None
    if has_auth:
        alibaba_browser = BrowserManager(
            headless=False,
            timeout=60000,
            request_delay=2.0,
            use_auth=True,
            auth_storage_path=AUTH_PATH,
        )

    try:
        await amazon_browser.start()
        print("Amazon browser started")

        if alibaba_browser:
            await alibaba_browser.start()
            print("1688 browser started")

        # Step 1: Amazon search
        print("\n--- Step 1: Amazon Search ---")
        searcher = AmazonSearcher(amazon_browser)
        search_results = await searcher.search(keyword="貯金箱", max_pages=1)
        print(f"Search results: {len(search_results)}")

        if not search_results:
            print("ERROR: No search results")
            return

        # Step 2: Get product details (first 3 only for speed)
        print("\n--- Step 2: Product Details ---")
        scraper = AmazonScraper(amazon_browser)
        products = []

        for i, item in enumerate(search_results[:5]):
            asin = item.get('asin')
            print(f"  Getting details for {asin}...")
            try:
                product = await scraper.get_product_detail(asin)
                if product:
                    products.append(product)
                    print(f"    Price: {product.price}, BSR: {product.bsr}, Reviews: {product.review_count}")
            except Exception as e:
                print(f"    ERROR: {e}")

        print(f"Products with details: {len(products)}")

        if not products:
            print("ERROR: No products with details")
            return

        # Step 3: Filter
        print("\n--- Step 3: Filter ---")
        product_filter = ProductFilter()
        filtered = product_filter.filter_with_details(products)
        print(f"Filtered products: {len(filtered)}")

        for product, result in filtered[:3]:
            print(f"  ASIN: {product.asin}")
            print(f"    Price: {product.price}, BSR: {product.bsr}")
            print(f"    Est. Sales: {result.estimated_monthly_sales}/month")

        if not filtered:
            print("WARNING: No products passed filter")
            # Show why products were filtered out
            for product in products:
                result = product_filter.check(product)
                if not result.passed:
                    print(f"  {product.asin}: {result.reason}")
            return

        # Step 4: 1688 image search (if auth available)
        if alibaba_browser and filtered:
            print("\n--- Step 4: 1688 Image Search ---")
            alibaba_searcher = AlibabaImageSearcher(alibaba_browser, max_results=5)

            product, _ = filtered[0]
            print(f"Searching 1688 for: {product.asin}")
            print(f"Image URL: {product.image_url[:60]}...")

            alibaba_products = await alibaba_searcher.search_by_image(
                image_url=product.image_url,
                max_results=5,
            )

            print(f"1688 results: {len(alibaba_products)}")

            for i, ap in enumerate(alibaba_products[:3], 1):
                print(f"  [{i}] Price: {ap.price_cny} CNY")
                print(f"      URL: {ap.product_url[:50]}...")

        print("\n" + "=" * 60)
        print("Pipeline test completed!")
        print("=" * 60)

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await amazon_browser.stop()
        if alibaba_browser:
            await alibaba_browser.stop()
        print("Browsers stopped")


if __name__ == "__main__":
    asyncio.run(test_pipeline())
