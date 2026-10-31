"""Trang chủ: giới thiệu web + vài số liệu nổi bật lấy trực tiếp từ dữ liệu hiện có."""
import html

import pandas as pd
import streamlit as st

HERO_CSS = """
<style>
.home-hero { padding: .4rem 0 .2rem; }
.home-kicker { font-weight: 800; letter-spacing: .08em; text-transform: uppercase; font-size: .78rem; opacity: .65; }
.home-title { font-size: clamp(2rem, 5vw, 3.2rem); font-weight: 900; letter-spacing: -.05em; line-height: 1.08; margin: .25rem 0 .6rem; }
.home-title span { background: linear-gradient(90deg,#6A57F2,#2fa8ff); -webkit-background-clip: text; background-clip: text; color: transparent; }
.home-lead { font-size: 1.08rem; line-height: 1.6; max-width: 46rem; opacity: .88; }
.home-pill { display: inline-block; margin-top: .8rem; padding: .25rem .8rem; border-radius: 999px; font-size: .82rem; font-weight: 700;
             background: rgba(123,97,255,.14); }
.home-card-title { font-weight: 800; font-size: 1.02rem; letter-spacing: -.02em; }
.home-card-text { font-size: .88rem; opacity: .78; line-height: 1.5; min-height: 6.2em; }
.home-step { display: flex; gap: .8rem; align-items: flex-start; margin: .5rem 0; }
.home-step b.n { flex: 0 0 auto; width: 1.9rem; height: 1.9rem; border-radius: 50%; display: grid; place-items: center;
                 background: linear-gradient(135deg,#6A57F2,#8b6cff); color: #fff; font-size: .9rem; }
.home-kpi-label { font-size: .85rem; font-weight: 700; opacity: .7; }
.home-kpi-value { font-size: 1.35rem; font-weight: 900; letter-spacing: -.03em; line-height: 1.2; margin: .15rem 0 .3rem; }
.home-kpi-note { font-size: .8rem; font-weight: 700; color: #16a34a; }
.home-note { font-size: .82rem; opacity: .65; line-height: 1.5; }
</style>
"""

FEATURES = [
    ("rs", "🏆", "Xếp hạng RS", "Điểm sức mạnh giá 1–99 cho từng mã và từng ngành, xem theo ngày hoặc theo tuần."),
    ("klgd", "📉", "Lọc KLGD", "Tìm các mã có khối lượng giao dịch co dần: TB10 < TB20 < TB30 (< TB50)."),
    ("dongtien", "📊", "Dòng tiền", "Chỉ số tổng hợp có trọng số dòng tiền cho cả thị trường và từng ngành."),
    ("theodoi", "⭐", "Theo dõi", "Lưu danh sách mã riêng của bạn kèm ghi chú, xem nhanh RS và biểu đồ."),
    ("bctc", "📑", "BCTC", "Doanh thu, lợi nhuận, cân đối kế toán và lưu chuyển tiền tệ theo quý."),
    ("tintuc", "📰", "Tin tức", "Tin mới từ các nguồn báo, lọc theo chuyên mục và theo mã cổ phiếu."),
    ("vimo", "🌐", "Vĩ mô", "Lãi suất, lạm phát, tỷ giá, vàng, dầu, trái phiếu và dự báo của Fed."),
    ("lich", "📅", "Lịch kinh tế", "Các sự kiện kinh tế sắp diễn ra trong nước và thế giới."),
    ("giaodich", "🎮", "Giao dịch giả lập", "Tập giao dịch bằng vốn ảo theo giá mới nhất: đặt lệnh, xem danh mục và so hiệu suất với VNINDEX."),
]

# Các mục lớn của menu (giữ khớp với `sections` trong app.py): (tên mục, [mã trang trong FEATURES])
SECTIONS = [
    ("Phân tích kỹ thuật", ["rs", "dongtien", "klgd"]),
    ("Phân tích vĩ mô", ["vimo", "lich"]),
    ("Tin tức & BCTC", ["tintuc", "bctc"]),
    ("Theo dõi", ["theodoi"]),
    ("Giao dịch giả lập", ["giaodich"]),
]


def _vnindex_card(vnindex: pd.DataFrame) -> tuple[str, str | None]:
    """(giá trị, mức thay đổi so với phiên trước)"""
    if vnindex is None or vnindex.empty:
        return "—", None
    c = vnindex.sort_values("date")["close"].reset_index(drop=True)
    if len(c) < 2:
        return f"{c.iloc[-1]:,.2f}", None
    return f"{c.iloc[-1]:,.2f}", f"{(c.iloc[-1] / c.iloc[-2] - 1) * 100:+.2f}%"


def render(user: dict, as_of: str, vnindex: pd.DataFrame, scores: pd.DataFrame, ind: pd.DataFrame, n_tickers: int,
           pages: dict) -> None:
    """pages: {url_path: st.Page} để tạo nút chuyển trang."""
    st.html(HERO_CSS)
    name = user.get("fullname") or user.get("username", "")
    st.html(f"""
    <div class="home-hero">
      <div class="home-kicker">Xin chào, {html.escape(str(name))}</div>
      <div class="home-title">Chứng khoán <span>sung rụng</span></div>
      <div class="home-lead">Bảng xếp hạng sức mạnh giá (RS) của cổ phiếu Việt Nam. Thay vì mở từng biểu đồ, bạn chỉ cần nhìn
      một bảng để biết mã nào, ngành nào đang mạnh hơn phần còn lại của thị trường — rồi đào sâu bằng khối lượng, dòng tiền,
      báo cáo tài chính, tin tức, vĩ mô và một trợ lý AI trả lời ngay trên dữ liệu của web.</div>
      <div class="home-pill">Dữ liệu giá đến {as_of} · {n_tickers} mã · {len(ind) if ind is not None else 0} ngành</div>
    </div>""")

    # ---- Số liệu nổi bật (lấy từ dữ liệu thật) ----
    if scores is not None and not scores.empty and ind is not None and not ind.empty:
        vn = _vnindex_card(vnindex)
        top = ind.iloc[0]
        cols = st.columns(4)
        with cols[0].container(border=True, key="card_kpi_0_home"):
            st.metric("VN-Index", vn[0], vn[1], help="Thay đổi so với phiên trước")
        with cols[1].container(border=True, key="card_kpi_1_home"):
            st.metric("Mã được xếp hạng", f"{len(scores)}", help="Mã đủ dữ liệu (≥ 120 phiên) để tính RS")
        with cols[2].container(border=True, key="card_kpi_2_home"):
            st.html(f'<div class="home-kpi-label">Ngành mạnh nhất</div>'
                    f'<div class="home-kpi-value">{html.escape(str(top["industry"]))}</div>'
                    f'<div class="home-kpi-note">RS ngành {int(top["RS_nganh"])}</div>')
        with cols[3].container(border=True, key="card_kpi_3_home"):
            st.metric("Mã RS ≥ 90", f"{int((scores['RS'] >= 90).sum())}")

        st.subheader("Nổi bật hôm nay")
        c1, c2 = st.columns(2)
        with c1.container(border=True, key="card_home_ind"):
            st.markdown("**5 ngành mạnh nhất** (RS ngành, khung ngày)")
            v = ind.head(5).rename(columns={"industry": "Ngành", "RS_nganh": "RS ngành"})[["Ngành", "RS ngành"]]
            st.dataframe(v, hide_index=True, width="stretch",
                         column_config={"RS ngành": st.column_config.ProgressColumn("RS ngành", min_value=1, max_value=99, format="%d")})
        with c2.container(border=True, key="card_home_stk"):
            st.markdown("**5 cổ phiếu RS cao nhất** (khung ngày)")
            v = scores.head(5).rename(columns={"ticker": "Mã", "industry": "Ngành"})[["Mã", "Ngành", "RS"]]
            st.dataframe(v, hide_index=True, width="stretch",
                         column_config={"RS": st.column_config.ProgressColumn("RS", min_value=1, max_value=99, format="%d")})

    # ---- Web có những gì ----
    st.subheader("Web có những gì?")
    by_path = {f[0]: f for f in FEATURES}
    for section_name, paths in SECTIONS:
        st.markdown(f"##### {section_name}")
        cols = st.columns(4)
        for col, (path, icon, title, text) in zip(cols, [by_path[p] for p in paths]):
            with col.container(border=True, key=f"card_home_f_{path}"):
                st.html(f'<div class="home-card-title">{icon} {title}</div><div class="home-card-text">{text}</div>')
                page = pages.get(path)
                if page is not None:
                    st.page_link(page, label="Mở trang", icon=":material/arrow_forward:", width="stretch")

    # ---- RS là gì + cách dùng ----
    left, right = st.columns([3, 2])
    with left.container(border=True, key="card_home_rs"):
        st.markdown("#### RS là gì?")
        st.markdown(
            "**RS (Relative Strength)** là điểm từ **1 đến 99** cho biết cổ phiếu tăng giá mạnh hay yếu so với các mã còn lại. "
            "RS 90 nghĩa là mã đó đang tốt hơn khoảng 90% số mã khác.\n\n"
            "Cách tính: lấy mức tăng giá của 4 khối thời gian gần nhất (mỗi khối 30 phiên với khung ngày, 20 tuần với khung tuần), "
            "cộng lại với trọng số **0,4 · 0,3 · 0,2 · 0,1** (khối gần nhất nặng nhất), rồi xếp hạng toàn thị trường. "
            "Điểm của ngành là trung bình điểm các mã trong ngành, cũng được xếp hạng 1–99.")
    with right.container(border=True, key="card_home_how"):
        st.markdown("#### Dùng thế nào?")
        st.html("""
        <div class="home-step"><b class="n">1</b><div><b>Xem RS</b><br>Tìm ngành và mã có điểm cao.</div></div>
        <div class="home-step"><b class="n">2</b><div><b>Lọc KLGD, xem dòng tiền</b><br>Kiểm tra lượng mua bán và tiền đang vào đâu.</div></div>
        <div class="home-step"><b class="n">3</b><div><b>Đối chiếu BCTC, tin tức</b><br>Xem doanh nghiệp phía sau con số.</div></div>
        <div class="home-step"><b class="n">4</b><div><b>Hỏi AI</b><br>Bấm nút 💬 góc dưới phải để hỏi bằng tiếng Việt.</div></div>""")

    st.html('<div class="home-note">Thông tin trên web chỉ để tham khảo, không phải khuyến nghị mua hay bán. Dữ liệu lấy từ nguồn bên ngoài '
            'nên có thể chậm hoặc sai sót; trợ lý AI cũng có thể nhầm — hãy đối chiếu với bảng số liệu trước khi quyết định.</div>')
