# Amazon商品リサーチ・中国輸入ツール強化 API/OSS調査レポート
作成日: 2026-02-22

---

## 1. 問いの再定義と調査観点

### 問いの再定義
現行ツール（Amazon-1688リサーチシステム）は、Playwright + OpenCV + imagehash による
ブラウザ自動化・画像マッチングを核としている。これをAPI/OSSで強化するにあたり、
「コスト対効果が高く、Python統合が容易で、現行アーキテクチャと衝突しない」ものを選定する。

### 調査論点（5軸）
1. Amazon商品データ取得・価格追跡API（現行scraperの代替・補完）
2. 1688/Alibaba連携API（現行1688モジュールの補完）
3. 画像マッチング・類似検索AI（現行phash/ORBの高精度化）
4. 需要予測・キーワードリサーチ（新機能追加）
5. OCR/翻訳（中日）（現行の手動コピペ工程を自動化）

---

## 2. プラットフォーム別 調査結果

---

### 2-1. RapidAPI（API世界最大マーケットプレイス）

#### A. Real-Time Amazon Data API
- **URL**: https://rapidapi.com/letscrape-6bRBa3QguO5/api/real-time-amazon-data
- **提供元**: letscrape
- **機能**: 商品検索・詳細・レビュー・ベストセラー・ディール・セラーデータをリアルタイム取得
- **料金**: 無料プランあり（月500リクエスト程度）、有料$29/月〜
- **Python**: requests/httpx で即座に統合可能
- **統合案**: `src/modules/amazon/scraper.py` の代替として、Playwright不要でAmazon商品データを高速取得。Playwright検出回避コストを削減
- **優先度**: 高

#### B. Amazon Product/Reviews/Keywords API
- **URL**: https://rapidapi.com/logicbuilder/api/amazon-product-reviews-keywords
- **機能**: 商品検索・レビュー・キーワードリサーチを16カ国対応で提供
- **料金**: 無料枠あり
- **Python**: 標準requests対応
- **統合案**: `src/modules/amazon/suggest.py` のキーワード候補取得を強化。現在の実装を補完する形でキーワードボリューム・競合度データを追加
- **優先度**: 高

#### C. Amazon Historical Price API
- **URL**: https://rapidapi.com/solo-xwz/api/amazon-historical-price
- **機能**: ASIN指定で過去価格推移を取得
- **料金**: 要確認（無料枠なし可能性あり）
- **Python**: requests対応
- **統合案**: 現行の `calculator/` モジュールに価格トレンド分析機能を追加。FBA利益計算の精度向上
- **優先度**: 中

#### D. Otapi 1688 API
- **URL**: https://rapidapi.com/open-trade-commerce-open-trade-commerce-default/api/otapi-1688
- **機能**: キーワード検索・**画像検索**・商品詳細取得（1688.com）
- **料金**: 有料、プラン詳細はRapidAPI要確認
- **Python**: requests対応
- **統合案**: 現行の `src/modules/alibaba/` における1688スクレイパーの安定化。特に画像検索機能は既存のphash/ORBマッチングを強化できる
- **優先度**: 高

#### E. 1688 API (gabrielius.u)
- **URL**: https://rapidapi.com/gabrielius.u/api/16881
- **機能**: 1688.com商品データ取得
- **料金**: 無料プランあり
- **Python**: requests対応
- **統合案**: Otapiの代替/補完として1688データ取得の冗長化
- **優先度**: 中

#### F. Price Tracking Tools API
- **URL**: https://rapidapi.com/apidojo/api/price-tracking-tools
- **機能**: Amazonを含む複数ECの価格追跡
- **料金**: 有料
- **Python**: requests対応
- **統合案**: ライバル商品の価格モニタリング機能として追加
- **優先度**: 中

#### G. Real-Time Image Search / Reverse Image Search API
- **URL**: https://rapidapi.com/letscrape-6bRBa3QguO5/api/real-time-image-search
- **URL**: https://rapidapi.com/letscrape-6bRBa3QguO5/api/reverse-image-search1
- **機能**: 画像の逆引き検索（Google画像検索相当）
- **料金**: 無料枠あり
- **Python**: requests対応
- **統合案**: `src/modules/matcher/` の補完として、Amazon商品画像から1688類似商品を逆引き検索
- **優先度**: 高

---

### 2-2. Hugging Face（AIモデル最大ハブ）

#### A. openai/clip-vit-base-patch32（画像類似検索）
- **URL**: https://huggingface.co/openai/clip-vit-base-patch32
- **機能**: テキスト・画像の双方向エンベディング。画像→類似画像検索、テキスト→画像検索
- **料金**: 完全無料（OSS）
- **Python**: `pip install transformers torch` で統合
- **統合案**: 現行の `phash.py`（知覚ハッシュ）・`smart.py`（ORB特徴量）の上位レイヤーとして追加。ECサイト間の商品マッチング精度を大幅向上。FAISSと組み合わせてベクトル検索化
- **優先度**: 高

```python
# 統合イメージ
from transformers import CLIPProcessor, CLIPModel
model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
```

#### B. Trendyol/trendyol-dino-v2-ecommerce-256d（EC特化画像エンベディング）
- **URL**: https://huggingface.co/Trendyol/trendyol-dino-v2-ecommerce-256d
- **機能**: EC商品画像に特化したDinoV2ファインチューン。256次元エンベディング
- **料金**: 完全無料（OSS）
- **Python**: transformers対応
- **統合案**: CLIPよりも軽量・EC特化。商品マッチングの精度と速度のバランスが良い。256次元なのでFAISSのメモリ効率も高い
- **優先度**: 高

#### C. patrickjohncyh/fashion-clip（ファッション・商品特化CLIP）
- **URL**: https://huggingface.co/patrickjohncyh/fashion-clip
- **機能**: ファッション商品に特化したCLIP。色・テクスチャ・スタイルを正確に識別
- **料金**: 完全無料（OSS）
- **Python**: transformers対応
- **統合案**: アパレル・雑貨カテゴリの商品マッチング精度向上
- **優先度**: 中

#### D. Adnan-AI-Labs/DistilBERT-ProductClassifier（商品カテゴリ分類）
- **URL**: https://huggingface.co/Adnan-AI-Labs/DistilBERT-ProductClassifier
- **機能**: 商品タイトル・説明文からカテゴリを自動分類（CPU/カメラ/食洗機等）
- **料金**: 完全無料（OSS）
- **Python**: transformers対応
- **統合案**: リサーチ結果の自動カテゴリ分類。フィルター精度向上（`src/modules/amazon/filter.py`）
- **優先度**: 中

#### E. amazon/chronos-2（需要予測）
- **URL**: https://huggingface.co/amazon/chronos-2
- **機能**: Amazon開発の時系列予測基盤モデル。120Mパラメータ。ゼロショット需要予測対応
- **料金**: 完全無料（OSS）
- **Python**: `pip install chronos-forecasting`
- **統合案**: 販売ランキングや価格推移の時系列データから需要予測を実施。「今が仕入れ時か」の判断支援機能として追加
- **優先度**: 中

```python
# 統合イメージ
import chronos
pipeline = chronos.BaseChronosPipeline.from_pretrained("amazon/chronos-2")
```

#### F. google/timesfm-1.0-200m（需要予測・代替）
- **URL**: https://huggingface.co/google/timesfm-1.0-200m
- **機能**: Google Research開発の時系列予測基盤モデル。1000億実世界データポイントで事前学習
- **料金**: 完全無料（OSS）
- **Python**: transformers統合済み
- **統合案**: Chronos-2の代替。週次・月次の価格・売上トレンド予測
- **優先度**: 低

#### G. PP-OCRv5（多言語OCR）
- **URL**: https://huggingface.co/blog/baidu/ppocrv5
- **機能**: 簡体字中国語・繁体字・英語・日本語対応OCR。手書き・印刷両対応
- **料金**: 完全無料（OSS、PaddleOCR経由）
- **Python**: `pip install paddlepaddle paddleocr`
- **統合案**: 1688の商品画像内テキスト（スペック表・サイズ表）のOCR自動抽出。現在の手動コピペを自動化
- **優先度**: 高

#### H. Qwen2-VL-OCR-2B-Instruct（マルチモーダルOCR）
- **URL**: https://huggingface.co/prithivMLmods/Qwen2-VL-OCR-2B-Instruct
- **機能**: 画像内テキスト認識・理解。中国語・日本語・英語対応
- **料金**: 完全無料（OSS）
- **Python**: transformers対応
- **統合案**: 1688商品画像からスペック情報を自動抽出・構造化
- **優先度**: 中

---

### 2-3. GitHub public-apis（無料APIコレクション）
- **URL**: https://github.com/public-apis/public-apis

調査対象カテゴリ内で現行ツールに直接統合できる実用的APIの確認結果：

#### A. LibreTranslate（中日翻訳）
- **URL**: https://libretranslate.com/
- **機能**: 80言語対応のOSS翻訳API。セルフホスト可能、APIキー不要
- **料金**: 完全無料（セルフホスト）または公開インスタンス利用
- **Python**: requests で即座に統合可能
- **統合案**: 1688商品タイトル・説明文の中国語→日本語自動翻訳。現行の手動翻訳作業を自動化

```python
import requests
response = requests.post("https://libretranslate.com/translate",
    json={"q": "商品名", "source": "zh", "target": "ja"})
```
- **優先度**: 高

#### B. OCR.space（画像OCR）
- **URL**: https://ocr.space/
- **機能**: 無料OCR API。中国語含む多言語対応
- **料金**: 無料（月25,000リクエスト）、有料プランあり
- **Python**: requests対応
- **統合案**: PP-OCRv5のクラウド代替として、ローカルリソース不要で1688画像のテキスト抽出
- **優先度**: 中

---

### 2-4. Libraries.io（OSSパッケージ）

#### A. keepa Python API
- **URL**: https://github.com/akaszynski/keepa / https://pypi.org/project/keepa/
- **機能**: Keepa.com APIのPythonラッパー。Amazon全商品の価格推移・ランキング推移・セラー情報を取得
- **料金**: Keepa API購読料 €19/月（約3,000円）。トークン制（1トークン/分 = 1商品）
- **Python**: `pip install keepa`（Python 3.10以上）
- **統合案**: `src/modules/amazon/` に価格推移取得モジュールを追加。現行のリアルタイム価格取得に過去180日のトレンドを付加。FBA利益計算の精度が大幅向上

```python
import keepa
api = keepa.Keepa('YOUR_API_KEY')
products = api.query(['ASIN1234'], history=True)
```
- **優先度**: 高（コスト対効果が最も高い有料サービス）

#### B. amazon-product-scraper-with-python
- **URL**: https://libraries.io/pypi/amazon-product-scraper-with-python
- **機能**: Amazon商品データのPythonスクレイパー
- **料金**: 無料（OSS）
- **Python**: pip installで利用可
- **統合案**: 現行scraperの参考実装として活用。ただしメンテナンス状態要確認
- **優先度**: 低

#### C. oxylabs/1688-scraper
- **URL**: https://github.com/oxylabs/1688-scraper
- **機能**: Oxylabs社提供の1688スクレイパー（要Oxylabs APIキー）
- **料金**: Oxylabs APIは有料（$49/月〜）
- **Python**: Python対応
- **統合案**: 現行1688モジュールの安定化。ただしコスト高のため中優先度
- **優先度**: 低

---

### 2-5. Apify Store（Apifyアクター）

#### A. Amazon Scraper（Free Amazon Product Scraper）
- **URL**: https://apify.com/junglee/free-amazon-product-scraper
- **機能**: Amazon商品データ・レビュー・価格をスクレイプ。4,000件/$0.25の従量課金
- **料金**: 無料枠月$5クレジット、Starter $39/月〜
- **Python**: `pip install apify-client`
- **統合案**: Playwright不要でAmazon商品データを安定取得。IP規制リスクをApify側に転嫁

```python
from apify_client import ApifyClient
client = ApifyClient("YOUR_TOKEN")
run = client.actor("junglee/free-amazon-product-scraper").call(
    run_input={"keyword": "wireless earbuds", "country": "JP"})
```
- **優先度**: 高

#### B. 1688 Product Search Scraper（MCPサーバー対応）
- **URL**: https://apify.com/ecomscrape/1688-product-search-scraper
- **機能**: 1688.com商品検索・詳細取得。MCPサーバーとして直接AI連携も可能
- **料金**: 従量課金（月$5無料枠内で試用可）
- **Python**: apify-client対応
- **統合案**: 現行の1688スクレイパーの代替。Playwright依存を排除してIP規制リスクを低減。MCPサーバーとしてClaude Codeから直接呼び出しも可能
- **優先度**: 高

#### C. 1688 Product Details Scraper
- **URL**: https://apify.com/ecomscrape/1688-product-details-page-scraper
- **機能**: 1688商品詳細ページから仕様・サプライヤー・価格を取得
- **料金**: 従量課金
- **Python**: apify-client対応
- **統合案**: 商品URL指定での詳細データ取得（現行の詳細ページスクレイプ代替）
- **優先度**: 中

#### D. 1688.com Search Scraper（B2B価格・バルクデータ）
- **URL**: https://apify.com/songd/1688-search-scraper
- **機能**: 1688の価格・スペック・サプライヤー・在庫情報を一括取得
- **料金**: 従量課金
- **Python**: apify-client対応
- **統合案**: バルク商品調査の自動化
- **優先度**: 中

#### E. Scrape Alibaba Products
- **URL**: https://apify.com/shareze001/scrape-alibaba-item
- **機能**: Alibaba.com商品リスト・価格・評価・レビューを取得
- **料金**: 従量課金
- **Python**: apify-client対応
- **統合案**: 1688に加えAlibaba.comも調査対象に追加できる
- **優先度**: 低

---

## 3. 統合優先度マトリクス

| 優先度 | ツール/API | 機能強化領域 | コスト | 実装難易度 |
|--------|-----------|------------|--------|-----------|
| 高 | Keepa Python API | 価格推移・ランキング追跡 | €19/月 | 低 |
| 高 | openai/clip-vit-base-patch32 | 画像マッチング精度向上 | 無料 | 中 |
| 高 | Trendyol DINOv2 ecommerce | EC特化画像マッチング | 無料 | 中 |
| 高 | PP-OCRv5（PaddleOCR） | 中国語OCR自動化 | 無料 | 中 |
| 高 | LibreTranslate | 中日翻訳自動化 | 無料 | 低 |
| 高 | Apify Amazon Scraper | Amazon取得の安定化 | $5無料枠〜 | 低 |
| 高 | Apify 1688 Scraper | 1688取得の安定化 | $5無料枠〜 | 低 |
| 高 | Otapi 1688 API (RapidAPI) | 1688画像検索 | 有料（要確認） | 低 |
| 高 | RapidAPI Reverse Image Search | 商品画像逆引き検索 | 無料枠あり | 低 |
| 中 | amazon/chronos-2 | 需要予測 | 無料 | 高 |
| 中 | DistilBERT-ProductClassifier | 自動カテゴリ分類 | 無料 | 中 |
| 中 | SerpApi Amazon API | キーワード・検索データ | $75/月〜 | 低 |
| 中 | Amazon Historical Price (RapidAPI) | 価格履歴 | 有料 | 低 |
| 低 | google/timesfm-1.0-200m | 需要予測（代替） | 無料 | 高 |
| 低 | oxylabs/1688-scraper | 1688スクレイプ | $49/月〜 | 中 |

---

## 4. 即時実装推奨ロードマップ

### Phase 1（今週中・無料で実装可能）
1. **LibreTranslate統合**: 1688タイトル・説明の自動翻訳
   - 対象: `src/modules/alibaba/` に `translator.py` 追加
   - 工数: 2時間

2. **PP-OCRv5統合**: 1688商品画像からのスペック自動抽出
   - 対象: `src/modules/alibaba/` に `ocr.py` 追加
   - 工数: 4時間

### Phase 2（来週・CLIP/DINOv2統合）
3. **CLIP/DINOv2画像マッチング**: 現行phash/ORBの精度向上
   - 対象: `src/modules/matcher/` に `clip_matcher.py` 追加
   - FAISSでベクトルインデックス化
   - 工数: 1日

### Phase 3（来週・価格データ強化）
4. **Keepa API統合**: 価格推移・ランキング追跡
   - 対象: `src/modules/amazon/` に `price_history.py` 追加
   - 工数: 半日（€19/月のサブスク必要）

### Phase 4（月内・スクレイピング安定化）
5. **Apify Amazon/1688 Scraper統合**: Playwright依存の段階的解消
   - 対象: 既存scraper.pyのラッパーとして追加
   - 工数: 1日

---

## 5. 結論

### 最重要発見事項
- **Keepa Python API**は月€19で既存ツールに最大の価値を追加できる。価格推移・ランキング追跡はFBA利益予測の精度を根本的に改善する
- **CLIP/DINOv2**（HuggingFace）は完全無料で現行のphash/ORBマッチングを大幅に超える精度を実現できる。EC特化DINOv2（Trendyol）は実装の最優先候補
- **Apify**の$5無料枠で1688・Amazon両方のスクレイピングをPlaywright不要で試験運用できる。IP規制リスクを外部化できる点が大きい
- **PP-OCRv5 + LibreTranslate**の組み合わせで、1688の中国語コンテンツ処理を完全自動化できる（両方無料）

### 重要ポイント
1. 無料で最大インパクト: CLIP/DINOv2（画像マッチング精度）+ PP-OCRv5（OCR）+ LibreTranslate（翻訳）
2. 最良の有料投資: Keepa API（€19/月）- ROIが最も高い
3. リスク軽減: Apify Amazon/1688 Scraper（$5無料枠〜）でPlaywright依存を段階的解消

### 未解決/追加調査事項
- Otapi 1688 APIの具体的な料金体系（要RapidAPIでの確認）
- CLIP vs DINOv2 の実際の商品マッチング精度比較実験
- Chronos-2による需要予測の実用性検証（Amazonランキングデータとの相関分析）
- amazon/chronos-2のCPU推論速度（GPU不要で実用的か）
- SerpApi（$75/月〜）がKeepa + RapidAPI無料枠の組み合わせに対して優位性があるか

---

## 6. 主要出典

- RapidAPI Amazon Collection: https://rapidapi.com/collection/amazon-products
- RapidAPI Real-Time Amazon Data: https://rapidapi.com/letscrape-6bRBa3QguO5/api/real-time-amazon-data
- RapidAPI Otapi 1688: https://rapidapi.com/open-trade-commerce-open-trade-commerce-default/api/otapi-1688
- RapidAPI 1688 API: https://rapidapi.com/gabrielius.u/api/16881
- RapidAPI Amazon Keywords: https://rapidapi.com/logicbuilder/api/amazon-product-reviews-keywords
- RapidAPI Reverse Image Search: https://rapidapi.com/letscrape-6bRBa3QguO5/api/reverse-image-search1
- HuggingFace CLIP: https://huggingface.co/openai/clip-vit-base-patch32
- HuggingFace Trendyol DINOv2: https://huggingface.co/Trendyol/trendyol-dino-v2-ecommerce-256d
- HuggingFace FashionCLIP: https://huggingface.co/patrickjohncyh/fashion-clip
- HuggingFace DistilBERT ProductClassifier: https://huggingface.co/Adnan-AI-Labs/DistilBERT-ProductClassifier
- HuggingFace Chronos-2: https://huggingface.co/amazon/chronos-2
- HuggingFace TimesFM: https://huggingface.co/google/timesfm-1.0-200m
- HuggingFace PP-OCRv5: https://huggingface.co/blog/baidu/ppocrv5
- HuggingFace Image Similarity Blog: https://huggingface.co/blog/image-similarity
- GitHub public-apis: https://github.com/public-apis/public-apis
- GitHub Keepa Python: https://github.com/akaszynski/keepa
- PyPI keepa: https://pypi.org/project/keepa/
- GitHub oxylabs 1688: https://github.com/oxylabs/1688-scraper
- Apify Amazon Scraper: https://apify.com/junglee/free-amazon-product-scraper
- Apify 1688 Search Scraper: https://apify.com/ecomscrape/1688-product-search-scraper
- Apify 1688 Details Scraper: https://apify.com/ecomscrape/1688-product-details-page-scraper
- Apify MCP Server GitHub: https://github.com/apify/apify-mcp-server
- SerpApi Amazon: https://serpapi.com/amazon-search-api
- Keepa Pricing Guide: https://revenuegeeks.com/keepa-pricing/
- FAISS + CLIP Tutorial: https://huggingface.co/learn/cookbook/en/faiss_with_hf_datasets_and_clip
