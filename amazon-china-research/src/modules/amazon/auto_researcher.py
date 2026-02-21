"""サジェスト再帰展開による自動リサーチエンジン v2

スコアベース優先探索でキーワード空間を探索:
1. シードキーワードをキューに入れる（初期スコア50）
2. 最高スコアのキーワードを取り出す（heapq）
3. Amazon suggestで派生キーワードを取得
4. 派生キーワードから「ビッグキーワード」を抽出してキューに追加
5. 元のキーワードでリサーチを実行
6. outcome.scoreで兄弟KWの優先度を更新
7. 商品タイトルから新シードを抽出してキューに追加
8. 停止条件（max_keywords / max_duration_minutes）に達するか、
   キューが空になるまで繰り返す
9. セッション終了時に統合レポート（HTML + Excel）を生成
"""
from __future__ import annotations

import heapq
import json
import logging
import re
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from src.modules.amazon.suggest import fetch_suggest_keywords

logger = logging.getLogger(__name__)


@dataclass
class AutoState:
    """自動リサーチの状態管理

    キーワード完了ごとにJSONへ保存し、Ctrl+Cや中断後に再開できる。
    """
    researched_keywords: set[str] = field(default_factory=set)
    queued_keywords: list[str] = field(default_factory=list)
    expanded_seeds: set[str] = field(default_factory=set)
    found_products: int = 0
    total_researched: int = 0
    started_at: str = ""
    last_keyword: str = ""
    # キーワードごとのリサーチ日時（cooldown用）
    keyword_timestamps: dict[str, str] = field(default_factory=dict)
    # キーワードごとのスコア（resume時に優先度キュー復元用）
    keyword_scores: dict[str, float] = field(default_factory=dict)

    def save(self, path: str | Path) -> None:
        """状態をJSONに保存"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "researched_keywords": sorted(self.researched_keywords),
            "queued_keywords": self.queued_keywords,
            "expanded_seeds": sorted(self.expanded_seeds),
            "found_products": self.found_products,
            "total_researched": self.total_researched,
            "started_at": self.started_at,
            "last_keyword": self.last_keyword,
            "keyword_timestamps": self.keyword_timestamps,
            "keyword_scores": self.keyword_scores,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> AutoState:
        """JSONから状態を復元"""
        path = Path(path)
        if not path.exists():
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(
                researched_keywords=set(data.get("researched_keywords", [])),
                queued_keywords=data.get("queued_keywords", []),
                expanded_seeds=set(data.get("expanded_seeds", [])),
                found_products=data.get("found_products", 0),
                total_researched=data.get("total_researched", 0),
                started_at=data.get("started_at", ""),
                last_keyword=data.get("last_keyword", ""),
                keyword_timestamps=data.get("keyword_timestamps", {}),
                keyword_scores=data.get("keyword_scores", {}),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"状態ファイルの読み込みに失敗、新規作成: {e}")
            return cls()

    @classmethod
    def reset(cls, path: str | Path) -> None:
        """状態ファイルを削除してリセット"""
        path = Path(path)
        if path.exists():
            path.unlink()
            print(f"[AUTO] 状態リセット: {path}")


def _load_known_asins(path: str | Path) -> set[str]:
    """過去にリサーチで発見済みのASINを読み込む"""
    path = Path(path)
    if not path.exists():
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("asins", []))
    except (json.JSONDecodeError, KeyError):
        return set()


def _save_known_asins(path: str | Path, asins: set[str]) -> None:
    """発見済みASINを永続保存"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"asins": sorted(asins)}, f, ensure_ascii=False, indent=2)


class AutoResearcher:
    """スコアベース優先探索による自動リサーチエンジン"""

    def __init__(self, browser, config):
        self.browser = browser
        self.config = config
        self.auto_config = config.auto
        self.state = AutoState.load(self.auto_config.state_file)
        # heapq: タプル(-score, insertion_order, keyword, depth)
        self._heap: list[tuple[float, int, str, int]] = []
        self._insertion_order: int = 0
        self._stop_requested = False
        self._start_time = time.time()
        # 枝刈り: 連続ゼロヒットカウント
        self._consecutive_zero_hits: int = 0
        # セッション蓄積データ
        self._session_data: list[dict] = []
        # ASIN重複排除用（過去セッションの既知ASINも含む）
        # known_asinsは常にプロジェクトのoutputディレクトリに保存（ジョブ間で共有）
        self._known_asins_path = Path(__file__).resolve().parent.parent.parent.parent / "output" / "known_asins.json"
        self._known_asins: set[str] = _load_known_asins(self._known_asins_path)
        self._seen_asins: set[str] = set()  # 今セッションで新規発見したASIN
        self._duplicate_count: int = 0  # 過去セッション被りカウント

    def _enqueue(self, keyword: str, depth: int, score: float = 50.0) -> None:
        """優先度キューにキーワードを追加"""
        heapq.heappush(
            self._heap,
            (-score, self._insertion_order, keyword, depth),
        )
        self._insertion_order += 1
        # スコアを記録（resume用）
        self.state.keyword_scores[keyword] = score

    def _dequeue(self) -> tuple[str, int, float] | None:
        """最高スコアのキーワードを取り出す"""
        while self._heap:
            neg_score, _, keyword, depth = heapq.heappop(self._heap)
            if not self._should_skip_keyword(keyword):
                return keyword, depth, -neg_score
        return None

    def _should_stop(self) -> bool:
        """停止条件チェック"""
        # max_keywords に到達
        max_kw = self.auto_config.max_keywords
        if max_kw > 0 and self.state.total_researched >= max_kw:
            print(f"[AUTO] 最大KW数（{max_kw}）に到達 → 停止")
            return True

        # max_duration_minutes に到達
        max_min = self.auto_config.max_duration_minutes
        if max_min > 0:
            elapsed_min = (time.time() - self._start_time) / 60
            if elapsed_min >= max_min:
                print(f"[AUTO] 最大時間（{max_min}分）に到達 → 停止")
                return True

        # max_candidates に到達
        max_cand = self.auto_config.max_candidates
        if max_cand > 0 and self.state.found_products >= max_cand:
            print(f"[AUTO] 候補商品上限（{max_cand}件）に到達 → 停止")
            return True

        return False

    async def run(
        self,
        seed_keywords: list[str],
        diagnose: bool = False,
        resume: bool = False,
    ) -> None:
        """メイン優先探索ループ

        Args:
            seed_keywords: 初期シードキーワード
            diagnose: 診断モード
            resume: 前回の状態から再開
        """
        self._setup_signal_handler()

        # 開始時刻の記録
        if not self.state.started_at:
            self.state.started_at = datetime.now().isoformat()

        # キューの初期化
        if resume and self.state.queued_keywords:
            # 前回の続きから再開（スコアを復元して優先度キュー再構築）
            for kw in self.state.queued_keywords:
                score = self.state.keyword_scores.get(kw, 50.0)
                self._enqueue(kw, 0, score)
            print(f"\n{'=' * 60}")
            print(f"自動リサーチモード再開（v2 スコア優先探索）")
            print(f"  前回からの未処理キュー: {len(self._heap)}件")
            print(f"  リサーチ済み: {self.state.total_researched}件")
            print(f"  発見商品: {self.state.found_products}件")
            print(f"{'=' * 60}")
        else:
            # 新規開始: シードキーワードをキューに追加
            for kw in seed_keywords:
                if not self._should_skip_keyword(kw):
                    self._enqueue(kw, 0, 50.0)
            print(f"\n{'=' * 60}")
            print(f"自動リサーチモード開始（v2 スコア優先探索）")
            print(f"  シード: {', '.join(seed_keywords)}")
            print(f"  最大深さ: {self.auto_config.max_depth}")
            max_kw = self.auto_config.max_keywords
            max_min = self.auto_config.max_duration_minutes
            if max_kw > 0:
                print(f"  最大KW数: {max_kw}")
            if max_min > 0:
                print(f"  最大時間: {max_min}分")
            print(f"{'=' * 60}")

        # 優先探索ループ
        while not self._stop_requested:
            # 停止条件チェック（max_keywords / max_duration_minutes）
            if self._should_stop():
                break

            # キューが空 → 追加キーワード生成を試みる
            if not self._heap:
                refilled = self._try_refill_queue()
                if not refilled:
                    print("[AUTO] 探索可能なキーワードがなくなりました")
                    break

            item = self._dequeue()
            if item is None:
                print("[AUTO] 有効なキーワードがキューにありません")
                break

            seed, depth, score = item

            # シードキーワード自体もリサーチ対象
            if not self._should_skip_keyword(seed):
                await self._run_single_research(
                    seed, self.state.total_researched + 1, diagnose
                )
                if self._stop_requested or self._should_stop():
                    break

            # サジェスト展開（深さ上限チェック）
            if seed not in self.state.expanded_seeds and depth < self.auto_config.max_depth:
                suggest_keywords = await self._expand_keyword(seed, depth)

                if suggest_keywords:
                    for suggest_kw in suggest_keywords:
                        if self._stop_requested or self._should_stop():
                            break
                        if self._should_skip_keyword(suggest_kw):
                            continue

                        await self._run_single_research(
                            suggest_kw, self.state.total_researched + 1, diagnose
                        )

                        if self._stop_requested:
                            break

            # 定期的に進捗表示
            if self.state.total_researched > 0 and self.state.total_researched % 10 == 0:
                self._print_progress()

        # セッション統合レポート生成
        if self._session_data:
            self._generate_session_report()

        # 新規発見ASINを永続保存（過去セッション被り検出用）
        if self._seen_asins:
            self._known_asins.update(self._seen_asins)
            _save_known_asins(self._known_asins_path, self._known_asins)
            print(f"[AUTO] 既知ASIN更新: {len(self._seen_asins)}件追加 → 合計{len(self._known_asins)}件")

        # 最終サマリー
        self._print_final_summary()

    async def _expand_keyword(self, seed: str, depth: int) -> list[str]:
        """キーワードをsuggestで展開し、新しいシードもキューに追加

        Args:
            seed: 展開するシードキーワード
            depth: 現在のBFS深さ

        Returns:
            サジェストキーワードのリスト（リサーチ対象）
        """
        print(f"\n[AUTO] シード展開: \"{seed}\" (深さ{depth})")

        suggestions = await fetch_suggest_keywords(seed)
        self.state.expanded_seeds.add(seed)

        if not suggestions:
            print(f"[AUTO]   サジェストなし")
            return []

        # サジェスト数制限
        suggestions = suggestions[:self.auto_config.max_suggests_per_seed]
        print(f"[AUTO]   → {len(suggestions)}件のサジェスト")

        # ビッグキーワードを抽出してキューに追加
        if depth + 1 < self.auto_config.max_depth:
            big_keywords = self._extract_big_keywords(suggestions, seed)
            new_bigs = []
            for bk in big_keywords[:self.auto_config.max_big_keywords_per_expand]:
                if not self._should_skip_keyword(bk) and bk not in self.state.expanded_seeds:
                    # 親のスコアを引き継ぐ（初期は50）
                    parent_score = self.state.keyword_scores.get(seed, 50.0)
                    self._enqueue(bk, depth + 1, parent_score)
                    new_bigs.append(bk)

            if new_bigs:
                print(f"[AUTO]   新規ビッグKW: {', '.join(new_bigs)}")

        print(f"[AUTO]   キュー: {len(self._heap)}件")

        # 状態保存（キュー状態を反映）
        self.state.queued_keywords = [kw for _, _, kw, _ in self._heap]
        self.state.save(self.auto_config.state_file)

        return suggestions

    def _extract_big_keywords(
        self, suggest_keywords: list[str], seed: str
    ) -> list[str]:
        """サジェスト結果からビッグキーワードを抽出

        "バンプラバー 車" → "車"
        "車 ステッカー" → "ステッカー"
        ルール: シード部分を除いた残りのトークンを抽出
        """
        big_keywords = []
        seen = set()
        seed_tokens = set(seed.split())

        for kw in suggest_keywords:
            tokens = kw.split()
            # シードのトークンを除いた残りを取得
            remaining = [t for t in tokens if t not in seed_tokens]
            if remaining:
                big = " ".join(remaining)
                if big not in seen and len(big) >= 2:
                    big_keywords.append(big)
                    seen.add(big)

        return big_keywords

    def _extract_title_keywords(self, outcome) -> list[str]:
        """フィルタ通過商品のタイトルからキーワードを抽出

        Args:
            outcome: KeywordResearchOutcome

        Returns:
            新しいシード候補キーワードのリスト（上位N件）
        """
        if not outcome.products_with_candidates:
            return []

        # 全タイトルからトークンを収集
        token_count: dict[str, int] = {}
        for prod_data in outcome.products_with_candidates:
            title = prod_data.get("amazon", {}).get("title", "")
            tokens = title.split()
            for token in tokens:
                # 1文字トークンを除外
                if len(token) < 2:
                    continue
                # 純英数字トークン（ブランド名の可能性）を除外
                if re.match(r'^[a-zA-Z0-9]+$', token):
                    continue
                # 数字のみを除外
                if re.match(r'^[\d,.]+$', token):
                    continue
                token_count[token] = token_count.get(token, 0) + 1

        if not token_count:
            return []

        # 頻出順にソート
        sorted_tokens = sorted(token_count.items(), key=lambda x: -x[1])

        # 既にリサーチ済み/キュー内のものを除外
        queued_set = {kw for _, _, kw, _ in self._heap}
        new_keywords = []
        for token, _ in sorted_tokens:
            if (
                token not in self.state.researched_keywords
                and token not in queued_set
                and not self._should_skip_keyword(token)
            ):
                new_keywords.append(token)
                if len(new_keywords) >= self.auto_config.max_title_keywords:
                    break

        return new_keywords

    def _should_skip_keyword(self, keyword: str) -> bool:
        """キーワードをスキップすべきか判定"""
        # 既にリサーチ済み
        if keyword in self.state.researched_keywords:
            return True

        # cooldown期間内にリサーチ済み
        if keyword in self.state.keyword_timestamps:
            last_time = datetime.fromisoformat(
                self.state.keyword_timestamps[keyword]
            )
            cooldown = timedelta(days=self.auto_config.keyword_cooldown_days)
            if datetime.now() - last_time < cooldown:
                return True

        # 空キーワード
        if not keyword.strip():
            return True

        # 禁止キーワードと完全一致
        keyword_lower = keyword.lower().strip()
        keyword_tokens = set(keyword_lower.split())
        for prohibited in self.config.filter.prohibited_keywords:
            if prohibited.lower() == keyword_lower or prohibited.lower() in keyword_tokens:
                return True

        # ブランド名と完全一致
        for brand in self.config.filter.excluded_brands:
            if brand.lower() == keyword_lower or brand.lower() in keyword_tokens:
                return True

        return False

    def _try_refill_queue(self) -> bool:
        """キューが空の時に追加キーワードを生成する

        Returns:
            True: キューに新しいキーワードが追加された
            False: これ以上生成できない
        """
        added = 0

        # 戦略1: リサーチ済みで良いスコアのKWからタイトルキーワードを再抽出
        for data in self._session_data:
            if data["score"] > 30:
                for prod in data["products"]:
                    title = prod.get("amazon", {}).get("title", "")
                    for token in title.split():
                        if len(token) < 2:
                            continue
                        if re.match(r'^[a-zA-Z0-9]+$', token):
                            continue
                        if (
                            token not in self.state.researched_keywords
                            and not self._should_skip_keyword(token)
                        ):
                            self._enqueue(token, 0, data["score"] * 0.8)
                            added += 1

        # 戦略2: 展開済みシードの深さを+1して再展開候補に
        expanded_list = list(self.state.expanded_seeds)
        for seed in expanded_list:
            score = self.state.keyword_scores.get(seed, 30.0)
            if score > 20:
                # シードのトークンを組み合わせて新しいキーワードを生成
                tokens = seed.split()
                for token in tokens:
                    if (
                        len(token) >= 2
                        and token not in self.state.researched_keywords
                        and not self._should_skip_keyword(token)
                    ):
                        self._enqueue(token, 0, score * 0.6)
                        added += 1

        if added > 0:
            print(f"[AUTO] キュー補充: {added}件の新規キーワードを追加")
            # 重複を排除するためheapifyし直し
            seen = set()
            deduped = []
            for entry in self._heap:
                kw = entry[2]
                if kw not in seen:
                    seen.add(kw)
                    deduped.append(entry)
            heapq.heapify(deduped)
            self._heap = deduped

        return added > 0

    async def _run_single_research(
        self, keyword: str, count: int, diagnose: bool
    ) -> None:
        """1つのキーワードでリサーチを実行"""
        from run_research import run_keyword_research

        print(f"\n[AUTO] [{count}] \"{keyword}\" リサーチ中...")

        try:
            outcome = await run_keyword_research(
                self.browser, keyword, self.config, diagnose=diagnose
            )

            found = len(outcome) if outcome else 0
            self.state.total_researched += 1
            self.state.researched_keywords.add(keyword)
            self.state.last_keyword = keyword
            self.state.keyword_timestamps[keyword] = datetime.now().isoformat()

            # スコア表示
            score = outcome.score if hasattr(outcome, 'score') else 0.0

            # セッションデータに蓄積（ASIN重複排除: セッション内 + 過去セッション）
            # 過去被りはレポートに記載するがカウントしない（is_duplicate=True）
            report_products = []
            if hasattr(outcome, 'products_with_candidates') and outcome.products_with_candidates:
                session_dup = 0
                history_dup = 0
                found_new = 0
                for p in outcome.products_with_candidates:
                    asin = p.get("amazon", {}).get("asin", "")
                    if not asin:
                        report_products.append(p)
                        found_new += 1
                        continue
                    if asin in self._seen_asins:
                        session_dup += 1
                        continue
                    if asin in self._known_asins:
                        history_dup += 1
                        self._duplicate_count += 1
                        p["is_duplicate"] = True
                        report_products.append(p)
                        title = p.get("amazon", {}).get("title", "")[:40]
                        print(f"[AUTO]   [過去被り] {asin} | {title}")
                        continue
                    self._seen_asins.add(asin)
                    report_products.append(p)
                    found_new += 1
                self.state.found_products += found_new
                if found > 0:
                    dup_parts = []
                    if session_dup > 0:
                        dup_parts.append(f"セッション内重複{session_dup}")
                    if history_dup > 0:
                        dup_parts.append(f"過去被り{history_dup}")
                    dup_msg = f" ({', '.join(dup_parts)}件除外)" if dup_parts else ""
                    print(f"[AUTO]   → {found_new}件の新規候補{dup_msg} (スコア: {score})")
                    self._consecutive_zero_hits = 0
                else:
                    print(f"[AUTO]   → 候補なし (スコア: {score})")
                    self._consecutive_zero_hits += 1
            else:
                print(f"[AUTO]   → 候補なし (スコア: {score})")
                self._consecutive_zero_hits += 1

            # all_filtered: フィルター通過全商品（候補なし含む）にもASIN重複チェック適用
            all_filtered_for_report = []
            if hasattr(outcome, 'all_filtered_products') and outcome.all_filtered_products:
                for p in outcome.all_filtered_products:
                    asin = p.get("amazon", {}).get("asin", "")
                    if not asin:
                        all_filtered_for_report.append(p)
                        continue
                    # 候補ありの商品は report_products で既に処理済み
                    has_cands = p.get("candidates") and len(p["candidates"]) > 0
                    if has_cands:
                        # report_products に含まれているものだけ追加
                        if any(rp.get("amazon", {}).get("asin") == asin for rp in report_products):
                            matching = next(rp for rp in report_products if rp.get("amazon", {}).get("asin") == asin)
                            all_filtered_for_report.append(matching)
                    else:
                        # 候補なし商品: セッション内重複のみスキップ
                        if asin in self._seen_asins or asin in self._known_asins:
                            continue
                        all_filtered_for_report.append(p)

            # Always record session data so total_searched is accurate
            # even when no candidates pass filters
            self._session_data.append({
                "keyword": keyword,
                "products": report_products,
                "all_filtered": all_filtered_for_report,
                "score": score,
                "total_searched": outcome.total_searched,
                "pass_count": outcome.pass_count,
                "filter_reasons": outcome.filter_reasons if hasattr(outcome, 'filter_reasons') else {},
            })

            # スコアに基づいてキュー内の兄弟KWの優先度を更新
            if hasattr(outcome, 'score') and outcome.score > 0:
                self._boost_siblings(keyword, outcome.score)

            # タイトルからキーワードを抽出して新シードとしてキューに追加
            if hasattr(outcome, 'products_with_candidates'):
                new_seeds = self._extract_title_keywords(outcome)
                if new_seeds:
                    for ns in new_seeds:
                        # 親のスコアを引き継ぐ
                        self._enqueue(ns, 0, max(score, 50.0))
                    print(f"[AUTO]   タイトルから新KW: {', '.join(new_seeds)}")

            # 枝刈り: 連続ゼロヒットが閾値を超えた場合
            if self._consecutive_zero_hits >= self.auto_config.dry_run_threshold:
                pruned = self._prune_low_score_entries()
                if pruned > 0:
                    print(f"[AUTO]   連続{self._consecutive_zero_hits}回ゼロヒット → "
                          f"低スコア{pruned}件を枝刈り")
                self._consecutive_zero_hits = 0

        except Exception as e:
            logger.error(f"[AUTO] リサーチエラー ({keyword}): {e}")
            print(f"[AUTO]   → エラー: {e}")
            # エラーでもリサーチ済みとして記録（無限リトライ防止）
            self.state.researched_keywords.add(keyword)
            self.state.total_researched += 1

        # 状態保存（キーワード完了ごと）
        self.state.queued_keywords = [kw for _, _, kw, _ in self._heap]
        self.state.save(self.auto_config.state_file)

    def _boost_siblings(self, keyword: str, score: float) -> None:
        """良いスコアのKWが見つかった場合、同一親シードの兄弟KWのスコアを上げる

        heapqは直接更新できないため、再構築する。
        """
        # キーワードのトークンを取得
        kw_tokens = set(keyword.split())
        if not kw_tokens:
            return

        new_heap = []
        for neg_score, order, kw, depth in self._heap:
            sibling_tokens = set(kw.split())
            # トークンが1つ以上共通なら兄弟とみなす
            if kw_tokens & sibling_tokens:
                # スコアをブースト（現在のスコアとoutcomeスコアの平均）
                old_score = -neg_score
                boosted = (old_score + score) / 2
                new_heap.append((-boosted, order, kw, depth))
                self.state.keyword_scores[kw] = boosted
            else:
                new_heap.append((neg_score, order, kw, depth))

        heapq.heapify(new_heap)
        self._heap = new_heap

    def _prune_low_score_entries(self) -> int:
        """低スコアのエントリをキューから除去"""
        if not self._heap:
            return 0

        # 平均スコアを算出
        scores = [-neg for neg, _, _, _ in self._heap]
        if not scores:
            return 0
        avg_score = sum(scores) / len(scores)

        # 平均未満を除去
        original_len = len(self._heap)
        new_heap = [
            entry for entry in self._heap
            if -entry[0] >= avg_score * 0.5  # 平均の50%未満を枝刈り
        ]
        heapq.heapify(new_heap)
        self._heap = new_heap

        return original_len - len(self._heap)

    def _generate_session_report(self) -> None:
        """セッション統合レポートを生成"""
        if not self._session_data:
            return

        elapsed = time.time() - self._start_time
        stats = {
            "total_keywords": self.state.total_researched,
            "total_candidates": sum(
                len(d["products"]) for d in self._session_data
            ),
            "elapsed_seconds": elapsed,
            "elapsed_str": self._format_elapsed(elapsed),
        }

        try:
            from pathlib import Path
            from src.output.session_report import SessionReportGenerator
            output_dir = str(Path(__file__).resolve().parent.parent.parent / "output")
            gen = SessionReportGenerator(output_dir=output_dir)
            html_path = gen.generate_html(self._session_data, stats)
            excel_path = gen.generate_excel(self._session_data, stats)
            print(f"\n[AUTO] 統合レポート生成:")
            print(f"  HTML: {html_path}")
            print(f"  Excel: {excel_path}")
        except Exception as e:
            logger.error(f"統合レポート生成エラー: {e}", exc_info=True)
            print(f"[AUTO] 統合レポート生成エラー: {e}")

    def _setup_signal_handler(self) -> None:
        """Ctrl+Cで安全停止するためのシグナルハンドラ"""
        def handler(sig, frame):
            if self._stop_requested:
                # 2回目のCtrl+Cで強制終了
                print("\n[AUTO] 強制停止")
                raise SystemExit(1)
            print("\n[AUTO] 停止リクエスト受信... 現在のキーワード完了後に停止します")
            self._stop_requested = True

        signal.signal(signal.SIGINT, handler)

    def _format_elapsed(self, elapsed: float) -> str:
        """経過時間をフォーマット"""
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        seconds = int(elapsed % 60)
        return f"{hours}時間{minutes:02d}分{seconds:02d}秒"

    def _print_progress(self) -> None:
        """進捗を表示"""
        elapsed = time.time() - self._start_time
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)

        print(f"\n--- 進捗 ---")
        print(
            f"[AUTO] リサーチ済み: {self.state.total_researched}件 | "
            f"発見: {self.state.found_products}件 | "
            f"キュー残: {len(self._heap)}件 | "
            f"セッション候補: {len(self._session_data)}KW | "
            f"経過: {hours}h{minutes:02d}m"
        )
        print(f"------------")

    def _print_final_summary(self) -> None:
        """最終サマリーを表示"""
        elapsed = time.time() - self._start_time

        print(f"\n{'=' * 60}")
        print(f"最終サマリー（v2 スコア優先探索）")
        print(f"  リサーチ済み: {self.state.total_researched}キーワード")
        print(f"  発見商品: {self.state.found_products}件（HTML確認待ち）")
        if self._duplicate_count > 0:
            print(f"  過去被り除外: {self._duplicate_count}件")
        print(f"  既知ASIN合計: {len(self._known_asins)}件")
        print(f"  キュー残: {len(self._heap)}件")
        print(f"  セッション候補KW: {len(self._session_data)}件")
        print(f"  経過時間: {self._format_elapsed(elapsed)}")

        if self._session_data:
            total_products = sum(len(d["products"]) for d in self._session_data)
            print(f"  統合レポート商品数: {total_products}件")
            # 上位3件のKWを表示
            sorted_data = sorted(self._session_data, key=lambda x: -x["score"])
            top_kws = sorted_data[:3]
            if top_kws:
                print(f"  上位KW:")
                for d in top_kws:
                    print(f"    {d['keyword']} (スコア: {d['score']}, 候補: {len(d['products'])}件)")

        if self._stop_requested and self._heap:
            print(f"\n  再開: python run_research.py --auto --resume")

        print(f"  状態: {self.auto_config.state_file}")
        print(f"{'=' * 60}")
