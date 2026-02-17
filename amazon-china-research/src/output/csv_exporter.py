"""CSV出力モジュール"""
from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..models.result import ResearchResult
from ..config import get_config

logger = logging.getLogger(__name__)


class CsvExporter:
    """CSV出力を行う

    UTF-8 BOM形式でExcel対応のCSVを出力する。
    """

    # CSVヘッダー（日本語）
    HEADERS = [
        "ASIN",
        "商品タイトル",
        "Amazon価格（円）",
        "レビュー数",
        "評価",
        "BSR",
        "カテゴリ",
        "FBA",
        "Amazon URL",
        "1688価格（元）",
        "1688価格（円）",
        "1688店舗",
        "1688 URL",
        "仕入原価（円）",
        "国際送料（円）",
        "関税（円）",
        "紹介料（円）",
        "FBA手数料（円）",
        "総コスト（円）",
        "利益（円）",
        "利益率（%）",
        "推定月間販売数",
        "推定月間売上（円）",
        "推定月間利益（円）",
        "リサーチスコア",
    ]

    def __init__(
        self,
        output_dir: Optional[str | Path] = None,
        encoding: Optional[str] = None,
    ):
        config = get_config()

        if output_dir is None:
            base_dir = Path(__file__).parent.parent.parent
            output_dir = base_dir / "output" / "results"

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.encoding = encoding or config.output.csv_encoding

    def export(
        self,
        results: list[ResearchResult],
        keyword: str,
        filename: Optional[str] = None,
    ) -> Path:
        """リサーチ結果をCSVに出力

        Args:
            results: リサーチ結果リスト
            keyword: 検索キーワード（ファイル名に使用）
            filename: 出力ファイル名（省略時は自動生成）

        Returns:
            出力ファイルのパス
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # キーワードから使用不可文字を除去
            safe_keyword = "".join(
                c for c in keyword if c.isalnum() or c in ('_', '-', ' ')
            ).strip().replace(' ', '_')
            filename = f"research_{safe_keyword}_{timestamp}.csv"

        filepath = self.output_dir / filename

        # CSVを書き出し
        with open(filepath, "w", encoding=self.encoding, newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.HEADERS)
            writer.writeheader()

            for result in results:
                row = result.to_csv_row()
                # ヘッダーに合わせてキーを変換
                csv_row = {
                    "ASIN": row.get("ASIN", ""),
                    "商品タイトル": row.get("商品タイトル", ""),
                    "Amazon価格（円）": row.get("Amazon価格（円）", 0),
                    "レビュー数": row.get("レビュー数", 0),
                    "評価": row.get("評価", ""),
                    "BSR": row.get("BSR", 0),
                    "カテゴリ": row.get("カテゴリ", ""),
                    "FBA": row.get("FBA", ""),
                    "Amazon URL": row.get("Amazon URL", ""),
                    "1688価格（元）": row.get("1688価格（元）", 0),
                    "1688価格（円）": row.get("1688価格（円）", 0),
                    "1688店舗": row.get("1688店舗", ""),
                    "1688 URL": row.get("1688 URL", ""),
                    "仕入原価（円）": row.get("仕入原価（円）", 0),
                    "国際送料（円）": row.get("国際送料（円）", 0),
                    "関税（円）": row.get("関税（円）", 0),
                    "紹介料（円）": row.get("紹介料（円）", 0),
                    "FBA手数料（円）": row.get("FBA手数料（円）", 0),
                    "総コスト（円）": row.get("総コスト（円）", 0),
                    "利益（円）": row.get("利益（円）", 0),
                    "利益率（%）": row.get("利益率（%）", 0),
                    "推定月間販売数": row.get("推定月間販売数", 0),
                    "推定月間売上（円）": row.get("推定月間売上（円）", 0),
                    "推定月間利益（円）": row.get("推定月間利益（円）", 0),
                    "リサーチスコア": row.get("リサーチスコア", 0),
                }
                writer.writerow(csv_row)

        logger.info(f"CSV出力完了: {filepath} ({len(results)}件)")
        return filepath

    def export_summary(
        self,
        results: list[ResearchResult],
        keyword: str,
        filename: Optional[str] = None,
    ) -> Path:
        """サマリーCSVを出力（簡易版）

        Args:
            results: リサーチ結果リスト
            keyword: 検索キーワード
            filename: 出力ファイル名

        Returns:
            出力ファイルのパス
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_keyword = "".join(
                c for c in keyword if c.isalnum() or c in ('_', '-', ' ')
            ).strip().replace(' ', '_')
            filename = f"summary_{safe_keyword}_{timestamp}.csv"

        filepath = self.output_dir / filename

        summary_headers = [
            "ASIN",
            "商品タイトル",
            "Amazon価格",
            "1688価格（円）",
            "利益",
            "利益率",
            "月間利益予測",
            "スコア",
        ]

        with open(filepath, "w", encoding=self.encoding, newline="") as f:
            writer = csv.DictWriter(f, fieldnames=summary_headers)
            writer.writeheader()

            for result in results:
                writer.writerow({
                    "ASIN": result.amazon_product.asin,
                    "商品タイトル": result.amazon_product.title[:50] + "...",
                    "Amazon価格": f"¥{result.amazon_product.price:,}",
                    "1688価格（円）": f"¥{result.alibaba_product.price_jpy:,}",
                    "利益": f"¥{result.profit_result.profit:,}",
                    "利益率": f"{result.profit_result.profit_rate_percentage:.1f}%",
                    "月間利益予測": f"¥{result.estimated_monthly_profit:,}",
                    "スコア": f"{result.score:.1f}",
                })

        logger.info(f"サマリーCSV出力完了: {filepath}")
        return filepath
