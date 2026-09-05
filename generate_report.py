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
"""

import os
import json
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

INPUT_FILE = "gia_lich_su_rs.csv"
OUTPUT_FILE = "docs/index.html"

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


INDEX_SMOOTH_WINDOW = 20  # m phiên - chu kỳ làm mượt SMA cho trọng số dòng tiền


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

    # forward-fill CHỈ để tính %Δ (nếu 1 mã nghỉ giao dịch rồi quay lại, %Δ phiên quay lại
    # so với giá hợp lệ gần nhất) - KHÔNG dùng bản ffill này để xác định mã có dữ liệu ngày nào,
    # việc đó vẫn dựa trên close_pivot/volume_pivot gốc (có NaN thật) để loại đúng mã thiếu
    # dữ liệu khỏi trọng số của đúng ngày đó.
    pct_change = close_pivot.ffill().pct_change(fill_method=None)
    raw_value_traded = close_pivot * volume_pivot  # T_i thô - dùng để hiển thị cột khối lượng
    smoothed_value_traded = raw_value_traded.rolling(
        window=smooth_window, min_periods=1
    ).mean()  # T_i đã làm mượt (SMA) - dùng để tính trọng số W_i

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
    # reset_index(drop=True): groupby(...).resample(..., on=...) của pandas cho kết quả SAI
    # (thiếu dữ liệu) nếu index của df đầu vào không liền mạch/không theo đúng thứ tự nhóm
    # (dễ xảy ra vì df đã qua sort_values + drop_duplicates trước đó trong main()).
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    weekly = (
        df.groupby("ticker")
        .resample("W-FRI", on="date")["close"]
        .last()
        .dropna()
        .reset_index()
    )
    return weekly


def main():
    df = pd.read_csv(INPUT_FILE, parse_dates=["date"], low_memory=False)

    # --- Loại bỏ dòng trùng lặp (cùng ngày + cùng mã) ngay từ đầu ---
    # Bảo vệ mọi bước tính toán phía sau (groupby, pivot...) khỏi lỗi nếu dữ liệu đầu vào
    # lỡ có dòng trùng (do fetch_data.py cũ chưa lọc, hoặc chỉnh sửa tay CSV).
    before_dedup = len(df)
    df = df.sort_values("date").drop_duplicates(subset=["date", "ticker"], keep="last")
    removed = before_dedup - len(df)
    if removed > 0:
        print(f"Đã loại bỏ {removed} dòng trùng lặp (cùng ngày + cùng mã) trong {INPUT_FILE}.")

    # --- Tách VNINDEX (chỉ số tham chiếu) ra khỏi dữ liệu cổ phiếu ---
    # VNINDEX không phải cổ phiếu, không thuộc ngành nào -> không được lẫn vào tính RS,
    # bảng xếp hạng, hay popup ngành/nhóm. Chỉ dùng riêng để vẽ đường so sánh trên biểu đồ Index.
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

    # --- RS khung TUẦN: gộp dữ liệu ngày có sẵn thành tuần, tính lại theo cùng công thức
    # (4 khối, trọng số 0.4/0.3/0.2/0.1) nhưng block_size = WEEKLY_BLOCK_SIZE tuần/khối ---
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
        print(
            f"CẢNH BÁO: không đủ {WEEKLY_MIN_SESSIONS} tuần dữ liệu cho bất kỳ mã nào "
            f"-> bỏ qua bảng RS khung tuần."
        )

    # --- Danh sách mã theo Ngành / Nhóm, sắp theo RS giảm dần (dùng cho popup) ---
    industry_tickers = {}
    for _, r in scores.iterrows():
        industry_tickers.setdefault(r["industry"], []).append({"ticker": r["ticker"], "rs": int(r["RS"])})

    group_tickers = {}
    if has_nhom:
        for _, r in scores.dropna(subset=["nhom"]).iterrows():
            group_tickers.setdefault(r["nhom"], []).append({"ticker": r["ticker"], "rs": int(r["RS"])})

    group_data = {**industry_tickers, **group_tickers}

    chart_data, has_ohlc, has_volume = build_chart_data(df)

    # --- Chỉ số tổng hợp trọng số dòng tiền (đã làm mượt) - toàn thị trường + từng ngành + từng tập đoàn ---
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

    # --- VNINDEX giá trị thực, vẽ trên trục phụ (secondary axis) riêng để không lệch
    # thang so với chỉ số dòng tiền tự tính (vốn quy đổi mốc 1000) ---
    vnindex_series = []
    if not vnindex_df.empty:
        vnindex_series = build_real_series(vnindex_df[["date", "close"]])

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

    def render_ranking_panel(panel_id, active, block_size, unit, min_required_hint, stock_df, industry_df_):
        """Dựng khối HTML: formula-box (thu gọn, bấm mới xổ), tab Cổ phiếu/Ngành + ô tìm kiếm,
        dùng chung cho cả khung ngày và khung tuần (chỉ khác block_size/unit/dữ liệu)."""
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
    <table id="{panel_id}-stock-table">
      <tr><th>Mã</th><th>Ngành</th><th>{labels[0]}</th><th>{labels[1]}</th><th>{labels[2]}</th><th>{labels[3]}</th><th>Điểm thô*</th><th>RS</th></tr>
      {stock_rows(stock_df)}
    </table>
  </div>

  <div id="{panel_id}-industry" class="subtab-panel" style="display:none">
    <div class="hint">Bấm vào tên ngành để xem biểu đồ tất cả mã trong ngành</div>
    <table>
      <tr><th>Ngành</th><th>Điểm thô Ngành</th><th>RS Ngành</th></tr>
      {industry_rows(industry_df_)}
    </table>
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

    # --- Khu vực Chỉ số dòng tiền (chỉ hiện nếu có volume) ---
    if index_data:
        vn_hint = (
            ' · <span style="color:#f59e0b">- - -</span> VNIndex thực (trục phụ bên trái, không quy đổi)'
            if vnindex_series else ""
        )
        index_section_html = f"""
  <div class="section-title">📊 Chỉ số dòng tiền (Money-flow Weighted Index)</div>
  <div class="hint">Mốc khởi điểm 1000 điểm tại phiên đầu tiên có dữ liệu. Trọng số mỗi mã = SMA({INDEX_SMOOTH_WINDOW} phiên) của giá trị giao dịch (giá × khối lượng) — đã làm mượt để giảm nhiễu.</div>
  <div class="hint"><span style="color:#60a5fa">—</span> Chỉ số tự tính{vn_hint} · cột xám bên dưới = tổng giá trị giao dịch mỗi phiên</div>
  <select id="index-select" class="index-select"></select>
  <div id="index-chart-container"></div>
"""
    else:
        index_section_html = ""

    updated_at = datetime.now(timezone.utc).astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M")
    chart_data_json = json.dumps(chart_data, ensure_ascii=False)
    group_data_json = json.dumps(group_data, ensure_ascii=False)
    index_data_json = json.dumps(index_data, ensure_ascii=False)
    index_categories_json = json.dumps(index_categories, ensure_ascii=False)
    vnindex_json = json.dumps(vnindex_series, ensure_ascii=False)
    has_ohlc_json = "true" if has_ohlc else "false"
    has_volume_json = "true" if has_volume else "false"

    index_nav_item = '<a class="sticky-nav-item" href="#section-index">📊 Dòng tiền</a>' if index_data else ""

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
  .tf-toggle-row {{ display:flex; gap:8px; margin: 4px 0 20px; }}
  .tf-toggle-btn {{
    background:#334155; border:none; color:#94a3b8; font-size:14px; font-weight:600;
    padding:8px 18px; border-radius:8px; cursor:pointer;
  }}
  .tf-toggle-btn:hover {{ background:#475569; }}
  .tf-toggle-active {{ background:#2563eb; color:#fff; }}
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

  .index-select {{
    background:#1e293b; color:#e2e8f0; border:1px solid #334155; border-radius:8px;
    padding:8px 12px; font-size:14px; margin-bottom:12px;
  }}
  #index-chart-container {{ width:100%; height:360px; margin-bottom:40px; background:#1e293b; border-radius:8px; }}

  #chart-overlay, #group-overlay {{
    display:none; position:fixed; inset:0; background:rgba(0,0,0,0.6);
    align-items:center; justify-content:center; z-index:50; padding:20px;
  }}
  #chart-panel {{
    background:#1e293b; border-radius:12px; padding:20px; width:min(720px, 92vw);
    box-shadow: 0 20px 60px rgba(0,0,0,0.5);
  }}
  #chart-panel-header, #group-panel-header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; gap:12px; }}
  #chart-title, #group-title {{ font-size:18px; font-weight:600; flex:1; }}
  #chart-close, #group-close {{
    background:#334155; border:none; color:#e2e8f0; width:28px; height:28px;
    border-radius:6px; cursor:pointer; font-size:16px; line-height:1; flex-shrink:0;
  }}
  #chart-close:hover, #group-close:hover {{ background:#475569; }}

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

  .tf-toolbar {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }}
  .tf-toolbar-title {{ font-size:14px; font-weight:600; color:#e2e8f0; }}
  .tf-btns {{ display:flex; gap:4px; }}
  .tf-btn {{
    background:#334155; border:none; color:#94a3b8; font-size:12px; padding:4px 10px;
    border-radius:6px; cursor:pointer;
  }}
  .tf-btn:hover {{ background:#475569; }}
  .tf-btn.tf-active {{ background:#2563eb; color:#fff; }}

  /* Menu điều hướng dính trên đầu trang */
  .sticky-nav {{
    position: sticky; top:0; z-index:40; display:flex; gap:6px; flex-wrap:wrap; align-items:center;
    background:rgba(15,23,42,0.95); backdrop-filter: blur(4px);
    margin: -24px -24px 20px; padding:10px 24px; border-bottom:1px solid #334155;
  }}
  .sticky-nav-item {{
    color:#93c5fd; text-decoration:none; font-size:13px; font-weight:600;
    background:#1e293b; padding:6px 12px; border-radius:999px; border:1px solid #334155;
    white-space:nowrap;
  }}
  .sticky-nav-item:hover {{ background:#334155; color:#bfdbfe; }}

  /* Nút về đầu trang */
  .back-to-top {{
    position: fixed; bottom:24px; right:24px; width:44px; height:44px; border-radius:50%;
    background:#2563eb; color:#fff; border:none; font-size:18px; cursor:pointer;
    display:none; align-items:center; justify-content:center; box-shadow:0 6px 20px rgba(0,0,0,0.4);
    z-index:45;
  }}
  .back-to-top:hover {{ background:#1d4ed8; }}

  /* Box công thức RS - thu gọn mặc định (details/summary) */
  details.formula-box summary {{ cursor:pointer; list-style:none; }}
  details.formula-box summary::-webkit-details-marker {{ display:none; }}
  details.formula-box summary .formula-arrow {{ display:inline-block; transition:transform 0.15s; }}
  details.formula-box[open] summary .formula-arrow {{ transform: rotate(90deg); }}
  details.formula-box .formula-list {{ margin-top:12px; }}

  /* Tab Cổ phiếu / Ngành trong mỗi khung */
  .subtabs {{ display:flex; gap:8px; margin: 4px 0 14px; border-bottom:1px solid #334155; }}
  .subtab-btn {{
    background:transparent; border:none; border-bottom:2px solid transparent; color:#94a3b8;
    font-size:15px; font-weight:600; padding:8px 4px; cursor:pointer; margin-bottom:-1px;
  }}
  .subtab-btn:hover {{ color:#cbd5e1; }}
  .subtab-active {{ color:#60a5fa; border-bottom-color:#60a5fa; }}

  /* Ô tìm kiếm/lọc mã trong bảng xếp hạng cổ phiếu */
  .table-toolbar {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin:4px 0 12px; }}
  .search-box {{
    background:#1e293b; color:#e2e8f0; border:1px solid #334155; border-radius:8px;
    padding:8px 12px; font-size:14px; flex:1; min-width:200px; max-width:320px;
  }}
  .search-box:focus {{ outline:none; border-color:#60a5fa; }}
  .table-count {{ color:#64748b; font-size:12px; white-space:nowrap; }}
</style>
</head>
<body>
  <div id="top"></div>
  <nav class="sticky-nav">
    <a class="sticky-nav-item" href="#top">⬆ Đầu trang</a>
    <a class="sticky-nav-item" href="#section-ranking">🏆 Xếp hạng</a>
    {index_nav_item}
  </nav>
  <div class="header-row">
    <h1>📈 Bảng xếp hạng RS chứng khoán</h1>
    <a class="refresh-btn" href="{ACTIONS_URL}" target="_blank" rel="noopener">
      🔄 Cập nhật dữ liệu & tính lại RS
    </a>
  </div>
  <div class="updated">Cập nhật lần cuối: {updated_at}</div>
  <div class="refresh-hint">Nút trên mở trang GitHub Actions — bấm "Run workflow" ở đó để lấy dữ liệu mới nhất và tính lại RS ngay (cần đăng nhập GitHub với quyền chủ repo).</div>
  {group_links_html}
  <div id="section-ranking">
  {ranking_toggle_html}
  {day_panel_html}
  {week_panel_html}
  </div>
  <div id="section-index">
  {index_section_html}
  </div>

  <button id="back-to-top" class="back-to-top" onclick="window.scrollTo({{top:0, behavior:'smooth'}})" title="Về đầu trang">↑</button>

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

<script>
const CHART_DATA = {chart_data_json};
const GROUP_DATA = {group_data_json};
const INDEX_DATA = {index_data_json};
const INDEX_CATEGORIES = {index_categories_json};
const VNINDEX_DATA = {vnindex_json};
const HAS_OHLC = {has_ohlc_json};
const HAS_VOLUME = {has_volume_json};

let currentChartState = null;   // {{ chart, container }} - popup 1 mã
let groupChartStates = [];      // danh sách {{ chart, container }} - popup ngành/nhóm
let indexChart = null;

// ---------- Gộp dữ liệu ngày -> tuần (Thứ 2 làm mốc tuần) ----------
function getMonday(dateStr) {{
  const d = new Date(dateStr + 'T00:00:00Z');
  const day = d.getUTCDay();
  const diff = (day === 0 ? -6 : 1 - day);
  d.setUTCDate(d.getUTCDate() + diff);
  return d.toISOString().slice(0, 10);
}}

function aggregateWeekly(dailyArr) {{
  if (!dailyArr.length) return [];
  const isOHLC = dailyArr[0].length >= 5;
  const weeks = {{}};
  const order = [];
  for (const r of dailyArr) {{
    const key = getMonday(r[0]);
    if (!weeks[key]) {{
      order.push(key);
      weeks[key] = isOHLC
        ? {{ time: key, open: r[1], high: r[2], low: r[3], close: r[4], volume: (r[5] || 0) }}
        : {{ time: key, close: r[1] }};
    }} else {{
      const w = weeks[key];
      if (isOHLC) {{
        w.high = Math.max(w.high, r[2]);
        w.low = Math.min(w.low, r[3]);
        w.close = r[4];
        w.volume += (r[5] || 0);
      }} else {{
        w.close = r[1];
      }}
    }}
  }}
  return order.map(k => {{
    const w = weeks[k];
    return isOHLC ? [w.time, w.open, w.high, w.low, w.close, w.volume] : [w.time, w.close];
  }});
}}

// ---------- Vẽ 1 biểu đồ giá (nến+volume hoặc đường) từ dữ liệu dạng mảng ----------
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
    candleSeries.setData(data.map(d => ({{ time: d[0], open: d[1], high: d[2], low: d[3], close: d[4] }})));

    if (HAS_VOLUME) {{
      const volumeSeries = chart.addHistogramSeries({{
        priceFormat: {{ type: 'volume' }},
        priceScaleId: 'volume',
      }});
      chart.priceScale('volume').applyOptions({{ scaleMargins: {{ top: 0.8, bottom: 0 }} }});
      volumeSeries.setData(
        data.filter(d => d[5] !== undefined && d[5] !== null).map(d => ({{
          time: d[0], value: d[5],
          color: d[4] >= d[1] ? 'rgba(22,163,74,0.5)' : 'rgba(220,38,38,0.5)',
        }}))
      );
    }}
  }} else {{
    const series = chart.addLineSeries({{ color: '#60a5fa', lineWidth: 2 }});
    series.setData(data.map(d => ({{ time: d[0], value: d[1] }})));
  }}

  chart.timeScale().fitContent();
  return chart;
}}

// ---------- Gắn 1 biểu đồ + toolbar Ngày/Tuần vào 1 khu vực (dùng chung cho popup 1 mã và mini-chart) ----------
function mountChart(parentEl, dailyData, height, titleText) {{
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
  const state = {{ chart: buildPriceChart(chartDiv, dailyData, height), container: chartDiv }};

  toolbar.querySelectorAll('.tf-btn').forEach(btn => {{
    btn.addEventListener('click', (e) => {{
      e.stopPropagation();
      if (btn.classList.contains('tf-active')) return;
      toolbar.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('tf-active'));
      btn.classList.add('tf-active');
      state.chart.remove();
      const newData = btn.dataset.tf === 'W' ? weeklyData : dailyData;
      state.chart = buildPriceChart(chartDiv, newData, height);
    }});
  }});

  return state;
}}

// ---------- Popup 1 mã ----------
function closeChart() {{
  document.getElementById('chart-overlay').style.display = 'none';
  if (currentChartState) {{ currentChartState.chart.remove(); currentChartState = null; }}
  document.getElementById('chart-mount').innerHTML = '';
}}

function showChart(ticker) {{
  const data = CHART_DATA[ticker];
  if (!data) return;

  document.getElementById('chart-title').textContent = ticker + ' — Biểu đồ giá';
  document.getElementById('chart-overlay').style.display = 'flex';

  const mount = document.getElementById('chart-mount');
  mount.innerHTML = '';
  if (currentChartState) {{ currentChartState.chart.remove(); }}

  currentChartState = mountChart(mount, data, 360, '');
}}

// ---------- Popup Ngành / Nhóm (danh sách nhiều mini-chart) ----------
function closeGroupPopup() {{
  document.getElementById('group-overlay').style.display = 'none';
  groupChartStates.forEach(s => s.chart.remove());
  groupChartStates = [];
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
  groupChartStates.forEach(s => s.chart.remove());
  groupChartStates = [];

  list.forEach(item => {{
    const data = CHART_DATA[item.ticker];
    if (!data) return;

    const block = document.createElement('div');
    block.className = 'mini-chart-block';
    container.appendChild(block);

    block.addEventListener('click', () => {{
      closeGroupPopup();
      showChart(item.ticker);
    }});

    const state = mountChart(block, data, 320, item.ticker + ' — RS: ' + item.rs);
    groupChartStates.push(state);
  }});
}}

// ---------- Chuyển đổi bảng xếp hạng RS: Khung ngày / Khung tuần ----------
function switchRankingTimeframe(tf, btn) {{
  const dayPanel = document.getElementById('tf-panel-day');
  const weekPanel = document.getElementById('tf-panel-week');
  if (dayPanel) dayPanel.style.display = (tf === 'day') ? '' : 'none';
  if (weekPanel) weekPanel.style.display = (tf === 'week') ? '' : 'none';
  btn.parentElement.querySelectorAll('.tf-toggle-btn').forEach(b => b.classList.remove('tf-toggle-active'));
  btn.classList.add('tf-toggle-active');
}}

// ---------- Chỉ số dòng tiền (Money-flow Weighted Index) ----------
function renderIndexChart(name) {{
  const entry = INDEX_DATA[name];
  const container = document.getElementById('index-chart-container');
  if (!entry || !container) return;
  const data = entry.index;
  const volData = entry.volume || [];

  container.innerHTML = '';
  if (indexChart) {{ indexChart.remove(); }}

  const hasVnIndex = !!(VNINDEX_DATA && VNINDEX_DATA.length);

  indexChart = LightweightCharts.createChart(container, {{
    width: container.clientWidth,
    height: 360,
    layout: {{ background: {{ color: '#1e293b' }}, textColor: '#cbd5e1' }},
    grid: {{ vertLines: {{ color: '#334155' }}, horzLines: {{ color: '#334155' }} }},
    timeScale: {{ borderColor: '#475569' }},
    rightPriceScale: {{
      borderColor: '#475569',
      scaleMargins: volData.length ? {{ top: 0.1, bottom: 0.3 }} : {{ top: 0.1, bottom: 0.1 }},
    }},
    leftPriceScale: {{
      visible: hasVnIndex,
      borderColor: '#475569',
      scaleMargins: {{ top: 0.1, bottom: 0.1 }},
    }},
  }});

  const series = indexChart.addAreaSeries({{
    lineColor: '#60a5fa', topColor: 'rgba(96,165,250,0.3)', bottomColor: 'rgba(96,165,250,0.0)',
    lineWidth: 2, title: name,
  }});
  series.setData(data.map(d => ({{ time: d[0], value: d[1] }})));

  // Đường VNIndex GIÁ TRỊ THỰC, vẽ trên trục phụ bên trái (không quy đổi mốc 1000
  // như chỉ số tự tính) để luôn hiển thị đúng thang điểm thật của VNIndex
  if (hasVnIndex) {{
    const vnSeries = indexChart.addLineSeries({{
      color: '#f59e0b', lineWidth: 2, lineStyle: LightweightCharts.LineStyle.Dashed, title: 'VNIndex',
      priceScaleId: 'left',
    }});
    vnSeries.setData(VNINDEX_DATA.map(d => ({{ time: d[0], value: d[1] }})));
  }}

  // Cột tổng giá trị giao dịch (Σ giá×khối lượng mỗi ngày) bên dưới đường Index
  if (volData.length) {{
    const volSeries = indexChart.addHistogramSeries({{
      priceFormat: {{ type: 'volume' }},
      priceScaleId: 'index-volume',
      color: 'rgba(148,163,184,0.5)',
    }});
    indexChart.priceScale('index-volume').applyOptions({{ scaleMargins: {{ top: 0.8, bottom: 0 }} }});
    volSeries.setData(volData.map(d => ({{ time: d[0], value: d[1] }})));
  }}

  indexChart.timeScale().fitContent();
}}

function initIndexSelect() {{
  const select = document.getElementById('index-select');
  if (!select) return;
  const groupLabels = {{ industry: '📂 Theo ngành', nhom: '🏢 Theo tập đoàn' }};
  (INDEX_CATEGORIES.market || []).forEach(name => {{
    const opt = document.createElement('option');
    opt.value = name; opt.textContent = name;
    select.appendChild(opt);
  }});
  ['industry', 'nhom'].forEach(cat => {{
    const names = INDEX_CATEGORIES[cat] || [];
    if (!names.length) return;
    const og = document.createElement('optgroup');
    og.label = groupLabels[cat];
    names.forEach(name => {{
      const opt = document.createElement('option');
      opt.value = name; opt.textContent = name;
      og.appendChild(opt);
    }});
    select.appendChild(og);
  }});
  select.addEventListener('change', () => renderIndexChart(select.value));
  if (select.options.length) renderIndexChart(select.value);
}}
initIndexSelect();

// ---------- Tab Cổ phiếu / Ngành trong mỗi khung ngày-tuần ----------
function switchSubtab(panelId, tab, btn) {{
  const stockPanel = document.getElementById(panelId + '-stock');
  const industryPanel = document.getElementById(panelId + '-industry');
  if (stockPanel) stockPanel.style.display = (tab === 'stock') ? '' : 'none';
  if (industryPanel) industryPanel.style.display = (tab === 'industry') ? '' : 'none';
  btn.parentElement.querySelectorAll('.subtab-btn').forEach(b => b.classList.remove('subtab-active'));
  btn.classList.add('subtab-active');
}}

// ---------- Ô tìm kiếm/lọc mã trong bảng xếp hạng cổ phiếu ----------
function filterStockTable(panelId) {{
  const input = document.getElementById(panelId + '-search');
  const table = document.getElementById(panelId + '-stock-table');
  const countEl = document.getElementById(panelId + '-count');
  if (!input || !table) return;
  const q = input.value.trim().toLowerCase();
  const rows = table.querySelectorAll('tr.stock-row');
  let visible = 0;
  rows.forEach(row => {{
    const match = row.textContent.toLowerCase().includes(q);
    row.style.display = match ? '' : 'none';
    if (match) visible++;
  }});
  if (countEl) countEl.textContent = `${{visible}}/${{rows.length}} mã`;
}}

// ---------- Nút về đầu trang ----------
window.addEventListener('scroll', () => {{
  const btn = document.getElementById('back-to-top');
  if (btn) btn.style.display = (window.scrollY > 400) ? 'flex' : 'none';
}});

// ---------- Resize ----------
window.addEventListener('resize', () => {{
  if (currentChartState) {{
    currentChartState.chart.applyOptions({{ width: currentChartState.container.clientWidth }});
  }}
  groupChartStates.forEach(s => {{
    s.chart.applyOptions({{ width: s.container.clientWidth }});
  }});
  if (indexChart) {{
    const c = document.getElementById('index-chart-container');
    if (c) indexChart.applyOptions({{ width: c.clientWidth }});
  }}
}});
</script>
</body>
</html>"""

    os.makedirs("docs", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    chart_kind = "nến+volume" if (has_ohlc and has_volume) else ("nến" if has_ohlc else "đường (thiếu OHLC đầy đủ)")
    print(
        f"Đã tạo {OUTPUT_FILE} (kèm biểu đồ {chart_kind}, {len(group_data)} mục ngành/nhóm có popup, "
        f"{len(index_data)} chỉ số dòng tiền)"
    )


if __name__ == "__main__":
    main()
