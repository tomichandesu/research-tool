"""1688候補HTMLビューアー生成モジュール

Amazon商品と1688候補を横並びで表示し、
人間が目視で同一商品の有無を確認できるHTMLビューアーを生成する。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class HtmlCandidateReport:
    """1688候補のHTMLビューアージェネレーター"""

    def generate(
        self,
        keyword: str,
        products_data: list[dict],
        output_dir: str = "output",
    ) -> str:
        """HTMLビューアーを生成

        Args:
            keyword: 検索キーワード
            products_data: 商品候補データのリスト
            output_dir: 出力ディレクトリ

        Returns:
            生成したHTMLファイルのパス
        """
        data = {
            "keyword": keyword,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "products": products_data,
        }

        json_data = json.dumps(data, ensure_ascii=True)
        html = _HTML_TEMPLATE.replace("__DATA_PLACEHOLDER__", json_data)

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = output_path / f"candidates_{keyword}_{timestamp}.html"

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

        logger.info(f"HTMLビューアー生成: {filepath}")
        return str(filepath)


_HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>1688 商品マッチング候補ビューアー</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI','Meiryo','Hiragino Sans',sans-serif;background:#f0f2f5;color:#333;padding:20px}
.header{text-align:center;margin-bottom:32px;padding:24px;background:#fff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.header h1{font-size:22px;color:#1a1a2e;margin-bottom:8px}
.header .stats{font-size:14px;color:#666}
.header .guide{font-size:13px;color:#888;margin-top:12px;line-height:1.6}

.product-card{background:#fff;border-radius:12px;padding:24px;margin-bottom:24px;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.product-num{display:inline-block;background:#1a1a2e;color:#fff;font-size:12px;font-weight:bold;padding:2px 10px;border-radius:12px;margin-bottom:12px}

.amazon-section{display:flex;gap:16px;padding-bottom:16px;border-bottom:1px solid #eee;margin-bottom:16px}
.amazon-img{width:130px;height:130px;object-fit:contain;border:1px solid #eee;border-radius:8px;background:#fafafa;flex-shrink:0}
.amazon-info{flex:1;min-width:0}
.amazon-info h3{font-size:14px;color:#333;margin-bottom:8px;line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.amazon-price{font-size:20px;font-weight:bold;color:#B12704;margin-bottom:6px}
.amazon-details{font-size:12px;color:#666;line-height:1.8}
.amazon-details span{display:inline-block;margin-right:12px}
.amazon-link{font-size:12px;color:#0066c0;text-decoration:none;margin-top:4px;display:inline-block}
.amazon-link:hover{text-decoration:underline}

.candidates-label{font-size:13px;font-weight:bold;color:#555;margin-bottom:12px}
.candidates{display:flex;gap:12px;flex-wrap:wrap}

.candidate{border:2px solid #e0e0e0;border-radius:10px;padding:10px;width:175px;transition:all .15s;background:#fff}
.candidate:hover{border-color:#90CAF9;transform:translateY(-2px);box-shadow:0 4px 12px rgba(0,0,0,.1)}
.candidate-img{width:100%;height:140px;object-fit:contain;border-radius:6px;background:#fafafa;display:block}
.candidate-img-error{width:100%;height:140px;display:flex;align-items:center;justify-content:center;background:#f5f5f5;border-radius:6px;color:#bbb;font-size:12px}
.candidate-price{font-size:16px;font-weight:bold;color:#c62828;margin:8px 0 4px}
.candidate-profit{font-size:13px;font-weight:bold;margin-bottom:4px}
.candidate-profit.good{color:#2E7D32}
.candidate-profit.mid{color:#F57F17}
.candidate-profit.low{color:#c62828}
.candidate-detail{font-size:11px;color:#888;margin-bottom:4px}
.candidate-link{font-size:11px;color:#1565C0;text-decoration:none;word-break:break-all;display:block;margin-top:4px}
.candidate-link:hover{text-decoration:underline}
.candidate-shop{font-size:10px;color:#999;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.no-candidates{color:#999;font-size:13px;padding:20px;text-align:center;background:#f9f9f9;border-radius:8px;border:1px dashed #ddd}
.product-card.no-cand{background:#fafafa;border-left:3px solid #ddd}
</style>
</head>
<body>

<div class="header">
  <h1>1688 商品マッチング候補ビューアー</h1>
  <div class="stats" id="statsLine"></div>
  <div class="guide">
    Amazon商品と1688候補の画像を比較して、同一商品があるか目視で確認できます。<br>
    候補画像の下にあるリンクから1688の商品ページを直接開けます。
  </div>
</div>

<div id="products"></div>

<script>
const DATA = __DATA_PLACEHOLDER__;

function init() {
  var withCandidates = DATA.products.filter(function(p) { return p.candidates && p.candidates.length > 0; }).length;
  document.getElementById('statsLine').textContent =
    'キーワード: ' + DATA.keyword + ' | フィルター通過: ' + DATA.products.length + '件 | 候補あり: ' + withCandidates + '件 | 生成: ' + DATA.generated_at;
  const container = document.getElementById('products');
  DATA.products.forEach(function(product, pi) {
    container.appendChild(buildCard(product, pi));
  });
}

function buildCard(product, pi) {
  const card = document.createElement('div');
  var hasCandidates = product.candidates && product.candidates.length > 0;
  card.className = 'product-card' + (hasCandidates ? '' : ' no-cand');

  const am = product.amazon;
  const dims = am.dimensions ? am.dimensions[0]+'x'+am.dimensions[1]+'x'+am.dimensions[2]+'cm' : '-';
  const weight = am.weight_kg ? am.weight_kg+'kg' : '-';

  let html = '<span class="product-num">#' + (pi+1) + '</span>';
  html += '<div class="amazon-section">';
  html += '<img class="amazon-img" src="' + escHtml(am.image_url) + '" onerror="this.style.display=\'none\'">';
  html += '<div class="amazon-info">';
  html += '<h3>' + escHtml(am.title) + '</h3>';
  html += '<div class="amazon-price">&yen;' + num(am.price) + '</div>';
  html += '<div class="amazon-details">';
  html += '<span>ASIN: ' + am.asin + '</span>';
  html += '<span>BSR: ' + num(am.bsr) + '</span>';
  html += '<span>レビュー: ' + am.review_count + '件</span>';
  if (am.rating) html += '<span>★' + am.rating + '</span>';
  html += '<span>FBA: ' + (am.is_fba ? '○' : '×') + '</span>';
  html += '<span>バリエ: ' + (am.variation_count || 1) + '</span>';
  html += '<span>寸法: ' + dims + '</span>';
  html += '<span>重量: ' + weight + '</span>';
  html += '</div>';
  html += '<div class="amazon-details"><span>月間販売: ' + num(product.estimated_monthly_sales) + '個</span>';
  html += '<span>月間売上: &yen;' + num(product.estimated_monthly_revenue) + '</span></div>';
  html += '<a class="amazon-link" href="' + escHtml(am.product_url || ('https://www.amazon.co.jp/dp/' + am.asin)) + '" target="_blank">Amazon で見る &rarr;</a>';
  html += '</div></div>';

  if (product.candidates && product.candidates.length > 0) {
    html += '<div class="candidates-label">1688 候補 (' + product.candidates.length + '件)</div>';
    html += '<div class="candidates">';

    product.candidates.forEach(function(cand) {
      var profitPct = cand.profit.profit_rate_percentage;
      var profitClass = profitPct >= 25 ? 'good' : profitPct >= 15 ? 'mid' : 'low';
      html += '<div class="candidate">';
      html += '<img class="candidate-img" src="' + escHtml(cand.alibaba.image_url) + '" onerror="this.outerHTML=\'<div class=candidate-img-error>画像読込失敗</div>\'">';
      var score = cand.combined_score != null ? (cand.combined_score * 100).toFixed(1) + '%' : '-';
      var orbPct = cand.orb_similarity != null ? (cand.orb_similarity * 100).toFixed(1) : '-';
      var histPct = cand.hist_similarity != null ? (cand.hist_similarity * 100).toFixed(1) : '-';
      var scoreColor = cand.combined_score >= 0.3 ? '#2E7D32' : cand.combined_score >= 0.15 ? '#F57F17' : '#c62828';
      html += '<div class="candidate-detail" style="font-weight:bold;color:' + scoreColor + '">類似度: ' + score + ' (ORB:' + orbPct + ' 色:' + histPct + ')</div>';
      html += '<div class="candidate-price">' + cand.alibaba.price_cny + '元 (&yen;' + num(Math.round(cand.alibaba.price_cny * 23)) + ')</div>';
      html += '<div class="candidate-profit ' + profitClass + '">利益: &yen;' + num(cand.profit.profit) + ' (' + profitPct + '%)</div>';
      html += '<div class="candidate-detail">総コスト: &yen;' + num(cand.profit.total_cost) + '</div>';
      if (cand.alibaba.shop_name) html += '<div class="candidate-shop">' + escHtml(cand.alibaba.shop_name) + '</div>';
      html += '<a class="candidate-link" href="' + escHtml(cand.alibaba.product_url) + '" target="_blank">1688で見る &rarr;</a>';
      html += '</div>';
    });

    html += '</div>';
  } else {
    html += '<div class="no-candidates">1688候補なし';
    if (product.no_candidates_reason) {
      html += ' &mdash; ' + escHtml(product.no_candidates_reason);
    }
    html += '</div>';
  }
  card.innerHTML = html;
  return card;
}

function escHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function num(n) {
  if (n == null) return '-';
  return Number(n).toLocaleString();
}

init();
</script>
</body>
</html>'''
