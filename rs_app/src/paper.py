"""Trang Giao dịch giả lập (paper trading): đặt lệnh giả lập, danh mục, lịch sử, hiệu suất. Logic ở paper_engine.py."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import engine, paper_engine as pe, paper_store, ui

VND = "{:,.0f}"


def _vnd(x: float) -> str:
    return f"{x:,.0f} đ"


def _cash_input(label: str, key: str, container=None) -> int:
    """Ô nhập vốn tự do (đồng), kèm dòng đọc lại số tiền cho dễ nhìn."""
    box = container or st
    v = box.number_input(label, min_value=pe.MIN_START_CASH, max_value=pe.MAX_START_CASH,
                         value=pe.DEFAULT_START_CASH, step=10_000_000, format="%d", key=key)
    box.caption(f"= {_vnd(v)}" + (f" (~{v / 1e9:,.2f} tỷ)" if v >= 1e9 else f" (~{v / 1e6:,.0f} triệu)"))
    return int(v)


def _midsession(date_str: str, now: datetime) -> bool:
    return date_str == f"{now:%Y-%m-%d}" and now.weekday() < 5 and 9 <= now.hour < 15


def render(stocks: pd.DataFrame, vnindex: pd.DataFrame, username: str, scores: pd.DataFrame, quotes: pd.DataFrame) -> None:
    st.header("🎮 Giao dịch giả lập")
    st.caption("Tài khoản giả lập, không dùng tiền thật. Lệnh khớp ngay theo giá đóng cửa của phiên mới nhất trong dữ liệu.")
    if not paper_store.auth.redis_enabled():
        st.warning("Chưa bật Redis (Upstash): dữ liệu được lưu file cục bộ và có thể mất khi máy chủ khởi động lại.")

    now = datetime.now(engine.VN_TZ)
    sessions = pe.sessions_from(vnindex, stocks)
    market_last = quotes["last_date"].max()
    date_str = f"{pd.Timestamp(market_last):%Y-%m-%d}"

    acct = paper_store.get_account(username)
    if acct is None:
        _render_create(username, f"{now:%Y-%m-%d}")
        return

    trades = paper_store.get_trades(username)
    start_cash = acct["start_cash"]
    summ = pe.account_summary(start_cash, trades, quotes)

    ui.kpi_row([
        ("Tổng tài sản", _vnd(summ["equity"]), f"Vốn ban đầu {_vnd(start_cash)}"),
        ("Tiền mặt", _vnd(summ["cash"]), None),
        ("Giá trị cổ phiếu", _vnd(summ["market_value"]), "Theo giá đóng cửa phiên mới nhất"),
        ("Lãi/lỗ tổng", _vnd(summ["pnl"]), f"{summ['pnl_pct']:+.2f}% so với vốn ban đầu"),
    ])
    st.caption(f"Giá theo phiên {pd.Timestamp(market_last):%d/%m/%Y}"
               + (" · đang giữa phiên, giá là nến CHƯA chốt" if _midsession(date_str, now) else ""))

    t_order, t_port, t_hist, t_perf = st.tabs(["Đặt lệnh", "Danh mục", "Lịch sử lệnh", "Hiệu suất"])
    with t_order:
        _render_order(username, trades, summ, scores, quotes, sessions, date_str, now)
    with t_port:
        _render_portfolio(trades, quotes, sessions)
    with t_hist:
        _render_history(trades)
    with t_perf:
        _render_perf(start_cash, trades, stocks, vnindex, sessions, summ)

    with st.expander("⚙️ Đặt lại tài khoản"):
        st.caption("Xoá toàn bộ lệnh và bắt đầu lại với số vốn mới. Không hoàn tác được.")
        c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
        cash = _cash_input("Vốn mới (đồng)", "pt_reset_cash", container=c1)
        sure = c1.checkbox("Tôi hiểu toàn bộ lệnh hiện tại sẽ bị xoá", key="pt_reset_sure")
        if c2.button("Đặt lại", disabled=not sure, width="stretch", key="pt_reset_btn"):
            ok, msg = pe.validate_start_cash(cash)
            if not ok:
                st.error(msg)
                return
            paper_store.create_account(username, cash, f"{now:%Y-%m-%d}")
            st.toast("Đã đặt lại tài khoản")
            st.rerun()


def _render_create(username: str, today: str) -> None:
    st.info("Bạn chưa có tài khoản giao dịch giả lập. Chọn số vốn ban đầu để bắt đầu.")
    cash = _cash_input("Vốn ban đầu (đồng)", "pt_new_cash")
    st.caption(f"Quy tắc: lô {pe.LOT} cổ phiếu · phí {pe.FEE_RATE:.2%} mỗi chiều · thuế bán {pe.SELL_TAX_RATE:.2%} · "
               f"mua xong phải qua T+{pe.SETTLE_SESSIONS} mới bán được · không bán khống, không margin.")
    if st.button("Tạo tài khoản", type="primary", key="pt_create_btn"):
        ok, msg = pe.validate_start_cash(cash)
        if not ok:
            st.error(msg)
            return
        paper_store.create_account(username, cash, today)
        st.rerun()


def _render_order(username, trades, summ, scores, quotes, sessions, date_str, now) -> None:
    rs_map = dict(zip(scores["ticker"], scores["RS"])) if len(scores) else {}
    ind_map = dict(zip(scores["ticker"], scores["industry"])) if len(scores) else {}
    tickers = sorted(quotes.index)
    c1, c2 = st.columns([2, 1])
    tk = c1.selectbox("Mã", tickers, index=None, placeholder="Gõ hoặc chọn mã...", key="pt_ticker")
    side_label = c2.radio("Chiều lệnh", ["Mua", "Bán"], horizontal=True, key="pt_side")
    if not tk:
        return
    side = "BUY" if side_label == "Mua" else "SELL"
    q = quotes.loc[tk]
    price = pe.to_vnd(q["close"])
    chg = (q["close"] / q["prev_close"] - 1) * 100 if pd.notna(q["prev_close"]) and q["prev_close"] else None
    ok_trade, why = pe.check_tradable(q, quotes["last_date"].max())

    pos, _ = pe.positions(trades)
    held = pos.get(tk, {}).get("qty", 0)
    sellable = pe.sellable_qty(trades, tk, sessions)

    st.markdown(f"**{tk}** · {ind_map.get(tk, '')} · RS {int(rs_map[tk]) if tk in rs_map else '–'}")
    ui.kpi_row([
        ("Giá khớp", _vnd(price), f"Đóng cửa phiên {pd.Timestamp(q['last_date']):%d/%m/%Y}"),
        ("% 1 phiên", f"{chg:+.2f}%" if chg is not None else "–", None),
        ("Đang nắm", f"{held:,}", None),
        ("Bán được ngay", f"{sellable:,}", f"Đã qua T+{pe.SETTLE_SESSIONS}"),
    ])
    if not ok_trade:
        st.warning(why)

    max_buy = int(summ["cash"] // (price * (1 + pe.FEE_RATE)) // pe.LOT * pe.LOT) if price > 0 else 0
    qty = st.number_input("Số lượng (cổ phiếu)", min_value=0, step=pe.LOT, value=pe.LOT, key="pt_qty",
                          help=f"Mua tối đa khoảng {max_buy:,} cổ phiếu với tiền mặt hiện có.")
    value = qty * price
    fee, tax = pe.calc_costs(side, value)
    total = value + fee if side == "BUY" else value - fee - tax
    st.caption(f"Giá trị {_vnd(value)} · phí {_vnd(fee)}" + (f" · thuế {_vnd(tax)}" if side == "SELL" else "")
               + f" · {'cần' if side == 'BUY' else 'nhận về'} **{_vnd(total)}**")

    if st.button(f"Đặt lệnh {side_label.lower()} {tk}", type="primary", disabled=not ok_trade or qty <= 0, key="pt_submit"):
        if len(trades) >= pe.MAX_TRADES:
            st.error(f"Đã đủ {pe.MAX_TRADES} lệnh. Hãy đặt lại tài khoản để tiếp tục.")
            return
        ok, msg = pe.validate_order(side, int(qty), price, summ["cash"], held, sellable)
        if not ok:
            st.error(msg)
            return
        trade = pe.make_trade(len(trades) + 1, tk, side, int(qty), price, date_str, f"{now:%Y-%m-%d %H:%M:%S}")
        ok, msg = paper_store.add_trade(username, trade, expected_len=len(trades))
        if not ok:
            st.error(msg)
            return
        st.toast(f"Đã {side_label.lower()} {int(qty):,} {tk} giá {_vnd(price)}")
        st.rerun()


def _render_portfolio(trades, quotes, sessions) -> None:
    tbl = pe.portfolio_table(trades, quotes, sessions)
    if tbl.empty:
        st.info("Chưa có cổ phiếu nào trong danh mục.")
        return
    styler = tbl.style.format({"Số lượng": "{:,}", "Bán được": "{:,}", "Giá vốn TB": VND, "Giá hiện tại": VND,
                               "Giá trị": VND, "Lãi/lỗ": "{:+,.0f}", "% lãi/lỗ": "{:+.2f}%"})
    styler = ui._cellmap(styler, ui._fg_sign, ["Lãi/lỗ", "% lãi/lỗ"])
    st.dataframe(styler, hide_index=True, width="stretch", column_config={"Mã": ui.CODE_COLUMN})
    st.caption("Giá vốn trung bình đã gồm phí mua. Lãi/lỗ chưa trừ phí và thuế bán sẽ phát sinh khi bán.")


def _render_history(trades) -> None:
    if not trades:
        st.info("Chưa có lệnh nào.")
        return
    df = pd.DataFrame(trades)
    df["Chiều"] = df["side"].map({"BUY": "Mua", "SELL": "Bán"})
    df["Giá trị"] = df["qty"] * df["price"]
    out = df.rename(columns={"id": "#", "date": "Phiên", "ts": "Đặt lúc", "ticker": "Mã", "qty": "Số lượng",
                             "price": "Giá", "fee": "Phí", "tax": "Thuế"})
    out = out[["#", "Phiên", "Đặt lúc", "Mã", "Chiều", "Số lượng", "Giá", "Giá trị", "Phí", "Thuế"]].iloc[::-1]
    st.dataframe(out.style.format({"Số lượng": "{:,}", "Giá": VND, "Giá trị": VND, "Phí": VND, "Thuế": VND}),
                 hide_index=True, width="stretch", column_config={"Mã": ui.CODE_COLUMN})


def _render_perf(start_cash, trades, stocks, vnindex, sessions, summ) -> None:
    curve = pe.equity_curve(start_cash, trades, stocks, sessions)
    if curve.empty:
        st.info("Chưa có dữ liệu hiệu suất. Hãy đặt lệnh đầu tiên.")
        return
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=curve.index, y=curve.values, name="Tài khoản", mode="lines", line=dict(width=2)))
    vn = vnindex.sort_values("date").drop_duplicates("date", keep="last").set_index("date")["close"].reindex(curve.index).ffill()
    if vn.notna().any() and vn.iloc[0]:
        fig.add_trace(go.Scatter(x=vn.index, y=vn / vn.iloc[0] * start_cash, name="VNINDEX (quy đổi cùng vốn)",
                                 mode="lines", line=dict(width=1.5, dash="dot")))
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=20, b=10), legend=dict(orientation="h", y=1.1),
                      yaxis=dict(tickformat=",.0f"), hovermode="x unified")
    st.plotly_chart(fig, width="stretch")
    ui.kpi_row([
        ("Lãi đã chốt", _vnd(summ["realized"]), "Sau phí và thuế"),
        ("Lãi/lỗ chưa chốt", _vnd(summ["unrealized"]), "Theo giá đóng cửa phiên mới nhất"),
        ("Số lệnh", f"{len(trades):,}", None),
    ])
