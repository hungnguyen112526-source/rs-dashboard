"""Trang Theo dõi: danh sách mã riêng của từng người dùng, kèm ghi chú."""
from datetime import datetime

import pandas as pd
import streamlit as st

from src import auth, engine, pages_extra, ui


def toggle(ticker: str, username: str, key: str) -> None:
    """Ô tick trong cửa sổ biểu đồ: thêm/bỏ mã khỏi danh sách theo dõi."""
    items = auth.get_watchlist(username)
    have = any(i["ticker"] == ticker for i in items)
    want = st.checkbox(f"⭐ Theo dõi {ticker}", value=have, key=f"{key}_wl_{ticker}")
    if want == have:
        return
    if want and len(items) >= auth.MAX_WATCH:
        st.warning(f"Danh sách đã đủ {auth.MAX_WATCH} mã.")
        return
    items = [i for i in items if i["ticker"] != ticker]
    if want:
        items.append({"ticker": ticker, "note": "", "added": f"{datetime.now(engine.VN_TZ):%Y-%m-%d}"})
    auth.set_watchlist(username, items)
    st.toast(f"Đã {'thêm' if want else 'bỏ'} {ticker} {'vào' if want else 'khỏi'} danh sách theo dõi")


def render(stocks: pd.DataFrame, username: str, scores: pd.DataFrame, vol_day: pd.DataFrame, fin: dict | None = None) -> None:
    rs_map = dict(zip(scores["ticker"], scores["RS"])) if len(scores) else {}
    st.header("⭐ Danh sách theo dõi")
    if not auth.redis_enabled():
        st.warning("Chưa bật Redis (Upstash): danh sách được lưu file cục bộ và có thể mất khi máy chủ khởi động lại.")
    items = auth.get_watchlist(username)
    tickers = sorted(stocks["ticker"].unique())
    c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
    pick = c1.selectbox("Thêm mã", tickers, index=None, placeholder="Gõ hoặc chọn mã...", key="wl_add")
    if c2.button("➕ Thêm", width="stretch", disabled=not pick) and pick:
        if any(i["ticker"] == pick for i in items):
            st.toast(f"{pick} đã có trong danh sách")
        elif len(items) >= auth.MAX_WATCH:
            st.warning(f"Danh sách đã đủ {auth.MAX_WATCH} mã.")
        else:
            auth.set_watchlist(username, items + [{"ticker": pick, "note": "", "added": f"{datetime.now(engine.VN_TZ):%Y-%m-%d}"}])
            st.rerun()
    if not items:
        st.info("Chưa có mã nào. Thêm ở ô trên, hoặc mở biểu đồ một mã (ở trang Xếp hạng RS / Lọc KLGD) rồi tick **⭐ Theo dõi**.")
        return

    last = stocks.sort_values("date").groupby("ticker").tail(2)
    tiers = dict(zip(vol_day["Mã"], vol_day["Số mốc đạt"])) if len(vol_day) else {}
    rows = []
    for it in items:
        t = it["ticker"]
        g = last[last["ticker"] == t]
        px = g["close"].tolist()
        t_ = tiers.get(t)
        rows.append({"Mã": t, "Ngành": g["industry"].iloc[-1] if len(g) else None, "RS": rs_map.get(t),
                     "Giá đóng cửa": px[-1] if px else None,
                     "% 1 phiên": (px[-1] / px[-2] - 1) * 100 if len(px) > 1 and px[-2] else None,
                     "KLGD (Ngày)": "Đủ 4/4" if t_ == 4 else ("Gần đạt 3/4" if t_ == 3 else "Không đạt"),
                     "Ngày thêm": it.get("added", ""), "Ghi chú": it.get("note", ""), "Bỏ": False})
    df = pd.DataFrame(rows)
    st.caption(f"{len(df)}/{auth.MAX_WATCH} mã · sửa **Ghi chú** hoặc tick **Bỏ**, rồi bấm Lưu.")
    edited = st.data_editor(
        df, hide_index=True, width="stretch", key="wl_editor", height=min(36 * (len(df) + 1) + 3, 560),
        disabled=[c for c in df.columns if c not in ("Ghi chú", "Bỏ")],
        column_config={"Mã": ui.CODE_COLUMN, "RS": ui.RS_COLUMN,
                       "Giá đóng cửa": st.column_config.NumberColumn(format="%.2f"),
                       "% 1 phiên": st.column_config.NumberColumn(format="%+.2f%%"),
                       "Ghi chú": st.column_config.TextColumn(max_chars=300, width="large")})
    if st.button("💾 Lưu thay đổi", type="primary"):
        keep = edited[~edited["Bỏ"]]
        notes = dict(zip(keep["Mã"], keep["Ghi chú"].fillna("")))
        auth.set_watchlist(username, [{**i, "note": notes[i["ticker"]]} for i in items if i["ticker"] in notes])
        st.toast("Đã lưu danh sách theo dõi")
        st.rerun()

    # ---- Chi tiết từng mã trong danh sách ----
    st.divider()
    st.subheader("🔎 Chi tiết mã đang theo dõi")
    ticker = st.selectbox("Chọn mã", [i["ticker"] for i in items], key="wl_detail")
    note = next((i.get("note") for i in items if i["ticker"] == ticker), "")
    if note:
        st.caption(f"📝 Ghi chú: {note}")
    _detail(stocks, scores, fin or {}, ticker)


def _chg(close: pd.Series, n: int):
    return (close.iloc[-1] / close.iloc[-1 - n] - 1) * 100 if len(close) > n and close.iloc[-1 - n] else None


def _detail(stocks: pd.DataFrame, scores: pd.DataFrame, fin: dict, ticker: str) -> None:
    g = stocks[stocks["ticker"] == ticker].sort_values("date")
    if g.empty:
        st.info("Không có dữ liệu giá cho mã này.")
        return
    close, vol = g["close"].astype(float).reset_index(drop=True), g["volume"].astype(float).values
    res = engine._chain(vol)
    mas, tiers = res if res else ([None] * 4, 0)
    gtgd = float((close.values[-20:] * 1000.0 * vol[-20:]).mean()) / 1e9 if len(g) >= 20 else None
    r = scores[scores["ticker"] == ticker]
    rs = int(r["RS"].iloc[0]) if len(r) and pd.notna(r["RS"].iloc[0]) else None
    ch1 = _chg(close, 1)
    ui.kpi_row([
        ("Giá đóng cửa", f"{close.iloc[-1]:,.2f}", f"{ch1:+.2f}% so với phiên trước" if ch1 is not None else None),
        ("RS", f"{rs}" if rs else "–", f"Ngành: {g['industry'].iloc[-1]}"),
        ("Bộ lọc KLGD (Ngày)", f"{tiers}/4 mốc", f"TB{engine.VOL_WINDOWS[0]} < TB{engine.VOL_WINDOWS[1]} < TB{engine.VOL_WINDOWS[2]} < TB{engine.VOL_WINDOWS[3]}"),
        ("GTGD TB20", f"{gtgd:,.1f} tỷ" if gtgd else "–", "Giá trị giao dịch trung bình 20 phiên"),
    ])
    tab_chart, tab_over, tab_fin = st.tabs(["📈 Biểu đồ", "📊 Tổng quan", "📑 BCTC"])
    with tab_chart:
        frame = st.radio("Khung biểu đồ", ["Ngày", "Tuần"], horizontal=True, key=f"wl_tf_{ticker}")
        ohlcv = engine.ohlcv_for(stocks, ticker, "week" if frame == "Tuần" else "day")
        if ohlcv.empty:
            st.info("Không có dữ liệu giá cho mã này.")
        else:
            ui.price_chart(ohlcv, f"{ticker} — {frame}")
    with tab_over:
        c1, c2 = st.columns(2)
        hi, lo = close.tail(250).max(), close.tail(250).min()
        px = pd.DataFrame({"Chỉ tiêu": ["1 phiên", "5 phiên", "20 phiên", "60 phiên", "120 phiên", "250 phiên",
                                        "So với đỉnh 250 phiên", "So với đáy 250 phiên"],
                           "% thay đổi": [_chg(close, n) for n in (1, 5, 20, 60, 120, 250)]
                                         + [(close.iloc[-1] / hi - 1) * 100, (close.iloc[-1] / lo - 1) * 100]})
        c1.markdown("**Biến động giá**")
        c1.dataframe(px.style.apply(ui._zebra, axis=None).format({"% thay đổi": "{:+.1f}%"}, na_rep="–"),
                     hide_index=True, width="stretch")
        blocks = pd.DataFrame({"Khối": [f"Khối {i} (30 phiên)" for i in range(1, 5)],
                               "% thay đổi": [r[f"pct_block{i}"].iloc[0] if len(r) else None for i in range(1, 5)]})
        c2.markdown(f"**RS theo khối** · điểm thô {r['raw_score'].iloc[0]:.1f}" if len(r) else "**RS theo khối**")
        c2.dataframe(blocks.style.apply(ui._zebra, axis=None).format({"% thay đổi": "{:+.1f}%"}, na_rep="–"),
                     hide_index=True, width="stretch")
        st.markdown("**Khối lượng trung bình**")
        tb = pd.DataFrame([mas], columns=engine.TB_COLS)
        st.dataframe(tb.style.format("{:,.0f}", na_rep="–"), hide_index=True, width="stretch")
    with tab_fin:
        data = (fin.get("tickers") or {}).get(ticker)
        if not data:
            st.info("Chưa có dữ liệu báo cáo tài chính cho mã này.")
        else:
            pages_extra.fin_tabs(data, "quý" if fin.get("period", "quarter") == "quarter" else "năm")
