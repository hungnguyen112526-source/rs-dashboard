"""RS Dashboard (Streamlit) — điểm vào. Chạy: streamlit run app.py"""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import auth, engine, ui  # noqa: E402

st.set_page_config(page_title="RS Dashboard", page_icon="📈", layout="wide", initial_sidebar_state="expanded")
ui.apply_css()

auth.ensure_admin()
auth.init_session()
if not st.session_state.get("authenticated"):
    ui.render_auth_portal()
    st.stop()

user = st.session_state["user"]
is_admin = user.get("role") == "admin"

# ---- Sidebar ----
with st.sidebar:
    c1, c2 = st.columns([3, 2])
    c1.markdown(f"👤 **{user.get('fullname', user['username'])}**")
    c1.caption("👑 Quản trị" if is_admin else "⭐ Thành viên")
    if c2.button("🚪 Thoát", width="stretch"):
        auth.logout()
    st.divider()
    pages = ["🏆 Xếp hạng RS", "📉 Lọc KLGD"] + (["👑 Quản trị"] if is_admin else [])
    page = st.radio("Trang", pages, label_visibility="collapsed")

if page == "👑 Quản trị":
    ui.render_admin_page()
    st.stop()


# ---- Dữ liệu ----
def _find_data() -> Path | None:
    for base in (ROOT, ROOT.parent):
        p = base / "gia_lich_su_rs.csv"
        if p.exists():
            return p
    return None


@st.cache_data(ttl=600, show_spinner="Đang nạp dữ liệu giá...")
def load_all(path_str: str, mtime: float):
    df = engine.load_prices(path_str)
    stocks, vnindex = engine.split_index(df)
    return stocks, vnindex


data_path = _find_data()
if data_path is None:
    st.error("Không tìm thấy gia_lich_su_rs.csv (đặt cạnh app.py hoặc ở thư mục gốc của repo).")
    st.stop()
stocks, vnindex = load_all(str(data_path), data_path.stat().st_mtime)
st.sidebar.caption(f"Dữ liệu đến {stocks['date'].max():%d/%m/%Y} · {stocks['ticker'].nunique()} mã")


@st.cache_data(ttl=600)
def cached_rs(path_str: str, mtime: float, frame: str):
    s, _ = load_all(path_str, mtime)
    scores = engine.compute_rs(s, frame)
    return scores, engine.industry_rs(scores)


def show_chart(ticker: str, key: str):
    frame = st.radio("Khung biểu đồ", ["Ngày", "Tuần"], horizontal=True, key=f"{key}_tf")
    ohlcv = engine.ohlcv_for(stocks, ticker, "week" if frame == "Tuần" else "day")
    st.plotly_chart(ui.candle_chart(ohlcv.tail(400 if frame == "Ngày" else 200), f"{ticker} — {frame}"),
                    width="stretch")


def table_with_select(frame_df: pd.DataFrame, key: str, column_config=None):
    event = st.dataframe(frame_df, width="stretch", hide_index=True, key=key,
                         on_select="rerun", selection_mode="single-row", column_config=column_config)
    rows = event.selection.rows
    return frame_df.iloc[rows[0]]["Mã"] if rows else None


# ---------------------------------------------------------------------------
if page == "🏆 Xếp hạng RS":
    st.title("🏆 Xếp hạng sức mạnh giá (RS)")
    frame_label = st.radio("Khung thời gian", ["Ngày (30 phiên/khối)", "Tuần (20 tuần/khối)"], horizontal=True)
    frame = "week" if frame_label.startswith("Tuần") else "day"
    scores, ind = cached_rs(str(data_path), data_path.stat().st_mtime, frame)
    if scores.empty:
        st.warning("Không đủ dữ liệu để tính RS ở khung này.")
        st.stop()

    unit = "tuần" if frame == "week" else "phiên"
    st.caption("Điểm thô = 0.4×%Δ(khối gần nhất) + 0.3×%Δ(khối kế) + 0.2×%Δ(khối kế nữa) + 0.1×%Δ(khối xa nhất). "
               "RS = thứ hạng quy đổi thang 1–99. Bấm vào 1 dòng để xem biểu đồ nến.")
    tab_stock, tab_ind = st.tabs(["Cổ phiếu", "Ngành"])
    with tab_stock:
        q = st.text_input("🔍 Lọc theo mã hoặc ngành", key="rs_q").strip().lower()
        view = scores.rename(columns={"ticker": "Mã", "industry": "Ngành", "raw_score": "Điểm thô", "RS": "RS"}).copy()
        size = engine.WEEKLY_BLOCK_SIZE if frame == "week" else engine.BLOCK_SIZE
        for i in range(1, 5):
            view = view.rename(columns={f"pct_block{i}": f"Khối {i} ({size} {unit}) %"})
        if q:
            view = view[view["Mã"].str.lower().str.contains(q) | view["Ngành"].fillna("").str.lower().str.contains(q)]
        view = view[["Mã", "Ngành"] + [c for c in view.columns if c.startswith("Khối")] + ["Điểm thô", "RS"]].reset_index(drop=True)
        st.caption(f"{len(view)} mã")
        picked = table_with_select(view, f"rs_tbl_{frame}", {c: st.column_config.NumberColumn(format="%.1f")
                                                             for c in view.columns if c.startswith("Khối") or c == "Điểm thô"})
        if picked:
            show_chart(picked, "rs")
    with tab_ind:
        v = ind.rename(columns={"industry": "Ngành", "raw_score": "Điểm thô ngành", "RS_nganh": "RS ngành", "so_ma": "Số mã"})
        st.dataframe(v, width="stretch", hide_index=True,
                     column_config={"Điểm thô ngành": st.column_config.NumberColumn(format="%.2f")})

# ---------------------------------------------------------------------------
elif page == "📉 Lọc KLGD":
    st.title("📉 Lọc cổ phiếu có khối lượng giao dịch giảm dần")
    with st.expander("📖 Bộ lọc này làm gì? Cách đọc kết quả"):
        st.markdown(
            "- **Ý nghĩa:** tìm cổ phiếu có lượng khớp lệnh đang co hẹp dần (thường gặp khi tích luỹ/đi ngang). "
            "Đây là công cụ sàng lọc, **không phải tín hiệu mua/bán**.\n"
            "- **Điều kiện:** KLGD trung bình 5 < 10 < 20 < 40 (phiên với khung Ngày, tuần với khung Tuần; "
            "KLGD tuần = tổng các phiên trong tuần kết thúc thứ Sáu).\n"
            "- **Số mốc đạt:** 4 = đạt đủ (mặc định hiển thị); 3 = mới đạt TB5<TB10<TB20, chưa < TB40.\n"
            "- **% TB5 so với TB40:** càng âm thì khối lượng càng cạn.\n"
            "- **GTGD TB20 (tỷ):** giá trị giao dịch TB 20 phiên, chỉ để tham khảo thanh khoản — không dùng để lọc.\n"
            "- Phiên/tuần đang diễn ra không được tính."
        )
    scores_day, _ = cached_rs(str(data_path), data_path.stat().st_mtime, "day")
    rs_map = dict(zip(scores_day["ticker"], scores_day["RS"])) if not scores_day.empty else {}

    @st.cache_data(ttl=600)
    def cached_vol(path_str: str, mtime: float, hour_bucket: str):
        s, _ = load_all(path_str, mtime)
        return engine.volume_screen(s, rs_map)

    now = datetime.now(engine.VN_TZ)
    day_df, week_df, last_d, last_w = cached_vol(str(data_path), data_path.stat().st_mtime,
                                                 f"{now:%Y-%m-%d}-{now.hour >= 15}")
    c1, c2 = st.columns([2, 3])
    frame_label = c1.radio("Khung", [f"Ngày ({int((day_df['Số mốc đạt'] >= 4).sum()) if len(day_df) else 0} mã đủ 4 mốc)",
                                     f"Tuần ({int((week_df['Số mốc đạt'] >= 4).sum()) if len(week_df) else 0} mã đủ 4 mốc)"],
                           horizontal=True)
    is_week = frame_label.startswith("Tuần")
    show_near = c2.checkbox("Hiện cả mã gần đạt (3/4 mốc: TB5 < TB10 < TB20 nhưng chưa < TB40)")
    data = week_df if is_week else day_df
    last = last_w if is_week else last_d
    unit = "tuần" if is_week else "phiên"
    if last:
        st.markdown(f'<div class="asof">Tính đến {unit} kết thúc ngày {last} (không tính {unit} đang diễn ra).</div>', unsafe_allow_html=True)
    if data.empty:
        st.info("Không có mã nào thỏa điều kiện.")
        st.stop()
    if not show_near:
        data = data[data["Số mốc đạt"] >= 4]
    q = st.text_input("🔍 Lọc theo mã hoặc ngành", key="vol_q").strip().lower()
    if q:
        data = data[data["Mã"].str.lower().str.contains(q) | data["Ngành"].fillna("").str.lower().str.contains(q)]
    data = data.sort_values("% TB5 so với TB40").reset_index(drop=True)
    st.caption(f"{len(data)} mã · bấm vào 1 dòng để xem biểu đồ nến + volume")
    cfg = {c: st.column_config.NumberColumn(format="%,.0f") for c in ["TB5", "TB10", "TB20", "TB40"]}
    cfg["% TB5 so với TB40"] = st.column_config.NumberColumn(format="%.1f%%")
    cfg["GTGD TB20 (tỷ)"] = st.column_config.NumberColumn(format="%.1f")
    picked = table_with_select(data, f"vol_tbl_{'w' if is_week else 'd'}_{int(show_near)}", cfg)
    if picked:
        show_chart(picked, "vol")
