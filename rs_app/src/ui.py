"""Giao diện: CSS, cổng đăng nhập/đăng ký, trang quản trị, biểu đồ nến."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from src import auth

CSS = """
<style>
/* Phong cách: bo tròn lớn, viền mảnh, bóng mềm, nút dạng viên thuốc, điểm nhấn tím→xanh.
   Dùng màu trung tính / currentColor để đúng cả nền sáng lẫn tối (màu chủ đạo lấy từ .streamlit/config.toml). */
.block-container { padding-top: 4.5rem; max-width: 1280px; }
footer, [data-testid="stDeployButton"] { display: none !important; }

h1, h2, h3 { font-weight: 900 !important; letter-spacing: -.04em !important; }
h1 { line-height: 1.15 !important; }

/* Thẻ: st.container(border=True, key="card_...") */
[class*="st-key-card"] {
  border-radius: 24px;
  border: 1px solid color-mix(in srgb, currentColor 11%, transparent) !important;
  background: color-mix(in srgb, currentColor 3.5%, transparent);
  box-shadow: 0 30px 60px -38px rgba(40,30,80,.38);
}
[data-testid="stMetricValue"] { font-weight: 900; letter-spacing: -.03em; }
[data-testid="stMetricLabel"] p { opacity: .7; font-size: .85rem; font-weight: 700; }

/* Nút & lựa chọn dạng viên thuốc */
[data-testid^="stBaseButton-"] { border-radius: 999px !important; font-weight: 800; letter-spacing: -.01em; }
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {
  box-shadow: 0 8px 18px -8px var(--primary-color, #6A57F2);
}
[data-testid="stButtonGroup"] button { border-radius: 999px !important; font-weight: 700; }
[data-testid="stTextInput"] [data-baseweb="input"] { border-radius: 999px; }
[data-testid="stSelectbox"] [data-baseweb="select"] > div,
[data-testid="stMultiSelect"] [data-baseweb="select"] > div { border-radius: 16px; }
[data-testid="stDataFrame"] { border-radius: 16px; overflow: hidden; }
[data-testid="stExpander"] details { border-radius: 18px; }

/* Thanh bên: menu trang dạng viên thuốc, trang đang mở được tô nhẹ */
[data-testid="stSidebar"] { border-right: 1px solid color-mix(in srgb, currentColor 9%, transparent); }
[data-testid="stSidebarNavLink"] { border-radius: 999px; font-weight: 700; }
[data-testid="stSidebarNavLink"][aria-current="page"] { background: rgba(123,97,255,.16); font-weight: 800; }

.auth-card { background: color-mix(in srgb, currentColor 4%, transparent); border: 1px solid color-mix(in srgb, currentColor 11%, transparent);
             border-radius: 24px; padding: 1.4rem 1.2rem; text-align: center; margin-bottom: 1rem; box-shadow: 0 30px 60px -38px rgba(40,30,80,.38); }
.auth-title { font-weight: 900; font-size: 1.3rem; letter-spacing: -.02em; }
.auth-sub { opacity: .7; font-size: .88rem; margin-top: .2rem; }
.hint-box { background: color-mix(in srgb, currentColor 4%, transparent); border: 1px dashed color-mix(in srgb, currentColor 25%, transparent);
            border-radius: 14px; padding: .7rem .9rem; font-size: .85rem; opacity: .9; }
.asof { opacity: .7; font-size: .85rem; margin-bottom: .4rem; }

.auth-logo { width: 54px; height: 54px; margin: 0 auto .6rem; border-radius: 18px; display: flex; align-items: center;
             justify-content: center; font-size: 1.7rem; background: linear-gradient(120deg,#7B61FF,#3D8BFF 55%,#1FB89A);
             box-shadow: 0 10px 24px -10px rgba(123,97,255,.7); }
.auth-head { text-align: center; margin-bottom: .6rem; }
.auth-foot { text-align: center; font-size: .75rem; opacity: .55; margin-top: .8rem; }

/* Hiệu ứng xuất hiện nhẹ cho tiêu đề và thẻ (backwards: không đè lên hiệu ứng mờ khi app đang chạy lại) */
@keyframes ux-rise { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }
[data-testid="stMain"] h1 { animation: ux-rise .7s cubic-bezier(.2,.8,.2,1) backwards; }
[class*="st-key-card"] { animation: ux-rise .8s cubic-bezier(.2,.8,.2,1) .08s backwards; }
@media (prefers-reduced-motion: reduce) {
  [data-testid="stMain"] h1, [class*="st-key-card"] { animation: none; }
}

/* ---- Điện thoại ---- */
@media (max-width: 640px) {
  .block-container { padding: 3.6rem .8rem 2rem !important; }
  h1, h2 { font-size: 1.35rem !important; line-height: 1.3 !important; }
  [data-testid="stMain"] [data-testid="stColumn"] { min-width: 100% !important; flex: 1 1 100% !important; }
  /* hàng thẻ số: 2 thẻ / hàng */
  [data-testid="stMain"] [data-testid="stHorizontalBlock"]:has([class*="st-key-card_kpi"]) > [data-testid="stColumn"] {
      min-width: calc(50% - .5rem) !important; flex: 1 1 calc(50% - .5rem) !important; }
  [data-testid="stMetricValue"] { font-size: 1.25rem !important; }
  [data-testid="stMetricLabel"] p { font-size: .78rem; }
  [class*="st-key-card"] { border-radius: 18px; }
}
</style>
"""


def apply_css():
    st.markdown(CSS, unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# Cổng đăng nhập / đăng ký
# ----------------------------------------------------------------------------

AUTH_CSS = """
<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"] { display: none !important; }
.block-container { padding-top: 9vh; max-width: 520px; }
@media (max-width: 640px) { .block-container { padding-top: 3.6rem; } }
</style>
"""


def render_auth_portal():
    """Cổng đăng nhập: thẻ gọn ở giữa trang, không sidebar."""
    st.markdown(AUTH_CSS, unsafe_allow_html=True)
    with st.container(border=True, key="card_auth"):
        st.markdown(
            '<div class="auth-head"><div class="auth-logo">📈</div>'
            '<div class="auth-title">CHỨNG KHOÁN SUNG RỤNG</div>'
            '<div class="auth-sub">Xếp hạng sức mạnh giá · Lọc khối lượng · Cổ phiếu Việt Nam</div></div>',
            unsafe_allow_html=True,
        )
        tab_login, tab_reg = st.tabs(["🔑 Đăng nhập", "📝 Đăng ký"])

        with tab_login:
            with st.form("form_login"):
                uname = st.text_input("Tên đăng nhập", placeholder="👤 Tên đăng nhập", label_visibility="collapsed")
                pwd = st.text_input("Mật khẩu", type="password", placeholder="🔒 Mật khẩu", label_visibility="collapsed")
                go_btn = st.form_submit_button("Đăng nhập", width="stretch", type="primary")
            if go_btn:
                ok, msg, user = auth.authenticate(uname, pwd)
                if ok and user:
                    auth.login(user)
                else:
                    st.error(msg)
            st.markdown('<div class="hint-box">Chưa có tài khoản? Chuyển sang tab <b>Đăng ký</b> — miễn phí, dùng được ngay.</div>',
                        unsafe_allow_html=True)

        with tab_reg:
            with st.form("form_register"):
                fullname = st.text_input("🏷️ Họ và tên")
                email = st.text_input("📧 Email")
                new_user = st.text_input("👤 Tên đăng nhập", help="3–20 ký tự: chữ không dấu, số, gạch dưới")
                pw1 = st.text_input("🔒 Mật khẩu", type="password", help=f"Tối thiểu {auth.MIN_PASSWORD_LEN} ký tự, gồm cả chữ và số")
                pw2 = st.text_input("🔁 Nhập lại mật khẩu", type="password")
                reg_btn = st.form_submit_button("Tạo tài khoản", width="stretch", type="primary")
            if reg_btn:
                ok, msg = auth.register_user(new_user, fullname, email, pw1, pw2)
                (st.success if ok else st.error)(msg)

        st.markdown('<div class="auth-foot">Công cụ sàng lọc, không phải khuyến nghị đầu tư.</div>', unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# Trang quản trị
# ----------------------------------------------------------------------------

def render_admin_page():
    st.title("👑 Quản trị người dùng")
    status = auth.storage_status()
    (st.success if status["ok"] else st.warning)(f"{status['label']} — {status['detail']}")

    users = auth.list_users()
    st.caption(f"{len(users)} tài khoản")
    if users:
        view = pd.DataFrame(users)[["username", "fullname", "email", "role", "status", "created_at"]]
        view.columns = ["Tên đăng nhập", "Họ tên", "Email", "Quyền", "Trạng thái", "Ngày tạo"]
        st.dataframe(view, width="stretch", hide_index=True)

    members = [u["username"] for u in users if u.get("role") != "admin"]
    if not members:
        st.info("Chưa có thành viên nào.")
        return
    target = st.selectbox("Chọn thành viên", members)
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("🔒 Khoá", width="stretch"):
            ok, msg = auth.set_user_status(target, "blocked")
            (st.success if ok else st.error)(msg)
        if st.button("🔓 Mở khoá", width="stretch"):
            ok, msg = auth.set_user_status(target, "active")
            (st.success if ok else st.error)(msg)
    with c2:
        new_pw = st.text_input("Mật khẩu mới", type="password", key="admin_new_pw")
        if st.button("🔁 Đặt lại mật khẩu", width="stretch"):
            ok, msg = auth.reset_password(target, new_pw)
            (st.success if ok else st.error)(msg)
    with c3:
        confirm = st.checkbox(f"Xác nhận xoá '{target}'")
        if st.button("🗑️ Xoá tài khoản", width="stretch", disabled=not confirm):
            ok, msg = auth.delete_user(target)
            (st.success if ok else st.error)(msg)
            if ok:
                st.rerun()


# ----------------------------------------------------------------------------
# Thẻ số tổng quan
# ----------------------------------------------------------------------------

def kpi_row(items):
    """items: list[(nhãn, giá trị, ghi chú|None)] -> 1 hàng thẻ số."""
    cols = st.columns(len(items))
    for i, (col, (label, value, note)) in enumerate(zip(cols, items)):
        with col.container(border=True, key=f"card_kpi_{i}_{label[:6]}"):
            st.metric(label, value, help=note)


# ----------------------------------------------------------------------------
# Tô màu bảng (Styler) — dùng rgba nên hợp cả nền sáng/tối
# ----------------------------------------------------------------------------
_ZEBRA = "background-color: rgba(127,127,127,.07)"


def _zebra(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame("", index=df.index, columns=df.columns)
    out.iloc[1::2, :] = _ZEBRA
    return out


def _cellmap(styler, func, subset):
    return (styler.map if hasattr(styler, "map") else styler.applymap)(func, subset=subset)


def _bg_drop(v):
    """% TB5 so với TB40: càng âm càng đỏ."""
    if pd.isna(v) or v >= 0:
        return ""
    a = 0.10 + 0.40 * min(abs(v) / 70.0, 1.0)
    return f"background-color: rgba(239,68,68,{a:.2f}); font-weight: 600"


def _bg_tiers(v):
    if v == "4/4":
        return "background-color: rgba(34,197,94,.30); font-weight: 700"
    if v == "3/4":
        return "background-color: rgba(234,179,8,.34); font-weight: 700"
    return ""


def _fg_sign(v):
    if pd.isna(v):
        return ""
    return "color: #16a34a" if v > 0 else ("color: #dc2626" if v < 0 else "")


def style_volume(df: pd.DataFrame):
    """Bảng lọc KLGD: nền đỏ nhạt theo % giảm, nhãn mốc xanh/vàng, dòng xen kẽ."""
    d = df.copy()
    d["Số mốc đạt"] = d["Số mốc đạt"].astype(int).map(lambda n: f"{n}/4")
    fmt = {c: "{:,.0f}" for c in ["TB5", "TB10", "TB20", "TB40"] if c in d}
    fmt["% TB5 so với TB40"] = "{:.1f}%"
    fmt["GTGD TB20 (tỷ)"] = "{:,.1f}"
    st_ = d.style.apply(_zebra, axis=None).format(fmt, na_rep="–")
    st_ = _cellmap(st_, _bg_drop, ["% TB5 so với TB40"])
    st_ = _cellmap(st_, _bg_tiers, ["Số mốc đạt"])
    return st_


def style_rs(df: pd.DataFrame):
    """Bảng RS: chữ xanh/đỏ cho %Δ từng khối, dòng xen kẽ. Cột RS dùng ProgressColumn."""
    pct_cols = [c for c in df.columns if c.startswith("Khối")]
    fmt = {c: "{:+.1f}%" for c in pct_cols}
    fmt["Điểm thô"] = "{:.1f}"
    st_ = df.style.apply(_zebra, axis=None).format(fmt, na_rep="–")
    return _cellmap(st_, _fg_sign, pct_cols)


RS_COLUMN = st.column_config.ProgressColumn("RS", min_value=1, max_value=99, format="%d")
CODE_COLUMN = st.column_config.TextColumn("Mã", pinned=True)  # giữ cố định khi cuộn ngang (điện thoại)


# ----------------------------------------------------------------------------
# Biểu đồ nến + volume
# ----------------------------------------------------------------------------

def candle_chart(ohlcv: pd.DataFrame, title: str, tail: int | None = None) -> go.Figure:
    """Nến + volume + đường TB khối lượng 5/20. Không ép nền -> theo theme sáng/tối của app."""
    ohlcv = ohlcv.copy()
    has_vol = "volume" in ohlcv.columns
    if has_vol:
        ohlcv["ma5"] = ohlcv["volume"].rolling(5).mean()
        ohlcv["ma20"] = ohlcv["volume"].rolling(20).mean()
    if tail:
        ohlcv = ohlcv.tail(tail)

    # Trục x dạng 'category' (mỗi phiên 1 nến, liền nhau): không còn khoảng trống ở ngày lễ/Tết/phiên thiếu
    # và không phụ thuộc cách Plotly tự tính khoảng ngày (rangebreaks) -> hết lệch/cắt cụt cửa sổ thời gian.
    dts = pd.to_datetime(ohlcv.index)
    xs = list(dts.strftime("%Y-%m-%d"))
    step = max(1, len(xs) // 8)
    tickvals = xs[::step]
    ticktext = [pd.Timestamp(v).strftime("%d/%m/%y") for v in tickvals]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.74, 0.26], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(
        x=xs, open=ohlcv["open"], high=ohlcv["high"], low=ohlcv["low"], close=ohlcv["close"],
        increasing_line_color="#16a34a", decreasing_line_color="#dc2626", name="Giá"), row=1, col=1)
    if has_vol:
        colors = ["rgba(22,163,74,.45)" if c >= o else "rgba(220,38,38,.45)" for o, c in zip(ohlcv["open"], ohlcv["close"])]
        fig.add_trace(go.Bar(x=xs, y=ohlcv["volume"], marker_color=colors, name="KLGD"), row=2, col=1)
        fig.add_trace(go.Scatter(x=xs, y=ohlcv["ma5"], mode="lines", name="TB5",
                                 line=dict(color="#f59e0b", width=1.4)), row=2, col=1)
        fig.add_trace(go.Scatter(x=xs, y=ohlcv["ma20"], mode="lines", name="TB20",
                                 line=dict(color="#7B61FF", width=1.4)), row=2, col=1)
    fig.update_layout(title=title, height=460, showlegend=has_vol, margin=dict(l=10, r=10, t=40, b=10),
                      legend=dict(orientation="h", y=1.04, x=1, xanchor="right"),
                      xaxis_rangeslider_visible=False)
    grid = "rgba(128,128,128,.18)"
    fig.update_xaxes(type="category", tickmode="array", tickvals=tickvals, ticktext=ticktext, gridcolor=grid)
    fig.update_yaxes(gridcolor=grid)
    return fig
