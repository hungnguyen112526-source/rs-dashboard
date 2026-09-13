"""
Sinh báo cáo HTML tĩnh (bảng xếp hạng RS) từ gia_lich_su_rs.csv
Dùng để publish lên GitHub Pages — không cần Streamlit, không cần server chạy liên tục.

Tính năng:
- Bấm vào 1 mã trong bảng -> hiện biểu đồ nến (candlestick) + khối lượng (volume) của mã đó,
  có nút chuyển đổi Ngày/Tuần.
- Bấm vào tên Ngành (hoặc tên Nhóm tập đoàn) -> popup danh sách biểu đồ nến+volume của tất cả
  mã trong ngành/nhóm đó, sắp theo RS giảm dần. Bấm vào 1 biểu đồ trong danh sách để phóng to.
- Chỉ số tổng hợp có trọng số dòng tiền (money-flow weighted index), mốc 1000 điểm, tính cho
  toàn thị trường và từng ngành riêng, chọn xem qua dropdown.
Toàn bộ dữ liệu OHLCV được nhúng sẵn vào file HTML (dạng mảng, tối ưu dung lượng) khi build,
nên khi người xem tương tác, biểu đồ vẽ ngay trên trình duyệt — không cần gọi API lại.

Kiến trúc output: thay vì 1 file docs/index.html duy nhất (nặng vì nhúng toàn bộ dữ liệu),
báo cáo được TÁCH THÀNH 3 FILE riêng theo chức năng, dùng chung 1 theme/nav:
  - docs/index.html      : Xếp hạng RS (mang theo chart_data OHLCV - phần nặng nhất)
  - docs/moneyflow.html  : Chỉ số dòng tiền (nhẹ hơn nhiều, không cần OHLCV từng mã)
  - docs/macro.html      : Dữ liệu vĩ mô (FRED, World Bank, vnstock)
"""

import os
import json
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

INPUT_FILE = "gia_lich_su_rs.csv"
OUTPUT_DIR = "docs"
RANKING_FILE = os.path.join(OUTPUT_DIR, "index.html")
MONEYFLOW_FILE = os.path.join(OUTPUT_DIR, "moneyflow.html")
MACRO_HTML_FILE = os.path.join(OUTPUT_DIR, "macro.html")
MACRO_DATA_FILE = "macro_data.json"

# Đổi 2 giá trị này đúng theo tài khoản/repo của bạn để nút "Cập nhật ngay" trỏ đúng chỗ
GITHUB_OWNER = "hungnguyen112526-source"
GITHUB_REPO = "rs-dashboard"
WORKFLOW_FILE = "update_data.yml"
ACTIONS_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{WORKFLOW_FILE}"

VN_TZ = timezone(timedelta(hours=7))  # giờ Việt Nam (UTC+7) - GitHub Actions chạy theo giờ UTC

BLOCK_SIZE = 30  # dữ liệu theo NGÀY (phiên giao dịch) -> đúng 30 phiên/khối theo công thức gốc
BLOCK_WEIGHTS = [0.4, 0.3, 0.2, 0.1]
DATA_UNIT = "phiên"

WEEKLY_BLOCK_SIZE = 20  # dữ liệu theo TUẦN (gộp từ dữ liệu ngày có sẵn) -> 20 tuần/khối
WEEKLY_UNIT = "tuần"
WEEKLY_MIN_SESSIONS = WEEKLY_BLOCK_SIZE * 4  # 80 tuần (~1.5 năm)

INDEX_SMOOTH_WINDOW = 20  # m phiên - chu kỳ làm mượt SMA cho trọng số dòng tiền


# ============================================================================
# 1. HÀM TÍNH TOÁN (không đổi so với bản trước)
# ============================================================================

def block_period_label(block_index, block_size=BLOCK_SIZE, unit=DATA_UNIT):
    """Sinh tên cột ngắn gọn: 'Khối N – 30 phiên ... (trọng số)'."""
    position_text = {1: "gần nhất", 2: "trước đó", 3: "trước nữa", 4: "xa nhất"}[block_index]
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
    """Nhúng dữ liệu OHLCV cho từng mã, dạng MẢNG (tối ưu dung lượng so với object):
    có OHLC: [time, open, high, low, close, volume-hoặc-null]
    chỉ có close: [time, close]
    Trả về (chart_data, has_ohlc, has_volume)."""
    has_ohlc = all(c in df.columns for c in ["open", "high", "low", "close"])
    has_volume = "volume" in df.columns
    chart_data = {}
    for ticker, g in df.groupby("ticker"):
        g = g.sort_values("date")
        rows = []
        for _, r in g.iterrows():
            t = r["date"].strftime("%Y-%m-%d")
            if has_ohlc:
                row = [t, round(float(r["open"]), 2), round(float(r["high"]), 2),
                       round(float(r["low"]), 2), round(float(r["close"]), 2)]
                if has_volume and pd.notna(r.get("volume")):
                    row.append(round(float(r["volume"]), 0))
                else:
                    row.append(None)
            else:
                row = [t, round(float(r["close"]), 2)]
            rows.append(row)
        chart_data[ticker] = rows
    return chart_data, has_ohlc, has_volume


def compute_index_series(sub_df: pd.DataFrame, smooth_window: int = INDEX_SMOOTH_WINDOW):
    """Tính chỉ số tổng hợp trọng số dòng tiền (đã làm mượt) cho 1 rổ mã (toàn thị trường
    hoặc 1 ngành). sub_df cần có cột: date, ticker, close, volume.

    Công thức (bản cải tiến, làm mượt):
      T_i = SMA(P_i * V_i, m)          # trung bình trượt m phiên, khử nhiễu
      W_i = T_i / sum(T_k)
      %ΔP_i = (P_i - P_trước,i) / P_trước,i
      %ΔIndex = sum(W_i * %ΔP_i)
      Index = Index_trước * (1 + %ΔIndex), mốc 1000 tại phiên đầu

    Trả về (index_series, volume_series):
      index_series:  [[time_str, index_value], ...]
      volume_series: [[time_str, tổng_giá_trị_giao_dịch_ngày_đó], ...] (chưa làm mượt,
                      dùng để hiển thị dạng cột khối lượng bên dưới biểu đồ)

    Mã thiếu dữ liệu ngày nào bị loại khỏi tính trọng số ngày đó (không làm hỏng cả index).
    """
    close_pivot = sub_df.pivot(index="date", columns="ticker", values="close").sort_index()
    volume_pivot = sub_df.pivot(index="date", columns="ticker", values="volume").sort_index()

    pct_change = close_pivot.ffill().pct_change(fill_method=None)
    raw_value_traded = close_pivot * volume_pivot
    smoothed_value_traded = raw_value_traded.rolling(window=smooth_window, min_periods=1).mean()

    dates = close_pivot.index
    index_result = []
    volume_result = []
    current = 1000.0
    for i in range(len(dates)):
        d = dates[i]
        day_total_raw = raw_value_traded.iloc[i].sum(skipna=True)
        volume_result.append([d.strftime("%Y-%m-%d"), round(float(day_total_raw), 0) if pd.notna(day_total_raw) else 0])

        if i == 0:
            index_result.append([d.strftime("%Y-%m-%d"), round(current, 2)])
            continue
        row_pct = pct_change.iloc[i]
        row_val = smoothed_value_traded.iloc[i]
        valid = row_pct.notna() & row_val.notna() & (row_val > 0)
        if valid.sum() > 0:
            w = row_val[valid] / row_val[valid].sum()
            pct_idx = (w * row_pct[valid]).sum()
            current = current * (1 + pct_idx)
        index_result.append([d.strftime("%Y-%m-%d"), round(current, 2)])
    return index_result, volume_result


def build_real_series(price_df: pd.DataFrame):
    """Chuỗi giá trị THỰC (không quy đổi mốc), dùng để vẽ VNIndex trên trục phụ riêng
    (secondary axis) cạnh chỉ số dòng tiền tự tính. price_df cần có cột date, close
    (1 mã duy nhất)."""
    d = price_df.sort_values("date").reset_index(drop=True)
    return [
        [d.loc[i, "date"].strftime("%Y-%m-%d"), round(float(d.loc[i, "close"]), 2)]
        for i in range(len(d))
    ]


def resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Gộp dữ liệu giá THEO NGÀY thành nến TUẦN (kết thúc thứ Sáu, đúng tuần giao dịch VN),
    lấy giá đóng cửa cuối tuần làm giá đại diện. Dùng để tính RS khung tuần mà không cần
    gọi API riêng - tái sử dụng dữ liệu ngày đã có trong gia_lich_su_rs.csv.
    df cần có cột: date, ticker, close. Trả về DataFrame cột: ticker, date, close."""
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    weekly = (
        df.groupby("ticker")
        .resample("W-FRI", on="date")["close"]
        .last()
        .dropna()
        .reset_index()
    )
    return weekly


# ============================================================================
# 2. GIAO DIỆN DÙNG CHUNG (theme, nav, khung trang)
# ============================================================================

SHARED_CSS = """
:root {
  --bg: #0a0f1e;
  --card: #121b30;
  --card-alt: #0f1728;
  --border: #22304a;
  --text: #e6eaf3;
  --text-dim: #93a1bd;
  --text-mute: #5b6780;
  --accent: #3b82f6;
  --accent-hover: #2563eb;
  --green: #22c55e;
  --amber: #f59e0b;
  --red: #ef4444;
  --radius: 14px;
}
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
  background: radial-gradient(circle at top, #101a30 0%, #0a0f1e 55%);
  color: var(--text);
  margin: 0;
  padding: 24px;
  -webkit-font-smoothing: antialiased;
}
h1 { font-size: 22px; margin: 0; font-weight: 700; letter-spacing: -0.02em; }
.updated { color: var(--text-mute); font-size: 13px; margin: 10px 0 2px; }
.refresh-hint { color: var(--text-mute); font-size: 12px; margin: 4px 0 20px; }
.header-row { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; margin-top: 6px; }
.refresh-btn {
  display:inline-flex; align-items:center; gap:8px;
  background: var(--accent); color:#fff; text-decoration:none;
  padding:9px 16px; border-radius:10px; font-size:14px; font-weight:600;
  white-space:nowrap; transition: background .15s;
}
.refresh-btn:hover { background: var(--accent-hover); }

.page-nav {
  position: sticky; top:0; z-index:40; display:flex; gap:8px; flex-wrap:wrap; align-items:center;
  background: rgba(10,15,30,0.92); backdrop-filter: blur(6px);
  margin: -24px -24px 20px; padding: 12px 24px; border-bottom:1px solid var(--border);
}
.page-nav-top { color: var(--text-dim); text-decoration:none; font-size:16px; padding: 4px 8px; }
.page-nav-item {
  color: var(--text-dim); text-decoration:none; font-size:13.5px; font-weight:600;
  background: var(--card); padding:7px 14px; border-radius:999px; border:1px solid var(--border);
  white-space:nowrap; transition: all .15s;
}
.page-nav-item:hover { background: var(--card-alt); color: var(--text); border-color: var(--accent); }
.page-nav-item.active { background: var(--accent); color:#fff; border-color: var(--accent); }

.card { background: var(--card); border:1px solid var(--border); border-radius: var(--radius); padding: 18px 20px; margin-bottom: 22px; }

.group-links-row { color:#93c5fd; font-size:13px; margin: 0 0 18px; }
.group-link { cursor:pointer; text-decoration:underline dotted; }
.group-link:hover { color:#bfdbfe; }

.tf-toggle-row { display:flex; gap:8px; margin: 4px 0 20px; }
.tf-toggle-btn {
  background: var(--card-alt); border:1px solid var(--border); color: var(--text-dim); font-size:14px; font-weight:600;
  padding:8px 18px; border-radius:10px; cursor:pointer; transition: all .15s;
}
.tf-toggle-btn:hover { background: var(--border); }
.tf-toggle-active { background: var(--accent); color:#fff; border-color: var(--accent); }

.formula-box { background: var(--card-alt); border:1px solid var(--border); border-radius:12px; padding:16px 20px; margin-bottom:22px; }
.formula-title { font-size:15px; font-weight:600; margin-bottom:10px; color: var(--text); }
.formula-list { margin:0; padding-left:20px; color: var(--text-dim); font-size:13px; line-height:1.7; }
.formula-list li { margin-bottom:4px; }
.formula-note { margin-top:10px; color: var(--text-mute); font-size:12px; }
details.formula-box summary { cursor:pointer; list-style:none; }
details.formula-box summary::-webkit-details-marker { display:none; }
details.formula-box summary .formula-arrow { display:inline-block; transition:transform 0.15s; }
details.formula-box[open] summary .formula-arrow { transform: rotate(90deg); }
details.formula-box .formula-list { margin-top:12px; }

.table-scroll { width:100%; overflow-x:auto; -webkit-overflow-scrolling:touch; border-radius:12px; }
table { width:100%; min-width:640px; border-collapse: collapse; background: var(--card-alt); border-radius:12px; overflow:hidden; }
th, td { padding: 10px 12px; text-align:left; border-bottom:1px solid var(--border); font-size: 14px; white-space:nowrap; }
th { background: var(--border); position: sticky; top:0; z-index:1; font-weight:600; }
th:first-child, td:first-child { position: sticky; left:0; background: var(--card-alt); z-index:2; }
th:first-child { z-index:3; }
.stock-row { cursor: pointer; }
.stock-row:hover td { background: var(--border); }
.ticker-cell { font-weight:700; color:#60a5fa; text-decoration: underline; text-decoration-style: dotted; }
.group-cell { cursor:pointer; color:#93c5fd; text-decoration: underline; text-decoration-style: dotted; }
.group-cell:hover { color:#bfdbfe; }
.section-title { font-size: 17px; margin: 0 0 4px; font-weight:700; }
.hint { color: var(--text-mute); font-size: 12px; margin: 0 0 14px; }

.index-select { background: var(--card-alt); color: var(--text); border:1px solid var(--border); border-radius:10px; padding:9px 12px; font-size:14px; margin-bottom:14px; max-width:100%; }
#index-chart-container, #macro-chart-container { width:100%; height:360px; background: var(--card-alt); border-radius:12px; }

#chart-overlay, #group-overlay { display:none; position:fixed; inset:0; background:rgba(4,7,16,0.7); align-items:center; justify-content:center; z-index:50; padding:16px; }
#chart-panel { background: var(--card); border-radius:16px; padding:18px; width:min(720px, 94vw); max-height:90vh; overflow-y:auto; box-shadow: 0 24px 70px rgba(0,0,0,0.55); }
#chart-panel-header, #group-panel-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; gap:12px; }
#chart-title, #group-title { font-size:17px; font-weight:700; flex:1; }
#chart-close, #group-close { background: var(--card-alt); border:1px solid var(--border); color: var(--text); width:30px; height:30px; border-radius:8px; cursor:pointer; font-size:16px; line-height:1; flex-shrink:0; }
#chart-close:hover, #group-close:hover { background: var(--border); }

#group-panel { background: var(--card); border-radius:16px; padding:18px; width:min(900px, 96vw); max-height:90vh; display:flex; flex-direction:column; box-shadow: 0 24px 70px rgba(0,0,0,0.55); }
#group-list { overflow-y:auto; padding-right:4px; }
.mini-chart-block { background: var(--card-alt); border:1px solid var(--border); border-radius:12px; padding:12px; margin-bottom:14px; cursor:pointer; transition: border-color .15s; }
.mini-chart-block:hover { border-color: var(--accent); }

.tf-toolbar { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; gap:10px; flex-wrap:wrap; }
.tf-toolbar-title { font-size:14px; font-weight:600; color: var(--text); }
.tf-btns { display:flex; gap:4px; }
.tf-btn { background: var(--border); border:none; color: var(--text-dim); font-size:12px; padding:5px 12px; border-radius:8px; cursor:pointer; }
.tf-btn:hover { background: #334155; }
.tf-btn.tf-active { background: var(--accent); color:#fff; }

.back-to-top { position: fixed; bottom:24px; right:24px; width:46px; height:46px; border-radius:50%; background: var(--accent); color:#fff; border:none; font-size:19px; cursor:pointer; display:none; align-items:center; justify-content:center; box-shadow:0 8px 24px rgba(0,0,0,0.45); z-index:45; }
.back-to-top:hover { background: var(--accent-hover); }

.subtabs { display:flex; gap:8px; margin: 4px 0 14px; border-bottom:1px solid var(--border); }
.subtab-btn { background:transparent; border:none; border-bottom:2px solid transparent; color: var(--text-dim); font-size:15px; font-weight:600; padding:8px 4px; cursor:pointer; margin-bottom:-1px; }
.subtab-btn:hover { color: var(--text); }
.subtab-active { color:#60a5fa; border-bottom-color:#60a5fa; }

.table-toolbar { display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin:4px 0 12px; }
.search-box { background: var(--card-alt); color: var(--text); border:1px solid var(--border); border-radius:10px; padding:9px 12px; font-size:14px; flex:1; min-width:180px; max-width:320px; }
.search-box:focus { outline:none; border-color: var(--accent); }
.table-count { color: var(--text-mute); font-size:12px; white-space:nowrap; }

@media (max-width: 640px) {
  body { padding: 14px; }
  .page-nav { margin: -14px -14px 16px; padding: 10px 14px; }
  h1 { font-size: 19px; }
  .card { padding: 14px; }
  #chart-panel, #group-panel { padding: 12px; width: 96vw; }
  .refresh-hint { display:none; }
  th, td { font-size: 13px; padding: 8px 10px; }
}
"""

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%%PAGE_TITLE%%</title>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>
%%CSS%%
</style>
</head>
<body>
<div id="top"></div>
%%NAV%%
<div class="header-row">
  <h1>%%PAGE_H1%%</h1>
  <a class="refresh-btn" href="%%ACTIONS_URL%%" target="_blank" rel="noopener">🔄 Cập nhật dữ liệu &amp; tính lại RS</a>
</div>
<div class="updated">Cập nhật lần cuối: %%UPDATED_AT%%</div>
<div class="refresh-hint">Nút trên mở trang GitHub Actions — bấm "Run workflow" ở đó để lấy dữ liệu mới nhất và tính lại RS ngay (cần đăng nhập GitHub với quyền chủ repo).</div>
%%BODY%%
<button id="back-to-top" class="back-to-top" onclick="window.scrollTo({top:0, behavior:'smooth'})" title="Về đầu trang">↑</button>
%%EXTRA_HTML%%
<script>
%%SCRIPT%%
</script>
</body>
</html>"""


def page_nav_html(active, has_moneyflow, has_macro):
    items = [("index.html", "🏆 Xếp hạng", "ranking", True)]
    items.append(("moneyflow.html", "📊 Dòng tiền", "moneyflow", has_moneyflow))
    items.append(("macro.html", "🌐 Vĩ mô", "macro", has_macro))
    links = ""
    for href, label, key, enabled in items:
        if not enabled:
            continue
        cls = "page-nav-item active" if key == active else "page-nav-item"
        links += f'<a class="{cls}" href="{href}">{label}</a>'
    return f'<nav class="page-nav"><a class="page-nav-top" href="#top" title="Về đầu trang">⬆</a>{links}</nav>'


def render_page(page_title, h1, active_nav, has_moneyflow, has_macro, updated_at, body_html, script_js, extra_html=""):
    nav = page_nav_html(active_nav, has_moneyflow, has_macro)
    html = PAGE_TEMPLATE
    html = html.replace("%%PAGE_TITLE%%", page_title)
    html = html.replace("%%CSS%%", SHARED_CSS)
    html = html.replace("%%NAV%%", nav)
    html = html.replace("%%PAGE_H1%%", h1)
    html = html.replace("%%ACTIONS_URL%%", ACTIONS_URL)
    html = html.replace("%%UPDATED_AT%%", updated_at)
    html = html.replace("%%BODY%%", body_html)
    html = html.replace("%%EXTRA_HTML%%", extra_html)
    html = html.replace("%%SCRIPT%%", script_js)
    return html


# ============================================================================
# 3. JS DÙNG CHUNG THEO TỪNG TRANG (plain string, không phải f-string
#    -> không cần escape ngoặc nhọn JS, dữ liệu được nạp bằng .replace() placeholder)
# ============================================================================

RANKING_SCRIPT = """
const CHART_DATA = %%CHART_DATA_JSON%%;
const GROUP_DATA = %%GROUP_DATA_JSON%%;
const HAS_OHLC = %%HAS_OHLC_JSON%%;
const HAS_VOLUME = %%HAS_VOLUME_JSON%%;

let currentChartState = null;
let groupChartStates = [];

function getMonday(dateStr) {
  const d = new Date(dateStr + 'T00:00:00Z');
  const day = d.getUTCDay();
  const diff = (day === 0 ? -6 : 1 - day);
  d.setUTCDate(d.getUTCDate() + diff);
  return d.toISOString().slice(0, 10);
}

function aggregateWeekly(dailyArr) {
  if (!dailyArr.length) return [];
  const isOHLC = dailyArr[0].length >= 5;
  const weeks = {};
  const order = [];
  for (const r of dailyArr) {
    const key = getMonday(r[0]);
    if (!weeks[key]) {
      order.push(key);
      weeks[key] = isOHLC
        ? { time: key, open: r[1], high: r[2], low: r[3], close: r[4], volume: (r[5] || 0) }
        : { time: key, close: r[1] };
    } else {
      const w = weeks[key];
      if (isOHLC) {
        w.high = Math.max(w.high, r[2]);
        w.low = Math.min(w.low, r[3]);
        w.close = r[4];
        w.volume += (r[5] || 0);
      } else {
        w.close = r[1];
      }
    }
  }
  return order.map(k => {
    const w = weeks[k];
    return isOHLC ? [w.time, w.open, w.high, w.low, w.close, w.volume] : [w.time, w.close];
  });
}

function buildPriceChart(container, data, height) {
  const chart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: height,
    layout: { background: { color: '#121b30' }, textColor: '#cbd5e1' },
    grid: { vertLines: { color: '#22304a' }, horzLines: { color: '#22304a' } },
    timeScale: { borderColor: '#334155' },
    rightPriceScale: {
      borderColor: '#334155',
      scaleMargins: HAS_VOLUME ? { top: 0.1, bottom: 0.3 } : { top: 0.1, bottom: 0.1 },
    },
  });

  if (HAS_OHLC) {
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#22c55e', downColor: '#ef4444',
      borderUpColor: '#22c55e', borderDownColor: '#ef4444',
      wickUpColor: '#22c55e', wickDownColor: '#ef4444',
    });
    candleSeries.setData(data.map(d => ({ time: d[0], open: d[1], high: d[2], low: d[3], close: d[4] })));

    if (HAS_VOLUME) {
      const volumeSeries = chart.addHistogramSeries({
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
      });
      chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
      volumeSeries.setData(
        data.filter(d => d[5] !== undefined && d[5] !== null).map(d => ({
          time: d[0], value: d[5],
          color: d[4] >= d[1] ? 'rgba(34,197,94,0.5)' : 'rgba(239,68,68,0.5)',
        }))
      );
    }
  } else {
    const series = chart.addLineSeries({ color: '#60a5fa', lineWidth: 2 });
    series.setData(data.map(d => ({ time: d[0], value: d[1] })));
  }

  chart.timeScale().fitContent();
  return chart;
}

function mountChart(parentEl, dailyData, height, titleText) {
  const toolbar = document.createElement('div');
  toolbar.className = 'tf-toolbar';
  toolbar.innerHTML =
    '<div class="tf-toolbar-title">' + (titleText || '') + '</div>' +
    '<div class="tf-btns">' +
      '<button class="tf-btn tf-active" data-tf="D">Ngày</button>' +
      '<button class="tf-btn" data-tf="W">Tuần</button>' +
    '</div>';
  parentEl.appendChild(toolbar);

  const chartDiv = document.createElement('div');
  chartDiv.style.width = '100%';
  chartDiv.style.height = height + 'px';
  parentEl.appendChild(chartDiv);

  const weeklyData = aggregateWeekly(dailyData);
  const chart = buildPriceChart(chartDiv, dailyData, height);
  const state = { chart, container: chartDiv };

  toolbar.querySelectorAll('.tf-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (btn.classList.contains('tf-active')) return;
      toolbar.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('tf-active'));
      btn.classList.add('tf-active');
      state.chart.remove();
      const newData = btn.dataset.tf === 'W' ? weeklyData : dailyData;
      state.chart = buildPriceChart(chartDiv, newData, height);
    });
  });

  return state;
}

function closeChart() {
  document.getElementById('chart-overlay').style.display = 'none';
  if (currentChartState) { currentChartState.chart.remove(); currentChartState = null; }
  document.getElementById('chart-mount').innerHTML = '';
}

function showChart(ticker) {
  const data = CHART_DATA[ticker];
  if (!data) return;

  document.getElementById('chart-title').textContent = ticker + ' — Biểu đồ giá';
  document.getElementById('chart-overlay').style.display = 'flex';

  const mount = document.getElementById('chart-mount');
  mount.innerHTML = '';
  if (currentChartState) { currentChartState.chart.remove(); }

  currentChartState = mountChart(mount, data, 360, '');
}

function closeGroupPopup() {
  document.getElementById('group-overlay').style.display = 'none';
  groupChartStates.forEach(s => s.chart.remove());
  groupChartStates = [];
  document.getElementById('group-list').innerHTML = '';
}

function showGroupPopup(name) {
  const list = GROUP_DATA[name];
  if (!list) return;

  closeChart();
  document.getElementById('group-title').textContent = name + ' (' + list.length + ' mã)';
  document.getElementById('group-overlay').style.display = 'flex';

  const container = document.getElementById('group-list');
  container.innerHTML = '';
  groupChartStates.forEach(s => s.chart.remove());
  groupChartStates = [];

  list.forEach(item => {
    const data = CHART_DATA[item.ticker];
    if (!data) return;

    const block = document.createElement('div');
    block.className = 'mini-chart-block';
    container.appendChild(block);

    block.addEventListener('click', () => {
      closeGroupPopup();
      showChart(item.ticker);
    });

    const state = mountChart(block, data, 320, item.ticker + ' — RS: ' + item.rs);
    groupChartStates.push(state);
  });
}

function switchRankingTimeframe(tf, btn) {
  const dayPanel = document.getElementById('tf-panel-day');
  const weekPanel = document.getElementById('tf-panel-week');
  if (dayPanel) dayPanel.style.display = (tf === 'day') ? '' : 'none';
  if (weekPanel) weekPanel.style.display = (tf === 'week') ? '' : 'none';
  btn.parentElement.querySelectorAll('.tf-toggle-btn').forEach(b => b.classList.remove('tf-toggle-active'));
  btn.classList.add('tf-toggle-active');
}

function switchSubtab(panelId, tab, btn) {
  const stockPanel = document.getElementById(panelId + '-stock');
  const industryPanel = document.getElementById(panelId + '-industry');
  if (stockPanel) stockPanel.style.display = (tab === 'stock') ? '' : 'none';
  if (industryPanel) industryPanel.style.display = (tab === 'industry') ? '' : 'none';
  btn.parentElement.querySelectorAll('.subtab-btn').forEach(b => b.classList.remove('subtab-active'));
  btn.classList.add('subtab-active');
}

function filterStockTable(panelId) {
  const input = document.getElementById(panelId + '-search');
  const table = document.getElementById(panelId + '-stock-table');
  const countEl = document.getElementById(panelId + '-count');
  if (!input || !table) return;
  const q = input.value.trim().toLowerCase();
  const rows = table.querySelectorAll('tr.stock-row');
  let visible = 0;
  rows.forEach(row => {
    const match = row.textContent.toLowerCase().includes(q);
    row.style.display = match ? '' : 'none';
    if (match) visible++;
  });
  if (countEl) countEl.textContent = visible + '/' + rows.length + ' mã';
}

window.addEventListener('scroll', () => {
  const btn = document.getElementById('back-to-top');
  if (btn) btn.style.display = (window.scrollY > 400) ? 'flex' : 'none';
});

window.addEventListener('resize', () => {
  if (currentChartState) {
    currentChartState.chart.applyOptions({ width: currentChartState.container.clientWidth });
  }
  groupChartStates.forEach(s => {
    s.chart.applyOptions({ width: s.container.clientWidth });
  });
});
"""

MONEYFLOW_SCRIPT = """
const INDEX_DATA = %%INDEX_DATA_JSON%%;
const INDEX_CATEGORIES = %%INDEX_CATEGORIES_JSON%%;
const VNINDEX_DATA = %%VNINDEX_JSON%%;

let indexChart = null;

function renderIndexChart(name) {
  const entry = INDEX_DATA[name];
  if (!entry) return;
  const container = document.getElementById('index-chart-container');
  if (!container) return;
  if (indexChart) { indexChart.remove(); indexChart = null; }

  const data = entry.index || [];
  const volData = entry.volume || [];
  const hasVnIndex = !!(VNINDEX_DATA && VNINDEX_DATA.length);

  indexChart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: 360,
    layout: { background: { color: '#121b30' }, textColor: '#cbd5e1' },
    grid: { vertLines: { color: '#22304a' }, horzLines: { color: '#22304a' } },
    timeScale: { borderColor: '#334155' },
    rightPriceScale: {
      borderColor: '#334155',
      scaleMargins: volData.length ? { top: 0.1, bottom: 0.3 } : { top: 0.1, bottom: 0.1 },
    },
    leftPriceScale: {
      visible: hasVnIndex,
      borderColor: '#334155',
      scaleMargins: { top: 0.1, bottom: 0.1 },
    },
  });

  const series = indexChart.addAreaSeries({
    lineColor: '#60a5fa', topColor: 'rgba(96,165,250,0.3)', bottomColor: 'rgba(96,165,250,0.0)',
    lineWidth: 2, title: name,
  });
  series.setData(data.map(d => ({ time: d[0], value: d[1] })));

  if (hasVnIndex) {
    const vnSeries = indexChart.addLineSeries({
      color: '#f59e0b', lineWidth: 2, lineStyle: LightweightCharts.LineStyle.Dashed, title: 'VNIndex',
      priceScaleId: 'left',
    });
    vnSeries.setData(VNINDEX_DATA.map(d => ({ time: d[0], value: d[1] })));
  }

  if (volData.length) {
    const volSeries = indexChart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: 'index-volume',
      color: 'rgba(148,163,184,0.5)',
    });
    indexChart.priceScale('index-volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    volSeries.setData(volData.map(d => ({ time: d[0], value: d[1] })));
  }

  indexChart.timeScale().fitContent();
}

function initIndexSelect() {
  const select = document.getElementById('index-select');
  if (!select) return;
  const groupLabels = { industry: '📂 Theo ngành', nhom: '🏢 Theo tập đoàn' };
  (INDEX_CATEGORIES.market || []).forEach(name => {
    const opt = document.createElement('option');
    opt.value = name; opt.textContent = name;
    select.appendChild(opt);
  });
  ['industry', 'nhom'].forEach(cat => {
    const names = INDEX_CATEGORIES[cat] || [];
    if (!names.length) return;
    const og = document.createElement('optgroup');
    og.label = groupLabels[cat];
    names.forEach(name => {
      const opt = document.createElement('option');
      opt.value = name; opt.textContent = name;
      og.appendChild(opt);
    });
    select.appendChild(og);
  });
  select.addEventListener('change', () => renderIndexChart(select.value));
  if (select.options.length) renderIndexChart(select.value);
}
initIndexSelect();

window.addEventListener('scroll', () => {
  const btn = document.getElementById('back-to-top');
  if (btn) btn.style.display = (window.scrollY > 400) ? 'flex' : 'none';
});

window.addEventListener('resize', () => {
  if (indexChart) {
    const c = document.getElementById('index-chart-container');
    if (c) indexChart.applyOptions({ width: c.clientWidth });
  }
});
"""

MACRO_SCRIPT = """
const MACRO_DATA = %%MACRO_DATA_JSON%%;

let macroChart = null;

function renderMacroChart(key) {
  const entry = MACRO_DATA.series && MACRO_DATA.series[key];
  if (!entry) return;

  const container = document.getElementById('macro-chart-container');
  const descEl = document.getElementById('macro-description');
  if (!container) return;

  if (macroChart) { macroChart.remove(); macroChart = null; }
  if (descEl) descEl.textContent = entry.description || '';

  const isYearly = entry.freq === 'yearly';

  macroChart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: 360,
    layout: { background: { color: '#121b30' }, textColor: '#cbd5e1' },
    grid: { vertLines: { color: '#22304a' }, horzLines: { color: '#22304a' } },
    timeScale: { borderColor: '#334155', timeVisible: !isYearly },
    rightPriceScale: { borderColor: '#334155' },
  });

  const values = (entry.values || [])
    .filter(v => v[1] !== null && v[1] !== undefined)
    .map(v => ({ time: v[0], value: v[1] }));

  if (!values.length) return;

  const series = macroChart.addAreaSeries({
    lineColor: '#60a5fa',
    topColor: 'rgba(96,165,250,0.25)',
    bottomColor: 'rgba(96,165,250,0.0)',
    lineWidth: 2,
    title: entry.label,
  });
  series.setData(values);
  macroChart.timeScale().fitContent();

  const ro = new ResizeObserver(() => {
    if (macroChart) macroChart.applyOptions({ width: container.clientWidth });
  });
  ro.observe(container);
}

function initMacroChart() {
  const select = document.getElementById('macro-select');
  if (!select || !MACRO_DATA.series) return;
  select.addEventListener('change', () => renderMacroChart(select.value));
  if (select.options.length) renderMacroChart(select.value);
}
initMacroChart();

window.addEventListener('scroll', () => {
  const btn = document.getElementById('back-to-top');
  if (btn) btn.style.display = (window.scrollY > 400) ? 'flex' : 'none';
});
"""


# ============================================================================
# 4. MAIN
# ============================================================================

def main():
    df = pd.read_csv(INPUT_FILE, parse_dates=["date"], low_memory=False)

    before_dedup = len(df)
    df = df.sort_values("date").drop_duplicates(subset=["date", "ticker"], keep="last")
    removed = before_dedup - len(df)
    if removed > 0:
        print(f"Đã loại bỏ {removed} dòng trùng lặp (cùng ngày + cùng mã) trong {INPUT_FILE}.")

    vnindex_df = df[df["ticker"] == "VNINDEX"].copy()
    df = df[df["ticker"] != "VNINDEX"].copy()

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

    has_nhom = "nhom" in df.columns
    if has_nhom:
        nhom_map = df.drop_duplicates("ticker").set_index("ticker")["nhom"]
        scores["nhom"] = scores["ticker"].map(nhom_map)

    industry_raw = scores.groupby("industry")["raw_score"].mean().rename("industry_raw_score")
    industry_df = industry_raw.reset_index()
    industry_df["RS_nganh"] = raw_score_to_rs(industry_df["industry_raw_score"])
    industry_df = industry_df.sort_values("RS_nganh", ascending=False)

    weekly_df = resample_weekly(df[["date", "ticker", "close"]])
    weekly_records = []
    for ticker, g in weekly_df.groupby("ticker"):
        g = g.sort_values("date")
        prices = g["close"].reset_index(drop=True)
        block_returns = [
            block_return(prices, i, block_size=WEEKLY_BLOCK_SIZE) for i in range(1, len(BLOCK_WEIGHTS) + 1)
        ]
        if any(pd.isna(r) for r in block_returns):
            continue
        raw_score = sum(w * r for w, r in zip(BLOCK_WEIGHTS, block_returns))
        record = {"ticker": ticker, "raw_score": raw_score}
        for i, r in enumerate(block_returns, start=1):
            record[f"pct_block{i}"] = r
        weekly_records.append(record)

    scores_weekly = pd.DataFrame(weekly_records)
    has_weekly_rs = not scores_weekly.empty
    if has_weekly_rs:
        scores_weekly["industry"] = scores_weekly["ticker"].map(industry_map)
        scores_weekly["RS"] = raw_score_to_rs(scores_weekly["raw_score"])
        scores_weekly = scores_weekly.sort_values("RS", ascending=False)

        industry_raw_w = scores_weekly.groupby("industry")["raw_score"].mean().rename("industry_raw_score")
        industry_df_weekly = industry_raw_w.reset_index()
        industry_df_weekly["RS_nganh"] = raw_score_to_rs(industry_df_weekly["industry_raw_score"])
        industry_df_weekly = industry_df_weekly.sort_values("RS_nganh", ascending=False)
    else:
        industry_df_weekly = pd.DataFrame(columns=["industry", "industry_raw_score", "RS_nganh"])
        print(f"CẢNH BÁO: không đủ {WEEKLY_MIN_SESSIONS} tuần dữ liệu cho bất kỳ mã nào -> bỏ qua bảng RS khung tuần.")

    industry_tickers = {}
    for _, r in scores.iterrows():
        industry_tickers.setdefault(r["industry"], []).append({"ticker": r["ticker"], "rs": int(r["RS"])})

    group_tickers = {}
    if has_nhom:
        for _, r in scores.dropna(subset=["nhom"]).iterrows():
            group_tickers.setdefault(r["nhom"], []).append({"ticker": r["ticker"], "rs": int(r["RS"])})

    group_data = {**industry_tickers, **group_tickers}

    chart_data, has_ohlc, has_volume = build_chart_data(df)

    index_data = {}
    index_categories = {"market": [], "industry": [], "nhom": []}
    if has_volume:
        idx_series, vol_series = compute_index_series(df[["date", "ticker", "close", "volume"]])
        index_data["Toàn thị trường"] = {"index": idx_series, "volume": vol_series}
        index_categories["market"].append("Toàn thị trường")

        for nganh in sorted(df["industry"].dropna().unique()):
            sub = df[df["industry"] == nganh][["date", "ticker", "close", "volume"]]
            if sub["ticker"].nunique() < 1:
                continue
            idx_series, vol_series = compute_index_series(sub)
            if idx_series:
                index_data[nganh] = {"index": idx_series, "volume": vol_series}
                index_categories["industry"].append(nganh)

        if has_nhom:
            for nhom_name in sorted(df["nhom"].dropna().unique()):
                sub = df[df["nhom"] == nhom_name][["date", "ticker", "close", "volume"]]
                if sub["ticker"].nunique() < 1:
                    continue
                idx_series, vol_series = compute_index_series(sub)
                if idx_series:
                    index_data[nhom_name] = {"index": idx_series, "volume": vol_series}
                    index_categories["nhom"].append(nhom_name)

    vnindex_series = []
    if not vnindex_df.empty:
        vnindex_series = build_real_series(vnindex_df[["date", "close"]])

    def rs_color(rs):
        if rs >= 80:
            return "var(--green)"
        if rs >= 50:
            return "var(--amber)"
        return "var(--red)"

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

    def render_ranking_panel(panel_id, active, block_size, unit, min_required_hint, stock_df, industry_df_):
        display_style = "" if active else ' style="display:none"'
        labels = [block_period_label(i, block_size=block_size, unit=unit) for i in range(1, 5)]
        n_stock = len(stock_df)
        return f"""
  <div id="{panel_id}" class="tf-panel"{display_style}>
  <details class="formula-box">
    <summary class="formula-title"><span class="formula-arrow">▶</span> 📐 Công thức xếp hạng RS (khung {unit}) — bấm để xem chi tiết</summary>
    <ol class="formula-list">
      <li>Chia dữ liệu giá thành <b>4 khối</b>, mỗi khối <b>{block_size} {unit}</b> liên tiếp, không chồng lấn (Khối 1 = {block_size} {unit} gần nhất, ... Khối 4 = {block_size} {unit} xa nhất).</li>
      <li>Tính <b>% thay đổi giá</b> của từng khối: %Δ = (Giá cuối khối − Giá đầu khối) / Giá đầu khối.</li>
      <li>Tính <b>Điểm thô</b> mỗi mã = 0.4×%Δ(Khối 1) + 0.3×%Δ(Khối 2) + 0.2×%Δ(Khối 3) + 0.1×%Δ(Khối 4) — khối gần nhất có trọng số cao nhất.</li>
      <li>Xếp hạng tất cả mã theo Điểm thô (cao → thấp), quy đổi <b>RS cổ phiếu</b> (thang 1–99) = ((N − hạng) / N) × 99 + 1, với N = tổng số mã.</li>
      <li><b>Điểm thô Ngành</b> = trung bình cộng Điểm thô của các mã trong ngành.</li>
      <li>Áp dụng lại bước 4 cho các ngành để ra <b>RS Ngành</b> (thang 1–99), với M = tổng số ngành.</li>
    </ol>
    <div class="formula-note">{min_required_hint}</div>
  </details>

  <div class="subtabs">
    <button class="subtab-btn subtab-active" onclick="switchSubtab('{panel_id}', 'stock', this)">🏆 Xếp hạng cổ phiếu</button>
    <button class="subtab-btn" onclick="switchSubtab('{panel_id}', 'industry', this)">🏭 Xếp hạng ngành</button>
  </div>

  <div id="{panel_id}-stock" class="subtab-panel">
    <div class="hint">Bấm vào mã để xem biểu đồ giá · Bấm vào tên ngành để xem biểu đồ tất cả mã trong ngành</div>
    <div class="hint">* Điểm thô = 0.4×(khối gần nhất) + 0.3×(khối tiếp theo) + 0.2×(khối kế) + 0.1×(khối xa nhất) — khối gần nhất được tính trọng số cao nhất vì phản ánh xu hướng giá mới nhất</div>
    <div class="table-toolbar">
      <input type="text" id="{panel_id}-search" class="search-box" placeholder="🔍 Lọc theo mã hoặc ngành..." oninput="filterStockTable('{panel_id}')">
      <span class="table-count" id="{panel_id}-count">{n_stock}/{n_stock} mã</span>
    </div>
    <div class="table-scroll">
    <table id="{panel_id}-stock-table">
      <tr><th>Mã</th><th>Ngành</th><th>{labels[0]}</th><th>{labels[1]}</th><th>{labels[2]}</th><th>{labels[3]}</th><th>Điểm thô*</th><th>RS</th></tr>
      {stock_rows(stock_df)}
    </table>
    </div>
  </div>

  <div id="{panel_id}-industry" class="subtab-panel" style="display:none">
    <div class="hint">Bấm vào tên ngành để xem biểu đồ tất cả mã trong ngành</div>
    <div class="table-scroll">
    <table>
      <tr><th>Ngành</th><th>Điểm thô Ngành</th><th>RS Ngành</th></tr>
      {industry_rows(industry_df_)}
    </table>
    </div>
  </div>
  </div>"""

    day_panel_html = render_ranking_panel(
        "tf-panel-day", True, BLOCK_SIZE, DATA_UNIT,
        f"Cần tối thiểu {BLOCK_SIZE * len(BLOCK_WEIGHTS)} phiên giao dịch (~6 tháng) mỗi mã để tính đủ 4 khối.",
        scores, industry_df,
    )

    if has_weekly_rs:
        week_panel_html = render_ranking_panel(
            "tf-panel-week", False, WEEKLY_BLOCK_SIZE, WEEKLY_UNIT,
            f"Cần tối thiểu {WEEKLY_MIN_SESSIONS} tuần giao dịch (~1.5 năm) mỗi mã để tính đủ 4 khối.",
            scores_weekly, industry_df_weekly,
        )
        ranking_toggle_html = """
  <div class="tf-toggle-row">
    <button class="tf-toggle-btn tf-toggle-active" onclick="switchRankingTimeframe('day', this)">Khung ngày</button>
    <button class="tf-toggle-btn" onclick="switchRankingTimeframe('week', this)">Khung tuần</button>
  </div>"""
    else:
        week_panel_html = ""
        ranking_toggle_html = ""

    group_names = sorted(group_tickers.keys())
    if group_names:
        links = " · ".join(
            f'<span class="group-link" onclick="showGroupPopup(\'{name}\')">{name}</span>'
            for name in group_names
        )
        group_links_html = f'<div class="group-links-row">🏢 Xem theo tập đoàn: {links}</div>'
    else:
        group_links_html = ""

    updated_at = datetime.now(timezone.utc).astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M")

    chart_data_json = json.dumps(chart_data, ensure_ascii=False)
    group_data_json = json.dumps(group_data, ensure_ascii=False)
    index_data_json = json.dumps(index_data, ensure_ascii=False)
    index_categories_json = json.dumps(index_categories, ensure_ascii=False)
    vnindex_json = json.dumps(vnindex_series, ensure_ascii=False)
    has_ohlc_json = "true" if has_ohlc else "false"
    has_volume_json = "true" if has_volume else "false"

    # --- Đọc dữ liệu vĩ mô từ macro_data.json (nếu có) ---
    macro_data = {}
    if os.path.exists(MACRO_DATA_FILE):
        try:
            with open(MACRO_DATA_FILE, encoding="utf-8") as f:
                macro_data = json.load(f)
            print(f"Đã đọc {MACRO_DATA_FILE} ({len(macro_data.get('series', {}))} series)")
        except Exception as e:
            print(f"CẢNH BÁO: Không đọc được {MACRO_DATA_FILE}: {e}")

    macro_data_json = json.dumps(macro_data, ensure_ascii=False)

    has_moneyflow = bool(index_data)
    has_macro = bool(macro_data.get("series")) if macro_data else False

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ---------------- TRANG 1: index.html (Xếp hạng RS) ----------------
    ranking_body = group_links_html + f"""
<div class="card" id="section-ranking">
{ranking_toggle_html}
{day_panel_html}
{week_panel_html}
</div>
"""
    ranking_extra = """
<div id="chart-overlay" onclick="if(event.target===this) closeChart()">
  <div id="chart-panel">
    <div id="chart-panel-header">
      <div id="chart-title">Biểu đồ giá</div>
      <button id="chart-close" onclick="closeChart()">✕</button>
    </div>
    <div id="chart-mount"></div>
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
"""
    ranking_script = (
        RANKING_SCRIPT
        .replace("%%CHART_DATA_JSON%%", chart_data_json)
        .replace("%%GROUP_DATA_JSON%%", group_data_json)
        .replace("%%HAS_OHLC_JSON%%", has_ohlc_json)
        .replace("%%HAS_VOLUME_JSON%%", has_volume_json)
    )
    ranking_html = render_page(
        page_title="Bảng xếp hạng RS chứng khoán",
        h1="📈 Bảng xếp hạng RS chứng khoán",
        active_nav="ranking",
        has_moneyflow=has_moneyflow,
        has_macro=has_macro,
        updated_at=updated_at,
        body_html=ranking_body,
        script_js=ranking_script,
        extra_html=ranking_extra,
    )
    with open(RANKING_FILE, "w", encoding="utf-8") as f:
        f.write(ranking_html)

    # ---------------- TRANG 2: moneyflow.html (Chỉ số dòng tiền) ----------------
    if has_moneyflow:
        vn_hint = (
            ' · <span style="color:#f59e0b">- - -</span> VNIndex thực (trục phụ bên trái, không quy đổi)'
            if vnindex_series else ""
        )
        moneyflow_body = f"""
<div class="card" id="section-index">
  <div class="section-title">📊 Chỉ số dòng tiền (Money-flow Weighted Index)</div>
  <div class="hint">Mốc khởi điểm 1000 điểm tại phiên đầu tiên có dữ liệu. Trọng số mỗi mã = SMA({INDEX_SMOOTH_WINDOW} phiên) của giá trị giao dịch (giá × khối lượng) — đã làm mượt để giảm nhiễu.</div>
  <div class="hint"><span style="color:#60a5fa">—</span> Chỉ số tự tính{vn_hint} · cột xám bên dưới = tổng giá trị giao dịch mỗi phiên</div>
  <select id="index-select" class="index-select"></select>
  <div id="index-chart-container"></div>
</div>
"""
        moneyflow_script = (
            MONEYFLOW_SCRIPT
            .replace("%%INDEX_DATA_JSON%%", index_data_json)
            .replace("%%INDEX_CATEGORIES_JSON%%", index_categories_json)
            .replace("%%VNINDEX_JSON%%", vnindex_json)
        )
        moneyflow_html = render_page(
            page_title="Chỉ số dòng tiền — RS Dashboard",
            h1="📊 Chỉ số dòng tiền",
            active_nav="moneyflow",
            has_moneyflow=has_moneyflow,
            has_macro=has_macro,
            updated_at=updated_at,
            body_html=moneyflow_body,
            script_js=moneyflow_script,
        )
        with open(MONEYFLOW_FILE, "w", encoding="utf-8") as f:
            f.write(moneyflow_html)
    else:
        if os.path.exists(MONEYFLOW_FILE):
            os.remove(MONEYFLOW_FILE)

    # ---------------- TRANG 3: macro.html (Dữ liệu vĩ mô) ----------------
    if has_macro:
        groups = macro_data.get("groups", {})
        series = macro_data.get("series", {})
        updated = macro_data.get("updated_at", "")

        opts_html = ""
        for group_name, keys in groups.items():
            opts_html += f'<optgroup label="{group_name}">'
            for key in keys:
                label = series[key]["label"] if key in series else key
                opts_html += f'<option value="{key}">{label}</option>'
            opts_html += "</optgroup>"

        macro_body = f"""
<div class="card" id="section-macro">
  <div class="section-title">🌐 Dữ liệu vĩ mô</div>
  <div class="hint">Nguồn: FRED (Mỹ) · World Bank (VN) · vnstock - Vietcombank &amp; SJC (VN) · Cập nhật lần cuối: {updated}</div>
  <div class="hint"><span style="color:#60a5fa">—</span> Chọn chỉ số từ dropdown để xem biểu đồ</div>
  <select id="macro-select" class="index-select">{opts_html}</select>
  <div id="macro-chart-container"></div>
  <div id="macro-description" class="hint" style="margin-top:8px;font-style:italic;"></div>
</div>
"""
        macro_script = MACRO_SCRIPT.replace("%%MACRO_DATA_JSON%%", macro_data_json)
        macro_html_out = render_page(
            page_title="Dữ liệu vĩ mô — RS Dashboard",
            h1="🌐 Dữ liệu vĩ mô",
            active_nav="macro",
            has_moneyflow=has_moneyflow,
            has_macro=has_macro,
            updated_at=updated_at,
            body_html=macro_body,
            script_js=macro_script,
        )
        with open(MACRO_HTML_FILE, "w", encoding="utf-8") as f:
            f.write(macro_html_out)
    else:
        if os.path.exists(MACRO_HTML_FILE):
            os.remove(MACRO_HTML_FILE)

    chart_kind = "nến+volume" if (has_ohlc and has_volume) else ("nến" if has_ohlc else "đường (thiếu OHLC đầy đủ)")
    files_created = [RANKING_FILE] + ([MONEYFLOW_FILE] if has_moneyflow else []) + ([MACRO_HTML_FILE] if has_macro else [])
    print(
        f"Đã tạo {len(files_created)} file: {', '.join(files_created)} "
        f"(kèm biểu đồ {chart_kind}, {len(group_data)} mục ngành/nhóm có popup, {len(index_data)} chỉ số dòng tiền)"
    )


if __name__ == "__main__":
    main()
