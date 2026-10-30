"""Các trang còn lại của bản Streamlit: Tin tức, Dòng tiền, BCTC, Vĩ mô.

Mỗi hàm render_* nhận dữ liệu đã nạp sẵn và tự vẽ trang. Dữ liệu JSON (news_data.json, financials_data.json,
macro_data.json, bond_yields.json) vẫn do GitHub Actions cập nhật như cũ; app chỉ đọc file.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import auth, engine, ui

ROOT = Path(__file__).resolve().parent.parent  # thư mục rs_app/
GREEN, RED, BLUE, AMBER = "#16a34a", "#dc2626", "#7B61FF", "#f59e0b"
GRID = "rgba(128,128,128,.18)"


# ----------------------------------------------------------------------------
# Tiện ích chung
# ----------------------------------------------------------------------------
def find_file(name: str) -> Path | None:
    """Tìm file dữ liệu trong rs_app/ hoặc thư mục cha (gốc repo)."""
    for base in (ROOT, ROOT.parent):
        p = base / name
        if p.exists():
            return p
    return None


@st.cache_resource(show_spinner="Đang nạp dữ liệu...")
def _load_json(path_str: str, mtime: float):
    with open(path_str, encoding="utf-8") as f:
        return json.load(f)


def load_json(name: str):
    """Đọc JSON (cache theo thời điểm sửa file). Trả None nếu thiếu/hỏng."""
    p = find_file(name)
    if p is None:
        return None
    try:
        return _load_json(str(p), p.stat().st_mtime)
    except Exception as e:  # file hỏng giữa chừng khi Actions đang ghi
        st.error(f"Không đọc được {name}: {type(e).__name__}")
        return None


def _missing(name: str, workflow: str):
    st.warning(f"Chưa có dữ liệu **{name}**. Chạy workflow **{workflow}** trên GitHub Actions để tạo file này.")


_PUNCT = re.compile(r"([!-/:-@\[-`{-~])")


def _md(s) -> str:
    """Escape mọi ký tự dấu câu ASCII để dữ liệu ngoài (RSS) không bị hiểu thành markdown/LaTeX."""
    return _PUNCT.sub(r"\\\1", "" if s is None else str(s))


def _safe_url(u) -> str | None:
    try:
        p = urlparse(str(u or ""))
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    return (str(u).replace(" ", "%20").replace("(", "%28").replace(")", "%29")
            .replace("<", "%3C").replace(">", "%3E"))


def _fmt_num(v) -> str:
    if v is None or pd.isna(v):
        return "–"
    a = abs(v)
    if a >= 1e9:
        return f"{v / 1e9:,.2f} tỷ"
    if a >= 1e6:
        return f"{v / 1e6:,.2f} triệu"
    if a >= 1000:
        return f"{v:,.1f}"
    if a >= 10:
        return f"{v:,.2f}"
    return f"{v:,.4f}"  # tỷ giá (EUR/USD...) cần nhiều số lẻ


def _pct(a, b) -> str:
    if a is None or b in (None, 0) or pd.isna(a) or pd.isna(b):
        return "–"
    return f"{(a / b - 1) * 100:+.2f}%"


def _style_axes(fig: go.Figure, weekend_gaps: bool = True):
    fig.update_xaxes(gridcolor=GRID, **({"rangebreaks": [dict(bounds=["sat", "mon"])]} if weekend_gaps else {}))
    fig.update_yaxes(gridcolor=GRID)


def _clip_years(df: pd.DataFrame, label: str) -> pd.DataFrame:
    years = {"1N": 1, "3N": 3, "5N": 5, "10N": 10}.get(label)
    if years is None or df.empty:
        return df
    return df[df.index >= df.index.max() - pd.DateOffset(years=years)]


# ----------------------------------------------------------------------------
# 📰 Tin tức
# ----------------------------------------------------------------------------
NEWS_PAGE = 30


def render_news(news, username: str | None = None):
    st.header("📰 Tin tức tổng hợp")
    if not news or not news.get("articles"):
        _missing("news_data.json", "Cập nhật tin tức (update_news)")
        return
    articles = sorted(news["articles"], key=lambda a: a.get("published_at") or "", reverse=True)
    cats = news.get("categories") or sorted({a.get("category") for a in articles if a.get("category")})

    counts = {}
    for a in articles:
        counts[a.get("source") or "Khác"] = counts.get(a.get("source") or "Khác", 0) + 1
    sources = sorted(counts, key=lambda k: (-counts[k], k))
    st.caption(f"Nguồn: {len(sources)} trang báo (RSS công khai) · Cập nhật lần cuối: "
               f"{news.get('updated_at', '–')} · {len(articles)} bài gần nhất")
    st.caption("Tag mã (VD `VIC`) được gắn tự động khi tiêu đề/tóm tắt có nhắc mã viết HOA — "
               "chỉ là gợi ý theo từ khoá, có thể sót hoặc nhầm.")

    # Bộ lọc trang báo: nhớ lựa chọn đã lưu của người dùng (nếu có), mặc định chọn tất cả
    if "news_src" not in st.session_state:
        saved = auth.get_pref(username, "news_sources", None) if username else None
        st.session_state["news_src"] = [x for x in (saved or []) if x in sources] or sources
    else:
        st.session_state["news_src"] = [x for x in st.session_state["news_src"] if x in sources]
    s1, s2 = st.columns([5, 1], vertical_alignment="bottom")
    picked = s1.multiselect("Trang báo theo dõi", sources, key="news_src",
                            format_func=lambda k: f"{k} ({counts[k]})", placeholder="Chọn trang báo...")
    if username and s2.button("💾 Lưu", width="stretch", help="Lưu các trang báo đang chọn làm mặc định của bạn"):
        auth.set_pref(username, "news_sources", picked)
        st.toast("Đã lưu các trang báo theo dõi")

    c1, c2 = st.columns([3, 2], vertical_alignment="bottom")
    cat = c1.pills("Chuyên mục", ["Tất cả"] + list(cats), default="Tất cả", key="news_cat") or "Tất cả"
    q = c2.text_input("Tìm kiếm", placeholder="🔍 Từ khoá hoặc mã (VD: VIC, ngân hàng, Fed...)", key="news_q",
                      label_visibility="collapsed").strip().lower()

    def hit(a):
        if (a.get("source") or "Khác") not in picked:
            return False
        if cat != "Tất cả" and a.get("category") != cat:
            return False
        if not q:
            return True
        hay = f"{a.get('title', '')} {a.get('summary', '')} {' '.join(a.get('tickers') or [])}".lower()
        return q in hay

    rows = [a for a in articles if hit(a)]
    sig = (cat, q, tuple(picked))
    if st.session_state.get("news_sig") != sig:  # đổi bộ lọc -> quay về trang đầu
        st.session_state["news_sig"], st.session_state["news_n"] = sig, NEWS_PAGE
    n = st.session_state.setdefault("news_n", NEWS_PAGE)

    st.caption(f"{len(rows)} bài")
    if not rows:
        st.info("Không có bài nào khớp bộ lọc hiện tại.")
        return
    for a in rows[:n]:
        url = _safe_url(a.get("link"))
        title = _md(a.get("title") or "(không có tiêu đề)")
        tags = " ".join(f"`{t}`" for t in (a.get("tickers") or []) if re.fullmatch(r"[A-Z0-9]{2,6}", str(t)))
        meta = " · ".join(x for x in [_md(a.get("source")), _md(a.get("category")), _md(a.get("published_at")), tags] if x)
        with st.container(border=True):
            st.markdown(f"**[{title}]({url})**" if url else f"**{title}**")
            st.caption(meta)
            if a.get("summary"):
                summ = str(a["summary"])
                st.markdown(_md(summ if len(summ) <= 400 else summ[:397] + "..."))
    if len(rows) > n and st.button(f"⬇️ Xem thêm ({len(rows) - n} bài)", key="news_more", width="stretch"):
        st.session_state["news_n"] = n + NEWS_PAGE
        st.rerun()


# ----------------------------------------------------------------------------
# 📊 Dòng tiền
# ----------------------------------------------------------------------------
FLOW_RANGES = {"3 tháng": 63, "6 tháng": 126, "1 năm": 252, "3 năm": 756, "Tất cả": None}


@st.cache_data(ttl=600, show_spinner="Đang tính chỉ số dòng tiền...")
def _flow_cached(path_str: str, mtime: float, kind: str, name: str, _stocks: pd.DataFrame) -> pd.DataFrame:
    d = _stocks
    if kind == "Ngành":
        d = d[d["industry"] == name]
    elif kind == "Tập đoàn":
        d = d[d["nhom"] == name]
    cols = [c for c in ["date", "ticker", "close", "volume", "high", "low"] if c in d.columns]
    return engine.money_flow_index(d[cols])


def _flow_panes(idx: pd.DataFrame, mode: str, vn: pd.DataFrame | None) -> list:
    main = ui.tv_candles(idx, "Dòng tiền") if mode == "Nến" else ui.tv_line(idx["close"], BLUE, "Dòng tiền", 2, dec=1)
    panes = [{"weight": 3, "series": [main]}]
    if vn is not None and not vn.empty:
        panes.append({"weight": 2, "series": [ui.tv_candles(vn, "VN-Index")]})
    panes.append({"weight": 1, "series": [ui.tv_hist(idx["value"], "GTGD (tỷ đồng)")]})
    return panes


def render_flow(stocks: pd.DataFrame, vnindex: pd.DataFrame, path_str: str, mtime: float):
    st.header("📊 Chỉ số dòng tiền")
    if "volume" not in stocks.columns or stocks["volume"].dropna().empty:
        st.warning("Dữ liệu giá chưa có cột khối lượng nên không tính được chỉ số dòng tiền.")
        return

    industries = sorted(stocks["industry"].dropna().unique())
    groups = sorted(stocks["nhom"].dropna().unique()) if "nhom" in stocks.columns else []
    kinds = ["Toàn thị trường", "Ngành"] + (["Tập đoàn"] if groups else [])

    c1, c2, c3 = st.columns([3, 3, 2], vertical_alignment="bottom")
    kind = c1.segmented_control("Rổ cổ phiếu", kinds, default="Toàn thị trường", key="flow_kind") or "Toàn thị trường"
    if kind == "Toàn thị trường":
        name = "Toàn thị trường"
    else:
        options = industries if kind == "Ngành" else groups
        name = c2.selectbox(kind, options, key=f"flow_name_{kind}")
    mode = c3.segmented_control("Kiểu biểu đồ", ["Đường", "Nến"], default="Đường", key="flow_mode") or "Đường"

    c4, c5 = st.columns([3, 2], vertical_alignment="bottom")
    rng = c4.segmented_control("Khoảng thời gian", list(FLOW_RANGES), default="1 năm", key="flow_rng") or "1 năm"
    show_vn = c5.toggle("Hiện VNIndex thực (trục phụ)", value=not vnindex.empty, key="flow_vn", disabled=vnindex.empty)

    idx = _flow_cached(path_str, mtime, kind, name, stocks)
    if idx.empty:
        st.info("Không có dữ liệu cho rổ này.")
        return
    close = idx["close"]
    ui.kpi_row([
        ("Chỉ số hiện tại", f"{close.iloc[-1]:,.1f}", f"Mốc 1000 điểm tại {idx.index[0]:%d/%m/%Y}"),
        ("So với phiên trước", _pct(close.iloc[-1], close.iloc[-2]) if len(close) > 1 else "–", None),
        ("So với 1 tháng trước", _pct(close.iloc[-1], close.iloc[-22]) if len(close) > 22 else "–", "22 phiên"),
        ("So với 1 năm trước", _pct(close.iloc[-1], close.iloc[-251]) if len(close) > 251 else "–", "250 phiên"),
    ])

    n = FLOW_RANGES[rng]
    view = idx.tail(n) if n else idx
    vn_close = None
    if show_vn and not vnindex.empty:
        vn_close = vnindex.sort_values("date").set_index("date")[["open", "high", "low", "close"]].loc[view.index.min():]
    with st.container(border=True, key="card_flow_chart"):
        ui.tv_chart(f"{name} — chỉ số dòng tiền", _flow_panes(view, mode, vn_close), height=640 if vn_close is not None else 520)

    with st.expander("📖 Chỉ số này tính thế nào?"):
        st.markdown(
            f"- Mốc khởi điểm **1000 điểm** tại phiên đầu tiên có dữ liệu.\n"
            f"- Trọng số mỗi mã = SMA({engine.INDEX_SMOOTH_WINDOW} phiên) của giá trị giao dịch (giá × khối lượng) — "
            f"đã làm mượt để giảm nhiễu; mã thiếu dữ liệu ngày nào bị loại khỏi trọng số ngày đó.\n"
            f"- %Δ chỉ số = Σ (trọng số × %Δ giá từng mã).\n"
            f"- Chế độ nến: Mở(t) = Đóng(t-1); High/Low tổng hợp theo cùng trọng số dòng tiền.\n"
            f"- Cột xám bên dưới = tổng giá trị giao dịch mỗi phiên (tỷ đồng). Đây là công cụ tham khảo, "
            f"không phải tín hiệu mua/bán."
        )


# ----------------------------------------------------------------------------
# 📑 Báo cáo tài chính
# ----------------------------------------------------------------------------
FIN_LABELS = {"income_statement": "Kết quả kinh doanh", "balance_sheet": "Cân đối kế toán",
              "cash_flow": "Lưu chuyển tiền tệ", "ratio": "Chỉ số tài chính"}
_META = ("item", "item_en", "item_id")
_HIDE_IDS = {"year", "quarter", "ratioTTMId", "ratioType"}  # dòng kỹ thuật của bảng chỉ số


def _fin_frame(table: dict, key: str, in_billions: bool):
    """Bảng BCTC dạng (chỉ tiêu × kỳ). Trả (DataFrame hiển thị, danh sách cột kỳ) hoặc (None, [])."""
    if not table or not table.get("columns") or not table.get("rows"):
        return None, []
    df = pd.DataFrame(table["rows"], columns=table["columns"])
    if "item" not in df.columns:
        return None, []
    if "item_id" in df.columns:
        df = df[~df["item_id"].isin(_HIDE_IDS)]
    periods = sorted((c for c in df.columns if c not in _META), reverse=True)  # kỳ mới nhất bên trái
    if not periods or df.empty:
        return None, []
    df = df.copy()
    df[periods] = df[periods].apply(pd.to_numeric, errors="coerce")
    unit = []
    for i, row in df.iterrows():
        vals = row[periods].astype(float)
        big = vals.abs().max() >= 1e6
        is_money = big if key != "ratio" else (row.get("item_id") == "market_cap")
        if is_money and in_billions:
            df.loc[i, periods] = vals / 1e9
            unit.append("tỷ đồng")
        else:
            unit.append("đồng" if is_money else "")
    out = pd.DataFrame({"Chỉ tiêu": df["item"].values, "Đơn vị": unit})
    for p in periods:
        out[p] = df[p].values
    return out, periods


def _fin_fmt(v) -> str:
    if v is None or pd.isna(v):
        return "–"
    a = abs(v)
    if a >= 1e6:
        return f"{v:,.0f}"
    if a >= 1000:
        return f"{v:,.1f}"
    return f"{v:,.2f}"


def fin_tabs(data: dict, period_label: str, in_billions: bool = True) -> None:
    """4 tab báo cáo (KQKD, CĐKT, LCTT, chỉ số) của một mã."""
    tabs = st.tabs(list(FIN_LABELS.values()))
    for tab, (key, label) in zip(tabs, FIN_LABELS.items()):
        with tab:
            frame, periods = _fin_frame(data.get(key), key, in_billions)
            if frame is None:
                st.info("Không có dữ liệu báo cáo này cho mã đã chọn.")
                continue
            styler = frame.style.apply(ui._zebra, axis=None).format(_fin_fmt, subset=periods, na_rep="–")
            st.caption(f"{len(frame)} chỉ tiêu · {len(periods)} {period_label}")
            st.dataframe(styler, hide_index=True, width="stretch", height=min(36 * (len(frame) + 1) + 3, 720),
                         column_config={"Chỉ tiêu": st.column_config.TextColumn("Chỉ tiêu", pinned=True, width="large"),
                                        "Đơn vị": st.column_config.TextColumn("Đơn vị", width="small")})


def render_fin(fin, industry_map: dict):
    st.header("📑 Báo cáo tài chính")
    tickers = (fin or {}).get("tickers") or {}
    if not tickers:
        _missing("financials_data.json", "Cập nhật báo cáo tài chính (update_financials)")
        return
    period_label = "quý" if fin.get("period", "quarter") == "quarter" else "năm"
    st.caption(f"Nguồn: vnstock (VCI) · Theo {period_label} · Cập nhật lần cuối: {fin.get('updated_at', '–')}")

    c1, c2 = st.columns([3, 2], vertical_alignment="bottom")
    ticker = c1.selectbox("Mã cổ phiếu", sorted(tickers), key="fin_ticker",
                          format_func=lambda t: f"{t} · {industry_map.get(t) or 'Khác'}")
    unit_choice = c2.segmented_control("Đơn vị tiền", ["Tỷ đồng", "Đồng (gốc)"], default="Tỷ đồng",
                                       key="fin_unit") or "Tỷ đồng"
    in_billions = unit_choice == "Tỷ đồng"

    fin_tabs(tickers[ticker], period_label, in_billions)


# ----------------------------------------------------------------------------
# 🌐 Vĩ mô
# ----------------------------------------------------------------------------
MACRO_RANGES = ["1N", "3N", "5N", "10N", "Tất cả"]
FED_COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#a78bfa", "#f472b6"]


def _series_df(entry: dict) -> tuple[pd.DataFrame, bool]:
    vals = entry.get("values") or []
    ohlc = any(len(v) >= 5 for v in vals)
    if ohlc:
        df = pd.DataFrame([v[:5] for v in vals if len(v) >= 5], columns=["date", "open", "high", "low", "close"])
    else:
        df = pd.DataFrame([v[:2] for v in vals if len(v) >= 2 and v[1] is not None], columns=["date", "close"])
    if df.empty:
        return df, ohlc
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.dropna(subset=["date", "close"]).set_index("date").sort_index(), ohlc


BOND_TENORS = {"2N": "series_2y", "10N": "series_10y", "30N": "series"}
BOND_COLORS = ["#4cc9f0", "#4361ee", "#f72585", "#e63946", "#80ed99", "#2a9d8f", "#ffbe0b", "#fb8500", "#9d4edd"]


def _bond_card(bonds):
    with st.container(border=True, key="card_macro_bond"):
        st.subheader("🏦 Lợi suất trái phiếu chính phủ")
        if not (bonds or {}).get("series"):
            _missing("bond_yields.json", "Cập nhật dữ liệu (update_data)")
            return
        st.caption(f"Nguồn: TradingView (TVC) · dữ liệu theo tuần · Cập nhật lần cuối: {bonds.get('updated_at', '–')}")
        t1, t2 = st.columns([2, 3], vertical_alignment="bottom")
        tenor = t1.segmented_control("Kỳ hạn", list(BOND_TENORS), default="30N", key="macro_bond_tenor") or "30N"
        rng = t2.segmented_control("Khoảng", MACRO_RANGES, default="5N", key="macro_bond_rng") or "5N"
        series = bonds.get(BOND_TENORS[tenor]) or {}
        if not series:
            st.info(f"Chưa có dữ liệu kỳ hạn {tenor}. Chạy workflow 'Cập nhật dữ liệu' để lấy.")
            return
        labels = {k: v.get("label", k) for k, v in series.items()}
        picked = st.multiselect("Quốc gia", list(labels), default=list(labels), format_func=labels.get,
                                key=f"macro_bond_pick_{tenor}")
        lines, rows = [], []
        for n, k in enumerate(picked):
            d = pd.DataFrame(series[k].get("data") or [], columns=["date", "y"])
            if d.empty:
                continue
            d["date"] = pd.to_datetime(d["date"], errors="coerce")
            d = d.dropna().set_index("date").sort_index()
            rows.append({"Quốc gia": labels[k], "Lợi suất (%)": d["y"].iloc[-1],
                         "Thay đổi 4 tuần (điểm %)": d["y"].iloc[-1] - d["y"].iloc[-5] if len(d) > 4 else None,
                         "Ngày": d.index[-1].strftime("%d/%m/%Y")})
            lines.append(ui.tv_line(_clip_years(d, rng)["y"], BOND_COLORS[n % len(BOND_COLORS)], labels[k], 1.8, dec=3))
        if not rows:
            st.info("Chọn ít nhất một quốc gia.")
            return
        ui.tv_chart(f"Lợi suất {tenor.replace('N', ' năm')} (%)", [{"weight": 1, "series": lines}], height=460)
        tbl = pd.DataFrame(rows).sort_values("Lợi suất (%)", ascending=False)
        st.dataframe(tbl.style.format({"Lợi suất (%)": "{:.3f}", "Thay đổi 4 tuần (điểm %)": "{:+.3f}"}, na_rep="–"),
                     hide_index=True, width="stretch")


def _vnindex_card(vnindex: pd.DataFrame):
    if vnindex.empty:
        return
    with st.container(border=True, key="card_macro_vnindex"):
        st.subheader("📈 VN-Index")
        c = vnindex.sort_values("date")["close"].astype(float)
        summary = f"{c.iloc[-1]:,.2f} ({_pct(c.iloc[-1], c.iloc[-2])} so với phiên trước)" if len(c) > 1 else f"{c.iloc[-1]:,.2f}"
        st.caption(f"Nguồn: dữ liệu giá của dashboard · nến + khối lượng · Đóng cửa gần nhất: {summary}")
        frame = st.segmented_control("Khung", ["Ngày", "Tuần"], default="Ngày", key="macro_vn_frame") or "Ngày"
        ohlcv = engine.ohlcv_for(vnindex, "VNINDEX", "week" if frame == "Tuần" else "day")
        if ohlcv.empty:
            st.info("Không có dữ liệu nến cho VN-Index.")
            return
        ui.price_chart(ohlcv, f"VN-Index — {frame}")


def _indicator_card(macro: dict):
    series, groups = macro.get("series") or {}, macro.get("groups") or {}
    with st.container(border=True, key="card_macro_detail"):
        st.subheader("🌐 Xem chi tiết 1 chỉ số")
        st.caption(f"Nguồn: FRED (Mỹ) · World Bank (VN) · yfinance (tỷ giá & hàng hoá) · "
                   f"Cập nhật lần cuối: {macro.get('updated_at', '–')}")
        group_names = [g for g, ks in groups.items() if any(k in series for k in ks)] or sorted(
            {s.get("group", "Khác") for s in series.values()})
        c1, c2, c3 = st.columns([2, 3, 2], vertical_alignment="bottom")
        group = c1.selectbox("Nhóm", group_names, key="macro_group")
        keys = [k for k in groups.get(group, []) if k in series] or [k for k, s in series.items() if s.get("group") == group]
        key = c2.selectbox("Chỉ số", keys, format_func=lambda k: series[k].get("label", k), key=f"macro_key_{group}")
        rng = c3.segmented_control("Khoảng", MACRO_RANGES, default="Tất cả", key="macro_rng") or "Tất cả"
        if not key:
            return
        entry = series[key]
        df, ohlc = _series_df(entry)
        if df.empty:
            st.info("Chỉ số này chưa có dữ liệu.")
            return
        last = df["close"].iloc[-1]
        prev = df["close"].iloc[-2] if len(df) > 1 else None
        freq = {"daily": "Ngày", "monthly": "Tháng", "yearly": "Năm", "quarterly": "Quý"}.get(entry.get("freq"), "–")
        ui.kpi_row([
            ("Giá trị mới nhất", _fmt_num(last), None),
            ("Kỳ dữ liệu", df.index[-1].strftime("%d/%m/%Y"), f"Tần suất: {freq}"),
            ("So với kỳ trước", _pct(last, prev) if prev else "–", None),
            ("Số điểm dữ liệu", f"{len(df):,}", None),
        ])
        view = _clip_years(df, rng)
        if entry.get("freq") != "yearly" or ohlc:
            ttl = entry.get("label", key)
            ui.tv_chart(ttl, [{"weight": 1, "series": [ui.tv_candles(view, "") if ohlc else ui.tv_line(view["close"], BLUE, ttl, 2, dec=3)]}], height=420)
        else:
            view = _clip_years(df, rng)
            fig = go.Figure()
            if ohlc:
                fig.add_trace(go.Candlestick(x=view.index, open=view["open"], high=view["high"], low=view["low"],
                                             close=view["close"], name=entry.get("label", key),
                                             increasing_line_color=GREEN, decreasing_line_color=RED))
            elif entry.get("freq") == "yearly":
                fig.add_trace(go.Bar(x=view.index.year, y=view["close"], name=entry.get("label", key), marker_color=BLUE))
            else:
                fig.add_trace(go.Scatter(x=view.index, y=view["close"], mode="lines", name=entry.get("label", key),
                                         line=dict(color=BLUE, width=2)))
            fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), xaxis_rangeslider_visible=False,
                              showlegend=False, hovermode="x unified")
            _style_axes(fig, weekend_gaps=False)
            st.plotly_chart(fig, width="stretch")
        if entry.get("description"):
            st.caption(entry["description"])


def _fed_card(macro: dict):
    proj = macro.get("fed_projections") or {}
    if not proj:
        return
    with st.container(border=True, key="card_macro_fed"):
        st.subheader("🏛️ Dự báo kinh tế của Fed (Summary of Economic Projections)")
        st.caption("Mỗi lần họp FOMC (thường 4 lần/năm: tháng 3, 6, 9, 12) Fed công bố một bộ dự báo mới — "
                   "biểu đồ so sánh các lần công bố gần nhất để thấy dự báo đang thay đổi ra sao.")
        cols = st.columns(len(proj))
        for col, (k, entry) in zip(cols, proj.items()):
            vint = entry.get("vintages") or []
            if not vint:
                continue
            years = sorted({y for v in vint for y in v.get("data", {})})
            fig = go.Figure()
            for i, v in enumerate(vint):
                fig.add_trace(go.Bar(x=years, y=[v["data"].get(y) for y in years], name=v.get("vintage", ""),
                                     marker_color=FED_COLORS[i % len(FED_COLORS)]))
            fig.update_layout(barmode="group", height=320, margin=dict(l=10, r=10, t=10, b=10),
                              legend=dict(orientation="h", y=-0.15), yaxis_title="%")
            _style_axes(fig, weekend_gaps=False)
            with col:
                st.markdown(f"**{entry.get('label', k)}**")
                st.plotly_chart(fig, width="stretch", key=f"fed_{k}")
                st.caption("Nguồn: FOMC Summary of Economic Projections, qua FRED")


def render_macro(macro, bonds, vnindex: pd.DataFrame):
    st.header("🌐 Dữ liệu vĩ mô")
    _bond_card(bonds)
    _vnindex_card(vnindex)
    if macro and macro.get("series"):
        _indicator_card(macro)
        _fed_card(macro)
    else:
        _missing("macro_data.json", "Cập nhật dữ liệu (update_data)")


# ----------------------------------------------------------------------------
# 📅 Lịch kinh tế
# ----------------------------------------------------------------------------
VN_TZ_NAME = "Asia/Ho_Chi_Minh"
WEEKDAYS = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ nhật"]
COUNTRY_NAMES = {"VN": "Việt Nam", "US": "Mỹ", "CN": "Trung Quốc", "EU": "Khu vực euro", "JP": "Nhật Bản",
                 "GB": "Anh", "DE": "Đức", "KR": "Hàn Quốc"}
IMPORTANCE = {1: "🔴 Cao", 0: "🟠 Trung bình", -1: "⚪ Thấp"}
CAL_RANGES = ["Hôm nay", "Ngày mai", "7 ngày tới", "30 ngày tới", "7 ngày qua"]


def _flag(code: str) -> str:
    """Mã ISO-2 -> emoji cờ (ký tự khu vực). Không hợp lệ thì trả nguyên mã."""
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in code) if len(code) == 2 and code.isalpha() and code.isupper() else code


def _cal_val(v, unit: str, scale: str) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "–"
    if isinstance(v, str):
        return v
    txt = f"{v:,.3f}".rstrip("0").rstrip(".")
    return f"{txt}{scale or ''}{'%' if unit == '%' else (' ' + unit if unit else '')}"


def _vs_forecast(actual, forecast) -> str:
    """So thực tế với dự báo — chỉ nêu cao/thấp hơn, không đánh giá tốt/xấu (tuỳ chỉ tiêu)."""
    if not isinstance(actual, (int, float)) or not isinstance(forecast, (int, float)):
        return ""
    if actual > forecast:
        return "▲ cao hơn"
    if actual < forecast:
        return "▼ thấp hơn"
    return "＝ đúng dự báo"


def render_calendar(cal):
    st.header("📅 Lịch kinh tế")
    events = (cal or {}).get("events") or []
    if not events:
        _missing("calendar_data.json", "Cập nhật lịch kinh tế (update_calendar)")
        return
    df = pd.DataFrame(events)
    df["dt"] = pd.to_datetime(df["date"], utc=True, errors="coerce").dt.tz_convert(VN_TZ_NAME)
    df = df.dropna(subset=["dt"]).sort_values(["dt", "importance"], ascending=[True, False])
    now = pd.Timestamp.now(tz=VN_TZ_NAME)
    today = now.normalize()

    st.caption(f"Nguồn: TradingView (không chính thức) · Giờ Việt Nam (GMT+7) · Cập nhật lần cuối: {cal.get('updated_at', '–')} · "
               "Số liệu chỉ để tham khảo, có thể trễ hoặc sai khác so với nguồn gốc.")

    countries = [c for c in COUNTRY_NAMES if c in set(df["country"])] + sorted(set(df["country"]) - set(COUNTRY_NAMES))
    c1, c2 = st.columns([3, 2], vertical_alignment="bottom")
    rng = c1.segmented_control("Khoảng thời gian", CAL_RANGES, default="7 ngày tới", key="cal_rng") or "7 ngày tới"
    imp_pick = c2.pills("Mức quan trọng", ["Cao", "Trung bình", "Thấp"], selection_mode="multi",
                        default=["Cao", "Trung bình"], key="cal_imp")
    picked = st.multiselect("Quốc gia", countries, default=[c for c in ["VN", "US"] if c in countries] or countries[:2],
                            format_func=lambda c: f"{_flag(c)} {COUNTRY_NAMES.get(c, c)}", key="cal_countries")

    lo, hi = {
        "Hôm nay": (today, today + pd.Timedelta(days=1)),
        "Ngày mai": (today + pd.Timedelta(days=1), today + pd.Timedelta(days=2)),
        "7 ngày tới": (today, today + pd.Timedelta(days=7)),
        "30 ngày tới": (today, today + pd.Timedelta(days=30)),
        "7 ngày qua": (today - pd.Timedelta(days=7), today + pd.Timedelta(days=1)),
    }[rng]
    imp_map = {"Cao": 1, "Trung bình": 0, "Thấp": -1}
    imp_vals = {imp_map[x] for x in (imp_pick or [])}
    view = df[(df["dt"] >= lo) & (df["dt"] < hi) & df["country"].isin(picked) & df["importance"].isin(imp_vals)]

    upcoming = df[(df["dt"] >= now) & (df["importance"] == 1) & df["country"].isin(picked)]
    nxt = upcoming.iloc[0] if not upcoming.empty else None
    ui.kpi_row([
        ("Số sự kiện (theo bộ lọc)", f"{len(view):,}", None),
        ("Mức quan trọng cao", f"{int((view['importance'] == 1).sum()):,}", "Trong bộ lọc hiện tại"),
        ("Đã công bố", f"{int(view['actual'].notna().sum()):,}", "Có số liệu thực tế"),
        ("Sự kiện lớn kế tiếp", f"{nxt['dt']:%d/%m %H:%M}" if nxt is not None else "–",
         f"{_flag(nxt['country'])} {nxt['title']}" if nxt is not None else "Không có trong bộ lọc quốc gia đã chọn"),
    ])
    if view.empty:
        st.info("Không có sự kiện nào khớp bộ lọc. Thử mở rộng khoảng thời gian, thêm quốc gia hoặc mức quan trọng.")
        return

    for day, g in view.groupby(view["dt"].dt.normalize(), sort=True):
        tag = " · Hôm nay" if day == today else ""
        st.subheader(f"{WEEKDAYS[day.weekday()]}, {day:%d/%m/%Y}{tag}")
        tbl = pd.DataFrame({
            "Giờ": g["dt"].dt.strftime("%H:%M"),
            "Quốc gia": [f"{_flag(c)} {c}" for c in g["country"]],
            "Sự kiện": [f"{t} ({p})" if p else t for t, p in zip(g["title"], g["period"])],
            "Mức": g["importance"].map(IMPORTANCE),
            "Thực tế": [_cal_val(a, u, s) for a, u, s in zip(g["actual"], g["unit"], g["scale"])],
            "Dự báo": [_cal_val(a, u, s) for a, u, s in zip(g["forecast"], g["unit"], g["scale"])],
            "Kỳ trước": [_cal_val(a, u, s) for a, u, s in zip(g["previous"], g["unit"], g["scale"])],
            "So với dự báo": [_vs_forecast(a, f) for a, f in zip(g["actual"], g["forecast"])],
        })
        st.dataframe(tbl.style.apply(ui._zebra, axis=None), hide_index=True, width="stretch",
                     height=min(36 * (len(tbl) + 1) + 3, 520),
                     column_config={"Sự kiện": st.column_config.TextColumn("Sự kiện", width="large"),
                                    "Giờ": st.column_config.TextColumn("Giờ", width="small")})
