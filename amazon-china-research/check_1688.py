"""1688画像検索の動作確認スクリプト"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def check():
    from src.utils.browser import BrowserManager
    bm = BrowserManager(headless=True)
    await bm.start()
    page = await bm.new_page()

    # 1688画像検索ページにアクセス
    print("=== 1688画像検索ページにアクセス ===")
    await page.goto("https://s.1688.com/youyuan/index.htm", wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(5)

    url = page.url
    print(f"URL: {url}")
    title = await page.title()
    print(f"Title: {title}")

    # ファイルアップロードフィールドの確認
    file_input = await page.query_selector('input[type="file"]')
    print(f"File input found: {file_input is not None}")

    # 搜索图片ボタンの確認
    search_btn = await page.query_selector("div.search-btn")
    print(f"Search btn (div.search-btn): {search_btn is not None}")

    # ページの主要HTML要素チェック
    body_text = await page.evaluate("() => document.body ? document.body.innerText.substring(0, 2000) : 'NO BODY'")
    print("=== Body Text (2000 chars) ===")
    print(body_text)

    print("\n=== 主要セレクタの存在チェック ===")
    selectors = [
        'input[type="file"]',
        "div.search-btn",
        ".search-btn",
        "#search-btn",
        ".upload-btn",
        ".img-upload",
        "button",
        "div.img-search",
        ".youyuan-main",
        ".search-box",
        "#root",
        "#app",
    ]
    for sel in selectors:
        el = await page.query_selector(sel)
        if el:
            tag = await el.evaluate("e => e.tagName + '.' + e.className")
            print(f"  {sel}: FOUND ({tag})")
        else:
            print(f"  {sel}: NOT FOUND")

    # テスト画像でアップロード試行
    print("\n=== テスト画像で検索試行 ===")
    import aiohttp
    import tempfile
    test_url = "https://m.media-amazon.com/images/I/71G+dXaznaL._AC_SL1500_.jpg"
    print(f"テスト画像DL: {test_url[:60]}...")
    async with aiohttp.ClientSession() as session:
        async with session.get(test_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status == 200:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
                    f.write(await resp.read())
                    temp_path = f.name
                print(f"DL完了: {temp_path}")
            else:
                print(f"DL失敗: status={resp.status}")
                temp_path = None

    if temp_path and file_input:
        import re
        await file_input.set_input_files(temp_path)
        print("画像アップロード完了")
        await asyncio.sleep(3)

        # アップロード後のポップアップ確認
        popup_text = await page.evaluate("() => document.body.innerText.substring(0, 1000)")
        print(f"アップロード後のページテキスト:\n{popup_text[:500]}")

        # 搜索图片ボタン再チェック
        search_btn = await page.query_selector("div.search-btn")
        if not search_btn:
            search_btn = await page.query_selector(".search-btn")
        if search_btn:
            # imageIdキャプチャ設定
            captured_id = {"value": None}
            def on_req(request):
                if "imageId=" in request.url and not captured_id["value"]:
                    m = re.search(r"imageId=(\d+)", request.url)
                    if m:
                        captured_id["value"] = m.group(1)
            page.on("request", on_req)

            await search_btn.click()
            print("搜索图片ボタンクリック完了")

            for i in range(15):
                await asyncio.sleep(1)
                if captured_id["value"]:
                    break

            page.remove_listener("request", on_req)

            if captured_id["value"]:
                print(f"imageId取得成功: {captured_id['value']}")

                # pages-fastに直接アクセス
                pf_url = f"https://pages-fast.1688.com/wow/cbu/srch_rec/image_search/youyuan/index.html?tab=imageSearch&imageId={captured_id['value']}"
                print(f"pages-fast URL: {pf_url[:80]}...")

                await page.goto(pf_url, wait_until="domcontentloaded", timeout=30000)

                # 検索結果の読み込み待機
                for i in range(25):
                    await asyncio.sleep(1)
                    card_count = await page.evaluate(
                        '() => document.querySelectorAll(\'[class*="searchOfferWrapper"]\').length'
                    )
                    if card_count > 0:
                        print(f"searchOfferWrapper: {card_count}件 ({i+1}秒で検出)")
                        break
                    if i == 24:
                        print(f"searchOfferWrapper: 0件 (25秒待機後)")

                # 現在のURL
                final_url = page.url
                print(f"最終URL: {final_url}")

                # ページテキスト
                result_text = await page.evaluate("() => document.body.innerText.substring(0, 3000)")
                print(f"\n=== 検索結果ページのテキスト ===")
                print(result_text[:2000])

                # 代替セレクタチェック
                print("\n=== 検索結果ページの主要セレクタ ===")
                result_selectors = [
                    '[class*="searchOfferWrapper"]',
                    '[class*="offerWrapper"]',
                    '[class*="OfferWrapper"]',
                    '[class*="offer-card"]',
                    '[class*="offerCard"]',
                    '[class*="OfferCard"]',
                    '[class*="card-item"]',
                    '[class*="resultItem"]',
                    '[class*="ResultItem"]',
                    '[class*="product-item"]',
                    '[class*="productItem"]',
                    '[class*="imgSearchResult"]',
                    '[class*="searchResult"]',
                    '[class*="SearchResult"]',
                    '[data-renderkey]',
                    'a[href*="detail.1688.com"]',
                ]
                for sel in result_selectors:
                    count = await page.evaluate(
                        f'() => document.querySelectorAll(\'{sel}\').length'
                    )
                    if count > 0:
                        print(f"  {sel}: {count}件")
                    else:
                        print(f"  {sel}: 0件")

            else:
                print("imageId取得失敗")
                curr_url = page.url
                print(f"現在のURL: {curr_url}")
                text = await page.evaluate("() => document.body.innerText.substring(0, 1000)")
                print(f"ページテキスト:\n{text[:500]}")
        else:
            print("搜索图片ボタンが見つかりません")
    else:
        print("テスト画像DLまたはファイル入力なし")

    # クリーンアップ
    if temp_path and os.path.exists(temp_path):
        os.unlink(temp_path)
    await page.close()
    await bm.close()

asyncio.run(check())
