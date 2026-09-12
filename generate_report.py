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
import importlib.util
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

INPUT_FILE = "gia_lich_su_rs.csv"
OUTPUT_FILE = "docs/index.html"
INDICATORS_DIR = "indicators"  # thư mục chứa các file chỉ báo

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


def load_indicators():
    """
    Đọc toàn bộ file chỉ báo trong thư mục INDICATORS_DIR.
    - File .py  : import module, lấy NAME/PANEL/compute
    - File .js  : đọc raw text để nhúng vào HTML
    Bỏ qua file bắt đầu bằng _ hoặc không đúng format.
    Trả về (py_indicators, js_indicators)
    """
    py_indicators = []
    js_raw = []

    if not os.path.isdir(INDICATORS_DIR):
        return py_indicators, js_raw

    for fname in sorted(os.listdir(INDICATORS_DIR)):
        fpath = os.path.join(INDICATORS_DIR, fname)
        if fname.startswith("_"):
            continue

        if fname.endswith(".py"):
            try:
                spec = importlib.util.spec_from_file_location(fname[:-3], fpath)
                mod  = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if not all(hasattr(mod, attr) for attr in ("NAME", "PANEL", "compute")):
                    print(f"  [indicators] Bỏ qua {fname}: thiếu NAME/PANEL/compute")
                    continue
                py_indicators.append({"name": mod.NAME, "panel": mod.PANEL, "module": mod, "file": fname})
                print(f"  [indicators] Đã load {fname} ({mod.NAME}, panel={mod.PANEL})")
            except Exception as e:
                print(f"  [indicators] Lỗi load {fname}: {e}")

        elif fname.endswith(".js") and not fname.startswith("custom_example"):
            try:
                with open(fpath, encoding="utf-8") as f:
                    js_raw.append({"file": fname, "code": f.read()})
                print(f"  [indicators] Đã load JS {fname}")
            except Exception as e:
                print(f"  [indicators] Lỗi load JS {fname}: {e}")

    return py_indicators, js_raw


def compute_indicators_for_ticker(ticker_df, py_indicators):
    """
    Chạy compute() của từng Python indicator trên dữ liệu 1 mã.
    Trả về dict: { indicator_name: { panel, series: [...] } }
    """
    results = {}
    df = ticker_df.sort_values("date").reset_index(drop=True)

    for ind in py_indicators:
        try:
            series_list = ind["module"].compute(df)
            results[ind["name"]] = {
                "panel" : ind["panel"],
                "series": series_list,
            }
        except Exception as e:
            print(f"  [indicators] Lỗi compute {ind['file']} cho {df['ticker'].iloc[0] if len(df) else '?'}: {e}")

    return results


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

    # --- Load chỉ báo kỹ thuật từ thư mục indicators/ ---
    print("\nĐang load chỉ báo kỹ thuật...")
    py_indicators, js_indicators = load_indicators()
    print(f"Đã load {len(py_indicators)} Python indicator(s), {len(js_indicators)} JS indicator(s)")

    # Tính toán chỉ báo cho từng mã (chỉ dùng dữ liệu ngày)
    indicator_data = {}
    if py_indicators:
        for ticker in df["ticker"].unique():
            ticker_df = df[df["ticker"] == ticker][["date","open","high","low","close","volume"]].copy()
            indicator_data[ticker] = compute_indicators_for_ticker(ticker_df, py_indicators)

    indicator_data_json = json.dumps(indicator_data, ensure_ascii=False)
    py_indicator_names  = json.dumps([i["name"] for i in py_indicators], ensure_ascii=False)
    js_indicators_code  = "\n\n".join(f"// --- {j['file']} ---\n{j['code']}" for j in js_indicators)
    chart_data_json = json.dumps(chart_data, ensure_ascii=False)
    group_data_json = json.dumps(group_data, ensure_ascii=False)
    index_data_json = json.dumps(index_data, ensure_ascii=False)
    index_categories_json = json.dumps(index_categories, ensure_ascii=False)
    vnindex_json = json.dumps(vnindex_series, ensure_ascii=False)
    has_ohlc_json = "true" if has_ohlc else "false"
    has_volume_json = "true" if has_volume else "false"

    index_nav_item = '<a class="sticky-nav-item" href="#section-index">📊 Dòng tiền</a>' if index_data else ""

    # --- Đọc dữ liệu vĩ mô từ macro_data.json (nếu có) ---
    macro_data = {}
    MACRO_FILE = "macro_data.json"
    if os.path.exists(MACRO_FILE):
        try:
            with open(MACRO_FILE, encoding="utf-8") as f:
                macro_data = json.load(f)
            print(f"Đã đọc {MACRO_FILE} ({len(macro_data.get('series', {}))} series)")
        except Exception as e:
            print(f"CẢNH BÁO: Không đọc được {MACRO_FILE}: {e}")

    macro_data_json = json.dumps(macro_data, ensure_ascii=False)
    macro_nav_item  = '<a class="sticky-nav-item" href="#section-macro">🌐 Vĩ mô</a>' if macro_data else ""

    # Build dropdown và section vĩ mô
    if macro_data and macro_data.get("series"):
        groups  = macro_data.get("groups", {})
        series  = macro_data.get("series", {})
        updated = macro_data.get("updated_at", "")

        # Tạo options theo optgroup
        opts_html = ""
        for group_name, keys in groups.items():
            opts_html += f'<optgroup label="{group_name}">'
            for key in keys:
                label = series[key]["label"] if key in series else key
                opts_html += f'<option value="{key}">{label}</option>'
            opts_html += '</optgroup>'

        macro_section_html = f"""
  <div class="section-title">🌐 Dữ liệu vĩ mô</div>
  <div class="hint">Nguồn: FRED (Federal Reserve Bank of St. Louis) · World Bank · Cập nhật lần cuối: {updated}</div>
  <div class="hint"><span style="color:#60a5fa">—</span> Chọn chỉ số từ dropdown để xem biểu đồ</div>
  <select id="macro-select" class="index-select">{opts_html}</select>
  <div id="macro-chart-container" style="width:100%;height:360px;background:#1e293b;border-radius:8px;margin-top:8px;"></div>
  <div id="macro-description" class="hint" style="margin-top:8px;color:#94a3b8;font-style:italic;"></div>
"""
    else:
        macro_section_html = ""

    # Section dự báo FOMC (Fed Funds & Core PCE, nhiều vintage) - chỉ hiện nếu có dữ liệu
    fomc_data = macro_data.get("fomc_projections", {}) if macro_data else {}
    if fomc_data:
        fomc_section_html = """
  <div class="section-title" style="margin-top:28px;">📊 Dự báo của Fed (Summary of Economic Projections)</div>
  <div class="hint">So sánh dự báo Fed Funds Rate &amp; Core PCE qua các kỳ họp FOMC gần nhất — mỗi màu cột là 1 lần công bố dự báo (nguồn: FRED/ALFRED).</div>
  <div class="fomc-grid">
    <div class="fomc-card">
      <div class="fomc-card-title">Dự báo Fed Funds Rate (Median)</div>
      <div id="fomc-fedfunds-chart"></div>
    </div>
    <div class="fomc-card">
      <div class="fomc-card-title">Dự báo Core PCE Inflation (Median)</div>
      <div id="fomc-corepce-chart"></div>
    </div>
  </div>
"""
    else:
        fomc_section_html = ""

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

  /* Thanh chỉ báo kỹ thuật ngay trên biểu đồ */
  .indicator-toolbar {{
    display: flex; flex-wrap: wrap; gap: 6px;
    padding: 8px 12px; background: #1e293b;
    border-bottom: 1px solid #334155;
  }}
  .ind-btn {{
    background: #334155; border: 1px solid #475569; color: #94a3b8;
    font-size: 12px; font-weight: 600; padding: 4px 10px;
    border-radius: 6px; cursor: pointer; white-space: nowrap;
  }}
  .ind-btn:hover {{ background: #475569; color: #e2e8f0; }}
  .ind-btn.ind-active {{ background: #2563eb; border-color: #3b82f6; color: #fff; }}
  .ind-panel {{ border-top: 1px solid #334155; }}

  /* Thanh công cụ vẽ kiểu TradingView (trendline, ngang/dọc, vùng, ghi chú, fibo) */
  .draw-toolbar {{
    display: flex; flex-wrap: wrap; gap: 6px; align-items:center;
    padding: 8px 12px; background: #1e293b;
    border-bottom: 1px solid #334155;
  }}
  .draw-toolbar-label {{ color:#64748b; font-size:12px; margin-right:2px; }}
  .draw-btn {{
    background: #334155; border: 1px solid #475569; color: #94a3b8;
    font-size: 12px; font-weight: 600; padding: 4px 10px;
    border-radius: 6px; cursor: pointer; white-space: nowrap;
  }}
  .draw-btn:hover {{ background: #475569; color: #e2e8f0; }}
  .draw-btn.draw-active {{ background: #059669; border-color: #10b981; color: #fff; }}
  .draw-btn.draw-erase.draw-active {{ background: #dc2626; border-color: #ef4444; }}
  #draw-canvas {{ position:absolute; top:0; left:0; z-index:5; }}

  /* Dự báo FOMC (Fed Funds & Core PCE, nhiều vintage) */
  .fomc-grid {{ display:grid; grid-template-columns: 1fr 1fr; gap:16px; margin-top:12px; }}
  @media (max-width: 700px) {{ .fomc-grid {{ grid-template-columns: 1fr; }} }}
  .fomc-card {{ background:#1e293b; border-radius:8px; padding:16px; }}
  .fomc-card-title {{ color:#94a3b8; font-size:13px; margin-bottom:10px; font-weight:600; }}
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
    {macro_nav_item}
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
  <div id="section-macro">
  {macro_section_html}
  {fomc_section_html}
  </div>

  <button id="back-to-top" class="back-to-top" onclick="window.scrollTo({{top:0, behavior:'smooth'}})" title="Về đầu trang">↑</button>

  <div id="chart-overlay" onclick="if(event.target===this) closeChart()">
    <div id="chart-panel">
      <div id="chart-panel-header">
        <div id="chart-title">Biểu đồ giá</div>
        <button id="chart-close" onclick="closeChart()">✕</button>
      </div>
      <div id="indicator-toolbar" class="indicator-toolbar" style="display:none"></div>
      <div id="draw-toolbar" class="draw-toolbar">
        <span class="draw-toolbar-label">✏️ Vẽ:</span>
        <button class="draw-btn" data-draw="trend">📈 Xu hướng</button>
        <button class="draw-btn" data-draw="hline">➖ Ngang</button>
        <button class="draw-btn" data-draw="vline">┃ Dọc</button>
        <button class="draw-btn" data-draw="rect">▭ Vùng</button>
        <button class="draw-btn" data-draw="text">🔤 Ghi chú</button>
        <button class="draw-btn" data-draw="fib">📐 Fibonacci</button>
        <button class="draw-btn draw-erase" data-draw="erase">🗑 Xoá nét</button>
        <button class="draw-btn" id="draw-clear-all">🧹 Xoá hết</button>
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
const INDICATOR_DATA = {indicator_data_json};
const PY_INDICATOR_NAMES = {py_indicator_names};
const MACRO_DATA = {macro_data_json};
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

  let mainSeries = null;

  if (HAS_OHLC) {{
    const candleSeries = chart.addCandlestickSeries({{
      upColor: '#16a34a', downColor: '#dc2626',
      borderUpColor: '#16a34a', borderDownColor: '#dc2626',
      wickUpColor: '#16a34a', wickDownColor: '#dc2626',
    }});
    candleSeries.setData(data.map(d => ({{ time: d[0], open: d[1], high: d[2], low: d[3], close: d[4] }})));
    mainSeries = candleSeries;

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
    mainSeries = series;
  }}

  chart.timeScale().fitContent();
  return {{ chart, series: mainSeries }};
}}

// ---------- Gắn 1 biểu đồ + toolbar Ngày/Tuần vào 1 khu vực (dùng chung cho popup 1 mã và mini-chart) ----------
function mountChart(parentEl, dailyData, height, titleText, enableDrawing) {{
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
  const built = buildPriceChart(chartDiv, dailyData, height);
  const state = {{ chart: built.chart, series: built.series, container: chartDiv }};

  if (enableDrawing) {{
    setupDrawingLayer(chartDiv, state.chart, state.series);
    window.currentChart = state.chart;
  }}

  toolbar.querySelectorAll('.tf-btn').forEach(btn => {{
    btn.addEventListener('click', (e) => {{
      e.stopPropagation();
      if (btn.classList.contains('tf-active')) return;
      toolbar.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('tf-active'));
      btn.classList.add('tf-active');
      state.chart.remove();
      const newData = btn.dataset.tf === 'W' ? weeklyData : dailyData;
      const rebuilt = buildPriceChart(chartDiv, newData, height);
      state.chart = rebuilt.chart;
      state.series = rebuilt.series;
      if (enableDrawing) {{
        setupDrawingLayer(chartDiv, state.chart, state.series);
        window.currentChart = state.chart;
        // Đổi khung Ngày/Tuần làm mất chart cũ -> vẽ lại chỉ báo đang bật (nếu có)
        if (_activeIndicators.size > 0 && _drawTicker) applyIndicators(_drawTicker);
      }}
    }});
  }});

  return state;
}}

// ---------- Popup 1 mã ----------
function closeChart() {{
  document.getElementById('chart-overlay').style.display = 'none';
  if (currentChartState) {{ currentChartState.chart.remove(); currentChartState = null; }}
  document.getElementById('chart-mount').innerHTML = '';
  window._draw = null;
  _drawMode = null;
  _drawPending = null;
  _drawHoverPt = null;
  document.querySelectorAll('#draw-toolbar .draw-btn').forEach(b => b.classList.remove('draw-active'));
}}

function showChart(ticker) {{
  const data = CHART_DATA[ticker];
  if (!data) return;

  document.getElementById('chart-title').textContent = ticker + ' — Biểu đồ giá';
  document.getElementById('chart-overlay').style.display = 'flex';

  const mount = document.getElementById('chart-mount');
  mount.innerHTML = '';
  if (currentChartState) {{ currentChartState.chart.remove(); }}

  // Xóa panel indicator cũ khi mở mã mới
  document.querySelectorAll('.ind-panel').forEach(el => el.remove());
  if (window._overlaySeriesRefs) window._overlaySeriesRefs = [];

  // Nạp nét vẽ đã lưu (localStorage) của mã này, tắt sẵn mọi công cụ vẽ
  _drawTicker = ticker;
  _drawings = loadDrawings(ticker);
  _drawMode = null;
  _drawPending = null;
  _drawHoverPt = null;
  document.querySelectorAll('#draw-toolbar .draw-btn').forEach(b => b.classList.remove('draw-active'));

  currentChartState = mountChart(mount, data, 360, '', true);
  window.currentChart = currentChartState.chart;

  // Build thanh nút chỉ báo + áp dụng các chỉ báo đang active
  buildIndicatorToolbar(ticker);
  if (_activeIndicators.size > 0) applyIndicators(ticker);
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

    const state = mountChart(block, data, 320, item.ticker + ' — RS: ' + item.rs, false);
    groupChartStates.push(state);
  }});
}}

// ---------- JS Indicators (từ thư mục indicators/*.js) ----------
{js_indicators_code}

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

// ---------- Chỉ báo kỹ thuật: toolbar + render ----------
const _activeIndicators = new Set();

function buildIndicatorToolbar(ticker) {{
  const toolbar = document.getElementById('indicator-toolbar');
  if (!toolbar) return;
  toolbar.innerHTML = '';
  if (!PY_INDICATOR_NAMES.length) {{ toolbar.style.display = 'none'; return; }}
  toolbar.style.display = 'flex';
  PY_INDICATOR_NAMES.forEach(name => {{
    const btn = document.createElement('button');
    btn.className = 'ind-btn' + (_activeIndicators.has(name) ? ' ind-active' : '');
    btn.textContent = name;
    btn.onclick = () => {{
      if (_activeIndicators.has(name)) _activeIndicators.delete(name);
      else _activeIndicators.add(name);
      btn.classList.toggle('ind-active');
      applyIndicators(ticker);
    }};
    toolbar.appendChild(btn);
  }});
}}

function applyIndicators(ticker) {{
  // Xóa tất cả panel indicator cũ
  document.querySelectorAll('.ind-panel').forEach(el => el.remove());

  const tickerData = INDICATOR_DATA[ticker];
  if (!tickerData || !currentChart) return;

  // Overlay: thêm series vào chart nến hiện tại
  if (_overlaySeriesRefs) {{
    _overlaySeriesRefs.forEach(s => {{ try {{ currentChart.removeSeries(s); }} catch(e) {{}} }});
  }}
  window._overlaySeriesRefs = [];

  const LW = LightweightCharts;
  const container = currentChartState ? currentChartState.container : null;
  if (!container) return;

  _activeIndicators.forEach(indName => {{
    const indData = tickerData[indName];
    if (!indData) return;

    if (indData.panel === 'overlay') {{
      // Vẽ chồng lên biểu đồ nến chính
      indData.series.forEach(s => {{
        const ls = currentChart.addLineSeries({{
          color: s.color, lineWidth: s.width || 1, title: s.label,
          lineStyle: s.dashed ? LW.LineStyle.Dashed : LW.LineStyle.Solid,
          priceLineVisible: false, lastValueVisible: true,
        }});
        ls.setData(s.values.filter(v => v[1] !== null).map(v => ({{time: v[0], value: v[1]}})));
        window._overlaySeriesRefs.push(ls);
      }});

    }} else if (indData.panel === 'volume') {{
      // Vẽ MA trên panel volume — dùng chung trục với volume series
      indData.series.forEach(s => {{
        const ls = currentChart.addLineSeries({{
          color: s.color, lineWidth: s.width || 2, title: s.label,
          priceScaleId: 'volume', priceLineVisible: false, lastValueVisible: true,
        }});
        ls.setData(s.values.filter(v => v[1] !== null).map(v => ({{time: v[0], value: v[1]}})));
        window._overlaySeriesRefs.push(ls);
      }});

    }} else {{
      // Separate panel: tạo chart mới bên dưới
      const panelDiv = document.createElement('div');
      panelDiv.className = 'ind-panel';
      panelDiv.style.cssText = 'height:120px;width:100%;';
      container.parentNode.insertBefore(panelDiv, container.nextSibling);

      const panelChart = LW.createChart(panelDiv, {{
        width: panelDiv.clientWidth, height: 120,
        layout: {{ background: {{color:'#1e293b'}}, textColor:'#cbd5e1' }},
        grid: {{ vertLines: {{color:'#334155'}}, horzLines: {{color:'#334155'}} }},
        timeScale: {{ borderColor:'#475569', visible: true }},
        rightPriceScale: {{ borderColor:'#475569', scaleMargins: {{top:0.05, bottom:0.05}} }},
        crosshair: {{ mode: LW.CrosshairMode.Normal }},
      }});

      // Đồng bộ timeScale với chart chính
      panelChart.timeScale().subscribeVisibleLogicalRangeChange(range => {{
        if (range && currentChart) currentChart.timeScale().setVisibleLogicalRange(range);
      }});

      indData.series.forEach(s => {{
        let series;
        if (s.type === 'histogram') {{
          series = panelChart.addHistogramSeries({{
            color: s.color, priceLineVisible: false, lastValueVisible: false,
            priceFormat: {{type:'price', precision:4, minMove:0.0001}},
          }});
          series.setData(s.values.filter(v => v[1] !== null)
            .map(v => ({{time: v[0], value: v[1], color: v[2] || s.color}})));
        }} else {{
          series = panelChart.addLineSeries({{
            color: s.color, lineWidth: s.width || 1, title: s.label,
            lineStyle: s.dashed ? LW.LineStyle.Dashed : LW.LineStyle.Solid,
            priceLineVisible: false, lastValueVisible: true,
            priceFormat: {{type:'price', precision:2, minMove:0.01}},
          }});
          series.setData(s.values.filter(v => v[1] !== null).map(v => ({{time: v[0], value: v[1]}})));
        }}
        // RSI: thêm ngưỡng overbought/oversold bằng price line
        if (s.y_min !== undefined) panelChart.priceScale('right').applyOptions({{
          autoScale: false, minimum: s.y_min, maximum: s.y_max,
        }});
      }});

      panelChart.timeScale().fitContent();
    }}
  }});
}}

// ---------- Công cụ vẽ kiểu TradingView (trend line, ngang/dọc, vùng, ghi chú, fibonacci) ----------
// Nét vẽ được lưu theo từng mã trong localStorage (key: rs_draw_<ticker>), không đồng bộ máy khác.
let _drawMode = null;      // 'trend' | 'hline' | 'vline' | 'rect' | 'text' | 'fib' | 'erase' | null
let _drawPending = null;   // điểm {{time, price}} đầu tiên khi cần 2 điểm (trend/rect/fib)
let _drawHoverPt = null;   // {{x, y}} vị trí chuột hiện tại, dùng để xem trước nét vẽ
let _drawings = [];        // mảng nét vẽ của mã đang mở popup
let _drawTicker = null;    // mã đang mở popup

const DRAW_COLORS = {{
  trend: '#3b82f6', hline: '#f59e0b', vline: '#a78bfa',
  rect: '#10b981', text: '#e2e8f0', fib: '#facc15',
}};

function loadDrawings(ticker) {{
  try {{
    const raw = localStorage.getItem('rs_draw_' + ticker);
    return raw ? JSON.parse(raw) : [];
  }} catch (e) {{
    return [];
  }}
}}

function saveDrawings() {{
  if (!_drawTicker) return;
  try {{ localStorage.setItem('rs_draw_' + _drawTicker, JSON.stringify(_drawings)); }} catch (e) {{}}
}}

// Gắn canvas vẽ đè lên 1 chartDiv (chỉ dùng cho popup 1 mã, không dùng cho mini-chart)
function setupDrawingLayer(container, chart, series) {{
  const old = container.querySelector('#draw-canvas');
  if (old) old.remove();

  container.style.position = 'relative';
  const canvas = document.createElement('canvas');
  canvas.id = 'draw-canvas';
  canvas.width = container.clientWidth;
  canvas.height = container.clientHeight;
  canvas.style.pointerEvents = _drawMode ? 'auto' : 'none';
  container.appendChild(canvas);

  window._draw = {{ canvas, ctx: canvas.getContext('2d'), chart, series, container }};

  canvas.addEventListener('click', onDrawCanvasClick);
  canvas.addEventListener('mousemove', onDrawCanvasMouseMove);
  canvas.addEventListener('mouseleave', () => {{ _drawHoverPt = null; redrawDrawings(); }});
  chart.timeScale().subscribeVisibleLogicalRangeChange(redrawDrawings);

  redrawDrawings();
}}

function xyToPoint(x, y) {{
  if (!window._draw) return null;
  const {{ chart, series }} = window._draw;
  const time = chart.timeScale().coordinateToTime(x);
  const price = series.coordinateToPrice(y);
  if (time === null || price === null) return null;
  return {{ time, price }};
}}

function pointToXY(pt) {{
  if (!window._draw || !pt) return null;
  const {{ chart, series }} = window._draw;
  const x = chart.timeScale().timeToCoordinate(pt.time);
  const y = series.priceToCoordinate(pt.price);
  if (x === null || y === null) return null;
  return {{ x, y }};
}}

function distToSegment(px, py, x1, y1, x2, y2) {{
  const dx = x2 - x1, dy = y2 - y1;
  const lenSq = dx * dx + dy * dy;
  let t = lenSq === 0 ? 0 : ((px - x1) * dx + (py - y1) * dy) / lenSq;
  t = Math.max(0, Math.min(1, t));
  const cx = x1 + t * dx, cy = y1 + t * dy;
  return Math.hypot(px - cx, py - cy);
}}

function findDrawingNear(x, y) {{
  const THRESH = 8;
  for (let i = _drawings.length - 1; i >= 0; i--) {{
    const d = _drawings[i];
    if (d.type === 'hline') {{
      const py = window._draw.series.priceToCoordinate(d.price);
      if (py !== null && Math.abs(y - py) <= THRESH) return i;
    }} else if (d.type === 'vline') {{
      const px = window._draw.chart.timeScale().timeToCoordinate(d.time);
      if (px !== null && Math.abs(x - px) <= THRESH) return i;
    }} else if (d.type === 'trend' || d.type === 'fib') {{
      const p1 = pointToXY(d.p1), p2 = pointToXY(d.p2);
      if (p1 && p2 && distToSegment(x, y, p1.x, p1.y, p2.x, p2.y) <= THRESH) return i;
    }} else if (d.type === 'rect') {{
      const p1 = pointToXY(d.p1), p2 = pointToXY(d.p2);
      if (!p1 || !p2) continue;
      const rx = Math.min(p1.x, p2.x), ry = Math.min(p1.y, p2.y);
      const rw = Math.abs(p2.x - p1.x), rh = Math.abs(p2.y - p1.y);
      const nearEdge = Math.abs(x - rx) <= THRESH || Math.abs(x - (rx + rw)) <= THRESH ||
                        Math.abs(y - ry) <= THRESH || Math.abs(y - (ry + rh)) <= THRESH;
      const inBounds = x >= rx - THRESH && x <= rx + rw + THRESH && y >= ry - THRESH && y <= ry + rh + THRESH;
      if (nearEdge && inBounds) return i;
    }} else if (d.type === 'text') {{
      const xy = pointToXY(d.p);
      if (xy && Math.abs(x - xy.x) <= 30 && Math.abs(y - xy.y) <= 12) return i;
    }}
  }}
  return -1;
}}

function finishDraw() {{
  _drawMode = null;
  document.querySelectorAll('#draw-toolbar .draw-btn').forEach(b => b.classList.remove('draw-active'));
  if (window._draw) window._draw.canvas.style.pointerEvents = 'none';
  saveDrawings();
  redrawDrawings();
}}

function onDrawCanvasClick(e) {{
  if (!_drawMode || !window._draw) return;
  const rect = window._draw.canvas.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;

  if (_drawMode === 'erase') {{
    const idx = findDrawingNear(x, y);
    if (idx >= 0) {{
      _drawings.splice(idx, 1);
      saveDrawings();
      redrawDrawings();
    }}
    return;
  }}

  const pt = xyToPoint(x, y);
  if (!pt) return;

  if (_drawMode === 'hline') {{
    _drawings.push({{ type: 'hline', price: pt.price, color: DRAW_COLORS.hline }});
    finishDraw();
    return;
  }}
  if (_drawMode === 'vline') {{
    _drawings.push({{ type: 'vline', time: pt.time, color: DRAW_COLORS.vline }});
    finishDraw();
    return;
  }}
  if (_drawMode === 'text') {{
    const txt = prompt('Nhập nội dung ghi chú:');
    if (txt) {{
      _drawings.push({{ type: 'text', p: pt, text: txt, color: DRAW_COLORS.text }});
      finishDraw();
    }}
    return;
  }}

  // Các loại cần 2 điểm: trend line / vùng / fibonacci
  if (!_drawPending) {{
    _drawPending = pt;
    redrawDrawings();
  }} else {{
    const type = _drawMode;
    _drawings.push({{ type, p1: _drawPending, p2: pt, color: DRAW_COLORS[type] }});
    _drawPending = null;
    finishDraw();
  }}
}}

function onDrawCanvasMouseMove(e) {{
  if (!_drawMode || !window._draw) return;
  if (!_drawPending) return; // chỉ cần preview khi đã có điểm đầu (trend/rect/fib)
  const rect = window._draw.canvas.getBoundingClientRect();
  _drawHoverPt = {{ x: e.clientX - rect.left, y: e.clientY - rect.top }};
  redrawDrawings();
}}

function renderDrawing(ctx, d) {{
  const {{ canvas }} = window._draw;

  if (d.type === 'hline') {{
    const y = window._draw.series.priceToCoordinate(d.price);
    if (y === null) return;
    ctx.strokeStyle = d.color; ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = d.color; ctx.font = '11px sans-serif';
    ctx.fillText(d.price.toFixed(2), canvas.width - 60, y - 4);
    return;
  }}
  if (d.type === 'vline') {{
    const x = window._draw.chart.timeScale().timeToCoordinate(d.time);
    if (x === null) return;
    ctx.strokeStyle = d.color; ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, canvas.height); ctx.stroke();
    ctx.setLineDash([]);
    return;
  }}
  if (d.type === 'text') {{
    const xy = pointToXY(d.p);
    if (!xy) return;
    ctx.font = '12px sans-serif';
    const padding = 4;
    const w = ctx.measureText(d.text).width + padding * 2;
    ctx.fillStyle = 'rgba(15,23,42,0.85)';
    ctx.fillRect(xy.x, xy.y - 16, w, 20);
    ctx.fillStyle = d.color;
    ctx.fillText(d.text, xy.x + padding, xy.y - 2);
    return;
  }}
  if (d.type === 'trend') {{
    const p1 = pointToXY(d.p1), p2 = pointToXY(d.p2);
    if (!p1 || !p2) return;
    ctx.strokeStyle = d.color; ctx.lineWidth = 2; ctx.setLineDash([]);
    ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke();
    return;
  }}
  if (d.type === 'rect') {{
    const p1 = pointToXY(d.p1), p2 = pointToXY(d.p2);
    if (!p1 || !p2) return;
    const x = Math.min(p1.x, p2.x), y = Math.min(p1.y, p2.y);
    const w = Math.abs(p2.x - p1.x), h = Math.abs(p2.y - p1.y);
    ctx.fillStyle = d.color + '33';
    ctx.fillRect(x, y, w, h);
    ctx.strokeStyle = d.color; ctx.lineWidth = 1; ctx.setLineDash([]);
    ctx.strokeRect(x, y, w, h);
    return;
  }}
  if (d.type === 'fib') {{
    const p1 = pointToXY(d.p1), p2 = pointToXY(d.p2);
    if (!p1 || !p2) return;
    const levels = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
    const xLeft = Math.min(p1.x, p2.x);
    ctx.font = '10px sans-serif';
    levels.forEach(lv => {{
      const price = d.p1.price + (d.p2.price - d.p1.price) * lv;
      const y = window._draw.series.priceToCoordinate(price);
      if (y === null) return;
      ctx.strokeStyle = d.color; ctx.globalAlpha = 0.7; ctx.lineWidth = 1; ctx.setLineDash([]);
      ctx.beginPath(); ctx.moveTo(xLeft, y); ctx.lineTo(canvas.width, y); ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.fillStyle = d.color;
      ctx.fillText(lv.toFixed(3) + ' (' + price.toFixed(2) + ')', xLeft + 4, y - 3);
    }});
    return;
  }}
}}

function renderPreview(ctx, mode, p1xy, p2xy) {{
  ctx.setLineDash([4, 3]);
  ctx.globalAlpha = 0.7;
  if (mode === 'trend' || mode === 'fib') {{
    ctx.strokeStyle = DRAW_COLORS[mode]; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(p1xy.x, p1xy.y); ctx.lineTo(p2xy.x, p2xy.y); ctx.stroke();
  }} else if (mode === 'rect') {{
    const x = Math.min(p1xy.x, p2xy.x), y = Math.min(p1xy.y, p2xy.y);
    const w = Math.abs(p2xy.x - p1xy.x), h = Math.abs(p2xy.y - p1xy.y);
    ctx.strokeStyle = DRAW_COLORS.rect; ctx.lineWidth = 1;
    ctx.strokeRect(x, y, w, h);
  }}
  ctx.setLineDash([]);
  ctx.globalAlpha = 1;
}}

function redrawDrawings() {{
  if (!window._draw) return;
  const {{ ctx, canvas }} = window._draw;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  _drawings.forEach(d => renderDrawing(ctx, d));
  if (_drawPending && _drawHoverPt) {{
    const p1xy = pointToXY(_drawPending);
    if (p1xy) renderPreview(ctx, _drawMode, p1xy, _drawHoverPt);
  }}
}}

// Gắn sự kiện cho thanh nút vẽ (chạy 1 lần lúc tải trang, các nút này cố định trong HTML)
document.querySelectorAll('#draw-toolbar .draw-btn[data-draw]').forEach(btn => {{
  btn.addEventListener('click', () => {{
    const mode = btn.dataset.draw;
    _drawMode = (_drawMode === mode) ? null : mode;
    _drawPending = null;
    document.querySelectorAll('#draw-toolbar .draw-btn').forEach(b => {{
      b.classList.toggle('draw-active', b.dataset.draw === _drawMode);
    }});
    if (window._draw) window._draw.canvas.style.pointerEvents = _drawMode ? 'auto' : 'none';
    redrawDrawings();
  }});
}});
const _drawClearAllBtn = document.getElementById('draw-clear-all');
if (_drawClearAllBtn) {{
  _drawClearAllBtn.addEventListener('click', () => {{
    if (!_drawTicker) return;
    if (!confirm('Xoá toàn bộ nét vẽ của mã ' + _drawTicker + '?')) return;
    _drawings = [];
    saveDrawings();
    redrawDrawings();
  }});
}}

// ---------- Biểu đồ vĩ mô (FRED + World Bank) ----------
let macroChart = null;

function renderMacroChart(key) {{
  const entry = MACRO_DATA.series && MACRO_DATA.series[key];
  if (!entry) return;

  const container = document.getElementById('macro-chart-container');
  const descEl    = document.getElementById('macro-description');
  if (!container) return;

  if (macroChart) {{ macroChart.remove(); macroChart = null; }}

  // Hiện mô tả
  if (descEl) descEl.textContent = entry.description || '';

  const isMonthly = entry.freq === 'monthly';
  const isYearly  = entry.freq === 'yearly';

  macroChart = LightweightCharts.createChart(container, {{
    width : container.clientWidth,
    height: 360,
    layout: {{ background: {{ color: '#1e293b' }}, textColor: '#cbd5e1' }},
    grid  : {{ vertLines: {{ color: '#334155' }}, horzLines: {{ color: '#334155' }} }},
    timeScale: {{ borderColor: '#475569', timeVisible: !isYearly }},
    rightPriceScale: {{ borderColor: '#475569' }},
  }});

  const values = (entry.values || [])
    .filter(v => v[1] !== null && v[1] !== undefined)
    .map(v => ({{ time: v[0], value: v[1] }}));

  if (!values.length) return;

  const series = macroChart.addAreaSeries({{
    lineColor   : '#60a5fa',
    topColor    : 'rgba(96,165,250,0.25)',
    bottomColor : 'rgba(96,165,250,0.0)',
    lineWidth   : 2,
    title       : entry.label,
  }});
  series.setData(values);
  macroChart.timeScale().fitContent();

  // Resize
  const ro = new ResizeObserver(() => {{
    if (macroChart) macroChart.applyOptions({{ width: container.clientWidth }});
  }});
  ro.observe(container);
}}

function initMacroChart() {{
  const select = document.getElementById('macro-select');
  if (!select || !MACRO_DATA.series) return;
  select.addEventListener('change', () => renderMacroChart(select.value));
  if (select.options.length) renderMacroChart(select.value);
}}
initMacroChart();

// ---------- Biểu đồ cột nhóm: Dự báo Fed Funds Rate & Core PCE qua nhiều kỳ họp FOMC ----------
const FOMC_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#a78bfa'];

function renderFomcBarChart(containerId, proj) {{
  const container = document.getElementById(containerId);
  if (!container) return;

  if (!proj || !proj.vintages || !proj.vintages.length) {{
    container.innerHTML = '<div style="padding:16px;color:#64748b;font-size:13px;">Chưa có dữ liệu dự báo.</div>';
    return;
  }}

  const legendHtml = proj.vintages.map((v, i) =>
    '<span style="display:inline-flex;align-items:center;gap:4px;margin-right:14px;font-size:11px;color:#cbd5e1;">' +
    '<span style="width:10px;height:10px;border-radius:2px;background:' + FOMC_COLORS[i % FOMC_COLORS.length] + ';display:inline-block;"></span>' +
    'Vintage: ' + v.vintage + '</span>'
  ).join('');

  container.innerHTML =
    '<div style="margin-bottom:8px;">' + legendHtml + '</div>' +
    '<canvas style="width:100%;height:260px;display:block;"></canvas>';

  const canvas = container.querySelector('canvas');
  const drawIt = () => {{
    const dpr  = window.devicePixelRatio || 1;
    const cssW = container.clientWidth;
    const cssH = 260;
    canvas.width  = cssW * dpr;
    canvas.height = cssH * dpr;
    canvas.style.width  = cssW + 'px';
    canvas.style.height = cssH + 'px';
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    const yearsSet = new Set();
    proj.vintages.forEach(v => v.values.forEach(([y]) => yearsSet.add(y)));
    const years = Array.from(yearsSet).sort();
    if (!years.length) return;

    const padding = {{ top: 14, right: 12, bottom: 26, left: 40 }};
    const plotW = cssW - padding.left - padding.right;
    const plotH = cssH - padding.top - padding.bottom;

    let maxVal = 0;
    proj.vintages.forEach(v => v.values.forEach(([, val]) => {{ if (val > maxVal) maxVal = val; }}));
    maxVal = maxVal > 0 ? maxVal * 1.2 : 1;

    ctx.strokeStyle = '#334155';
    ctx.fillStyle   = '#94a3b8';
    ctx.font = '11px sans-serif';
    ctx.textAlign = 'left';
    const gridLines = 4;
    for (let i = 0; i <= gridLines; i++) {{
      const y = padding.top + plotH - (plotH * i / gridLines);
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(padding.left + plotW, y);
      ctx.stroke();
      ctx.fillText((maxVal * i / gridLines).toFixed(1), 4, y + 4);
    }}

    const groupW = plotW / years.length;
    const barW = Math.min(30, groupW / (proj.vintages.length + 1.5));

    years.forEach((year, yi) => {{
      const groupX = padding.left + yi * groupW + groupW / 2;
      proj.vintages.forEach((v, vi) => {{
        const entry = v.values.find(([y]) => y === year);
        if (!entry) return;
        const val = entry[1];
        const barH = (val / maxVal) * plotH;
        const x = groupX - (proj.vintages.length * barW) / 2 + vi * barW;
        const y = padding.top + plotH - barH;
        ctx.fillStyle = FOMC_COLORS[vi % FOMC_COLORS.length];
        ctx.fillRect(x, y, barW - 3, barH);
        ctx.fillStyle = '#e2e8f0';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(val.toFixed(2), x + (barW - 3) / 2, y - 3);
      }});
      ctx.fillStyle = '#cbd5e1';
      ctx.font = '12px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(year, groupX, padding.top + plotH + 18);
    }});
    ctx.textAlign = 'left';
  }};

  drawIt();
  const ro = new ResizeObserver(drawIt);
  ro.observe(container);
}}

function initFomcCharts() {{
  const fp = MACRO_DATA.fomc_projections;
  if (!fp) return;
  if (fp.FEDTARMD) renderFomcBarChart('fomc-fedfunds-chart', fp.FEDTARMD);
  if (fp.JCXFEMD)  renderFomcBarChart('fomc-corepce-chart', fp.JCXFEMD);
}}
initFomcCharts();

// ---------- Resize ----------
window.addEventListener('resize', () => {{
  if (currentChartState) {{
    currentChartState.chart.applyOptions({{ width: currentChartState.container.clientWidth }});
    if (window._draw) {{
      window._draw.canvas.width = currentChartState.container.clientWidth;
      window._draw.canvas.height = currentChartState.container.clientHeight;
      redrawDrawings();
    }}
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
