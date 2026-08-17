"""
Sinh báo cáo HTML tĩnh (bảng xếp hạng RS) từ gia_lich_su_rs.csv
Dùng để publish lên GitHub Pages — không cần Streamlit, không cần server chạy liên tục.

Tính năng biểu đồ:
- Bấm vào 1 mã trong bảng -> hiện biểu đồ nến (candlestick) + khối lượng (volume) của mã đó.
- Bấm vào tên Ngành (hoặc tên Nhóm tập đoàn) -> hiện popup danh sách biểu đồ nến+volume của
  tất cả mã trong ngành/nhóm đó, sắp xếp theo RS giảm dần. Bấm vào 1 biểu đồ trong danh sách
  sẽ phóng to thành biểu đồ chi tiết (dùng lại popup 1 mã).
Toàn bộ dữ liệu OHLCV được nhúng sẵn vào file HTML (dạng JSON) khi build,
nên khi người xem bấm vào mã/ngành, biểu đồ vẽ ngay trên trình duyệt — không cần gọi API lại.
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

BLOCK_SIZE = 30  # dữ liệu theo NGÀY (phiên giao dịch) -> đúng 30 phiên/khối theo công thức gốc
BLOCK_WEIGHTS = [0.4, 0.3, 0.2, 0.1]
DATA_UNIT = "phiên"


def block_period_label(block_index, block_size=BLOCK_SIZE, unit=DATA_UNIT):
    """Sinh tên cột ngắn gọn: 'Khối N – 30 phiên ... (trọng số)'."""
    position_text = {
        1: "gần nhất",
        2: "trước đó",
        3: "trước nữa",
        4: "xa nhất",
    }[block_index]
    weight = BLOCK_WEIGHTS[block_index - 1]
    return f"Khối {block_index} – {block_size} {unit} {position_text} ({weight})"


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
    """Nhúng dữ liệu OHLCV cho từng mã, dạng lightweight-charts yêu cầu.
    Trả về (chart_data, has_ohlc, has_volume)."""
    has_ohlc = all(c in df.columns for c in ["open", "high", "low", "close"])
    has_volume = "volume" in df.columns
    chart_data = {}
    for ticker, g in df.groupby("ticker"):
        g = g.sort_values("date")
        rows = []
        for _, r in g.iterrows():
            if has_ohlc:
                row = {
                    "time": r["date"].strftime("%Y-%m-%d"),
                    "open": round(float(r["open"]), 2),
                    "high": round(float(r["high"]), 2),
                    "low": round(float(r["low"]), 2),
                    "close": round(float(r["close"]), 2),
                }
                if has_volume and pd.notna(r["volume"]):
                    row["volume"] = float(r["volume"])
            else:
                row = {"time": r["date"].strftime("%Y-%m-%d"), "value": round(float(r["close"]), 2)}
            rows.append(row)
        chart_data[ticker] = rows
    return chart_data, has_ohlc, has_volume


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

    # Cột "nhom" (tập đoàn) là tuỳ chọn, chỉ dùng để mở popup xem biểu đồ theo tập đoàn -
    # KHÔNG tham gia tính RS Ngành (khác với "industry" ở trên).
    has_nhom = "nhom" in df.columns
    if has_nhom:
        nhom_map = df.drop_duplicates("ticker").set_index("ticker")["nhom"]
        scores["nhom"] = scores["ticker"].map(nhom_map)

    industry_raw = scores.groupby("industry")["raw_score"].mean().rename("industry_raw_score")
    industry_df = industry_raw.reset_index()
    industry_df["RS_nganh"] = raw_score_to_rs(industry_df["industry_raw_score"])
    industry_df = industry_df.sort_values("RS_nganh", ascending=False)

    # --- Danh sách mã theo Ngành / Nhóm, sắp theo RS giảm dần (dùng cho popup) ---
    # scores đã sort theo RS giảm dần ở trên nên chỉ cần append theo đúng thứ tự duyệt.
    industry_tickers = {}
    for _, r in scores.iterrows():
        industry_tickers.setdefault(r["industry"], []).append({"ticker": r["ticker"], "rs": int(r["RS"])})

    group_tickers = {}
    if has_nhom:
        for _, r in scores.dropna(subset=["nhom"]).iterrows():
            group_tickers.setdefault(r["nhom"], []).append({"ticker": r["ticker"], "rs": int(r["RS"])})

    group_data = {**industry_tickers, **group_tickers}

    chart_data, has_ohlc, has_volume = build_chart_data(df)

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
                <td class="group-cell" onclick="event.stopPropagation(); showGroupPopup('{r['industry']}')">{r['industry']}</td>
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
                <td class="group-cell" onclick="showGroupPopup('{r['industry']}')">{r['industry']}</td>
                <td>{r['industry_raw_score']:.1f}</td>
                <td style="font-weight:bold;color:{rs_color(r['RS_nganh'])}">{r['RS_nganh']}</td>
            </tr>"""
        return rows

    # --- Khu vực link "Xem theo tập đoàn" (chỉ hiện nếu có dữ liệu nhóm) ---
    group_names = sorted(group_tickers.keys())
    if group_names:
        links = " · ".join(
            f'<span class="group-link" onclick="showGroupPopup(\'{name}\')">{name}</span>'
            for name in group_names
        )
        group_links_html = f'<div class="group-links-row">🏢 Xem theo tập đoàn: {links}</div>'
    else:
        group_links_html = ""

    updated_at = datetime.now().strftime("%d/%m/%Y %H:%M")
    chart_data_json = json.dumps(chart_data, ensure_ascii=False)
    group_data_json = json.dumps(group_data, ensure_ascii=False)
    has_ohlc_json = "true" if has_ohlc else "false"
    has_volume_json = "true" if has_volume else "false"

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
  .updated {{ color:#94a3b8; font-size: 13px; margin-bottom: 8px; }}
  .header-row {{ display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; }}
  .refresh-btn {{
    display:inline-flex; align-items:center; gap:8px;
    background:#2563eb; color:#fff; text-decoration:none;
    padding:9px 16px; border-radius:8px; font-size:14px; font-weight:600;
    white-space:nowrap;
  }}
  .refresh-btn:hover {{ background:#1d4ed8; }}
  .refresh-hint {{ color:#64748b; font-size:12px; margin: 4px 0 12px; }}
  .group-links-row {{ color:#93c5fd; font-size:13px; margin: 0 0 24px; }}
  .group-link {{ cursor:pointer; text-decoration:underline dotted; }}
  .group-link:hover {{ color:#bfdbfe; }}
  .formula-box {{ background:#1e293b; border:1px solid #334155; border-radius:10px; padding:16px 20px; margin-bottom:28px; }}
  .formula-title {{ font-size:15px; font-weight:600; margin-bottom:10px; color:#e2e8f0; }}
  .formula-list {{ margin:0; padding-left:20px; color:#cbd5e1; font-size:13px; line-height:1.7; }}
  .formula-list li {{ margin-bottom:4px; }}
  .formula-note {{ margin-top:10px; color:#64748b; font-size:12px; }}
  table {{ width:100%; border-collapse: collapse; margin-bottom: 40px; background:#1e293b; border-radius:8px; overflow:hidden; }}
  th, td {{ padding: 8px 12px; text-align:left; border-bottom:1px solid #334155; font-size: 14px; }}
  th {{ background:#334155; position: sticky; top:0; }}
  .stock-row {{ cursor: pointer; }}
  .stock-row:hover {{ background:#334155; }}
  .ticker-cell {{ font-weight:600; color:#60a5fa; text-decoration: underline; text-decoration-style: dotted; }}
  .group-cell {{ cursor:pointer; color:#93c5fd; text-decoration: underline; text-decoration-style: dotted; }}
  .group-cell:hover {{ color:#bfdbfe; }}
  .section-title {{ font-size: 18px; margin: 24px 0 12px; }}
  .hint {{ color:#64748b; font-size: 12px; margin: -12px 0 16px; }}

  #chart-overlay, #group-overlay {{
    display:none; position:fixed; inset:0; background:rgba(0,0,0,0.6);
    align-items:center; justify-content:center; z-index:50; padding:20px;
  }}
  #chart-panel {{
    background:#1e293b; border-radius:12px; padding:20px; width:min(720px, 92vw);
    box-shadow: 0 20px 60px rgba(0,0,0,0.5);
  }}
  #chart-panel-header, #group-panel-header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }}
  #chart-title, #group-title {{ font-size:18px; font-weight:600; }}
  #chart-close, #group-close {{
    background:#334155; border:none; color:#e2e8f0; width:28px; height:28px;
    border-radius:6px; cursor:pointer; font-size:16px; line-height:1; flex-shrink:0;
  }}
  #chart-close:hover, #group-close:hover {{ background:#475569; }}
  #chart-container {{ width:100%; height:360px; }}

  #group-panel {{
    background:#1e293b; border-radius:12px; padding:20px; width:min(900px, 95vw);
    max-height: 90vh; display:flex; flex-direction:column;
    box-shadow: 0 20px 60px rgba(0,0,0,0.5);
  }}
  #group-list {{ overflow-y:auto; padding-right:4px; }}
  .mini-chart-block {{
    background:#0f172a; border:1px solid #334155; border-radius:10px;
    padding:12px; margin-bottom:14px; cursor:pointer;
  }}
  .mini-chart-block:hover {{ border-color:#60a5fa; }}
  .mini-chart-header {{ font-size:14px; font-weight:600; margin-bottom:8px; color:#e2e8f0; }}
  .mini-chart-container {{ width:100%; height:320px; }}
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
  {group_links_html}

  <div class="formula-box">
    <div class="formula-title">📐 Công thức xếp hạng RS</div>
    <ol class="formula-list">
      <li>Chia dữ liệu giá thành <b>4 khối</b>, mỗi khối <b>30 phiên giao dịch</b> liên tiếp, không chồng lấn (Khối 1 = 30 phiên gần nhất, ... Khối 4 = 30 phiên xa nhất).</li>
      <li>Tính <b>% thay đổi giá</b> của từng khối: %Δ = (Giá cuối khối − Giá đầu khối) / Giá đầu khối.</li>
      <li>Tính <b>Điểm thô</b> mỗi mã = 0.4×%Δ(Khối 1) + 0.3×%Δ(Khối 2) + 0.2×%Δ(Khối 3) + 0.1×%Δ(Khối 4) — khối gần nhất có trọng số cao nhất.</li>
      <li>Xếp hạng tất cả mã theo Điểm thô (cao → thấp), quy đổi <b>RS cổ phiếu</b> (thang 1–99) = ((N − hạng) / N) × 99 + 1, với N = tổng số mã.</li>
      <li><b>Điểm thô Ngành</b> = trung bình cộng Điểm thô của các mã trong ngành.</li>
      <li>Áp dụng lại bước 4 cho các ngành để ra <b>RS Ngành</b> (thang 1–99), với M = tổng số ngành.</li>
    </ol>
    <div class="formula-note">Cần tối thiểu 120 phiên giao dịch (~6 tháng) mỗi mã để tính đủ 4 khối.</div>
  </div>

  <div class="section-title">🏆 Xếp hạng cổ phiếu</div>
  <div class="hint">Bấm vào mã để xem biểu đồ giá · Bấm vào tên ngành để xem biểu đồ tất cả mã trong ngành</div>
  <div class="hint">* Điểm thô = 0.4×(khối gần nhất) + 0.3×(khối tiếp theo) + 0.2×(khối kế) + 0.1×(khối xa nhất) — khối gần nhất được tính trọng số cao nhất vì phản ánh xu hướng giá mới nhất</div>
  <table>
    <tr><th>Mã</th><th>Ngành</th><th>{block_period_label(1)}</th><th>{block_period_label(2)}</th><th>{block_period_label(3)}</th><th>{block_period_label(4)}</th><th>Điểm thô*</th><th>RS</th></tr>
    {stock_rows(scores)}
  </table>

  <div class="section-title">🏭 Xếp hạng ngành</div>
  <div class="hint">Bấm vào tên ngành để xem biểu đồ tất cả mã trong ngành</div>
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

  <div id="group-overlay" onclick="if(event.target===this) closeGroupPopup()">
    <div id="group-panel">
      <div id="group-panel-header">
        <div id="group-title">Danh sách mã</div>
        <button id="group-close" onclick="closeGroupPopup()">✕</button>
      </div>
      <div id="group-list"></div>
    </div>
  </div>

<script>
const CHART_DATA = {chart_data_json};
const GROUP_DATA = {group_data_json};
const HAS_OHLC = {has_ohlc_json};
const HAS_VOLUME = {has_volume_json};

let currentChart = null;      // biểu đồ trong popup 1 mã
let groupCharts = [];         // danh sách biểu đồ mini trong popup ngành/nhóm

function buildPriceChart(container, data, height) {{
  const chart = LightweightCharts.createChart(container, {{
    width: container.clientWidth,
    height: height,
    layout: {{ background: {{ color: '#1e293b' }}, textColor: '#cbd5e1' }},
    grid: {{ vertLines: {{ color: '#334155' }}, horzLines: {{ color: '#334155' }} }},
    timeScale: {{ borderColor: '#475569' }},
    rightPriceScale: {{
      borderColor: '#475569',
      scaleMargins: HAS_VOLUME ? {{ top: 0.1, bottom: 0.3 }} : {{ top: 0.1, bottom: 0.1 }},
    }},
  }});

  if (HAS_OHLC) {{
    const candleSeries = chart.addCandlestickSeries({{
      upColor: '#16a34a', downColor: '#dc2626',
      borderUpColor: '#16a34a', borderDownColor: '#dc2626',
      wickUpColor: '#16a34a', wickDownColor: '#dc2626',
    }});
    candleSeries.setData(data.map(d => ({{ time: d.time, open: d.open, high: d.high, low: d.low, close: d.close }})));

    if (HAS_VOLUME) {{
      const volumeSeries = chart.addHistogramSeries({{
        priceFormat: {{ type: 'volume' }},
        priceScaleId: 'volume',
      }});
      chart.priceScale('volume').applyOptions({{ scaleMargins: {{ top: 0.8, bottom: 0 }} }});
      volumeSeries.setData(data.filter(d => d.volume !== undefined).map(d => ({{
        time: d.time,
        value: d.volume,
        color: d.close >= d.open ? 'rgba(22,163,74,0.5)' : 'rgba(220,38,38,0.5)',
      }})));
    }}
  }} else {{
    const series = chart.addLineSeries({{ color: '#60a5fa', lineWidth: 2 }});
    series.setData(data);
  }}

  chart.timeScale().fitContent();
  return chart;
}}

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

  currentChart = buildPriceChart(container, data, 360);
}}

function closeGroupPopup() {{
  document.getElementById('group-overlay').style.display = 'none';
  groupCharts.forEach(entry => entry.chart.remove());
  groupCharts = [];
  document.getElementById('group-list').innerHTML = '';
}}

function showGroupPopup(name) {{
  const list = GROUP_DATA[name];
  if (!list) return;

  closeChart();
  document.getElementById('group-title').textContent = name + ' (' + list.length + ' mã)';
  document.getElementById('group-overlay').style.display = 'flex';

  const container = document.getElementById('group-list');
  container.innerHTML = '';
  groupCharts.forEach(entry => entry.chart.remove());
  groupCharts = [];

  list.forEach(item => {{
    const data = CHART_DATA[item.ticker];
    if (!data) return;

    const block = document.createElement('div');
    block.className = 'mini-chart-block';
    block.innerHTML = '<div class="mini-chart-header">' + item.ticker + ' — RS: ' + item.rs + '</div>' +
                       '<div class="mini-chart-container"></div>';
    container.appendChild(block);

    block.addEventListener('click', () => {{
      closeGroupPopup();
      showChart(item.ticker);
    }});

    const chartDiv = block.querySelector('.mini-chart-container');
    const chart = buildPriceChart(chartDiv, data, 320);
    groupCharts.push({{ chart: chart, container: chartDiv }});
  }});
}}

window.addEventListener('resize', () => {{
  if (currentChart) {{
    currentChart.applyOptions({{ width: document.getElementById('chart-container').clientWidth }});
  }}
  groupCharts.forEach(entry => {{
    entry.chart.applyOptions({{ width: entry.container.clientWidth }});
  }});
}});
</script>
</body>
</html>"""

    os.makedirs("docs", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    chart_kind = "nến+volume" if (has_ohlc and has_volume) else ("nến" if has_ohlc else "đường (thiếu OHLC đầy đủ)")
    print(f"Đã tạo {OUTPUT_FILE} (kèm biểu đồ {chart_kind}, {len(group_data)} mục ngành/nhóm có popup)")


if __name__ == "__main__":
    main()
