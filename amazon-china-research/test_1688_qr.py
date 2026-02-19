"""Test: Can headless Playwright capture 1688 QR code on VPS Docker?

Usage: python test_1688_qr.py
Output: saves screenshot to /app/output/test_1688_qr.png (Docker) or ./output/test_1688_qr.png (local)
"""
import asyncio
import base64
import sys
from pathlib import Path

async def test_qr():
    from playwright.async_api import async_playwright

    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    screenshot_path = output_dir / "test_1688_qr.png"

    print("[1/4] Launching headless Chromium...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )

        context = await browser.new_context(
            viewport={"width": 500, "height": 700},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )

        page = await context.new_page()

        print("[2/4] Navigating to 1688 login page...")
        try:
            await page.goto(
                "https://login.1688.com/member/signin.htm",
                wait_until="domcontentloaded",
                timeout=30000,
            )
        except Exception as e:
            print(f"  Navigation warning: {e}")

        print("[3/4] Waiting 5 seconds for QR code to render...")
        await asyncio.sleep(5)

        # Log page info
        print(f"  Current URL: {page.url}")
        title = await page.title()
        print(f"  Page title: {title}")

        # Check for common QR selectors
        for selector in [
            "img#J_QRCodeImg",
            "canvas",
            "#J_QRCodeImg",
            ".qrcode-img",
            "img[src*='qrcode']",
            ".login-qrcode",
            "#login-qrcode-img",
        ]:
            el = await page.query_selector(selector)
            if el:
                print(f"  Found element: {selector}")
                box = await el.bounding_box()
                if box:
                    print(f"    Size: {box['width']:.0f}x{box['height']:.0f} at ({box['x']:.0f},{box['y']:.0f})")

        print(f"[4/4] Taking screenshot -> {screenshot_path}")
        await page.screenshot(path=str(screenshot_path), full_page=True)

        # Also save as base64 for quick check
        screenshot_bytes = await page.screenshot(full_page=True)
        b64 = base64.b64encode(screenshot_bytes).decode()
        print(f"  Screenshot size: {len(screenshot_bytes)} bytes")
        print(f"  Base64 length: {len(b64)} chars")

        await browser.close()

    print(f"\nDone! Check {screenshot_path}")
    print("If QR code is visible in the screenshot, headless login will work.")
    return True

if __name__ == "__main__":
    asyncio.run(test_qr())
