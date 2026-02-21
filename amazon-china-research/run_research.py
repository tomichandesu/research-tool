#!/usr/bin/env python
"""Amazon-1688 中国製品リサーチツール

使用方法:
    python run_research.py "キーワード"
    python run_research.py "キーワード1" "キーワード2" "キーワード3"
    python run_research.py --file keywords.txt
    python run_research.py --suggest "貯金箱"
    python run_research.py --finalize selections.json
    python run_research.py --auto "バンプラバー"
    python run_research.py --auto --resume

オプション:
    --file: キーワードファイル（1行1キーワード）
    --suggest: サジェストキーワードを自動展開してリサーチ
    --auto: 自動リサーチモード（サジェスト再帰展開）
    --resume: 前回の自動リサーチを再開
    --auto-reset: 自動リサーチの状態をリセット
    --diagnose: 診断モード（各段階の除外理由を詳細出力）
    --finalize: HTML候補レビュー後のJSONから最終Excelを生成
    --debug: デバッグモード（ブラウザ表示）
"""
from __future__ import annotations

import argparse
import asyncio
import io
import logging
import sys
from pathlib import Path

# Windows cp932環境で中国語テキスト出力時のエラーを防止
if sys.platform == "win32":
    import ctypes
    ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    ctypes.windll.kernel32.SetConsoleCP(65001)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
if sys.stdin and sys.stdin.encoding and sys.stdin.encoding.lower() != "utf-8":
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent))

from src.utils.browser import BrowserManager
from src.utils.auth import AuthManager
from src.config import get_config

# ロガー設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 中国輸入スコアリング & タイトル関連度
# ---------------------------------------------------------------------------

import re as _re

# 日本の産地・地名（これが含まれていたら日本製 → 除外）
_JAPAN_PLACE_NAMES = [
    # だるま・伝統工芸
    "高崎", "会津",
    # タオル・繊維
    "今治", "泉州",
    # 金属加工
    "燕三条", "燕", "三条",
    # 陶磁器・焼物
    "有田", "波佐見", "美濃", "瀬戸", "信楽", "九谷", "益子", "常滑",
    "備前", "伊万里", "小石原", "笠間", "丹波", "薩摩", "萩",
    "清水焼", "京焼", "万古焼", "砥部", "唐津",
    # 漆器・木工
    "輪島", "山中", "越前", "木曽", "秋田",
    # ガラス・切子
    "江戸切子", "津軽",
    # 鉄器
    "南部鉄",
    # 刃物
    "堺", "関", "土佐",
    # 織物・染物
    "西陣", "博多", "琉球", "大島", "結城",
    # 和紙
    "美濃和紙", "越前和紙", "土佐和紙",
]

# 日本製を示すキーワード（含まれていたら除外）
_JAPAN_MADE_KEYWORDS = [
    # 直接的な表現
    "日本製", "国産", "made in japan", "メイドインジャパン",
    # お土産・文化
    "日本のお土産", "japanese souvenir", "japan souvenir",
    "日本土産", "和雑貨",
    # 伝統・工芸
    "日本伝統", "伝統工芸", "伝統的工芸品", "経済産業大臣指定",
    "職人手作り", "職人が作", "匠の技", "老舗",
    # 和素材
    "和紙", "漆塗", "桐箱入", "竹細工",
    # 日本文化品
    "着物", "浴衣", "草履", "下駄", "風呂敷", "手ぬぐい",
    # 英語表現
    "traditional japanese", "handmade in japan",
    "authentic japanese", "genuine japanese",
]


def _is_japan_made(title: str) -> bool:
    """日本製の商品かどうかを判定。Trueなら1688検索をスキップ。"""
    title_lower = title.lower()

    for place in _JAPAN_PLACE_NAMES:
        if place in title:
            return True

    for kw in _JAPAN_MADE_KEYWORDS:
        if kw in title_lower:
            return True

    # 「○○焼」パターン（有田焼、九谷焼、信楽焼 等）
    if _re.search(r'[\u4e00-\u9fff]{1,4}焼', title):
        return True

    return False


def _estimate_china_import_score(title: str, seller_name: str | None = None) -> float:
    """Amazon商品が中国輸入品である可能性をスコアリング (0.0〜1.0)

    高い = 中国輸入の可能性高い（1688にある可能性高い）
    低い = 不明（ただし日本製は _is_japan_made で事前に除外済み）
    """
    if _is_japan_made(title):
        return 0.0  # 日本製 → 除外対象

    score = 0.5  # デフォルト: 不明

    # --- 中国輸入の可能性を上げる要因 ---
    # タイトル先頭が英字ブランド名（例: "NOELAMOUR だるま..."）
    brand_match = _re.match(r'^([A-Za-z][A-Za-z0-9&\-\'\.]{1,25})\s', title)
    if brand_match:
        brand = brand_match.group(1).lower()
        # 有名な日本/海外ブランドは除外
        _known_brands = {
            "amazon", "sony", "panasonic", "sharp", "toshiba", "hitachi",
            "canon", "nikon", "toyota", "honda", "yamaha", "casio",
            "apple", "samsung", "lg", "philips", "braun",
        }
        if brand not in _known_brands:
            score += 0.25

    # 販売元に ".jp" ドメイン（中国セラーに多い）
    if seller_name:
        seller_lower = seller_name.lower()
        if _re.search(r'[a-z0-9]+\.jp', seller_lower):
            score += 0.1

    return max(0.0, min(1.0, score))


def _compute_title_relevance(amazon_title: str, alibaba_title: str) -> float:
    """Amazon商品タイトルと1688候補タイトルの関連度 (0.0〜1.0)

    タイトルのキーワードが全く被らない場合は別商品の可能性が高い。
    """
    if not amazon_title or not alibaba_title:
        return 0.5  # 判定不能の場合は中立

    # 日本語・中国語の単語（2文字以上の漢字/ひらがな/カタカナの連続）を抽出
    word_pattern = _re.compile(r'[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]{2,}')
    amazon_words = set(word_pattern.findall(amazon_title))
    alibaba_words = set(word_pattern.findall(alibaba_title))

    # 一般的すぎる単語を除外
    _filler = {"です", "ます", "する", "した", "ある", "ない", "この", "その",
               "もの", "ため", "から", "まで", "ところ", "こと", "について"}
    amazon_words -= _filler
    alibaba_words -= _filler

    if not amazon_words:
        return 0.5

    # 完全一致チェック
    common = amazon_words & alibaba_words
    if common:
        return min(1.0, len(common) / len(amazon_words) + 0.3)

    # 部分一致チェック（「だるま」が「だるまさん」に含まれる等）
    substring_matches = 0
    for aw in amazon_words:
        if len(aw) >= 2:
            for bw in alibaba_words:
                if aw in bw or bw in aw:
                    substring_matches += 1
                    break

    if substring_matches > 0:
        return min(1.0, substring_matches / len(amazon_words) + 0.2)

    return 0.0


# ---------------------------------------------------------------------------
# 禁止キーワード / 除外ブランドのカテゴリ分類（UI教育表示用）
# ---------------------------------------------------------------------------
_PROHIBITED_KW_TO_CATEGORY = {
    # ファッション・アクセサリー
    "ピアス": "fashion", "イヤリング": "fashion", "ネックレス": "fashion",
    "ブレスレット": "fashion", "指輪": "fashion", "ダイヤ": "fashion",
    "宝石": "fashion", "ジュエリー": "fashion", "バッグ": "fashion",
    "カバン": "fashion", "鞄": "fashion", "ポーチ": "fashion",
    "財布": "fashion", "帽子": "fashion", "靴": "fashion",
    "サンダル": "fashion", "スニーカー": "fashion", "Tシャツ": "fashion",
    "パンツ": "fashion", "スカート": "fashion", "ドレス": "fashion",
    "コート": "fashion", "ジャケット": "fashion",
    # 飲食・サプリ
    "食品": "food", "お菓子": "food", "飲料": "food",
    "サプリ": "food", "サプリメント": "food", "プロテイン": "food",
    "ビタミン": "food",
    # 食品衛生法（口に触れるもの）
    "食器": "food_hygiene", "お皿": "food_hygiene", "茶碗": "food_hygiene",
    "コップ": "food_hygiene", "グラス": "food_hygiene", "マグカップ": "food_hygiene",
    "箸": "food_hygiene", "スプーン": "food_hygiene", "フォーク": "food_hygiene",
    "ナイフ": "food_hygiene", "弁当箱": "food_hygiene", "水筒": "food_hygiene",
    "哺乳瓶": "food_hygiene", "おしゃぶり": "food_hygiene",
    "歯固め": "food_hygiene", "ベビー食器": "food_hygiene",
    # PSE対象（電気用品）
    "充電器": "pse", "ACアダプター": "pse", "電源アダプター": "pse",
    "コンセント": "pse", "延長コード": "pse", "電源タップ": "pse",
    "モバイルバッテリー": "pse", "バッテリー充電": "pse",
    "USB充電": "pse", "ワイヤレス充電": "pse",
    # 乳幼児向け（食品衛生法・ST基準）
    "乳児": "baby", "幼児": "baby", "0歳": "baby", "1歳": "baby",
    "2歳": "baby", "3歳": "baby", "ベビー玩具": "baby",
    "赤ちゃん用": "baby", "ベビー用": "baby", "知育玩具": "baby",
    # 日本製
    "日本製": "japan_made", "MADE IN JAPAN": "japan_made",
    "国産": "japan_made", "日本産": "japan_made",
    "日本国内生産": "japan_made", "日本国内製造": "japan_made",
    # アダルト
    "アダルト": "adult", "大人のおもちゃ": "adult", "セクシー": "adult",
    "ランジェリー": "adult", "下着": "adult", "コスプレ衣装": "adult",
    # その他規制
    "医療": "regulated", "薬": "regulated", "レーザー": "regulated",
    "電子タバコ": "regulated", "vape": "regulated", "CBD": "regulated",
}

_BRAND_TO_CATEGORY = {
    # スポーツブランド
    "Nike": "brand_sports", "ナイキ": "brand_sports",
    "adidas": "brand_sports", "アディダス": "brand_sports",
    "PUMA": "brand_sports", "プーマ": "brand_sports",
    "New Balance": "brand_sports", "ニューバランス": "brand_sports",
    "UNDER ARMOUR": "brand_sports", "アンダーアーマー": "brand_sports",
    "Reebok": "brand_sports", "リーボック": "brand_sports",
    "ASICS": "brand_sports", "アシックス": "brand_sports",
    "MIZUNO": "brand_sports", "ミズノ": "brand_sports",
    "FILA": "brand_sports", "フィラ": "brand_sports",
    "Converse": "brand_sports", "コンバース": "brand_sports",
    "VANS": "brand_sports", "バンズ": "brand_sports",
    # ラグジュアリー
    "GUCCI": "brand_luxury", "グッチ": "brand_luxury",
    "Louis Vuitton": "brand_luxury", "ルイヴィトン": "brand_luxury",
    "CHANEL": "brand_luxury", "シャネル": "brand_luxury",
    "HERMES": "brand_luxury", "エルメス": "brand_luxury",
    "PRADA": "brand_luxury", "プラダ": "brand_luxury",
    "COACH": "brand_luxury", "コーチ": "brand_luxury",
    "Burberry": "brand_luxury", "バーバリー": "brand_luxury",
    "Supreme": "brand_luxury", "シュプリーム": "brand_luxury",
    "THE NORTH FACE": "brand_luxury", "ノースフェイス": "brand_luxury",
    "Patagonia": "brand_luxury", "パタゴニア": "brand_luxury",
    "Columbia": "brand_luxury", "コロンビア": "brand_luxury",
    "RALPH LAUREN": "brand_luxury", "ラルフローレン": "brand_luxury",
    "Calvin Klein": "brand_luxury", "カルバンクライン": "brand_luxury",
    "Tommy Hilfiger": "brand_luxury", "トミーヒルフィガー": "brand_luxury",
    # キャラクター・著作権
    "Disney": "brand_character", "ディズニー": "brand_character",
    "ミッキー": "brand_character", "ミニー": "brand_character",
    "プーさん": "brand_character", "アナと雪の女王": "brand_character",
    "Marvel": "brand_character", "マーベル": "brand_character",
    "アベンジャーズ": "brand_character", "スパイダーマン": "brand_character",
    "DC Comics": "brand_character", "バットマン": "brand_character",
    "スーパーマン": "brand_character",
    "POKEMON": "brand_character", "ポケモン": "brand_character",
    "ピカチュウ": "brand_character",
    "Nintendo": "brand_character", "任天堂": "brand_character",
    "マリオ": "brand_character", "ゼルダ": "brand_character",
    "Sanrio": "brand_character", "サンリオ": "brand_character",
    "ハローキティ": "brand_character", "キティちゃん": "brand_character",
    "すみっコぐらし": "brand_character", "リラックマ": "brand_character",
    "ドラえもん": "brand_character", "ワンピース": "brand_character",
    "鬼滅の刃": "brand_character", "呪術廻戦": "brand_character",
    "進撃の巨人": "brand_character", "ドラゴンボール": "brand_character",
    "NARUTO": "brand_character", "ナルト": "brand_character",
    "スヌーピー": "brand_character", "ムーミン": "brand_character",
    "トミカ": "brand_character", "プラレール": "brand_character",
    "LEGO": "brand_character", "レゴ": "brand_character",
    "Barbie": "brand_character", "バービー": "brand_character",
    "Star Wars": "brand_character", "スターウォーズ": "brand_character",
    "ジブリ": "brand_character", "トトロ": "brand_character",
    # 文具ブランド
    "KOKUYO": "brand_stationery", "コクヨ": "brand_stationery",
    "PILOT": "brand_stationery", "パイロット": "brand_stationery",
    "三菱鉛筆": "brand_stationery", "uni": "brand_stationery",
    "ZEBRA": "brand_stationery", "ゼブラ": "brand_stationery",
    "ぺんてる": "brand_stationery", "Pentel": "brand_stationery",
    "STAEDTLER": "brand_stationery", "ステッドラー": "brand_stationery",
    "FABER-CASTELL": "brand_stationery", "ファーバーカステル": "brand_stationery",
    # テック・家電
    "Apple": "brand_tech", "アップル": "brand_tech",
    "iPhone": "brand_tech", "iPad": "brand_tech",
    "Samsung": "brand_tech", "サムスン": "brand_tech",
    "SONY": "brand_tech", "ソニー": "brand_tech",
    "Panasonic": "brand_tech", "パナソニック": "brand_tech",
    "SHARP": "brand_tech", "シャープ": "brand_tech",
    "TOSHIBA": "brand_tech", "東芝": "brand_tech",
    "Dyson": "brand_tech", "ダイソン": "brand_tech",
    "BOSE": "brand_tech", "ボーズ": "brand_tech",
    # その他有名ブランド
    "IKEA": "brand_other", "イケア": "brand_other",
    "無印良品": "brand_other", "MUJI": "brand_other",
    "Nitori": "brand_other", "ニトリ": "brand_other",
    "DAISO": "brand_other", "ダイソー": "brand_other",
    "3M": "brand_other", "Coleman": "brand_other", "コールマン": "brand_other",
}

# カテゴリ→教育テキスト（UI表示用）
FILTER_CATEGORY_INFO = {
    # --- 禁止キーワード系 ---
    "fashion": {
        "label": "ファッション・アクセサリー",
        "icon": "\U0001F45C",
        "reason": "ファッション・アクセサリー用品をAmazon FBAに納品すると、"
                  "通常の雑貨倉庫ではなくファッション専用倉庫に振り分けられます。"
                  "倉庫が異なると他商品との同梱ができず、配送コストが上がるため"
                  "中国輸入の物販ビジネスには不向きです。",
    },
    "food": {
        "label": "飲食・サプリメント",
        "icon": "\U0001F35C",
        "reason": "食品・飲料・サプリメントは食品衛生法により輸入時に届出・検査が必要です。"
                  "賞味期限管理や成分表示義務もあり、個人での輸入販売は非常にハードルが高いです。",
    },
    "food_hygiene": {
        "label": "食品衛生法対象（口に触れる製品）",
        "icon": "\U0001F37D",
        "reason": "食器・コップ・箸など口に触れる製品は食品衛生法の規制対象です。"
                  "輸入時に厚生労働省の検査が必要で、鉛やカドミウムなどの基準をクリアする"
                  "必要があります。検査費用が高額で、不合格なら廃棄となるリスクがあります。",
    },
    "pse": {
        "label": "PSE法対象（電気用品）",
        "icon": "\u26A1",
        "reason": "コンセント・充電器・電源タップなどの電気用品は電気用品安全法（PSE法）の"
                  "規制対象です。PSEマークなしでの販売は法律違反（罰則あり）となります。"
                  "技術基準適合確認・届出が必要で、個人での取得は現実的ではありません。",
    },
    "baby": {
        "label": "乳幼児向け製品",
        "icon": "\U0001F476",
        "reason": "乳幼児（6歳未満）が使う製品は食品衛生法の規制対象です。"
                  "子どもが口に入れる可能性があるため、有害物質の検査が必要です。"
                  "知育玩具も対象で、ST（玩具安全）基準への適合も求められます。"
                  "検査費用は1商品あたり数万円〜で、不合格リスクもあります。",
    },
    "japan_made": {
        "label": "日本製品",
        "icon": "\U0001F1EF\U0001F1F5",
        "reason": "「日本製」「国産」「MADE IN JAPAN」と明記された商品は"
                  "中国から仕入れることができません。",
    },
    "adult": {
        "label": "アダルト関連",
        "icon": "\U0001F6AB",
        "reason": "アダルト関連商品はAmazonの出品規制が厳しく、"
                  "アカウント停止リスクがあります。また輸入時の税関検査で"
                  "差し止められる可能性もあります。",
    },
    "regulated": {
        "label": "法規制対象",
        "icon": "\u2696",
        "reason": "医療機器（薬機法）、レーザー製品（消費生活用製品安全法）、"
                  "電子タバコ・CBD（薬機法・関税法）など、各種法規制の対象です。"
                  "許認可なしでの輸入・販売は法律違反となります。",
    },
    # --- 除外ブランド系 ---
    "brand_sports": {
        "label": "スポーツブランド",
        "icon": "\U0001F3C3",
        "reason": "Nike・adidas等のスポーツブランドは商標権が強く保護されています。"
                  "中国から仕入れた場合、ほぼ確実に偽物・模倣品であり、"
                  "税関で差し止め、Amazonアカウント停止、法的措置のリスクがあります。",
    },
    "brand_luxury": {
        "label": "ラグジュアリー・ファッションブランド",
        "icon": "\U0001F48E",
        "reason": "GUCCI・Louis Vuitton等のハイブランドは偽物の流通が多く、"
                  "税関での摘発対象です。商標権侵害は10年以下の懲役または"
                  "1000万円以下の罰金が科される可能性があります。",
    },
    "brand_character": {
        "label": "キャラクター・アニメ（著作権）",
        "icon": "\U0001F3AC",
        "reason": "ディズニー・ポケモン・鬼滅の刃等のキャラクター商品は"
                  "著作権・商標権で厳重に保護されています。"
                  "正規ライセンスなしでの販売は権利侵害となり、"
                  "Amazonでは即アカウント停止の対象です。",
    },
    "brand_stationery": {
        "label": "文具ブランド",
        "icon": "\u270F",
        "reason": "コクヨ・PILOT等の日本文具メーカーは商標権を保有しています。"
                  "中国製の模倣品を正規品として販売すると商標権侵害となります。",
    },
    "brand_tech": {
        "label": "家電・テックブランド",
        "icon": "\U0001F4F1",
        "reason": "Apple・SONY等の家電ブランドは商標権に加え、"
                  "PSE法・技適マーク（電波法）の規制もあります。"
                  "中国からの並行輸入品は保証対象外で、故障時のリスクも大きいです。",
    },
    "brand_other": {
        "label": "その他有名ブランド",
        "icon": "\U0001F3F7",
        "reason": "IKEA・無印良品・ニトリ等は商標権を保有しています。"
                  "これらのブランド名が含まれる商品を中国から仕入れて"
                  "販売すると商標権侵害のリスクがあります。",
    },
    # --- 除外カテゴリ系 ---
    "excluded_category": {
        "label": "除外カテゴリ",
        "icon": "\U0001F4E6",
        "reason": "このカテゴリは輸入規制・取扱困難・利益率の問題から除外しています。",
    },
}


def _categorize_filter_reasons(diag: dict) -> list[dict]:
    """diagデータを教育表示用のカテゴリ別リストに変換する。

    Returns:
        [{"category": "pse", "label": "...", "icon": "...", "reason": "...",
          "count": N, "keywords": ["コンセント", ...]}]
    """
    result = []

    # 1. 禁止キーワード（カテゴリ別に集約）
    prohibited_detail = diag.get("prohibited_detail", {})
    cat_agg = {}  # {category: {"count": N, "keywords": [...]}}
    for kw, cnt in prohibited_detail.items():
        cat = _PROHIBITED_KW_TO_CATEGORY.get(kw, "regulated")
        if cat not in cat_agg:
            cat_agg[cat] = {"count": 0, "keywords": []}
        cat_agg[cat]["count"] += cnt
        cat_agg[cat]["keywords"].append(kw)

    for cat, data in sorted(cat_agg.items(), key=lambda x: -x[1]["count"]):
        info = FILTER_CATEGORY_INFO.get(cat, FILTER_CATEGORY_INFO["regulated"])
        result.append({
            "category": cat,
            "label": info["label"],
            "icon": info.get("icon", ""),
            "reason": info["reason"],
            "count": data["count"],
            "keywords": data["keywords"],
        })

    # 2. 除外ブランド（カテゴリ別に集約）
    brand_detail = diag.get("brand_detail", {})
    brand_cat_agg = {}
    for brand, cnt in brand_detail.items():
        cat = _BRAND_TO_CATEGORY.get(brand, "brand_other")
        if cat not in brand_cat_agg:
            brand_cat_agg[cat] = {"count": 0, "keywords": []}
        brand_cat_agg[cat]["count"] += cnt
        brand_cat_agg[cat]["keywords"].append(brand)

    for cat, data in sorted(brand_cat_agg.items(), key=lambda x: -x[1]["count"]):
        info = FILTER_CATEGORY_INFO.get(cat, FILTER_CATEGORY_INFO["brand_other"])
        result.append({
            "category": cat,
            "label": info["label"],
            "icon": info.get("icon", ""),
            "reason": info["reason"],
            "count": data["count"],
            "keywords": data["keywords"],
        })

    # 数値フィルタ（価格・レビュー・BSR等）は教育表示不要のため省略

    return result


async def run_keyword_research(
    browser: BrowserManager,
    keyword: str,
    config,
    diagnose: bool = False,
):
    """1つのキーワードのリサーチを実行（ブラウザは外部で管理）

    Args:
        browser: 起動済みのBrowserManager
        keyword: 検索キーワード
        config: 設定
        diagnose: 診断モード（各段階の除外理由を詳細出力）

    Returns:
        KeywordResearchOutcome（後方互換: len(), iter(), bool() が動作）
    """
    from src.modules.amazon.scraper import AmazonScraper
    from src.modules.amazon.filter import ProductFilter
    from src.modules.amazon.searcher import AmazonSearcher
    from src.modules.alibaba.image_search import AlibabaImageSearcher
    from src.modules.calculator.profit import ProfitCalculator
    from src.models.product import ProductDetail, AlibabaProduct
    from src.models.result import ResearchResult, MatchResult, ProfitResult, KeywordResearchOutcome
    from src.output.spreadsheet_exporter import SpreadsheetExporter

    min_profit_rate = config.filter.min_profit_rate
    tag = f"[{keyword}]"

    # フィルタ除外理由カウンター（UI表示用に常時記録）
    diag = {
        "price_low": 0, "price_high": 0, "reviews": 0,
        "prohibited": 0, "brand": 0, "price_zero": 0,
        "prohibited_detail": {},  # {matched_keyword: count}
        "brand_detail": {},       # {matched_brand: count}
    }

    print(f"\n{'=' * 60}")
    print(f"リサーチ開始: {keyword}")
    if diagnose:
        print(f"  *** 診断モード ON ***")
    print(f"{'=' * 60}")

    # 1. Amazon検索
    organic_label = "（オーガニックのみ）" if config.search.organic_only else ""
    print(f"{tag} [1/6] Amazon検索中...{organic_label}")
    search = AmazonSearcher(browser, organic_only=config.search.organic_only)
    search_results = await search.search(keyword, max_pages=config.search.max_pages)
    print(f"{tag}   → {len(search_results)}件の商品を取得")

    if diagnose and search_results:
        print(f"\n{tag} [診断] Amazon検索結果の一覧:")
        for i, item in enumerate(search_results, 1):
            title_short = (item.get("title", "") or "")[:40]
            print(f"{tag}   {i:2d}. {item.get('asin','')} | "
                  f"{item.get('price',0):,}円 | "
                  f"レビュー{item.get('review_count',0)}件 | "
                  f"{title_short}")
        print()

    if not search_results:
        print(f"{tag} 検索結果がありません")
        return KeywordResearchOutcome(keyword=keyword, filter_reasons=diag)

    # 2. 事前フィルタ（検索結果の価格・レビュー数で足切り）
    print(f"{tag} [2/6] 事前フィルタリング中...")
    product_filter = ProductFilter()
    pre_filtered = []
    for item in search_results:
        price = item.get("price", 0)
        reviews = item.get("review_count", 0)
        title = item.get("title", "")
        asin = item.get("asin", "")

        # 価格0円（取得失敗）
        if price == 0:
            diag["price_zero"] += 1
            if diagnose:
                print(f"{tag}   [除外] {asin} 価格=0円（取得失敗）| {title[:40]}")
            continue

        # 価格フィルタ（下限）
        if price < config.filter.min_price:
            diag["price_low"] += 1
            if diagnose:
                print(f"{tag}   [除外] {asin} 価格{price:,}円 < {config.filter.min_price:,}円 | {title[:40]}")
            continue

        # 価格フィルタ（上限）
        if price > config.filter.max_price:
            diag["price_high"] += 1
            if diagnose:
                print(f"{tag}   [除外] {asin} 価格{price:,}円 > {config.filter.max_price:,}円 | {title[:40]}")
            continue

        # レビュー数フィルタ
        if reviews > config.filter.max_reviews:
            diag["reviews"] += 1
            if diagnose:
                print(f"{tag}   [除外] {asin} レビュー{reviews}件 > {config.filter.max_reviews}件 | {title[:40]}")
            continue

        # 禁止キーワードフィルタ
        title_lower = title.lower()
        matched_kw = None
        for kw in config.filter.prohibited_keywords:
            if kw.lower() in title_lower:
                matched_kw = kw
                break
        if matched_kw:
            diag["prohibited"] += 1
            diag["prohibited_detail"][matched_kw] = diag["prohibited_detail"].get(matched_kw, 0) + 1
            if diagnose:
                print(f"{tag}   [除外] {asin} 禁止KW「{matched_kw}」| {title[:40]}")
            continue

        # ブランド除外フィルタ
        matched_brand = None
        for brand in config.filter.excluded_brands:
            if brand.lower() in title_lower:
                matched_brand = brand
                break
        if matched_brand:
            diag["brand"] += 1
            diag["brand_detail"][matched_brand] = diag["brand_detail"].get(matched_brand, 0) + 1
            if diagnose:
                print(f"{tag}   [除外] {asin} ブランド「{matched_brand}」| {title[:40]}")
            continue

        if diagnose:
            print(f"{tag}   [通過] {asin} {price:,}円 レビュー{reviews}件 | {title[:40]}")
        pre_filtered.append(item)

    print(f"{tag}   → {len(pre_filtered)}/{len(search_results)}件が事前フィルタ通過")

    if diagnose:
        print(f"\n{tag} [診断] 事前フィルタ除外サマリー:")
        print(f"{tag}   価格=0円（取得失敗）: {diag['price_zero']}件")
        print(f"{tag}   価格が安い（<{config.filter.min_price:,}円）: {diag['price_low']}件")
        print(f"{tag}   価格が高い（>{config.filter.max_price:,}円）: {diag['price_high']}件")
        print(f"{tag}   レビュー多い（>{config.filter.max_reviews}件）: {diag['reviews']}件")
        print(f"{tag}   禁止キーワード: {diag['prohibited']}件")
        print(f"{tag}   除外ブランド: {diag['brand']}件")
        print(f"{tag}   → 通過: {len(pre_filtered)}件")
        print()

    if not pre_filtered:
        print(f"{tag} 事前フィルタを通過した商品がありません")
        return KeywordResearchOutcome(
            keyword=keyword,
            total_searched=len(search_results),
            filter_reasons=diag,
        )

    # 3. 商品詳細取得（事前フィルタ通過分のみ）
    print(f"{tag} [3/6] 商品詳細を取得中...（{len(pre_filtered)}件）")
    scraper = AmazonScraper(browser)
    products = await scraper.get_product_details_batch(
        [r["asin"] for r in pre_filtered],
        progress_callback=lambda i, t, a: print(f"{tag}   → {i}/{t} {a}"),
    )
    print(f"{tag}   → {len(products)}件の詳細を取得")

    if diagnose:
        failed_count = len(pre_filtered) - len(products)
        if failed_count > 0:
            print(f"{tag} [診断] 詳細取得失敗: {failed_count}件（日本製除外 or ページエラー）")
        print(f"\n{tag} [診断] 取得した商品詳細:")
        for p in products:
            dims_str = f"{sum(p.dimensions):.0f}cm" if p.dimensions else "不明"
            print(f"{tag}   {p.asin} | {p.price:,}円 | BSR:{p.bsr:,} | "
                  f"レビュー{p.review_count} | 評価{p.rating} | "
                  f"バリエ{p.variation_count} | 寸法合計{dims_str} | "
                  f"{'Amazon直販' if p.is_amazon_direct else 'FBA' if p.is_fba else 'FBM'} | "
                  f"販売元:{p.seller_name or '不明'} | {p.category}")
        print()

    # 4. 最終フィルタリング（BSR、バリエーション等）
    print(f"{tag} [4/6] 最終フィルタリング中...")

    if diagnose:
        # 診断モード: 全商品にチェックをかけて理由を表示
        filtered = []
        final_diag = {}
        for product in products:
            result = product_filter.check(product)
            if result.passed:
                filtered.append((product, result))
                print(f"{tag}   [通過] {product.asin} | BSR:{product.bsr:,} | "
                      f"バリエ{product.variation_count} | 月間売上{result.estimated_monthly_revenue:,}円")
            else:
                # 除外理由をカウント
                reason_key = result.reason.split(":")[0] if result.reason else "不明"
                final_diag[reason_key] = final_diag.get(reason_key, 0) + 1
                print(f"{tag}   [除外] {product.asin} → {result.reason}")

        diag["final_filter"] = final_diag
        print(f"\n{tag} [診断] 最終フィルタ除外サマリー:")
        for reason, count in sorted(final_diag.items(), key=lambda x: -x[1]):
            print(f"{tag}   {reason}: {count}件")
        print(f"{tag}   → 通過: {len(filtered)}件")
        print()
    else:
        filtered = []
        final_diag = {}
        for product in products:
            result = product_filter.check(product)
            if result.passed:
                filtered.append((product, result))
            else:
                reason_key = result.reason.split(":")[0].strip() if result.reason else "不明"
                final_diag[reason_key] = final_diag.get(reason_key, 0) + 1
        diag["final_filter"] = final_diag

    print(f"{tag}   → {len(filtered)}/{len(products)}件がフィルタ通過")

    if not filtered:
        print(f"{tag} フィルタを通過した商品がありません")
        return KeywordResearchOutcome(
            keyword=keyword,
            total_searched=len(search_results),
            pass_count=0,
            filter_reasons=diag,
        )

    # 5. 1688画像検索 → 候補収集（人間が最終確認）
    # 機械的な画像マッチングでは精度に限界があるため、
    # 候補を収集してHTMLレポートで人間が目視確認する方式に変更。
    # ORBゴミ除去フィルタで明らかに別商品の候補は除外する。
    print(f"{tag} [5/6] 1688画像検索中...")
    alibaba_search = AlibabaImageSearcher(browser, max_results=config.search.alibaba_results)
    profit_calc = ProfitCalculator()

    min_price_cny = config.matcher.min_price_cny
    max_profit_rate = config.matcher.max_profit_rate
    max_candidates = config.matcher.max_candidates
    orb_garbage_threshold = config.matcher.orb_garbage_threshold
    use_dino = config.matcher.use_dino and smart_matcher._dino_available
    dino_garbage_threshold = config.matcher.dino_garbage_threshold

    # 1688候補フィルタ用: 禁止キーワード + 除外ブランド + 中国語ブランド名
    # （著作権・商標品を1688候補から除外）
    _chinese_ng_brands = [
        # ディズニー系
        "迪士尼", "米奇", "米妮", "维尼", "冰雪奇缘", "disney",
        # サンリオ系
        "三丽鸥", "凯蒂猫", "kitty", "美乐蒂", "库洛米", "大耳狗",
        # マーベル・DC系
        "漫威", "蜘蛛侠", "蝙蝠侠", "超人", "复仇者",
        # ポケモン・任天堂
        "宝可梦", "皮卡丘", "pokemon", "任天堂", "nintendo", "马里奥",
        # 日本アニメ
        "海贼王", "航海王", "鬼灭之刃", "火影忍者", "龙珠",
        "哆啦a梦", "机器猫", "吉卜力", "龙猫",
        # その他キャラクター
        "乐高", "lego", "芭比", "barbie", "星球大战",
        "史努比", "snoopy", "小黄人",
        # スポーツブランド
        "耐克", "nike", "阿迪达斯", "adidas", "彪马", "puma",
        # ラグジュアリー
        "古驰", "gucci", "路易威登", "lv", "香奈儿", "chanel",
        "爱马仕", "hermes", "普拉达", "prada",
    ]
    alibaba_ng_words = [
        w.lower() for w in
        config.filter.prohibited_keywords
        + config.filter.excluded_brands
        + _chinese_ng_brands
    ]

    # ORBゴミ除去フィルタ
    from src.modules.matcher.smart import SmartMatcher
    smart_matcher = SmartMatcher()

    products_with_candidates: list[dict] = []
    all_filtered_products: list[dict] = []

    # 診断モード用カウンター
    alibaba_diag = {
        "no_results": 0, "no_valid": 0, "has_candidates": 0,
        "ng_brand": 0, "orb_rejected": 0, "dino_rejected": 0,
        "title_rejected": 0, "japan_skipped": 0,
    }

    # 中国輸入スコアで並べ替え（中国輸入品を先にリサーチ）
    scored_filtered = []
    for product, filter_result in filtered:
        ci_score = _estimate_china_import_score(product.title, product.seller_name)
        scored_filtered.append((product, filter_result, ci_score))
    scored_filtered.sort(key=lambda x: x[2], reverse=True)

    try:
        for product, filter_result, ci_score in scored_filtered:
            # 日本製の商品は1688検索をスキップ（完全除外）
            if ci_score == 0.0:
                alibaba_diag["japan_skipped"] += 1
                print(f"{tag}   → [除外] {product.asin}: 日本製のため1688検索スキップ"
                      f" | {product.title[:40]}")
                all_filtered_products.append({
                    "amazon": product.to_dict(),
                    "estimated_monthly_sales": filter_result.estimated_monthly_sales,
                    "estimated_monthly_revenue": filter_result.estimated_monthly_revenue,
                    "candidates": [],
                    "no_candidates_reason": "日本製のため1688検索スキップ",
                })
                continue

            ci_label = ""
            if ci_score >= 0.7:
                ci_label = " [中国輸入◎]"
            print(f"{tag}   → {product.asin}: {product.title[:30]}...{ci_label}")

            # Amazon画像を準備（商品ごとに1回だけ）
            # DINOv2優先、失敗時はORBにフォールバック
            amazon_dino = None
            amazon_gray = None
            if use_dino:
                amazon_dino = await smart_matcher.prepare_image_dino(product.image_url)
                if amazon_dino is None and diagnose:
                    print(f"{tag}     [診断] DINOv2特徴量抽出失敗、ORBフォールバック")
            if amazon_dino is None:
                amazon_gray = await smart_matcher.prepare_image(product.image_url)
                if amazon_gray is None and diagnose:
                    print(f"{tag}     [診断] Amazon画像DL失敗、画像フィルタなしで続行")
            amazon_color = await smart_matcher.prepare_image_color(product.image_url)

            # 画像検索
            alibaba_products = await alibaba_search.search_by_image(product.image_url)
            if not alibaba_products:
                alibaba_diag["no_results"] += 1
                print(f"{tag}     1688商品が見つかりません")
                if diagnose:
                    print(f"{tag}     [診断] 画像URL: {product.image_url[:80]}")
                all_filtered_products.append({
                    "amazon": product.to_dict(),
                    "estimated_monthly_sales": filter_result.estimated_monthly_sales,
                    "estimated_monthly_revenue": filter_result.estimated_monthly_revenue,
                    "candidates": [],
                    "no_candidates_reason": "1688画像検索で結果なし",
                })
                continue

            if diagnose:
                print(f"{tag}     [診断] 1688検索結果: {len(alibaba_products)}件")

            # 各候補の利益を計算してフィルタ
            candidates = []
            for j, ap in enumerate(alibaba_products):
                # 価格サニティチェック
                if ap.price_cny < min_price_cny:
                    if diagnose:
                        print(f"{tag}       {j+1}. [SKIP] {ap.price_cny}元 < "
                              f"{min_price_cny}元（価格サニティ）")
                    continue

                # 禁止ブランド・キーワードチェック（著作権・商標品を除外）
                ap_title_lower = (ap.title or "").lower()
                ng_hit = next(
                    (w for w in alibaba_ng_words if w in ap_title_lower), None
                )
                if ng_hit:
                    alibaba_diag["ng_brand"] += 1
                    if diagnose:
                        print(f"{tag}       {j+1}. [SKIP] NG語「{ng_hit}」: "
                              f"{(ap.title or '')[:30]}")
                    continue

                # 画像類似度計算 + ゴミ除去フィルタ
                hist_sim = 0.0
                orb_sim = 0.0
                dino_sim = 0.0
                used_dino = False

                # ヒストグラム比較（DINOv2/ORB共通）
                if amazon_color is not None and ap.image_url:
                    ali_color = await smart_matcher.prepare_image_color(ap.image_url)
                    if ali_color is not None:
                        hist_sim = smart_matcher.histogram_similarity(amazon_color, ali_color)

                if amazon_dino is not None and ap.image_url:
                    # === DINOv2パス（primary） ===
                    ali_dino = await smart_matcher.prepare_image_dino(ap.image_url)
                    if ali_dino is not None:
                        dino_sim = smart_matcher.dino_similarity(amazon_dino, ali_dino)
                        used_dino = True

                        # ゴミ判定
                        is_garbage = False
                        if dino_sim < dino_garbage_threshold:
                            is_garbage = True
                        elif dino_sim < 0.35 and hist_sim < 0.3:
                            is_garbage = True

                        if is_garbage:
                            alibaba_diag["dino_rejected"] += 1
                            if diagnose:
                                print(f"{tag}       {j+1}. [SKIP] DINO={dino_sim:.3f}"
                                      f" hist={hist_sim:.2f}"
                                      f"（別商品）: "
                                      f"{(ap.title or '')[:25]}")
                            continue
                        elif diagnose:
                            print(f"{tag}       {j+1}. [MATCH] DINO={dino_sim:.3f}"
                                  f" hist={hist_sim:.2f}")

                elif amazon_gray is not None and ap.image_url:
                    # === ORBパス（fallback） ===
                    ali_gray = await smart_matcher.prepare_image(ap.image_url)
                    if ali_gray is not None:
                        orb_sim = smart_matcher.similarity(amazon_gray, ali_gray)

                    is_garbage = False
                    if orb_sim == 0.0:
                        is_garbage = True
                    elif orb_sim < orb_garbage_threshold and hist_sim < 0.4:
                        is_garbage = True
                    elif orb_sim < 0.03 and hist_sim < 0.6:
                        is_garbage = True

                    if is_garbage:
                        alibaba_diag["orb_rejected"] += 1
                        if diagnose:
                            print(f"{tag}       {j+1}. [SKIP] ORB={orb_sim:.3f}"
                                  f" hist={hist_sim:.2f}"
                                  f"（別商品）: "
                                  f"{(ap.title or '')[:25]}")
                        continue
                    elif diagnose:
                        print(f"{tag}       {j+1}. [MATCH] ORB={orb_sim:.3f}"
                              f" hist={hist_sim:.2f}")

                pr = profit_calc.calculate(
                    amazon_price=product.price,
                    cny_price=ap.price_cny,
                    is_fba=product.is_fba,
                    category=product.category,
                    weight_kg=product.weight_kg,
                    dimensions=product.dimensions,
                )

                # 利益率50%超は別商品とみなしてスキップ
                if pr.profit_rate_percentage > max_profit_rate:
                    if diagnose:
                        print(f"{tag}       {j+1}. [SKIP] {ap.price_cny}元 "
                              f"利益率{pr.profit_rate_percentage:.1f}% > "
                              f"{max_profit_rate}%（別商品とみなす）")
                    continue

                if diagnose:
                    print(f"{tag}       {j+1}. [候補] {ap.price_cny}元 | "
                          f"利益{pr.profit:,}円 ({pr.profit_rate_percentage:.1f}%) | "
                          f"{(ap.title or '')[:25]}")

                # タイトル関連度チェック
                title_rel = _compute_title_relevance(product.title, ap.title or "")
                if title_rel == 0.0:
                    alibaba_diag["title_rejected"] += 1
                    if diagnose:
                        print(f"{tag}       {j+1}. [SKIP] タイトル無関連: "
                              f"{(ap.title or '')[:30]}")
                    continue

                # 複合スコア
                if used_dino:
                    # DINOv2: DINO(60%) + ヒストグラム(20%) + タイトル関連度(20%)
                    combined = round(
                        dino_sim * 0.6 + hist_sim * 0.2 + title_rel * 0.2, 4
                    )
                else:
                    # ORB: ORB(50%) + ヒストグラム(30%) + タイトル関連度(20%)
                    combined = round(
                        orb_sim * 0.5 + hist_sim * 0.3 + title_rel * 0.2, 4
                    )
                candidates.append({
                    "alibaba": ap.to_dict(),
                    "dino_similarity": round(dino_sim, 4),
                    "orb_similarity": round(orb_sim, 4),
                    "hist_similarity": round(hist_sim, 4),
                    "title_relevance": round(title_rel, 4),
                    "combined_score": combined,
                    "profit": {
                        **pr.to_dict(),
                        "profit_rate_percentage": round(pr.profit_rate_percentage, 1),
                    },
                })

            if candidates:
                # 複合スコア（ORB+ヒストグラム）でソート（降順）、上位N件に制限
                candidates.sort(
                    key=lambda x: x.get("combined_score", 0),
                    reverse=True,
                )
                candidates = candidates[:max_candidates]

                entry = {
                    "amazon": product.to_dict(),
                    "estimated_monthly_sales": filter_result.estimated_monthly_sales,
                    "estimated_monthly_revenue": filter_result.estimated_monthly_revenue,
                    "candidates": candidates,
                }
                products_with_candidates.append(entry)
                all_filtered_products.append(entry)

                alibaba_diag["has_candidates"] += 1
                print(f"{tag}     {len(candidates)}件の候補")
            else:
                alibaba_diag["no_valid"] += 1
                print(f"{tag}     有効な候補なし")
                all_filtered_products.append({
                    "amazon": product.to_dict(),
                    "estimated_monthly_sales": filter_result.estimated_monthly_sales,
                    "estimated_monthly_revenue": filter_result.estimated_monthly_revenue,
                    "candidates": [],
                    "no_candidates_reason": "1688で有効な候補なし",
                })

    finally:
        await alibaba_search.close()
        await smart_matcher.close()

    if diagnose:
        print(f"\n{tag} [診断] 1688候補収集サマリー:")
        print(f"{tag}   日本製スキップ: {alibaba_diag['japan_skipped']}件")
        print(f"{tag}   1688検索結果なし: {alibaba_diag['no_results']}件")
        print(f"{tag}   NGブランド除外: {alibaba_diag['ng_brand']}件")
        print(f"{tag}   DINOv2ゴミ除去: {alibaba_diag['dino_rejected']}件")
        print(f"{tag}   ORBゴミ除去: {alibaba_diag['orb_rejected']}件")
        print(f"{tag}   タイトル無関連: {alibaba_diag['title_rejected']}件")
        print(f"{tag}   有効な候補なし: {alibaba_diag['no_valid']}件")
        print(f"{tag}   → 候補あり: {alibaba_diag['has_candidates']}件")
        print()

    # 1688画像検索の全件失敗検出
    alibaba_search_error = ""
    searched_on_1688 = len(scored_filtered) - alibaba_diag["japan_skipped"]
    if searched_on_1688 > 0 and alibaba_diag["no_results"] == searched_on_1688:
        alibaba_search_error = (
            f"1688画像検索がすべて失敗しました（{searched_on_1688}件中{searched_on_1688}件が結果0）。"
            f"1688のサイト仕様変更やアクセス制限の可能性があります。管理者にお問い合わせください。"
        )
        print(f"\n{tag} [警告] {alibaba_search_error}")
    elif searched_on_1688 > 3 and alibaba_diag["no_results"] >= searched_on_1688 * 0.8:
        alibaba_search_error = (
            f"1688画像検索の大半が失敗しました（{searched_on_1688}件中{alibaba_diag['no_results']}件が結果0）。"
            f"1688のアクセスが不安定な可能性があります。"
        )
        print(f"\n{tag} [警告] {alibaba_search_error}")

    # 6. HTMLビューアー + Excel自動生成
    print(f"{tag} [6/6] レポート生成中...")

    results: list[ResearchResult] = []

    if all_filtered_products:
        # HTMLビューアー（目視確認用：フィルター通過全商品を表示）
        from src.output.html_report import HtmlCandidateReport
        report = HtmlCandidateReport()
        html_path = report.generate(keyword, all_filtered_products,
                                     error_message=alibaba_search_error)
        print(f"{tag}   HTML: {html_path}")

        # Excel自動生成（各商品の利益率ベスト候補を採用）
        for prod_data in products_with_candidates:
            best = prod_data["candidates"][0]  # 利益率降順ソート済み
            try:
                amazon = ProductDetail.from_dict(prod_data["amazon"])
                alibaba = AlibabaProduct.from_dict(best["alibaba"])
                profit = ProfitResult.from_dict(best["profit"])

                match_result = MatchResult(
                    amazon_product=amazon,
                    alibaba_product=alibaba,
                    is_matched=True,
                    match_confidence=None,
                )

                result = ResearchResult(
                    amazon_product=amazon,
                    alibaba_product=alibaba,
                    profit_result=profit,
                    estimated_monthly_sales=prod_data["estimated_monthly_sales"],
                    estimated_monthly_revenue=prod_data["estimated_monthly_revenue"],
                    match_result=match_result,
                )
                results.append(result)
            except (KeyError, TypeError) as e:
                logger.warning(f"結果データのパースエラー: {e}")
                continue

        if results:
            exporter = SpreadsheetExporter()
            excel_path = exporter.export(results, keyword)
            print(f"{tag}   Excel: {excel_path}")
    else:
        print(f"{tag}   フィルター通過商品がありません")

    # サマリー
    print(f"\n{tag} リサーチ完了")
    print(f"{tag}   検索結果: {len(search_results)}件")
    print(f"{tag}   フィルタ通過: {len(filtered)}件")
    print(f"{tag}   1688候補あり: {len(products_with_candidates)}件")
    print(f"{tag}   Excel出力: {len(results)}件")
    if all_filtered_products:
        print(f"\n{tag}   HTMLビューアーで画像を目視確認できます")

    return KeywordResearchOutcome(
        keyword=keyword,
        results=results,
        total_searched=len(search_results),
        pass_count=len(filtered),
        products_with_candidates=products_with_candidates,
        all_filtered_products=all_filtered_products,
        filter_reasons=diag,
        alibaba_search_error=alibaba_search_error,
    )


async def run_research(keyword: str, headless: bool = True, diagnose: bool = False):
    """単一キーワードリサーチ

    Args:
        keyword: 検索キーワード
        headless: ヘッドレスモードで実行するか
        diagnose: 診断モード
    """
    config = get_config()

    # 1688認証の設定
    auth = AuthManager()
    auth_kwargs = {}
    if auth.is_logged_in():
        auth_kwargs["use_auth"] = True
        auth_kwargs["auth_storage_path"] = auth.storage_path
        logger.info("1688認証データを使用します")
    else:
        logger.warning("1688認証データがありません。画像検索結果が空になる可能性があります。")
        logger.warning("ログインするには: python run_research.py --login")

    browser = BrowserManager(
        headless=headless,
        timeout=config.browser.timeout,
        request_delay=config.browser.request_delay,
        **auth_kwargs,
    )

    try:
        async with browser.browser_session():
            outcome = await run_keyword_research(browser, keyword, config, diagnose=diagnose)

        # セッション統合レポート生成
        if outcome and outcome.products_with_candidates:
            session_data = [{
                "keyword": keyword,
                "products": outcome.products_with_candidates,
                "score": outcome.score,
                "total_searched": outcome.total_searched,
                "pass_count": outcome.pass_count,
            }]
            stats = {
                "total_keywords": 1,
                "total_candidates": len(outcome.products_with_candidates),
                "elapsed_seconds": 0,
                "elapsed_str": "-",
            }
            from src.output.session_report import SessionReportGenerator
            output_dir = str(Path(__file__).parent / "output")
            gen = SessionReportGenerator(output_dir=output_dir)
            html_path = gen.generate_html(session_data, stats)
            excel_path = gen.generate_excel(session_data, stats)
            print(f"\n[統合レポート]")
            print(f"  HTML: {html_path}")
            print(f"  Excel: {excel_path}")

    except Exception as e:
        logger.error(f"リサーチエラー: {e}", exc_info=True)
        raise


async def run_research_batch(keywords: list[str], headless: bool = True, diagnose: bool = False):
    """複数キーワード並列リサーチ

    1つのブラウザで複数キーワードを同時に処理する。
    同時実行数はconfig.search.max_concurrent_keywordsで制御。

    Args:
        keywords: 検索キーワードのリスト
        headless: ヘッドレスモードで実行するか
        diagnose: 診断モード
    """
    config = get_config()
    max_concurrent = config.search.max_concurrent_keywords

    # 1688認証の設定
    auth = AuthManager()
    auth_kwargs = {}
    if auth.is_logged_in():
        auth_kwargs["use_auth"] = True
        auth_kwargs["auth_storage_path"] = auth.storage_path
        logger.info("1688認証データを使用します")
    else:
        logger.warning("1688認証データがありません。画像検索結果が空になる可能性があります。")
        logger.warning("ログインするには: python run_research.py --login")

    browser = BrowserManager(
        headless=headless,
        timeout=config.browser.timeout,
        request_delay=config.browser.request_delay,
        **auth_kwargs,
    )

    semaphore = asyncio.Semaphore(max_concurrent)

    async def run_with_semaphore(kw: str) -> list:
        async with semaphore:
            try:
                return await run_keyword_research(browser, kw, config, diagnose=diagnose)
            except Exception as e:
                print(f"\n[{kw}] エラー: {e}")
                logger.error(f"キーワード '{kw}' のリサーチ失敗: {e}", exc_info=True)
                return []

    print("\n" + "=" * 60)
    print(f"並列リサーチ開始: {len(keywords)}件（同時{max_concurrent}件）")
    if diagnose:
        print("  *** 診断モード ON ***")
    print("=" * 60)

    try:
        async with browser.browser_session():
            tasks = [run_with_semaphore(kw) for kw in keywords]
            all_results = await asyncio.gather(*tasks)

    except Exception as e:
        logger.error(f"バッチリサーチエラー: {e}", exc_info=True)
        raise

    # 全体サマリー
    total_matches = sum(len(r) for r in all_results)
    print("\n" + "=" * 60)
    print("全キーワードのリサーチ完了")
    print("=" * 60)
    for kw, results in zip(keywords, all_results):
        print(f"  {kw}: {len(results)}件マッチ")
    print(f"  合計: {total_matches}件")
    print("=" * 60)

    # セッション統合レポート生成
    session_data = []
    for kw, outcome in zip(keywords, all_results):
        if hasattr(outcome, 'products_with_candidates') and outcome.products_with_candidates:
            session_data.append({
                "keyword": kw,
                "products": outcome.products_with_candidates,
                "score": outcome.score if hasattr(outcome, 'score') else 0.0,
                "total_searched": outcome.total_searched if hasattr(outcome, 'total_searched') else 0,
                "pass_count": outcome.pass_count if hasattr(outcome, 'pass_count') else 0,
            })

    if session_data:
        import time as _time
        stats = {
            "total_keywords": len(keywords),
            "total_candidates": sum(len(d["products"]) for d in session_data),
            "elapsed_seconds": 0,
            "elapsed_str": "",
        }
        try:
            from src.output.session_report import SessionReportGenerator
            output_dir = str(Path(__file__).parent / "output")
            gen = SessionReportGenerator(output_dir=output_dir)
            html_path = gen.generate_html(session_data, stats)
            excel_path = gen.generate_excel(session_data, stats)
            print(f"\n  統合レポート:")
            print(f"    HTML: {html_path}")
            print(f"    Excel: {excel_path}")
            print(f"  ※ 全キーワードの結果を1つのファイルにまとめています")
        except Exception as e:
            logger.error(f"統合レポート生成エラー: {e}", exc_info=True)
            print(f"  統合レポート生成エラー: {e}")


def finalize_selections(json_path: str):
    """HTML候補レビュー後のJSONからExcelレポートを生成

    Args:
        json_path: エクスポートされたJSONファイルのパス
    """
    import json
    from src.models.product import ProductDetail, AlibabaProduct
    from src.models.result import ResearchResult, MatchResult, ProfitResult
    from src.output.spreadsheet_exporter import SpreadsheetExporter

    print(f"\n{'=' * 60}")
    print(f"選択結果からExcelレポートを生成")
    print(f"{'=' * 60}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    keyword = data["keyword"]
    selections = data.get("selections", [])

    print(f"  キーワード: {keyword}")
    print(f"  選択数: {len(selections)}件")
    print(f"  確定日時: {data.get('finalized_at', '不明')}")

    if not selections:
        print("\n  選択された商品がありません")
        return

    results: list[ResearchResult] = []

    for sel in selections:
        try:
            amazon = ProductDetail.from_dict(sel["amazon"])
            alibaba = AlibabaProduct.from_dict(sel["alibaba"])
            profit = ProfitResult.from_dict(sel["profit"])

            match_result = MatchResult(
                amazon_product=amazon,
                alibaba_product=alibaba,
                is_matched=True,
                match_confidence=1.0,  # 人間確認済み
            )

            result = ResearchResult(
                amazon_product=amazon,
                alibaba_product=alibaba,
                profit_result=profit,
                estimated_monthly_sales=sel["estimated_monthly_sales"],
                estimated_monthly_revenue=sel["estimated_monthly_revenue"],
                match_result=match_result,
            )
            results.append(result)

            print(f"\n  ✓ {amazon.asin}: {amazon.title[:40]}")
            print(f"    1688: {alibaba.price_cny}元 | "
                  f"利益: {profit.profit:,}円 ({profit.profit_rate * 100:.1f}%)")

        except (KeyError, TypeError) as e:
            logger.warning(f"選択データのパースエラー: {e}")
            continue

    if results:
        exporter = SpreadsheetExporter()
        output_path = exporter.export(results, keyword)
        print(f"\n  Excel出力: {output_path}")

        detailed_path = exporter.export_detailed(results, keyword)
        print(f"  詳細版: {detailed_path}")

        avg_profit_rate = sum(
            r.profit_result.profit_rate_percentage for r in results
        ) / len(results)
        print(f"\n  合計: {len(results)}件")
        print(f"  平均利益率: {avg_profit_rate:.1f}%")
    else:
        print("\n  有効な結果がありません")

    print(f"\n{'=' * 60}")


async def auto_research(
    seed_keywords: list[str],
    headless: bool = True,
    diagnose: bool = False,
    resume: bool = False,
    max_keywords: int | None = None,
    max_duration_minutes: int | None = None,
) -> None:
    """自動リサーチモード（サジェスト再帰展開）

    Args:
        seed_keywords: シードキーワードのリスト
        headless: ヘッドレスモードで実行するか
        diagnose: 診断モード
        resume: 前回の状態から再開
        max_keywords: 最大KW数（CLI上書き）
        max_duration_minutes: 最大時間（CLI上書き）
    """
    from src.modules.amazon.auto_researcher import AutoResearcher

    config = get_config()

    # CLI引数でconfig値を上書き
    if max_keywords is not None:
        config.auto.max_keywords = max_keywords
    if max_duration_minutes is not None:
        config.auto.max_duration_minutes = max_duration_minutes

    # 1688認証の設定
    auth = AuthManager()
    auth_kwargs = {}
    if auth.is_logged_in():
        auth_kwargs["use_auth"] = True
        auth_kwargs["auth_storage_path"] = auth.storage_path
        logger.info("1688認証データを使用します")
    else:
        logger.warning("1688認証データがありません。画像検索結果が空になる可能性があります。")
        logger.warning("ログインするには: python run_research.py --login")

    browser = BrowserManager(
        headless=headless,
        timeout=config.browser.timeout,
        request_delay=config.browser.request_delay,
        **auth_kwargs,
    )

    try:
        async with browser.browser_session():
            researcher = AutoResearcher(browser, config)
            await researcher.run(
                seed_keywords=seed_keywords,
                diagnose=diagnose,
                resume=resume,
            )
    except Exception as e:
        logger.error(f"自動リサーチエラー: {e}", exc_info=True)
        raise


def load_keywords_from_file(filepath: str) -> list[str]:
    """ファイルからキーワードを読み込む（1行1キーワード）"""
    keywords = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            keyword = line.strip()
            if keyword and not keyword.startswith("#"):  # 空行とコメント行をスキップ
                keywords.append(keyword)
    return keywords


def main():
    parser = argparse.ArgumentParser(
        description="Amazon-1688 中国製品リサーチツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  1つのキーワード:     python run_research.py "収納ボックス"
  複数キーワード:      python run_research.py "収納ボックス" "折りたたみ椅子" "LEDライト"
  ファイルから読込:    python run_research.py --file keywords.txt
  サジェスト展開:      python run_research.py --suggest "貯金箱"
  自動リサーチ:        python run_research.py --auto "バンプラバー"
  自動（複数シード）:  python run_research.py --auto "バンプラバー" "収納ボックス"
  自動（上限指定）:    python run_research.py --auto --max-keywords 30 --max-time 45 "バンプラバー"
  自動リサーチ再開:    python run_research.py --auto --resume
  自動リセット:        python run_research.py --auto --auto-reset "バンプラバー"
  診断モード:          python run_research.py --diagnose "収納ボックス"
  候補確定→Excel:     python run_research.py --finalize selections_収納ボックス.json
  デバッグモード:      python run_research.py "収納ボックス" --debug
  1688ログイン:        python run_research.py --login

キーワードファイルの形式（1行1キーワード）:
  収納ボックス
  折りたたみ椅子
  # コメント行（スキップされます）
  LEDライト
        """,
    )

    parser.add_argument("keywords", nargs="*", help="検索キーワード（複数指定可）")
    parser.add_argument("--file", "-f", help="キーワードファイル（1行1キーワード）")
    parser.add_argument("--suggest", "-s", action="store_true",
                        help="Amazonサジェストキーワードを自動展開してリサーチ")
    parser.add_argument("--diagnose", "-d", action="store_true",
                        help="診断モード（各段階の除外理由を詳細出力）")
    parser.add_argument("--finalize", metavar="JSON",
                        help="HTML候補レビュー後のJSONからExcelレポートを生成")
    parser.add_argument("--auto", action="store_true",
                        help="自動リサーチモード（サジェスト再帰展開）")
    parser.add_argument("--resume", action="store_true",
                        help="前回の自動リサーチを再開")
    parser.add_argument("--auto-reset", action="store_true",
                        help="自動リサーチの状態をリセット")
    parser.add_argument("--max-keywords", type=int, default=None, metavar="N",
                        help="自動リサーチの最大KW数（例: 50）")
    parser.add_argument("--max-time", type=int, default=None, metavar="MIN",
                        help="自動リサーチの最大時間（分、例: 60）")
    parser.add_argument("--debug", action="store_true", help="デバッグモード（ブラウザ表示）")
    parser.add_argument("--login", action="store_true",
                        help="1688にログイン（画像検索に必要）")
    parser.add_argument("--interactive", action="store_true",
                        help="対話入力モード（バッチファイルから使用）")

    args = parser.parse_args()

    # --interactive: 対話入力モード
    if args.interactive:
        try:
            mode = "自動リサーチ" if args.auto else "商品リサーチ"
            print()
            print("=" * 60)
            print(f"  Amazon-1688 {mode}ツール")
            print("=" * 60)
            print()
            print("  入力項目:")
            print("    1. 検索キーワード")
            print("    2. リサーチ最大時間（分）")
            print("    3. 上限キーワード数")
            print()
            print("  ※ 各項目を入力してEnterを押してください")
            print("  ※ 2と3は空欄Enterで無制限")
            print()
            print("-" * 60)
            print()
            print("  1. 検索キーワード")
            sys.stdout.flush()
            kw = input("     > ").strip()
            if not kw:
                print("  キーワードが入力されませんでした")
                sys.stdout.flush()
                input("  Enter...")
                return
            print()
            print("  2. リサーチ最大時間（分、空欄で無制限）")
            sys.stdout.flush()
            mt = input("     > ").strip()
            print()
            print("  3. 上限キーワード数（空欄で無制限）")
            sys.stdout.flush()
            mk = input("     > ").strip()
            print()
            print("-" * 60)
            print(f"  キーワード: {kw}")
            if mt:
                print(f"  最大時間:   {mt}分")
            if mk:
                print(f"  上限KW数:   {mk}")
            print("-" * 60)
            print()
            # argparse の値を上書き
            args.keywords = [kw]
            if not args.auto:
                args.suggest = True
            if mt:
                try:
                    args.max_time = int(mt)
                except ValueError:
                    args.max_time = None
            if mk:
                try:
                    args.max_keywords = int(mk)
                except ValueError:
                    args.max_keywords = None
        except Exception as e:
            print(f"\n[ERROR] 対話入力でエラー: {type(e).__name__}: {e}")
            sys.stdout.flush()
            input("  Enter...")
            return

    # --login: 1688ログインセットアップ
    if args.login:
        from src.utils.auth import setup_1688_login
        asyncio.run(setup_1688_login())
        return

    # --finalize: 選択結果からExcel生成（ブラウザ不要）
    if args.finalize:
        finalize_selections(args.finalize)
        return

    # --auto: 自動リサーチモード
    if args.auto:
        from src.modules.amazon.auto_researcher import AutoState

        config = get_config()
        headless = not args.debug

        if args.auto_reset:
            AutoState.reset(config.auto.state_file)

        # キーワード収集（autoモード用）
        keywords = list(args.keywords) if args.keywords else []
        if args.file:
            try:
                keywords.extend(load_keywords_from_file(args.file))
            except FileNotFoundError:
                print(f"エラー: ファイルが見つかりません - {args.file}")
                sys.exit(1)

        if args.resume and not keywords:
            # 前回の状態から再開（シード不要）
            asyncio.run(auto_research(
                seed_keywords=[],
                headless=headless,
                diagnose=args.diagnose,
                resume=True,
                max_keywords=args.max_keywords,
                max_duration_minutes=args.max_time,
            ))
        elif keywords:
            asyncio.run(auto_research(
                seed_keywords=keywords,
                headless=headless,
                diagnose=args.diagnose,
                max_keywords=args.max_keywords,
                max_duration_minutes=args.max_time,
            ))
        else:
            print("エラー: --auto にはシードキーワードが必要です")
            print('例: python run_research.py --auto "バンプラバー"')
            print("再開: python run_research.py --auto --resume")
            sys.exit(1)
        return

    # キーワードを収集
    keywords = []

    # ファイルからキーワードを読み込む
    if args.file:
        try:
            keywords.extend(load_keywords_from_file(args.file))
            print(f"ファイルから {len(keywords)} 件のキーワードを読み込みました")
        except FileNotFoundError:
            print(f"エラー: ファイルが見つかりません - {args.file}")
            sys.exit(1)

    # コマンドライン引数のキーワードを追加
    if args.keywords:
        keywords.extend(args.keywords)

    if not keywords:
        parser.print_help()
        print("\nエラー: 検索キーワードを指定してください")
        print('例: python run_research.py "収納ボックス" "折りたたみ椅子"')
        print("例: python run_research.py --file keywords.txt")
        print('例: python run_research.py --suggest "貯金箱"')
        sys.exit(1)

    headless = not args.debug

    # 1688認証状態の表示
    auth = AuthManager()
    if auth.is_logged_in():
        print("\n[1688認証] ログイン済み - 画像検索が有効です")
    else:
        print("\n[1688認証] 未ログイン - 画像検索結果が空になる可能性があります")
        print("  ログインするには: python run_research.py --login")

    # サジェスト展開
    if args.suggest:
        from src.modules.amazon.suggest import expand_keywords

        print("\n" + "=" * 60)
        print("Amazonサジェストキーワードを取得中...")
        print("=" * 60)

        original_count = len(keywords)
        keywords = asyncio.run(expand_keywords(keywords))

        # --max-keywords でサジェスト展開後のKW数を制限
        if args.max_keywords and len(keywords) > args.max_keywords:
            keywords = keywords[:args.max_keywords]
            print(f"\n元キーワード: {original_count}件")
            print(f"サジェスト展開後: {len(keywords)}件（上限{args.max_keywords}件に制限）")
        else:
            print(f"\n元キーワード: {original_count}件")
            print(f"サジェスト展開後: {len(keywords)}件")
        print("-" * 40)
        for i, kw in enumerate(keywords, 1):
            print(f"  {i:3d}. {kw}")
        print("-" * 40)
        print()

    # 単一キーワードの場合
    if len(keywords) == 1:
        asyncio.run(run_research(keywords[0], headless=headless, diagnose=args.diagnose))
    # 複数キーワードの場合 → 並列処理
    else:
        asyncio.run(run_research_batch(keywords, headless=headless, diagnose=args.diagnose))


if __name__ == "__main__":
    main()
