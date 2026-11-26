"""Giao diện: CSS, cổng đăng nhập/đăng ký, trang quản trị, biểu đồ nến."""
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

/* ===== Hệ nút: 3 mức cùng chiều cao / bo góc / viền khi bàn phím =====
   chính  = nền tím, chữ trắng   (primary)
   phụ    = viền mảnh            (secondary)
   nhẹ    = không viền, hiện nền khi rê chuột (tertiary) */
[data-testid^="stBaseButton-"] {
  border-radius: 999px !important; font-weight: 700; letter-spacing: -.01em; min-height: 40px; padding: .25rem 1.1rem;
  transition: background-color .15s ease, border-color .15s ease, box-shadow .15s ease, transform .15s ease;
}
[data-testid^="stBaseButton-"]:active { transform: scale(.98); }
[data-testid^="stBaseButton-"]:focus-visible { outline: 2px solid rgba(123,97,255,.9) !important; outline-offset: 2px; }
[data-testid^="stBaseButton-"]:disabled { opacity: .45; cursor: not-allowed; box-shadow: none !important; }

[data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-secondaryFormSubmit"] {
  background: transparent; border: 1px solid color-mix(in srgb, currentColor 20%, transparent);
}
[data-testid="stBaseButton-secondary"]:hover:not(:disabled), [data-testid="stBaseButton-secondaryFormSubmit"]:hover:not(:disabled) {
  background: rgba(123,97,255,.10); border-color: rgba(123,97,255,.55); color: inherit;
}
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {
  background: linear-gradient(135deg, #6A57F2, #8b6cff) !important; color: #fff !important; border: 0 !important;
  box-shadow: 0 10px 22px -10px rgba(106,87,242,.85);
}
[data-testid="stBaseButton-primary"]:hover:not(:disabled), [data-testid="stBaseButton-primaryFormSubmit"]:hover:not(:disabled) {
  filter: brightness(1.08); transform: translateY(-1px);
}
[data-testid="stBaseButton-tertiary"] { background: transparent; border: 0; min-height: 36px; padding: .2rem .6rem; }
[data-testid="stBaseButton-tertiary"]:hover:not(:disabled) { background: color-mix(in srgb, currentColor 9%, transparent); color: inherit; }

/* Nút chọn (st.segmented_control: Ngày|Tuần, Gọn|Vừa|Lớn...): một thanh liền, ô đang chọn tô tím đặc */
[data-testid="stButtonGroup"] [role="radiogroup"], [data-testid="stButtonGroup"] [role="group"] {
  display: inline-flex; flex-wrap: nowrap; gap: 2px !important; padding: 3px; border-radius: 999px;
  background: color-mix(in srgb, currentColor 7%, transparent); border: 1px solid color-mix(in srgb, currentColor 8%, transparent);
}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"] {
  border: 0 !important; background: transparent !important; box-shadow: none !important; border-radius: 999px !important;
  min-height: 32px !important; padding: 0 .95rem !important; font-weight: 700; color: inherit !important;
}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"]:hover:not([data-selected="true"]) {
  background: color-mix(in srgb, currentColor 10%, transparent) !important;
}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"][data-selected="true"],
[data-testid="stButtonGroup"] button[data-variant="segmented_control"][aria-checked="true"] {
  background: linear-gradient(135deg, #6A57F2, #8b6cff) !important; color: #fff !important;
  box-shadow: 0 6px 14px -6px rgba(106,87,242,.9) !important;
}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"] p { color: inherit !important; }
[data-testid="stTextInput"] [data-baseweb="input"] { border-radius: 999px; }
[data-testid="stSelectbox"] [data-baseweb="select"] > div,
[data-testid="stMultiSelect"] [data-baseweb="select"] > div { border-radius: 16px; }
[data-testid="stDataFrame"] { border-radius: 16px; overflow: hidden; }
[data-testid="stExpander"] details { border-radius: 18px; }

/* ===== Thanh bên =====
   mục danh sách giữ nguyên; thêm: khoảng thoáng, rê chuột, thanh nhấn tím cho trang đang mở */
[data-testid="stSidebar"] { border-right: 1px solid color-mix(in srgb, currentColor 9%, transparent); }
[data-testid="stSidebarNavItems"] { gap: 2px; }
[data-testid="stSidebarNavLink"] {
  position: relative; border-radius: 14px; font-weight: 600; padding: .38rem .8rem; min-height: 40px;
  transition: background-color .15s ease, transform .15s ease;
}
[data-testid="stSidebarNavLink"]:hover:not([aria-current="page"]) { background: color-mix(in srgb, currentColor 7%, transparent); transform: translateX(2px); }
[data-testid="stSidebarNavLink"][aria-current="page"] { background: rgba(123,97,255,.16); font-weight: 800; }
[data-testid="stSidebarNavLink"][aria-current="page"]::before {
  content: ""; position: absolute; left: 0; top: 22%; bottom: 22%; width: 4px; border-radius: 0 4px 4px 0;
  background: linear-gradient(180deg, #6A57F2, #2fa8ff);
}
/* Menu mục lục tự vẽ (key="side_nav" ở app.py): mục lớn thu gọn được, trang con thụt vào có đường kẻ dọc */
.st-key-side_nav { gap: 4px !important; margin: .5rem 0 .4rem; }
.st-key-side_nav [data-testid="stElementContainer"] { margin: 0; }
.st-key-side_nav [data-testid="stPageLink-NavLink"] {
  position: relative; border-radius: 14px; font-weight: 600; padding: .38rem .8rem; min-height: 40px;
  transition: background-color .15s ease, transform .15s ease;
}
.st-key-side_nav [data-testid="stPageLink-NavLink"]:hover:not([aria-current="page"]) { background: color-mix(in srgb, currentColor 7%, transparent); transform: translateX(2px); }
.st-key-side_nav [data-testid="stPageLink-NavLink"][aria-current="page"] { background: rgba(123,97,255,.16); font-weight: 800; }
.st-key-side_nav [data-testid="stPageLink-NavLink"][aria-current="page"]::before {
  content: ""; position: absolute; left: 0; top: 22%; bottom: 22%; width: 4px; border-radius: 0 4px 4px 0;
  background: linear-gradient(180deg, #6A57F2, #2fa8ff);
}
/* mục lớn: trang đứng riêng + tiêu đề khối thu gọn cùng kiểu chữ đậm */
.st-key-side_nav [class*="st-key-nav_top_"] [data-testid="stPageLink-NavLink"] { font-weight: 800; }
.st-key-side_nav [data-testid="stExpander"] details { border: 0 !important; background: transparent !important; }
.st-key-side_nav [data-testid="stExpander"] summary { padding: .45rem .8rem; min-height: 40px; border-radius: 14px; font-weight: 800; }
.st-key-side_nav [data-testid="stExpander"] summary:hover { background: color-mix(in srgb, currentColor 7%, transparent); }
.st-key-side_nav [data-testid="stExpanderDetails"] { gap: 2px; padding: 0 0 .25rem .35rem; margin-left: 1.2rem;
  border-left: 2px solid color-mix(in srgb, currentColor 13%, transparent); }
.st-key-side_nav [data-testid="stExpanderDetails"] [data-testid="stPageLink-NavLink"] { font-weight: 600; font-size: .93rem; min-height: 36px; }
/* Thẻ người dùng + chân thanh bên (key="side_user", "side_foot" ở app.py) */
.st-key-side_user { border: 1px solid color-mix(in srgb, currentColor 12%, transparent); border-radius: 18px; padding: .7rem .75rem .6rem;
  background: color-mix(in srgb, currentColor 4%, transparent); }
.side-id { display: flex; align-items: center; gap: .65rem; margin-bottom: .55rem; }
.side-av { flex: 0 0 auto; width: 2.35rem; height: 2.35rem; border-radius: 50%; display: grid; place-items: center; color: #fff; font-weight: 900;
  background: linear-gradient(135deg, #6A57F2, #2fa8ff); }
.side-name { font-weight: 800; letter-spacing: -.02em; line-height: 1.2; overflow-wrap: anywhere; }
.side-role { display: inline-block; margin-top: .15rem; padding: .05rem .5rem; border-radius: 999px; font-size: .72rem; font-weight: 800;
  background: rgba(123,97,255,.15); }
.st-key-side_foot { margin-top: .4rem; }
.st-key-side_foot [data-testid="stCaptionContainer"] { opacity: .6; font-size: .78rem; }

.auth-card { background: color-mix(in srgb, currentColor 4%, transparent); border: 1px solid color-mix(in srgb, currentColor 11%, transparent);
             border-radius: 24px; padding: 1.4rem 1.2rem; text-align: center; margin-bottom: 1rem; box-shadow: 0 30px 60px -38px rgba(40,30,80,.38); }
.auth-title { font-weight: 900; font-size: 1.3rem; letter-spacing: -.02em; }
.auth-sub { opacity: .7; font-size: .88rem; margin-top: .2rem; }
.hint-box { background: color-mix(in srgb, currentColor 4%, transparent); border: 1px dashed color-mix(in srgb, currentColor 25%, transparent);
            border-radius: 14px; padding: .7rem .9rem; font-size: .85rem; opacity: .9; }
.asof { opacity: .7; font-size: .85rem; margin-bottom: .4rem; }

.auth-logo { width: 76px; height: 76px; margin: 0 auto .7rem; border-radius: 22px; overflow: hidden;
             box-shadow: 0 10px 24px -10px rgba(0,0,0,.55); }
.auth-logo img { display: block; width: 100%; height: 100%; }
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
  [data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-primary"] { min-height: 44px; }
  [data-testid="stSidebarNavLink"], .st-key-side_nav [data-testid="stPageLink-NavLink"] { padding: .5rem .8rem; min-height: 44px; }
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


@__import__("functools").lru_cache(maxsize=1)
def _logo_html() -> str:
    """Logo nhúng thẳng vào HTML (base64). Tìm ở rs_app/assets hoặc ../assets; thiếu ảnh thì dùng emoji, không để ảnh vỡ."""
    import base64
    from pathlib import Path
    here = Path(__file__).resolve().parent.parent
    for d in (here / "assets", here.parent / "assets"):
        f = d / "logo-160.png"
        if f.is_file():
            return f'<img src="data:image/png;base64,{base64.b64encode(f.read_bytes()).decode()}" alt="">'
    return '<div style="font-size:2.4rem;line-height:76px;text-align:center">📈</div>'


def render_auth_portal():
    """Cổng đăng nhập: thẻ gọn ở giữa trang, không sidebar."""
    st.markdown(AUTH_CSS, unsafe_allow_html=True)
    with st.container(border=True, key="card_auth"):
        st.markdown(
            f'<div class="auth-head"><div class="auth-logo">{_logo_html()}</div>'
            '<div class="auth-title">FINSIGHT</div>'
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
    from src import engine
    pct = engine.PCT_COL
    fmt = {c: "{:,.0f}" for c in engine.TB_COLS if c in d}
    fmt[pct] = "{:.1f}%"
    fmt["GTGD TB20 (tỷ)"] = "{:,.1f}"
    st_ = d.style.apply(_zebra, axis=None).format(fmt, na_rep="–")
    st_ = _cellmap(st_, _bg_drop, [pct])
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
    # Đặt range tường minh + uirevision riêng theo dữ liệu: không phụ thuộc autorange và không "thừa hưởng"
    # vùng nhìn cũ khi mở biểu đồ mã khác (nghi nguyên nhân biểu đồ bị lệch/cắt cụt cửa sổ thời gian).
    fig.update_xaxes(type="category", tickmode="array", tickvals=tickvals, ticktext=ticktext,
                     range=[-1, len(xs) + 1], gridcolor=grid)
    fig.update_layout(uirevision=f"{title}|{len(xs)}|{xs[-1]}")
    fig.update_yaxes(gridcolor=grid)
    return fig


# ---------------------------------------------------------------- Biểu đồ kiểu TradingView
# TradingView Lightweight Charts v5.2.1 (Apache-2.0; giữ nguyên logo TradingView trên biểu đồ để ghi công).
# Kéo = di chuyển · lăn chuột = zoom quanh con trỏ · kéo trên trục = co giãn · các ngăn dùng chung trục thời gian.
# Mọi biểu đồ đều có thanh công cụ vẽ (nút to) và nút "Phóng to toàn trang": bản phóng to là một iframe thứ hai gắn vào <body>
# của trang cha (nên không bị thẻ/khung cha cắt), dựng lại từ chính mã HTML này; nét vẽ chia sẻ qua localStorage.
_LWC_VER = "5.2.1"
_TV_HTML = """<!doctype html><meta charset="utf-8">
<style>html,body{margin:0;height:100%;background:transparent;font:12px system-ui,sans-serif;overflow:hidden}
body.fs{background:__BG__}
#c{position:absolute;inset:0}
#t{position:absolute;left:10px;top:6px;z-index:3;font-weight:600;color:__FG__;pointer-events:none}
#o{position:absolute;left:10px;top:24px;right:90px;z-index:3;color:__FG__;font-size:11px;line-height:1.5;pointer-events:none}
#r,#x{position:absolute;right:62px;top:6px;z-index:5;border:1px solid __GRID__;background:rgba(128,128,128,.12);color:__FG__;
border-radius:6px;padding:3px 10px;font-size:12px;cursor:pointer}
#x{display:none;right:10px;background:rgba(220,38,38,.85);border-color:#dc2626;color:#fff;font-weight:600}
#dv{position:absolute;left:0;top:0;width:100%;height:100%;z-index:2;pointer-events:none}
#tb{position:absolute;left:6px;top:50px;z-index:4;display:flex;flex-direction:column;gap:3px}
#tb .fsonly{display:none}
#tb button{position:relative;width:34px;height:34px;padding:0;border:1px solid __GRID__;background:rgba(128,128,128,.14);color:__FG__;
border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center}
#tb button svg{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;pointer-events:none}
#tb button:hover{background:rgba(128,128,128,.32)}
#tb button.on{background:rgba(41,98,255,.42);border-color:#2962ff;color:#fff}
#tb .sep{height:1px;background:__GRID__;margin:3px 5px}
#tb button::after{content:attr(data-tip);position:absolute;left:calc(100% + 8px);top:50%;transform:translateY(-50%);white-space:nowrap;
background:#111827;color:#fff;font-size:12px;padding:4px 9px;border-radius:6px;opacity:0;pointer-events:none;transition:opacity .12s;z-index:9}
#tb button:hover::after{opacity:1}
#toast{position:absolute;left:50%;top:14px;transform:translateX(-50%);z-index:9;background:#111827;color:#fff;padding:6px 12px;border-radius:8px;display:none}
body.fs #c,body.fs #dv{left:66px;width:calc(100% - 66px)}
body.fs #t{left:78px;top:10px;font-size:16px}
body.fs #o{left:78px;top:36px;font-size:13px;right:200px}
body.fs #tb{left:8px;top:12px;gap:6px}
body.fs #tb .fsonly{display:flex}
body.fs #tb button{width:48px;height:48px}
body.fs #tb button svg{width:27px;height:27px}
@media (max-height:760px){body.fs #tb{gap:4px}body.fs #tb button{width:40px;height:40px}body.fs #tb button svg{width:23px;height:23px}}
@media (max-height:640px){body.fs #tb{gap:3px}body.fs #tb button{width:34px;height:34px}body.fs #tb button svg{width:20px;height:20px}}
body.fs #r{right:112px;top:10px;font-size:13px;padding:5px 12px}
body.fs #x{display:block;right:12px;top:10px;font-size:13px;padding:5px 12px}</style>
<div id="c"></div><canvas id="dv"></canvas><div id="t"></div><div id="o"></div><div id="tb"></div><div id="toast"></div>
<button id="r" title="Về mặc định">⟲ Reset</button><button id="x" title="Đóng (Esc)">✕ Đóng (Esc)</button>
__LIB__
<script>
const FS = !!window.__FS;                       // true: đây là bản phóng to (cửa sổ phủ toàn trang)
const PRISTINE = FS ? "" : "<!doctype html>" + document.documentElement.outerHTML;   // bản gốc, chụp trước khi vẽ biểu đồ
const D = __DATA__, FG = "__FG__", GRID = "__GRID__", L = LightweightCharts, UP = "#16a34a", DN = "#dc2626";
const BG = D.dark ? "#0e1117" : "#ffffff";
if (FS) document.body.classList.add("fs");
document.getElementById("t").textContent = D.title;
const chart = L.createChart(document.getElementById("c"), {
  autoSize: true,
  layout: { background: { type: "solid", color: "transparent" }, textColor: FG, fontFamily: "system-ui, sans-serif",
            fontSize: FS ? 14 : 12, panes: { separatorColor: GRID } },
  grid: { vertLines: { color: GRID }, horzLines: { color: GRID } },
  leftPriceScale: { visible: D.left, borderColor: GRID }, rightPriceScale: { borderColor: GRID },
  timeScale: { borderColor: GRID, rightOffset: 6, minBarSpacing: 0.4 },
  crosshair: { mode: L.CrosshairMode.Normal }
});
const H = [];
D.panes.forEach((p, pi) => p.series.forEach(s => {
  const o = { priceLineVisible: false, lastValueVisible: false, priceScaleId: s.scale || "right" };
  let T;
  if (s.type === "candle") { T = L.CandlestickSeries; Object.assign(o, { upColor: UP, downColor: DN, borderUpColor: UP,
    borderDownColor: DN, wickUpColor: UP, wickDownColor: DN }); }
  else if (s.type === "hist") { T = L.HistogramSeries; Object.assign(o, { color: s.color || "#888",
    priceFormat: s.fmt === "vol" ? { type: "volume" } : { type: "price" } }); }
  else { T = L.LineSeries; Object.assign(o, { color: s.color, lineWidth: s.width || 1.5, crosshairMarkerVisible: false }); }
  const ser = chart.addSeries(T, o, pi); ser.setData(s.data);
  s.m = {}; s.data.forEach(x => s.m[x.time] = x); H.push([s, ser]);
}));
const ps = chart.panes(); D.panes.forEach((p, i) => ps[i] && ps[i].setStretchFactor(p.weight || 1));
chart.timeScale().fitContent();
if (window.__RANGE) { try { chart.timeScale().setVisibleLogicalRange(window.__RANGE); } catch (e) {} }   // giữ đúng đoạn đang xem khi phóng to

const fmtV = n => n >= 1e6 ? (n / 1e6).toFixed(2) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "K" : String(n);
const tkey = t => typeof t === "object" && t ? t.year + "-" + String(t.month).padStart(2, "0") + "-" + String(t.day).padStart(2, "0") : t;
function show(t) {
  const out = [t];
  H.forEach(([s]) => {
    const x = s.m[t]; if (!x || s.title === undefined) return;
    let txt;
    if (s.type === "candle") { const c = x.close >= x.open ? UP : DN;
      txt = (s.title ? s.title + " " : "") + "M " + x.open + " C " + x.high + " T " + x.low + " Đ <b style='color:" + c + "'>" + x.close + "</b>"; }
    else { const v = s.fmt === "vol" ? fmtV(x.value) : Number(x.value).toFixed(s.dec === undefined ? 2 : s.dec);
      txt = "<span style='color:" + (s.color || FG) + "'>" + s.title + "</span> " + v; }
    out.push(txt);
  });
  document.getElementById("o").innerHTML = out.join(" &nbsp; ");
}
const first = D.panes[0].series[0].data, lastT = first[first.length - 1].time; show(lastT);
chart.subscribeCrosshairMove(p => { show(p.time ? tkey(p.time) : lastT); });
document.getElementById("r").onclick = () => { chart.priceScale("right").applyOptions({ autoScale: true }); chart.timeScale().fitContent(); };

// ---- Biểu tượng + nút của thanh công cụ (nút to, có chú thích khi rê chuột)
const ICONS = {
  cur: '<path d="M5 3l14 7-6 2 4 7-3 1-4-7-5 4z"/>',
  m: '<path d="M3 17L17 3l4 4L7 21z"/><path d="M7 13l2 2M10 10l2 2M13 7l2 2"/>',
  t: '<circle cx="5" cy="19" r="2"/><circle cx="19" cy="5" r="2"/><path d="M6.5 17.5L17.5 6.5"/>',
  h: '<path d="M3 12h18"/><circle cx="12" cy="12" r="2"/>',
  r: '<rect x="4" y="6" width="16" height="12" rx="1"/>',
  f: '<path d="M3 5h18M3 10h18M3 15h18M3 20h18" opacity=".9"/><path d="M6 20L18 5" stroke-dasharray="2 2"/>',
  undo: '<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 010 12h-3"/>',
  del: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  zin: '<circle cx="11" cy="11" r="6"/><path d="M16 16l5 5M11 8v6M8 11h6"/>',
  zout: '<circle cx="11" cy="11" r="6"/><path d="M16 16l5 5M8 11h6"/>',
  fit: '<path d="M20 12a8 8 0 11-3-6.2"/><path d="M20 4v5h-5"/>',
  full: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  close: '<path d="M5 5l14 14M19 5L5 19"/>'
};
function mkBtn(tb, tip, icon, fn, cls) {
  const b = document.createElement("button"); if (cls) b.className = cls; b.setAttribute("data-tip", tip); b.setAttribute("aria-label", tip);
  b.innerHTML = '<svg viewBox="0 0 24 24">' + ICONS[icon] + "</svg>"; b.onclick = fn; tb.appendChild(b); return b;
}
function mkSep(tb, cls) { const d = document.createElement("div"); d.className = "sep" + (cls ? " " + cls : ""); tb.appendChild(d); }
function toast(msg) {
  const t = document.getElementById("toast"); t.textContent = msg; t.style.display = "block";
  setTimeout(() => { t.style.display = "none"; }, 3500);
}

// ---- Phóng to: mở một cửa sổ phủ kín trang (gắn vào body của trang cha nên không bị khung/thẻ cha cắt)
let ov = null, savedOverflow = "";
function escParent(e) { if (e.key === "Escape") closeOv(); }
function closeOv() {
  if (!ov) return;
  const P = window.parent;
  try { if (P.document.fullscreenElement) P.document.exitFullscreen(); } catch (e) {}
  try { ov.remove(); } catch (e) {}
  ov = null;
  try { P.document.body.style.overflow = savedOverflow; P.removeEventListener("keydown", escParent); P.__rsMax = null; } catch (e) {}
  if (window.__reload) window.__reload();          // nét vẽ mới vẽ ở bản phóng to hiện lại ở bản nhỏ
}
function openMax() {
  let P = null;
  try { P = window.parent; void P.document.body; } catch (e) { P = null; }
  if (!P || P === window) {                         // không chạm được trang cha: thử toàn màn hình thật của khung này
    const el = document.documentElement;
    if (el.requestFullscreen) el.requestFullscreen().catch(() => toast("Trình duyệt không cho phóng to biểu đồ này"));
    else toast("Trình duyệt không cho phóng to biểu đồ này");
    return;
  }
  if (ov) return;
  let rg = null; try { rg = chart.timeScale().getVisibleLogicalRange(); } catch (e) {}
  ov = P.document.createElement("iframe");
  ov.setAttribute("allow", "fullscreen"); ov.setAttribute("allowfullscreen", ""); ov.title = D.title;
  ov.style.cssText = "position:fixed;left:0;top:0;width:100vw;height:100vh;border:0;z-index:2147483000;background:" + BG;
  const flag = "<script>window.__FS=1;window.__RANGE=" + JSON.stringify(rg) + ";</" + "script>";
  ov.srcdoc = PRISTINE.replace("<head>", "<head>" + flag);
  ov.addEventListener("load", () => { try { ov.contentWindow.focus(); } catch (e) {} });
  savedOverflow = P.document.body.style.overflow; P.document.body.style.overflow = "hidden";
  P.document.body.appendChild(ov);
  P.addEventListener("keydown", escParent); P.__rsMax = { close: closeOv };
}
function closeMax() {                                // gọi từ bản phóng to
  try { const P = window.parent; if (P.__rsMax && P.__rsMax.close) { P.__rsMax.close(); return; } } catch (e) {}
  try { if (document.fullscreenElement) document.exitFullscreen(); } catch (e) {}
}
function toggleReal() {                              // toàn màn hình thật của trình duyệt (ẩn cả thanh địa chỉ)
  try {
    const P = window.parent;
    if (P.document.fullscreenElement) P.document.exitFullscreen();
    else window.frameElement.requestFullscreen().catch(() => toast("Trình duyệt không cho bật toàn màn hình thật"));
  } catch (e) { toast("Trình duyệt không cho bật toàn màn hình thật"); }
}
document.getElementById("x").onclick = closeMax;
window.addEventListener("pagehide", closeOv);

// ---- Công cụ vẽ: thước đo, đường xu hướng, đường ngang, hộp, Fibonacci (mọi biểu đồ, kể cả biểu đồ đường)
(function () {
  const tb = document.getElementById("tb");
  try {
    const main = H[0][1], wrap = document.getElementById("c"), ts = chart.timeScale();
    const cv = document.getElementById("dv"), g = cv.getContext("2d");
    const BLUE = "#2962ff", UPA = "rgba(22,163,74,.16)", DNA = "rgba(220,38,38,.16)", BLA = "rgba(41,98,255,.12)";
    const times = first.map(x => x.time), key = "rsdraw:" + D.title;
    let shapes = [], ruler = null, pend = null, hover = null, tool = "";
    const load = () => { try { return JSON.parse(localStorage.getItem(key) || "[]"); } catch (e) { return []; } };
    shapes = load();
    const save = () => { try { localStorage.setItem(key, JSON.stringify(shapes)); } catch (e) {} };

    const offX = () => { try { return D.left ? chart.priceScale("left").width() : 0; } catch (e) { return 0; } };
    const plotW = () => ts.width(), plotH = () => chart.panes()[0].getHeight();
    const X = l => ts.logicalToCoordinate(l), Y = p => main.priceToCoordinate(p);
    const fp = p => Math.abs(p) >= 1000 ? p.toFixed(0) : p.toFixed(2);
    const day = l => { const i = Math.round(l); return i >= 0 && i < times.length ? new Date(times[i] + "T00:00:00Z") : null; };
    const fsz = FS ? 13 : 11;

    function pt(e) {
      const r = wrap.getBoundingClientRect(), x = e.clientX - r.left - offX(), y = e.clientY - r.top;
      if (x < 0 || x > plotW() || y < 0 || y > plotH()) return null;
      const l = ts.coordinateToLogical(x), p = main.coordinateToPrice(y);
      return l == null || p == null ? null : { l: Math.round(l), p: p };
    }

    function tag(lines, x, y, col) {
      g.font = fsz + "px system-ui, sans-serif";
      const lh = fsz + 4, w = Math.max.apply(null, lines.map(s => g.measureText(s).width)) + 10, h = lines.length * lh + 6;
      x = Math.min(Math.max(x, 2), plotW() - w - 2); y = Math.min(Math.max(y, 2), plotH() - h - 2);
      g.fillStyle = col; g.fillRect(x, y, w, h); g.fillStyle = "#fff";
      lines.forEach((s, i) => g.fillText(s, x + 5, y + lh + i * lh - 4));
    }

    function drawShape(s, b) {
      const a = s.a, x1 = X(a.l), y1 = Y(a.p);
      if (x1 == null || y1 == null) return;
      g.lineWidth = FS ? 2 : 1.5; g.setLineDash([]); g.strokeStyle = BLUE;
      if (s.t === "h") {
        g.setLineDash([5, 4]); g.beginPath(); g.moveTo(0, y1); g.lineTo(plotW(), y1); g.stroke(); g.setLineDash([]);
        tag([fp(a.p)], plotW() - 62, y1 - 10, BLUE); return;
      }
      b = b || s.b; if (!b) return;
      const x2 = X(b.l), y2 = Y(b.p);
      if (x2 == null || y2 == null) return;
      if (s.t === "m") {                       // thước đo
        const dp = b.p - a.p, pc = dp / a.p * 100, n = Math.round(Math.abs(b.l - a.l)), d1 = day(a.l), d2 = day(b.l);
        const days = d1 && d2 ? Math.round(Math.abs(d2 - d1) / 864e5) : null, col = dp >= 0 ? UP : DN;
        g.fillStyle = dp >= 0 ? UPA : DNA; g.fillRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
        g.strokeStyle = col; g.strokeRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
        g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.stroke();
        tag([(dp >= 0 ? "+" : "") + fp(dp) + " (" + (pc >= 0 ? "+" : "") + pc.toFixed(2) + "%)",
             n + " phiên" + (days != null ? " · " + days + " ngày" : "")], Math.max(x1, x2) + 8, (y1 + y2) / 2 - 17, col);
      } else if (s.t === "t") {                // đường xu hướng
        g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.stroke();
      } else if (s.t === "r") {                // hộp chữ nhật
        g.fillStyle = BLA; g.fillRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
        g.strokeRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
      } else if (s.t === "f") {                // Fibonacci thoái lui
        const L0 = Math.min(x1, x2), L1 = Math.max(x1, x2);
        [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1].forEach(lv => {
          const p = b.p + (a.p - b.p) * lv, y = Y(p); if (y == null) return;
          g.globalAlpha = 0.85; g.beginPath(); g.moveTo(L0, y); g.lineTo(L1, y); g.stroke(); g.globalAlpha = 1;
          g.fillStyle = BLUE; g.font = fsz + "px system-ui, sans-serif"; g.fillText(lv + "  (" + fp(p) + ")", L1 + 4, y + 4);
        });
      }
    }

    function paint() {
      const dpr = window.devicePixelRatio || 1, w = wrap.clientWidth, h = wrap.clientHeight;
      if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
      g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
      if (!shapes.length && !ruler && !pend) return;
      g.save(); g.translate(offX(), 0); g.beginPath(); g.rect(0, 0, plotW(), plotH()); g.clip();
      shapes.forEach(s => drawShape(s));
      if (ruler) drawShape(ruler);
      if (pend && hover) drawShape(pend, hover);
      else if (pend) { const x = X(pend.a.l), y = Y(pend.a.p); if (x != null && y != null) { g.fillStyle = BLUE; g.beginPath(); g.arc(x, y, 4.5, 0, 6.3); g.fill(); } }
      g.restore();
    }
    let raf = 0;
    const redraw = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; try { paint(); } catch (e) {} }); };
    window.__reload = () => { shapes = load(); ruler = null; pend = null; redraw(); };

    const TOOLS = [["", "cur", "Con trỏ (Esc)"], ["m", "m", "Thước đo: bấm 2 điểm để đo % và số phiên"],
                   ["t", "t", "Đường xu hướng: bấm 2 điểm"], ["h", "h", "Đường ngang: bấm 1 điểm"],
                   ["r", "r", "Hộp chữ nhật: bấm 2 góc"], ["f", "f", "Fibonacci thoái lui: bấm 2 điểm"]];
    const btns = {};
    function setTool(t) {
      tool = t; pend = null; hover = null; ruler = null;
      Object.keys(btns).forEach(k => btns[k].classList.toggle("on", k === t));
      wrap.style.cursor = t ? "crosshair" : ""; redraw();
    }
    TOOLS.forEach(([k, ic, tip]) => { btns[k] = mkBtn(tb, tip, ic, () => setTool(k)); });
    mkSep(tb);
    mkBtn(tb, "Xoá nét vẽ gần nhất", "undo", () => { shapes.pop(); save(); redraw(); });
    mkBtn(tb, "Xoá tất cả nét vẽ", "del", () => { shapes = []; ruler = null; pend = null; save(); redraw(); });
    mkSep(tb, "fsonly");
    const zoom = f => { const r = ts.getVisibleLogicalRange(); if (!r) return; const c = (r.from + r.to) / 2, h = (r.to - r.from) / 2 * f;
      ts.setVisibleLogicalRange({ from: c - h, to: c + h }); redraw(); };
    mkBtn(tb, "Phóng to biểu đồ (zoom +)", "zin", () => zoom(0.7), "fsonly");
    mkBtn(tb, "Thu nhỏ biểu đồ (zoom −)", "zout", () => zoom(1.4), "fsonly");
    mkBtn(tb, "Xem toàn bộ dữ liệu", "fit", () => { chart.priceScale("right").applyOptions({ autoScale: true }); ts.fitContent(); setTimeout(redraw, 80); }, "fsonly");
    if (D.left && !FS) tb.style.left = "62px";
    btns[""].classList.add("on");

    let down = null;
    wrap.addEventListener("mousedown", e => { down = [e.clientX, e.clientY]; }, true);
    wrap.addEventListener("click", e => {
      if (!tool || !down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;   // kéo để di chuyển thì bỏ qua
      const p = pt(e); if (!p) return;
      if (tool === "h") { shapes.push({ t: "h", a: p }); save(); }
      else if (!pend) { ruler = null; pend = { t: tool, a: p }; }
      else if (tool === "m") { ruler = { t: "m", a: pend.a, b: p }; pend = null; }
      else { shapes.push({ t: pend.t, a: pend.a, b: p }); pend = null; save(); }
      hover = null; redraw();
    }, true);
    wrap.addEventListener("mousemove", e => { if (tool && pend) hover = pt(e) || hover; redraw(); });
    wrap.addEventListener("wheel", redraw, { passive: true });
    window.addEventListener("mouseup", () => setTimeout(redraw, 0));
    document.addEventListener("keydown", e => {
      if (e.key !== "Escape") return;
      if (tool) setTool(""); else if (FS) closeMax();           // Esc lần 1 bỏ công cụ, lần 2 thoát phóng to
    });
    document.getElementById("r").addEventListener("click", () => setTimeout(redraw, 80));
    ts.subscribeVisibleLogicalRangeChange(redraw); chart.subscribeCrosshairMove(redraw);
    new ResizeObserver(redraw).observe(wrap); setInterval(redraw, 600); redraw();
  } catch (err) { /* lỗi công cụ vẽ thì chỉ còn các nút bên dưới */ }
  // ---- Nút phóng to / đóng ở cuối thanh công cụ
  mkSep(tb);
  if (!FS) mkBtn(tb, "Phóng to toàn trang (như TradingView)", "full", openMax);
  else { mkBtn(tb, "Toàn màn hình thật của trình duyệt", "full", toggleReal); mkBtn(tb, "Đóng (Esc)", "close", closeMax); }
})();
</script>"""


@__import__("functools").lru_cache(maxsize=1)
def _lwc_read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _lwc_script() -> str:
    """Thư viện nhúng thẳng vào trang (không phụ thuộc phục vụ file tĩnh); thiếu file thì dùng CDN."""
    from pathlib import Path
    f = Path(__file__).resolve().parent.parent / "static" / "lightweight-charts.standalone.production.js"
    try:
        return "<script>" + _lwc_read(str(f)).replace("</script", "<\\/script") + "</script>"
    except OSError:
        return f'<script src="https://unpkg.com/lightweight-charts@{_LWC_VER}/dist/lightweight-charts.standalone.production.js"></script>'


def _tv_clean(obj, cols=None):
    d = obj.dropna(subset=cols) if cols else obj.dropna()
    d = d.copy()
    d.index = pd.to_datetime(d.index)
    return d[~d.index.duplicated(keep="last")].sort_index()


def tv_candles(df: pd.DataFrame, title: str = "", scale: str = "right") -> dict:
    d = _tv_clean(df, ["open", "high", "low", "close"])
    t = d.index.strftime("%Y-%m-%d")
    data = [{"time": a, "open": round(float(o), 4), "high": round(float(h), 4), "low": round(float(l), 4),
             "close": round(float(c), 4)} for a, o, h, l, c in zip(t, d["open"], d["high"], d["low"], d["close"])]
    return {"type": "candle", "data": data, "title": title, "scale": scale}


def tv_line(s: pd.Series, color: str, title: str = "", width: float = 1.5, scale: str = "right", dec: int = 2) -> dict:
    d = _tv_clean(s.dropna())
    data = [{"time": a, "value": round(float(v), 4)} for a, v in zip(d.index.strftime("%Y-%m-%d"), d)]
    return {"type": "line", "data": data, "color": color, "title": title, "width": width, "scale": scale, "dec": dec}


def tv_hist(s: pd.Series, title: str = "", up: "pd.Series | None" = None, color: str = "rgba(128,128,128,.55)") -> dict:
    d = _tv_clean(s.fillna(0))
    flag = up.reindex(d.index) if up is not None else None
    data = []
    for i, (a, v) in enumerate(zip(d.index.strftime("%Y-%m-%d"), d)):
        p = {"time": a, "value": float(v)}
        if flag is not None:
            p["color"] = "rgba(22,163,74,.45)" if bool(flag.iloc[i]) else "rgba(220,38,38,.45)"
        data.append(p)
    return {"type": "hist", "data": data, "color": color, "title": title, "fmt": "vol"}


def tv_chart(title: str, panes: list, height: int = 560) -> None:
    """panes = [{"weight": 3, "series": [tv_candles(...), tv_line(...), ...]}, ...]"""
    import json
    panes = [p for p in panes if any(s["data"] for s in p["series"])]
    if not panes:
        st.info("Chưa có dữ liệu để vẽ biểu đồ.")
        return
    left = any(s.get("scale") == "left" for p in panes for s in p["series"])
    dark = getattr(st.context.theme, "type", None) == "dark"
    html = (_TV_HTML.replace("__LIB__", _lwc_script())
            .replace("__DATA__", json.dumps({"title": title, "panes": panes, "left": left, "dark": dark}, ensure_ascii=False))
            .replace("__BG__", "#0e1117" if dark else "#ffffff")
            .replace("__FG__", "#d7dbe0" if dark else "#3b3a42").replace("__GRID__", "rgba(128,128,128,.22)"))
    if hasattr(st, "iframe"):          # components.v1.html đã bị Streamlit loại bỏ dần -> ưu tiên st.iframe
        st.iframe(html, height=height)
    else:
        import streamlit.components.v1 as components
        components.html(html, height=height)


def price_chart(ohlcv: pd.DataFrame, title: str, height: int = 560) -> None:
    """Biểu đồ giá: nến + khối lượng (TB5, TB20). CHART_ENGINE=plotly để quay lại Plotly cũ."""
    import os
    if os.environ.get("CHART_ENGINE") == "plotly":
        st.plotly_chart(candle_chart(ohlcv, title), width="stretch")
        return
    d = _tv_clean(ohlcv, ["open", "high", "low", "close"])
    vol = d["volume"].fillna(0)
    tv_chart(title, [
        {"weight": 3, "series": [tv_candles(d)]},
        {"weight": 1, "series": [tv_hist(vol, "KL", up=d["close"] >= d["open"]),
                                 tv_line(vol.rolling(5).mean(), "#f59e0b", "TB5", 1, dec=0),
                                 tv_line(vol.rolling(20).mean(), "#7B61FF", "TB20", 1, dec=0)]},
    ], height)
