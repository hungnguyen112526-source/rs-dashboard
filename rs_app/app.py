"""Chứng khoán sung rụng (Streamlit) — điểm vào. Chạy: streamlit run app.py"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import auth, engine, night, pages_extra, ui  # noqa: E402
try:
    from src import watch  # noqa: E402
except ImportError:      # thiếu rs_app/src/watch.py thì chỉ trang Theo dõi báo lỗi, không sập cả app
    watch = None

ASSETS = next((d for d in (ROOT / "assets", ROOT.parent / "assets") if d.is_dir()), ROOT / "assets")
_FAVICON, _LOGO = ASSETS / "favicon-192.png", ASSETS / "logo.png"
# thiếu file ảnh thì dùng emoji / bỏ logo sidebar, không để app sập
st.set_page_config(page_title="Chứng khoán sung rụng", page_icon=str(_FAVICON) if _FAVICON.is_file() else "📈",
                   layout="wide", initial_sidebar_state="auto")
if _LOGO.is_file():
    st.logo(str(_LOGO), size="large")
ui.apply_css()

auth.ensure_admin()
auth.init_session()
if not st.session_state.get("authenticated"):
    ui.render_auth_portal()
    st.stop()

user = st.session_state["user"]
is_admin = user.get("role") == "admin"

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
MTIME = data_path.stat().st_mtime
stocks, vnindex = load_all(str(data_path), MTIME)
as_of = f"{stocks['date'].max():%d/%m/%Y}"

# ---- Sidebar: chỉ còn người dùng + Thoát + mốc dữ liệu ----
with st.sidebar:
    c1, c2 = st.columns([3, 2])
    c1.markdown(f"👤 **{user.get('fullname', user['username'])}**")
    c1.caption("👑 Quản trị" if is_admin else "⭐ Thành viên")
    if c2.button("🚪 Thoát", width="stretch"):
        auth.logout()
    st.caption(f"Dữ liệu đến {as_of} · {stocks['ticker'].nunique()} mã")
    night.render(night.toggle())


@st.cache_data(ttl=600)
def cached_rs(path_str: str, mtime: float, frame: str):
    s, _ = load_all(path_str, mtime)
    scores = engine.compute_rs(s, frame)
    return scores, engine.industry_rs(scores)


@st.cache_data(ttl=600)
def cached_vol(path_str: str, mtime: float, hour_bucket: str):
    s, _ = load_all(path_str, mtime)
    scores, _ = cached_rs(path_str, mtime, "day")
    rs_map = dict(zip(scores["ticker"], scores["RS"])) if not scores.empty else {}
    return engine.volume_screen(s, rs_map)


@st.cache_data(ttl=600)
def cached_hits(path_str: str, mtime: float, start: str, end: str, weekly: bool, hour_bucket: str):
    s, _ = load_all(path_str, mtime)
    scores, _ = cached_rs(path_str, mtime, "day")
    rs_map = dict(zip(scores["ticker"], scores["RS"])) if not scores.empty else {}
    return engine.volume_hits(s, rs_map, start, end, weekly)


# ---- Biểu đồ trong cửa sổ nổi ----
def show_chart(ticker: str, key: str):
    frame = st.radio("Khung biểu đồ", ["Ngày", "Tuần"], horizontal=True, key=f"{key}_tf")
    ohlcv = engine.ohlcv_for(stocks, ticker, "week" if frame == "Tuần" else "day")
    if ohlcv.empty:
        st.info("Không có dữ liệu giá cho mã này.")
        return
    ui.price_chart(ohlcv, f"{ticker} — {frame}")


def open_chart(frame_df: pd.DataFrame, ticker: str, key: str):
    row = frame_df[frame_df["Mã"] == ticker]
    info = []
    if not row.empty:
        r = row.iloc[0]
        if pd.notna(r.get("Ngành")):
            info.append(f"Ngành: {r['Ngành']}")
        if "RS" in r and pd.notna(r["RS"]):
            info.append(f"RS: {int(r['RS'])}")
        if "GTGD TB20 (tỷ)" in r and pd.notna(r["GTGD TB20 (tỷ)"]):
            info.append(f"GTGD TB20: {r['GTGD TB20 (tỷ)']:,.1f} tỷ")

    @st.dialog(f"📈 {ticker}", width="large")
    def _dlg():
        if info:
            st.caption(" · ".join(info))
        if watch:
            watch.toggle(ticker, user["username"], key)
        show_chart(ticker, key)

    _dlg()


def table_with_select(frame_df: pd.DataFrame, key: str, display=None, column_config=None):
    """Bảng + cửa sổ nổi biểu đồ. Chọn mã: tick ô vuông đầu dòng HOẶC dùng ô chọn mã.
    Chỉ mở cửa sổ khi lựa chọn THAY ĐỔI (tránh bật lại mỗi lần gõ bộ lọc); có nút mở lại."""
    ss = st.session_state
    kt, kb, ka = f"{key}_t", f"{key}_b", f"{key}_a"
    c1, c2 = st.columns([3, 2], vertical_alignment="bottom")
    pick_box = c1.selectbox("📊 Chọn mã để xem biểu đồ nến", frame_df["Mã"].tolist(), index=None,
                            placeholder="Gõ hoặc chọn mã...", key=f"{key}_pick")
    reopen = bool(ss.get(ka)) and c2.button(f"📈 Mở lại biểu đồ {ss.get(ka)}", key=f"{key}_reopen", width="stretch")
    st.caption("Hoặc **tick ô vuông ở đầu dòng** (cột ngoài cùng bên trái). Bấm vào chữ trong ô thì chưa chọn dòng.")
    event = st.dataframe(display if display is not None else frame_df, width="stretch", hide_index=True,
                         key=key, on_select="rerun", selection_mode="single-row", column_config=column_config,
                         **tbl_dims(len(frame_df)))

    rows = event.selection.rows
    cur_t = frame_df.iloc[rows[0]]["Mã"] if rows else None
    active = None
    if cur_t != ss.get(kt):
        active = cur_t
    elif pick_box != ss.get(kb):
        active = pick_box
    ss[kt], ss[kb] = cur_t, pick_box
    if active:
        ss[ka] = active
    target = active or (ss.get(ka) if reopen else None)
    if target:
        open_chart(frame_df, target, key)


W = engine.VOL_WINDOWS
TB_RULE = f"TB{W[0]} < TB{W[1]} < TB{W[2]}"


# Cỡ bảng: (chiều cao tối đa px, độ cao dòng px). None = tự tính theo số dòng ("Toàn trang").
TBL_SIZES = {"Gọn": (400, None), "Vừa": (640, 40), "Lớn": (900, 46), "Toàn trang": (None, 44)}


def tbl_dims(n_rows: int) -> dict:
    """Tham số height/row_height cho st.dataframe theo cỡ bảng người dùng chọn; bảng ngắn không để khoảng trống."""
    h, rh = TBL_SIZES.get(st.session_state.get("tbl_size") or "Vừa", TBL_SIZES["Vừa"])
    content = (rh or 35) * (n_rows + 1) + 8
    kw = {"height": int(min(h, content) if h else min(content, 5000))}
    if rh:
        kw["row_height"] = rh
    return kw


def frame_filters(with_near: bool = False, key: str = "f"):
    """Bộ lọc 1 hàng: khung thời gian · (mã gần đạt) · tìm kiếm."""
    widths = [2, 3, 3, 3] if with_near else [2, 3, 4]
    cols = st.columns(widths, vertical_alignment="bottom")
    frame = cols[0].segmented_control("Khung", ["Ngày", "Tuần"], default="Ngày", key=f"{key}_frame") or "Ngày"
    near = False
    if with_near:
        near = cols[1].toggle("Hiện cả mã gần đạt (3/4 mốc)", key=f"{key}_near",
                              help=f"{TB_RULE} nhưng chưa < TB{W[3]}")
    cols[-2].segmented_control("Cỡ bảng", list(TBL_SIZES), default="Vừa", key="tbl_size",
                               help="Phóng to bảng: tăng chiều cao và độ cao dòng để xem được nhiều mã hơn một lúc")
    q = cols[-1].text_input("Tìm kiếm", placeholder="🔍 Lọc theo mã hoặc ngành", key=f"{key}_q",
                            label_visibility="collapsed").strip().lower()
    return frame, near, q


def _match(df: pd.DataFrame, q: str, ind_col: str) -> pd.DataFrame:
    if not q:
        return df
    name = df[ind_col].fillna("").str.lower()
    if "Mã" in df.columns:
        return df[df["Mã"].str.lower().str.contains(q) | name.str.contains(q)]
    return df[name.str.contains(q)]


# ---------------------------------------------------------------------------
def page_rs():
    st.header("🏆 Xếp hạng sức mạnh giá (RS)")
    frame_ui, _, q = frame_filters(key="rs")
    frame = "week" if frame_ui == "Tuần" else "day"
    scores, ind = cached_rs(str(data_path), MTIME, frame)
    if scores.empty:
        st.warning("Không đủ dữ liệu để tính RS ở khung này.")
        return

    top = ind.iloc[0]
    ui.kpi_row([
        ("Mã được xếp hạng", f"{len(scores)}", "Mã đủ dữ liệu (≥ 120 phiên) để tính RS"),
        ("Số ngành", f"{len(ind)}", None),
        ("Ngành mạnh nhất", str(top["industry"]), f"RS ngành {int(top['RS_nganh'])}"),
        ("Mã RS ≥ 90", f"{int((scores['RS'] >= 90).sum())}", f"Dữ liệu đến {as_of}"),
    ])

    unit = "tuần" if frame == "week" else "phiên"
    size = engine.WEEKLY_BLOCK_SIZE if frame == "week" else engine.BLOCK_SIZE
    with st.container(border=True, key="card_rs_table"):
        st.caption("Điểm thô = 0.4×%Δ(khối gần nhất) + 0.3×%Δ(khối kế) + 0.2×%Δ(khối kế nữa) + 0.1×%Δ(khối xa nhất). "
                   "RS = thứ hạng quy đổi thang 1–99.")
        tab_stock, tab_ind = st.tabs(["Cổ phiếu", "Ngành"])
        with tab_stock:
            view = scores.rename(columns={"ticker": "Mã", "industry": "Ngành", "raw_score": "Điểm thô"}).copy()
            for i in range(1, 5):
                view = view.rename(columns={f"pct_block{i}": f"Khối {i} ({size} {unit}) %"})
            view = _match(view, q, "Ngành")
            view = view[["Mã", "Ngành"] + [c for c in view.columns if c.startswith("Khối")] + ["Điểm thô", "RS"]]
            view = view.reset_index(drop=True)
            st.caption(f"{len(view)} mã")
            if view.empty:
                st.info("Không có mã nào khớp bộ lọc.")
            else:
                table_with_select(view, f"rs_tbl_{frame}", display=ui.style_rs(view),
                                  column_config={"Mã": ui.CODE_COLUMN, "RS": ui.RS_COLUMN})
        with tab_ind:
            v = ind.rename(columns={"industry": "Ngành", "raw_score": "Điểm thô ngành",
                                    "RS_nganh": "RS ngành", "so_ma": "Số mã"})
            v = _match(v, q, "Ngành").reset_index(drop=True)
            st.dataframe(v.style.apply(ui._zebra, axis=None).format({"Điểm thô ngành": "{:.2f}"}),
                         width="stretch", hide_index=True, **tbl_dims(len(v)),
                         column_config={"RS ngành": st.column_config.ProgressColumn("RS ngành", min_value=1,
                                                                                    max_value=99, format="%d")})


# ---------------------------------------------------------------------------
def page_vol():
    st.header("📉 Lọc cổ phiếu có khối lượng giao dịch giảm dần")
    now = datetime.now(engine.VN_TZ)
    day_df, week_df, last_d, last_w = cached_vol(str(data_path), MTIME, f"{now:%Y-%m-%d}-{now.hour >= 15}")

    def _n(df, n):
        return int((df["Số mốc đạt"] == n).sum()) if len(df) else 0

    ui.kpi_row([
        ("Mã đủ 4 mốc · Ngày", f"{_n(day_df, 4)}", f"Tính đến {last_d}" if last_d else None),
        ("Mã đủ 4 mốc · Tuần", f"{_n(week_df, 4)}", f"Tính đến {last_w}" if last_w else None),
        ("Mã gần đạt (3/4) · Ngày", f"{_n(day_df, 3)}", f"{TB_RULE} nhưng chưa < TB{W[3]}"),
        ("Dữ liệu đến", as_of, None),
    ])

    with st.expander("📖 Bộ lọc này làm gì? Cách đọc kết quả"):
        st.markdown(
            "- **Ý nghĩa:** tìm cổ phiếu có lượng khớp lệnh đang co hẹp dần (thường gặp khi tích luỹ/đi ngang). "
            "Đây là công cụ sàng lọc, **không phải tín hiệu mua/bán**.\n"
            f"- **Điều kiện:** KLGD trung bình {W[0]} < {W[1]} < {W[2]} < {W[3]} (phiên với khung Ngày, tuần với khung Tuần; "
            "KLGD tuần = tổng các phiên trong tuần kết thúc thứ Sáu).\n"
            f"- **Số mốc đạt:** 4/4 = đạt đủ (mặc định hiển thị); 3/4 = mới đạt TB{W[0]}<TB{W[1]}<TB{W[2]}, chưa < TB{W[3]}.\n"
            f"- **{engine.PCT_COL}:** càng đỏ đậm thì khối lượng càng cạn.\n"
            "- **GTGD TB20 (tỷ):** giá trị giao dịch TB 20 phiên, chỉ để tham khảo thanh khoản — không dùng để lọc.\n"
            "- **Khoảng thời gian:** bảng liệt kê mọi mã từng đủ điều kiện ở ít nhất một phiên/tuần trong khoảng bạn chọn.\n"
            "- Phiên/tuần đang diễn ra không được tính."
        )

    frame_ui, _, q = frame_filters(key="vol")
    is_week = frame_ui == "Tuần"
    unit = "tuần" if is_week else "phiên"
    last = last_w if is_week else last_d
    with st.container(border=True, key="card_vol_table"):
        end_d = datetime.strptime(last, "%d/%m/%Y").date() if last else datetime.now(engine.VN_TZ).date()
        back = 90 if is_week else 30
        st.caption(f"Chọn khoảng thời gian: trả về các mã **từng** đủ điều kiện ({TB_RULE} < TB{W[3]}) ở ít nhất một {unit} trong khoảng.")
        rng = st.date_input("Khoảng thời gian", value=(end_d - timedelta(days=back), end_d),
                            min_value=stocks["date"].min().date(), max_value=end_d, format="DD/MM/YYYY",
                            key=f"vol_rng_{'w' if is_week else 'd'}")
        if not (isinstance(rng, (tuple, list)) and len(rng) == 2):
            st.info("Chọn đủ ngày bắt đầu và ngày kết thúc.")
            return
        data = cached_hits(str(data_path), MTIME, str(rng[0]), str(rng[1]), is_week, f"{now:%Y-%m-%d}-{now.hour >= 15}")
        if len(data):
            data = _match(data, q, "Ngành").reset_index(drop=True)
        if data.empty:
            st.info("Không có mã nào từng đủ điều kiện trong khoảng này.")
            return
        st.caption(f"{len(data)} mã")
        pct = engine.PCT_COL + " (lần cuối)"
        table_with_select(data, f"vol_tbl_{'w' if is_week else 'd'}",
                          display=data.style.apply(ui._zebra, axis=None).format({pct: "{:.1f}%"}, na_rep="–"),
                          column_config={"Mã": ui.CODE_COLUMN, "RS": ui.RS_COLUMN})


# ---------------------------------------------------------------------------
# Các trang còn lại (logic nằm trong src/pages_extra.py)
# ---------------------------------------------------------------------------
def page_news():
    pages_extra.render_news(pages_extra.load_json("news_data.json"), user["username"])


def page_flow():
    pages_extra.render_flow(stocks, vnindex, str(data_path), MTIME)


def page_fin():
    ind_map = stocks.drop_duplicates("ticker").set_index("ticker")["industry"].to_dict()
    pages_extra.render_fin(pages_extra.load_json("financials_data.json"), ind_map)


def page_macro():
    pages_extra.render_macro(pages_extra.load_json("macro_data.json"),
                             pages_extra.load_json("bond_yields.json"), vnindex)


def page_calendar():
    pages_extra.render_calendar(pages_extra.load_json("calendar_data.json"))


def page_watch():
    if watch is None:
        st.error("Thiếu file `rs_app/src/watch.py` trên GitHub. Hãy up file này vào thư mục `rs_app/src/` rồi Reboot app.")
        return
    now = datetime.now(engine.VN_TZ)
    day_df, _, _, _ = cached_vol(str(data_path), MTIME, f"{now:%Y-%m-%d}-{now.hour >= 15}")
    scores, _ = cached_rs(str(data_path), MTIME, "day")
    watch.render(stocks, user["username"], scores, day_df, pages_extra.load_json("financials_data.json"))


def page_admin():
    ui.render_admin_page()


# ---- Điều hướng ở thanh bên trái ----
pages = [
    st.Page(page_rs, title="Xếp hạng RS", icon="🏆", url_path="rs", default=True),
    st.Page(page_news, title="Tin tức", icon="📰", url_path="tintuc"),
    st.Page(page_flow, title="Dòng tiền", icon="📊", url_path="dongtien"),
    st.Page(page_vol, title="Lọc KLGD", icon="📉", url_path="klgd"),
    st.Page(page_watch, title="Theo dõi", icon="⭐", url_path="theodoi"),
    st.Page(page_fin, title="BCTC", icon="📑", url_path="bctc"),
    st.Page(page_macro, title="Vĩ mô", icon="🌐", url_path="vimo"),
    st.Page(page_calendar, title="Lịch kinh tế", icon="📅", url_path="lich"),
]
if is_admin:
    pages.append(st.Page(page_admin, title="Quản trị", icon="👑", url_path="admin"))
st.navigation(pages, position="sidebar").run()
