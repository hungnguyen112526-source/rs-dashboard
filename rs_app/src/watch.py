"""Trang Theo dõi: danh sách mã riêng của từng người dùng, kèm ghi chú."""
from datetime import datetime

import pandas as pd
import streamlit as st

from src import auth, engine, ui


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


def render(stocks: pd.DataFrame, username: str, rs_map: dict, vol_day: pd.DataFrame) -> None:
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
        df, hide_index=True, width="stretch", key="wl_editor",
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
