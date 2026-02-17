"""ログ出力モジュール"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import get_config


def setup_logger(
    name: str = "amazon_china_research",
    log_dir: Optional[str | Path] = None,
    log_level: Optional[str] = None,
    console_output: bool = True,
    file_output: bool = True,
) -> logging.Logger:
    """ロガーをセットアップする

    Args:
        name: ロガー名
        log_dir: ログ出力ディレクトリ
        log_level: ログレベル（DEBUG, INFO, WARNING, ERROR）
        console_output: コンソール出力を有効にするか
        file_output: ファイル出力を有効にするか

    Returns:
        設定済みのロガー
    """
    config = get_config()

    if log_level is None:
        log_level = config.output.log_level

    if log_dir is None:
        base_dir = Path(__file__).parent.parent.parent
        log_dir = base_dir / "output" / "logs"

    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    # ルートロガーも設定（子ロガーに継承）
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # 名前付きロガーを取得
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # 既存のハンドラをクリア
    root_logger.handlers.clear()
    logger.handlers.clear()

    # フォーマッター
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # コンソールハンドラ（ルートロガーに追加）
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        # verboseモードの場合はDEBUGレベル、それ以外はINFO
        console_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        root_logger.addHandler(console_handler)

    # ファイルハンドラ（ルートロガーに追加）
    if file_output:
        timestamp = datetime.now().strftime("%Y%m%d")
        log_file = log_dir / f"research_{timestamp}.log"

        file_handler = logging.FileHandler(
            log_file,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        root_logger.addHandler(file_handler)

    return logger


class ProgressReporter:
    """進捗表示クラス"""

    def __init__(
        self,
        total: int,
        description: str = "処理中",
        logger: Optional[logging.Logger] = None,
    ):
        self.total = total
        self.current = 0
        self.description = description
        self.logger = logger or logging.getLogger(__name__)
        self._last_percentage = -1

    def update(self, current: Optional[int] = None, message: str = ""):
        """進捗を更新

        Args:
            current: 現在の処理数（省略時は1増加）
            message: 追加メッセージ
        """
        if current is not None:
            self.current = current
        else:
            self.current += 1

        percentage = int(self.current / self.total * 100) if self.total > 0 else 0

        # 10%刻みでログ出力
        if percentage // 10 > self._last_percentage // 10:
            self._last_percentage = percentage
            progress_bar = self._create_progress_bar(percentage)
            log_message = (
                f"{self.description}: {progress_bar} "
                f"{self.current}/{self.total} ({percentage}%)"
            )
            if message:
                log_message += f" - {message}"
            self.logger.info(log_message)

    def _create_progress_bar(self, percentage: int, width: int = 20) -> str:
        """プログレスバーを生成（ASCII文字使用）"""
        filled = int(width * percentage / 100)
        bar = "#" * filled + "-" * (width - filled)
        return f"[{bar}]"

    def complete(self, message: str = "完了"):
        """完了を報告"""
        self.current = self.total
        progress_bar = self._create_progress_bar(100)
        self.logger.info(
            f"{self.description}: {progress_bar} "
            f"{self.total}/{self.total} (100%) - {message}"
        )


class ResearchStats:
    """リサーチ統計"""

    def __init__(self):
        self.total_searched = 0
        self.total_filtered = 0
        self.total_matched = 0
        self.total_profitable = 0
        self.errors = 0
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None

    def start(self):
        """統計開始"""
        self.start_time = datetime.now()

    def finish(self):
        """統計終了"""
        self.end_time = datetime.now()

    @property
    def elapsed_time(self) -> float:
        """経過時間（秒）"""
        if self.start_time is None:
            return 0
        end = self.end_time or datetime.now()
        return (end - self.start_time).total_seconds()

    def to_dict(self) -> dict:
        """辞書に変換"""
        return {
            "total_searched": self.total_searched,
            "total_filtered": self.total_filtered,
            "total_matched": self.total_matched,
            "total_profitable": self.total_profitable,
            "errors": self.errors,
            "elapsed_seconds": self.elapsed_time,
        }

    def summary(self) -> str:
        """サマリー文字列を生成"""
        return (
            f"=== リサーチ統計 ===\n"
            f"検索商品数: {self.total_searched}\n"
            f"フィルタ通過: {self.total_filtered}\n"
            f"1688マッチ: {self.total_matched}\n"
            f"利益商品: {self.total_profitable}\n"
            f"エラー: {self.errors}\n"
            f"処理時間: {self.elapsed_time:.1f}秒"
        )
