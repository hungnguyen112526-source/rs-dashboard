"""Giao diện: CSS, cổng đăng nhập/đăng ký, trang quản trị, biểu đồ nến."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from src import auth

CSS = """
<style>
.block-container { padding-top: 1.6rem; max-width: 1280px; }
.auth-card { background: linear-gradient(135deg,#0f172a,#1e293b); border-radius:16px; padding:1.4rem 1.2rem; text-align:center; color:#e2e8f0; margin-bottom:1rem; }
.auth-title { font-weight:800; font-size:1.25rem; letter-spacing:.02em; }
.auth-sub { color:#94a3b8; font-size:.88rem; margin-top:.2rem; }
.hint-box { background:#f8fafc; border:1px dashed #cbd5e1; border-radius:8px; padding:.7rem .9rem; font-size:.85rem; color:#475569; }
.asof { color:#64748b; font-size:.85rem; margin-bottom:.4rem; }
</style>
"""


def apply_css():
    st.markdown(CSS, unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# Cổng đăng nhập / đăng ký
# ----------------------------------------------------------------------------

def render_auth_portal():
    _, col, _ = st.columns([1, 2.2, 1])
    with col:
        st.markdown(
            '<div class="auth-card"><div class="auth-title">📈 RS DASHBOARD</div>'
            '<div class="auth-sub">Xếp hạng sức mạnh giá · Lọc khối lượng · Dòng tiền cổ phiếu Việt Nam</div></div>',
            unsafe_allow_html=True,
        )
        tab_login, tab_reg = st.tabs(["🔑 Đăng nhập", "📝 Đăng ký"])

        with tab_login:
            with st.form("form_login"):
                uname = st.text_input("👤 Tên đăng nhập")
                pwd = st.text_input("🔒 Mật khẩu", type="password")
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
# Biểu đồ nến + volume
# ----------------------------------------------------------------------------

def candle_chart(ohlcv: pd.DataFrame, title: str) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(
        x=ohlcv.index, open=ohlcv["open"], high=ohlcv["high"], low=ohlcv["low"], close=ohlcv["close"],
        increasing_line_color="#22c55e", decreasing_line_color="#ef4444", name="Giá"), row=1, col=1)
    if "volume" in ohlcv.columns:
        colors = ["rgba(34,197,94,.5)" if c >= o else "rgba(239,68,68,.5)" for o, c in zip(ohlcv["open"], ohlcv["close"])]
        fig.add_trace(go.Bar(x=ohlcv.index, y=ohlcv["volume"], marker_color=colors, name="KLGD"), row=2, col=1)
    fig.update_layout(title=title, height=520, showlegend=False, margin=dict(l=10, r=10, t=40, b=10),
                      xaxis_rangeslider_visible=False, template="plotly_white")
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    return fig
