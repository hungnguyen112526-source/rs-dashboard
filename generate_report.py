"""
Sinh báo cáo HTML tĩnh (bảng xếp hạng RS) từ gia_lich_su_rs.csv
Dùng để publish lên GitHub Pages — không cần Streamlit, không cần server chạy liên tục.

Có thêm: bấm vào 1 mã trong bảng -> hiện biểu đồ nến (candlestick) của mã đó.
Toàn bộ dữ liệu OHLCV được nhúng sẵn vào file HTML (dạng JSON) khi build,
nên khi người xem bấm vào mã, biểu đồ vẽ ngay trên trình duyệt — không cần gọi API lại.
"""

import os
import json
import pandas as pd
import numpy as np
from datetime import datetime

INPUT_FILE = "gia_lich_su_rs.csv"
OUTPUT_FILE = "docs/index.html"

# Đổi 2 giá trị này đúng theo tài khoản/repo của bạn để nút "Cập nhật ngay" trỏ đúng chỗ
GITHUB_OWNER = "hungnguyen112526-source"
GITHUB_REPO = "rs-dashboard"
WORKFLOW_FILE = "update_data.yml"
ACTIONS_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{WORKFLOW_FILE}"

BLOCK_SIZE = 4  # dữ liệu hiện là theo TUẦN (mỗi dòng cách nhau 7 ngày) -> 4 tuần/khối ~ 1 tháng
BLOCK_WEIGHTS = [0.4, 0.3, 0.2, 0.1]
DATA_UNIT = "tuần"  # đơn vị của mỗi dòng dữ liệu: "tuần" nếu dữ liệu theo tuần, "phiên" nếu theo ngày


def block_period_label(block_index, block_size=BLOCK_SIZE, unit=DATA_UNIT):
    """Sinh tên cột thể hiện đúng khoảng thời gian & ý nghĩa của khối,
    thay vì chỉ ghi chung chung 'Khối 1', 'Khối 2'..."""
    start = block_size * (block_index - 1) + 1
    end = block_size * block_index
    if block_index == 1:
        return f"% thay đổi giá {block_size} {unit} gần nhất"
    return f"% thay đổi giá {unit} thứ {start}-{end} trước"


def block_return(prices, block_index, block_size=BLOCK_SIZE):
    n = len(prices)
    end_offset = block_size * (block_index - 1)
    start_offset = block_size * block_index
    end_idx = n - 1 - end_offset
    start_idx = n - 1 - start_offset
    if start_idx < 0 or end_idx < 0:
        return np.nan
    end_price = prices.iloc[end_idx]
    start_price = prices.iloc[start_idx]
    return (end_price - start_price) / start_price * 100


def raw_score_to_rs(raw_scores):
    n = len(raw_scores)
    rank = raw_scores.rank(method="min", ascending=False)
    rs = ((n - rank) / n) * 99 + 1
    return rs.round(0).astype(int)


def build_chart_data(df: pd.DataFrame):
    """Nhúng dữ liệu OHLC cho từng mã, dạng lightweight-charts yêu cầu:
    [{time: 'YYYY-MM-DD', open, high, low, close}, ...]"""
    has_ohlc = all(c in df.columns for c in ["open", "high", "low", "close"])
    chart_data = {}
    for ticker, g in df.groupby("ticker"):
        g = g.sort_values("date")
        rows = []
        for _, r in g.iterrows():
            if has_ohlc:
                rows.append({
                    "time": r["date"].strftime("%Y-%m-%d"),
                    "open": round(float(r["open"]), 2),
                    "high": round(float(r["high"]), 2),
                    "low": round(float(r["low"]), 2),
                    "close": round(float(r["close"]), 2),
                })
            else:
                rows.append({"time": r["date"].strftime("%Y-%m-%d"), "value": round(float(r["close"]), 2)})
        chart_data[ticker] = rows
    return chart_data, has_ohlc


def main():
    df = pd.read_csv(INPUT_FILE, parse_dates=["date"])

    records = []
    for ticker, g in df.groupby("ticker"):
        g = g.sort_values("date")
        prices = g["close"].reset_index(drop=True)
        block_returns = [block_return(prices, i) for i in range(1, len(BLOCK_WEIGHTS) + 1)]
        if any(pd.isna(r) for r in block_returns):
            continue
        raw_score = sum(w * r for w, r in zip(BLOCK_WEIGHTS, block_returns))
        record = {"ticker": ticker, "raw_score": raw_score}
        for i, r in enumerate(block_returns, start=1):
            record[f"pct_block{i}"] = r
        records.append(record)

    scores = pd.DataFrame(records)
    if scores.empty:
        raise SystemExit(
            f"Không có mã nào đủ dữ liệu để tính RS. "
            f"Cần tối thiểu {BLOCK_SIZE * len(BLOCK_WEIGHTS)} dòng dữ liệu/mã "
            f"(hiện BLOCK_SIZE={BLOCK_SIZE}). Hãy kiểm tra lại {INPUT_FILE}."
        )
    industry_map = df.drop_duplicates("ticker").set_index("ticker")["industry"]
    scores["industry"] = scores["ticker"].map(industry_map)
    scores["RS"] = raw_score_to_rs(scores["raw_score"])
    scores = scores.sort_values("RS", ascending=False)

    industry_raw = scores.groupby("industry")["raw_score"].mean().rename("industry_raw_score")
    industry_df = industry_raw.reset_index()
    industry_df["RS_nganh"] = raw_score_to_rs(industry_df["industry_raw_score"])
    industry_df = industry_df.sort_values("RS_nganh", ascending=False)

    chart_data, has_ohlc = build_chart_data(df)

    def rs_color(rs):
        if rs >= 80:
            return "#16a34a"
        if rs >= 50:
            return "#ca8a04"
        return "#dc2626"

    def stock_rows(df_):
        rows = ""
        for _, r in df_.iterrows():
            rows += f"""<tr class="stock-row" onclick="showChart('{r['ticker']}')">
                <td class="ticker-cell">{r['ticker']}</td>
                <td>{r['industry']}</td>
                <td>{r['pct_block1']:.1f}%</td>
                <td>{r['pct_block2']:.1f}%</td>
                <td>{r['pct_block3']:.1f}%</td>
                <td>{r['pct_block4']:.1f}%</td>
                <td>{r['raw_score']:.1f}</td>
                <td style="font-weight:bold;color:{rs_color(r['RS'])}">{r['RS']}</td>
            </tr>"""
        return rows

    def industry_rows(df_):
        rows = ""
        for _, r in df_.iterrows():
            rows += f"""<tr>
                <td>{r['industry']}</td>
                <td>{r['industry_raw_score']:.1f}</td>
                <td style="font-weight:bold;color:{rs_color(r['RS_nganh'])}">{r['RS_nganh']}</td>
            </tr>"""
        return rows

    updated_at = datetime.now().strftime("%d/%m/%Y %H:%M")
    chart_data_json = json.dumps(chart_data, ensure_ascii=False)
    series_type = "candlestick" if has_ohlc else "line"

    html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bảng xếp hạng RS chứng khoán</title>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, Arial, sans-serif; background:#0f172a; color:#e2e8f0; margin:0; padding:24px; }}
  h1 {{ font-size: 22px; }}
  .updated {{ color:#94a3b8; font-size: 13px; margin-bottom: 24px; }}
  .header-row {{ display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; }}
  .refresh-btn {{
    display:inline-flex; align-items:center; gap:8px;
    background:#2563eb; color:#fff; text-decoration:none;
    padding:9px 16px; border-radius:8px; font-size:14px; font-weight:600;
    white-space:nowrap;
  }}
  .refresh-btn:hover {{ background:#1d4ed8; }}
  .refresh-hint {{ color:#64748b; font-size:12px; margin: 4px 0 24px; }}
  table {{ width:100%; border-collapse: collapse; margin-bottom: 40px; background:#1e293b; border-radius:8px; overflow:hidden; }}
  th, td {{ padding: 8px 12px; text-align:left; border-bottom:1px solid #334155; font-size: 14px; }}
  th {{ background:#334155; position: sticky; top:0; }}
  .stock-row {{ cursor: pointer; }}
  .stock-row:hover {{ background:#334155; }}
  .ticker-cell {{ font-weight:600; color:#60a5fa; text-decoration: underline; text-decoration-style: dotted; }}
  .section-title {{ font-size: 18px; margin: 24px 0 12px; }}
  .hint {{ color:#64748b; font-size: 12px; margin: -12px 0 16px; }}

  #chart-overlay {{
    display:none; position:fixed; inset:0; background:rgba(0,0,0,0.6);
    align-items:center; justify-content:center; z-index:50;
  }}
  #chart-panel {{
    background:#1e293b; border-radius:12px; padding:20px; width:min(720px, 92vw);
    box-shadow: 0 20px 60px rgba(0,0,0,0.5);
  }}
  #chart-panel-header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }}
  #chart-title {{ font-size:18px; font-weight:600; }}
  #chart-close {{
    background:#334155; border:none; color:#e2e8f0; width:28px; height:28px;
    border-radius:6px; cursor:pointer; font-size:16px; line-height:1;
  }}
  #chart-close:hover {{ background:#475569; }}
  #chart-container {{ width:100%; height:360px; }}
</style>
</head>
<body>
  <div class="header-row">
    <h1>📈 Bảng xếp hạng RS chứng khoán</h1>
    <a class="refresh-btn" href="{ACTIONS_URL}" target="_blank" rel="noopener">
      🔄 Cập nhật dữ liệu & tính lại RS
    </a>
  </div>
  <div class="updated">Cập nhật lần cuối: {updated_at}</div>
  <div class="refresh-hint">Nút trên mở trang GitHub Actions — bấm "Run workflow" ở đó để lấy dữ liệu mới nhất và tính lại RS ngay (cần đăng nhập GitHub với quyền chủ repo).</div>

  <div class="section-title">🏆 Xếp hạng cổ phiếu</div>
  <div class="hint">Bấm vào mã để xem biểu đồ giá</div>
  <div class="hint">* Điểm thô = 0.4×(khối gần nhất) + 0.3×(khối tiếp theo) + 0.2×(khối kế) + 0.1×(khối xa nhất) — khối gần nhất được tính trọng số cao nhất vì phản ánh xu hướng giá mới nhất</div>
  <table>
    <tr><th>Mã</th><th>Ngành</th><th>{block_period_label(1)}</th><th>{block_period_label(2)}</th><th>{block_period_label(3)}</th><th>{block_period_label(4)}</th><th>Điểm thô*</th><th>RS</th></tr>
    {stock_rows(scores)}
  </table>

  <div class="section-title">🏭 Xếp hạng ngành</div>
  <table>
    <tr><th>Ngành</th><th>Điểm thô Ngành</th><th>RS Ngành</th></tr>
    {industry_rows(industry_df)}
  </table>

  <div id="chart-overlay" onclick="if(event.target===this) closeChart()">
    <div id="chart-panel">
      <div id="chart-panel-header">
        <div id="chart-title">Biểu đồ giá</div>
        <button id="chart-close" onclick="closeChart()">✕</button>
      </div>
      <div id="chart-container"></div>
    </div>
  </div>

<script>
const CHART_DATA = {chart_data_json};
const SERIES_TYPE = "{series_type}";
let currentChart = null;

function closeChart() {{
  document.getElementById('chart-overlay').style.display = 'none';
  if (currentChart) {{ currentChart.remove(); currentChart = null; }}
}}

function showChart(ticker) {{
  const data = CHART_DATA[ticker];
  if (!data) return;

  document.getElementById('chart-title').textContent = ticker + ' — Biểu đồ giá';
  document.getElementById('chart-overlay').style.display = 'flex';

  const container = document.getElementById('chart-container');
  container.innerHTML = '';
  if (currentChart) {{ currentChart.remove(); }}

  currentChart = LightweightCharts.createChart(container, {{
    width: container.clientWidth,
    height: 360,
    layout: {{ background: {{ color: '#1e293b' }}, textColor: '#cbd5e1' }},
    grid: {{ vertLines: {{ color: '#334155' }}, horzLines: {{ color: '#334155' }} }},
    timeScale: {{ borderColor: '#475569' }},
    rightPriceScale: {{ borderColor: '#475569' }},
  }});

  if (SERIES_TYPE === "candlestick") {{
    const series = currentChart.addCandlestickSeries({{
      upColor: '#16a34a', downColor: '#dc2626',
      borderUpColor: '#16a34a', borderDownColor: '#dc2626',
      wickUpColor: '#16a34a', wickDownColor: '#dc2626',
    }});
    series.setData(data);
  }} else {{
    const series = currentChart.addLineSeries({{ color: '#60a5fa', lineWidth: 2 }});
    series.setData(data);
  }}

  currentChart.timeScale().fitContent();
}}

window.addEventListener('resize', () => {{
  if (currentChart) {{
    currentChart.applyOptions({{ width: document.getElementById('chart-container').clientWidth }});
  }}
}});
</script>
</body>
</html>"""

    os.makedirs("docs", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Đã tạo {OUTPUT_FILE} (kèm biểu đồ {'nến' if has_ohlc else 'đường (thiếu OHLC đầy đủ)'})")


if __name__ == "__main__":
    main()
