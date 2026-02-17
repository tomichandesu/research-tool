"""FBAシミュレーターからサイズ・重量を取得するモジュール

セラーセントラルにログイン済みの状態で使用する。
商品ページでサイズが取得できない場合のフォールバックとして利用。
"""
from __future__ import annotations

import logging
import re
from typing import Optional
from dataclasses import dataclass

from playwright.async_api import Page

from ...utils.browser import BrowserManager

logger = logging.getLogger(__name__)


@dataclass
class ProductDimensions:
    """商品サイズ・重量データ"""
    length: float  # 長さ (cm)
    width: float   # 幅 (cm)
    height: float  # 高さ (cm)
    weight_kg: float  # 重量 (kg)

    @property
    def dimensions_tuple(self) -> tuple[float, float, float]:
        """寸法をタプルで返す"""
        return (self.length, self.width, self.height)

    @property
    def dimensions_sum(self) -> float:
        """寸法の合計を返す"""
        return self.length + self.width + self.height


class FbaSimulator:
    """FBAシミュレーターからサイズ・重量を取得する

    専用ページを1つ開いて使い回す。初回に1度だけサインインを処理する。
    """

    SIMULATOR_URL = "https://sellercentral.amazon.co.jp/fba/profitabilitycalculator/index"

    def __init__(self, browser: BrowserManager):
        self.browser = browser
        self._page: Optional[Page] = None
        self._ready = False

    async def _ensure_page(self) -> Optional[Page]:
        """FBAシミュレーター専用ページを準備する（初回のみ）"""
        if self._page and self._ready:
            return self._page

        try:
            # 専用ページを作成
            self._page = await self.browser.new_page()
            await self._page.goto(self.SIMULATOR_URL, wait_until="domcontentloaded", timeout=30000)
            await self._page.wait_for_timeout(3000)

            # サインインが求められた場合の処理
            await self._handle_signin_prompt(self._page)

            # ログインページにリダイレクトされた場合
            if "signin" in self._page.url.lower() or "ap/signin" in self._page.url.lower():
                logger.warning("セラーセントラルにログインされていません。FBAシミュレーターをスキップします。")
                await self._page.close()
                self._page = None
                return None

            self._ready = True
            logger.info("FBAシミュレーター準備完了")
            return self._page

        except Exception as e:
            logger.error(f"FBAシミュレーター準備エラー: {e}")
            if self._page:
                await self._page.close()
                self._page = None
            return None

    async def _handle_signin_prompt(self, page: Page) -> None:
        """サインイン/ゲストの選択画面を処理する"""
        try:
            # 「サインイン」ボタンを探してクリック
            signin_selectors = [
                'a:has-text("サインイン")',
                'button:has-text("サインイン")',
                'a:has-text("Sign in")',
                'button:has-text("Sign in")',
                'a[href*="signin"]',
                '#signin-button',
                '.signin-button',
            ]

            for selector in signin_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element and await element.is_visible():
                        logger.info(f"サインインボタンをクリック: {selector}")
                        await element.click()
                        await page.wait_for_timeout(5000)

                        # サインイン後にシミュレーターに戻っているか確認
                        if "profitabilitycalculator" in page.url.lower():
                            logger.info("サインイン成功、FBAシミュレーターに戻りました")
                            return
                        elif "signin" in page.url.lower():
                            # ログインページに飛ばされた → 永続コンテキストのクッキーで自動ログインを待つ
                            await page.wait_for_timeout(5000)
                            if "profitabilitycalculator" not in page.url.lower():
                                # 自動ログインされなかった → シミュレーターに戻る
                                await page.goto(self.SIMULATOR_URL, wait_until="domcontentloaded", timeout=30000)
                                await page.wait_for_timeout(3000)
                        return
                except Exception:
                    continue

            # ゲストモードを回避: シミュレーターページが表示されていればOK
            if "profitabilitycalculator" in page.url.lower():
                return

        except Exception as e:
            logger.debug(f"サインインプロンプト処理: {e}")

    async def close(self) -> None:
        """専用ページを閉じる"""
        if self._page:
            try:
                await self._page.close()
            except Exception:
                pass
            self._page = None
            self._ready = False

    async def get_dimensions(self, asin: str, page: Page = None) -> Optional[ProductDimensions]:
        """ASINからサイズ・重量を取得

        Args:
            asin: Amazon商品ID
            page: 未使用（後方互換のため残す）

        Returns:
            ProductDimensions: サイズ・重量データ、取得失敗時はNone
        """
        try:
            logger.info(f"FBAシミュレーターでサイズ取得: {asin}")

            # 専用ページを取得（初回は準備、2回目以降は使い回し）
            sim_page = await self._ensure_page()
            if not sim_page:
                return None

            # ASIN入力フィールドを探す
            asin_input = await self._find_asin_input(sim_page)
            if not asin_input:
                logger.warning("ASIN入力フィールドが見つかりません")
                return None

            # ASIN入力（前回の値をクリアしてから）
            await asin_input.fill("")
            await asin_input.fill(asin)

            # 検索ボタンをクリック
            search_button = await self._find_search_button(sim_page)
            if search_button:
                await search_button.click()
            else:
                await asin_input.press("Enter")

            # 結果の読み込み待機
            await sim_page.wait_for_timeout(3000)

            # サイズ・重量を抽出
            dimensions = await self._extract_dimensions(sim_page)

            if dimensions:
                logger.info(
                    f"サイズ取得成功: {asin} - "
                    f"{dimensions.length}x{dimensions.width}x{dimensions.height}cm, "
                    f"{dimensions.weight_kg}kg"
                )
            else:
                logger.warning(f"サイズ取得失敗: {asin}")

            return dimensions

        except Exception as e:
            logger.error(f"FBAシミュレーターエラー: {asin} - {e}")
            # ページが壊れた場合はリセット
            self._ready = False
            return None

    async def _find_asin_input(self, page: Page):
        """ASIN入力フィールドを探す"""
        selectors = [
            'input[name="asin"]',
            'input[id*="asin"]',
            'input[placeholder*="ASIN"]',
            'input[aria-label*="ASIN"]',
            '#search-input',
            'input[type="text"]',
        ]

        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    return element
            except Exception:
                continue

        return None

    async def _find_search_button(self, page: Page):
        """検索ボタンを探す"""
        selectors = [
            'button[type="submit"]',
            'button:has-text("検索")',
            'button:has-text("Search")',
            'input[type="submit"]',
            '#search-button',
            'button[aria-label*="search"]',
        ]

        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    return element
            except Exception:
                continue

        return None

    async def _extract_dimensions(self, page: Page) -> Optional[ProductDimensions]:
        """ページからサイズ・重量を抽出"""
        try:
            # ページ全体のテキストを取得
            content = await page.content()

            # サイズパターンを検索
            # パターン1: 「30 x 20 x 10 cm」
            dims_match = re.search(
                r'(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*cm',
                content,
                re.IGNORECASE
            )

            # パターン2: 「30 cm x 20 cm x 10 cm」
            if not dims_match:
                dims_match = re.search(
                    r'(\d+(?:\.\d+)?)\s*cm\s*[x×]\s*(\d+(?:\.\d+)?)\s*cm\s*[x×]\s*(\d+(?:\.\d+)?)\s*cm',
                    content,
                    re.IGNORECASE
                )

            # 重量パターンを検索
            # パターン1: 「1.5 kg」
            weight_match = re.search(
                r'(?:重量|weight)[：:\s]*(\d+(?:\.\d+)?)\s*kg',
                content,
                re.IGNORECASE
            )

            # パターン2: 「500 g」
            if not weight_match:
                weight_match_g = re.search(
                    r'(?:重量|weight)[：:\s]*(\d+(?:\.\d+)?)\s*g(?:ram)?',
                    content,
                    re.IGNORECASE
                )
                if weight_match_g:
                    weight_kg = float(weight_match_g.group(1)) / 1000
                else:
                    weight_kg = None
            else:
                weight_kg = float(weight_match.group(1))

            # パターン3: 重量がテーブルセル内にある場合
            if weight_kg is None:
                weight_cells = await page.query_selector_all('td, span, div')
                for cell in weight_cells:
                    text = await cell.inner_text()
                    if text:
                        kg_match = re.search(r'(\d+(?:\.\d+)?)\s*kg', text, re.IGNORECASE)
                        if kg_match:
                            weight_kg = float(kg_match.group(1))
                            break
                        g_match = re.search(r'(\d+(?:\.\d+)?)\s*g(?:ram)?', text, re.IGNORECASE)
                        if g_match and 'kg' not in text.lower():
                            weight_kg = float(g_match.group(1)) / 1000
                            break

            if dims_match:
                return ProductDimensions(
                    length=float(dims_match.group(1)),
                    width=float(dims_match.group(2)),
                    height=float(dims_match.group(3)),
                    weight_kg=weight_kg or 0.5,  # デフォルト0.5kg
                )

            # サイズがセル内にある場合を試行
            dimension_data = await self._extract_dimensions_from_table(page)
            if dimension_data:
                return dimension_data

            return None

        except Exception as e:
            logger.error(f"サイズ抽出エラー: {e}")
            return None

    async def _extract_dimensions_from_table(self, page: Page) -> Optional[ProductDimensions]:
        """テーブルからサイズ・重量を抽出"""
        try:
            # 商品情報が表示されるエリアを探す
            info_selectors = [
                '#product-info',
                '.product-details',
                '[data-testid="product-info"]',
                '.fba-calculator-result',
            ]

            for selector in info_selectors:
                element = await page.query_selector(selector)
                if element:
                    text = await element.inner_text()

                    # サイズ抽出
                    dims_match = re.search(
                        r'(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)',
                        text
                    )

                    # 重量抽出
                    weight_match = re.search(r'(\d+(?:\.\d+)?)\s*kg', text, re.IGNORECASE)
                    weight_kg = float(weight_match.group(1)) if weight_match else 0.5

                    if dims_match:
                        return ProductDimensions(
                            length=float(dims_match.group(1)),
                            width=float(dims_match.group(2)),
                            height=float(dims_match.group(3)),
                            weight_kg=weight_kg,
                        )

            return None

        except Exception:
            return None


async def get_dimensions_with_fallback(
    browser: BrowserManager,
    page: Page,
    asin: str,
    current_dimensions: Optional[tuple[float, float, float]],
    current_weight: Optional[float],
    simulator: Optional[FbaSimulator] = None,
) -> tuple[Optional[tuple[float, float, float]], Optional[float]]:
    """商品ページでサイズが取れない場合、FBAシミュレーターで取得

    Args:
        browser: ブラウザマネージャー
        page: Playwrightページ（未使用、後方互換のため残す）
        asin: 商品ASIN
        current_dimensions: 商品ページで取得した寸法（あれば）
        current_weight: 商品ページで取得した重量（あれば）
        simulator: FbaSimulatorインスタンス（使い回し推奨）

    Returns:
        (dimensions, weight_kg): 寸法タプルと重量
    """
    # すでに両方取得できていればそのまま返す
    if current_dimensions is not None and current_weight is not None:
        return current_dimensions, current_weight

    # FBAシミュレーターで取得を試みる
    sim = simulator or FbaSimulator(browser)
    result = await sim.get_dimensions(asin)

    if result:
        dimensions = current_dimensions or result.dimensions_tuple
        weight = current_weight or result.weight_kg
        return dimensions, weight

    # 取得できなければ元の値を返す
    return current_dimensions, current_weight
