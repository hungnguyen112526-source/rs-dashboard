"""Trang Giao dịch giả lập: đặt lệnh (kèm biểu đồ + thông tin mã), danh mục, lịch sử, hiệu suất.
Logic tính toán ở paper_engine.py, lưu trữ ở paper_store.py."""
from __future__ import annotations

import html
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import engine, paper_engine as pe, paper_store, ui

VND = "{:,.0f}"
UP, DOWN, REF, CEIL, FLOOR = "#16a34a", "#dc2626", "#d4a017", "#a855f7", "#06b6d4"
VIEWS = ["Đặt lệnh", "Danh mục", "Lịch sử", "Hiệu suất"]
KEEP_KEYS = ("pt_ticker", "pt_side", "pt_qty")      # giữ trạng thái khi chuyển qua lại giữa các chế độ xem

PT_CSS = """
<style>
.pt-quote { display:flex; align-items:baseline; flex-wrap:wrap; gap:.6rem; margin:.1rem 0 .5rem; }
.pt-code { font-size:1.5rem; font-weight:900; }
.pt-sub { opacity:.65; font-size:.85rem; }
.pt-price { font-size:2.1rem; font-weight:900; line-height:1.1; }
.pt-badge { display:inline-block; padding:.12rem .55rem; border-radius:999px; font-weight:800; font-size:.8rem;
  background:rgba(123,97,255,.16); }
.pt-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.45rem; margin:.5rem 0 .2rem; }
.pt-cell { border:1px solid color-mix(in srgb, currentColor 11%, transparent); border-radius:12px; padding:.4rem .6rem; }
.pt-cell small { display:block; opacity:.6; font-size:.7rem; letter-spacing:.02em; }
.pt-cell b { font-size:.95rem; }
.pt-rows { margin:.55rem 0 .2rem; }
.pt-row { display:flex; justify-content:space-between; gap:.8rem; padding:.28rem 0; font-size:.9rem;
  border-bottom:1px dashed color-mix(in srgb, currentColor 14%, transparent); }
.pt-row span:first-child { opacity:.68; }
.pt-row.total { font-weight:800; font-size:1rem; border-bottom:none; padding-top:.45rem; }
.pt-bar { height:.6rem; border-radius:999px; overflow:hidden; background:color-mix(in srgb, currentColor 10%, transparent); margin:.35rem 0 .15rem; }
.pt-bar > i { display:block; height:100%; background:linear-gradient(90deg,#6A57F2,#2fa8ff); }
.pt-range { position:relative; height:.4rem; border-radius:999px; background:color-mix(in srgb, currentColor 12%, transparent); margin:.55rem 0 .25rem; }
.pt-range > i { position:absolute; top:-.25rem; width:.9rem; height:.9rem; border-radius:50%; background:#6A57F2; transform:translateX(-50%); }
@media (max-width:640px) { .pt-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .pt-price { font-size:1.7rem; } }
</style>
"""


def _vnd(x: float) -> str:
    return f"{x:,.0f} đ"


def _k(x) -> str:
    """Giá trong CSV (nghìn đồng) -> chuỗi đồng."""
    return "–" if x is None or pd.isna(x) else f"{pe.to_vnd(x):,.0f}"


def _pct(x: float, d: int = 2) -> str:
    return f"{x:+.{d}f}%"


def _color(v: float) -> str:
    return UP if v > 0 else (DOWN if v < 0 else REF)


def _kpis(items: list, tag: str) -> None:
    """items: (nhãn, giá trị, ghi chú|None, delta|None). Khoá có tiền tố card_kpi để dùng chung CSS thẻ số của app."""
    cols = st.columns(len(items))
    for i, (col, (label, value, note, delta)) in enumerate(zip(cols, items)):
        with col.container(border=True, key=f"card_kpi_pt{tag}_{i}"):
            st.metric(label, value, delta=delta, help=note)


def _row(label: str, value: str, cls: str = "") -> str:
    return f'<div class="pt-row {cls}"><span>{label}</span><span>{value}</span></div>'


def _midsession(date_str: str, now: datetime) -> bool:
    return date_str == f"{now:%Y-%m-%d}" and now.weekday() < 5 and 9 <= now.hour < 15


# ----------------------------------------------------------------------------- callbacks (chạy trước khi vẽ lại trang)
def _goto_order(tk: str, side: str) -> None:
    st.session_state["pt_view"] = "Đặt lệnh"
    st.session_state["pt_ticker"] = tk
    st.session_state["pt_side"] = side
    st.session_state["pt_qty"] = pe.LOT


def _goto_from_select(side: str) -> None:
    tk = st.session_state.get("pt_act_tk")
    if tk:
        _goto_order(tk, side)


def _set_qty(q: int) -> None:
    st.session_state["pt_qty"] = int(q)


# ----------------------------------------------------------------------------- trang chính
def render(stocks: pd.DataFrame, vnindex: pd.DataFrame, username: str, scores: pd.DataFrame, quotes: pd.DataFrame) -> None:
    st.html(PT_CSS)
    for k in KEEP_KEYS:                                   # chống Streamlit xoá trạng thái widget khi chuyển chế độ xem
        if k in st.session_state:
            st.session_state[k] = st.session_state[k]
    st.session_state.setdefault("pt_view", VIEWS[0])
    st.session_state.setdefault("pt_side", "Mua")
    st.session_state.setdefault("pt_qty", pe.LOT)

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
    rs_map = dict(zip(scores["ticker"], scores["RS"])) if len(scores) else {}
    ind_map = dict(zip(scores["ticker"], scores["industry"])) if len(scores) else {}

    flash = st.session_state.pop("pt_flash", None)
    if flash:
        st.success(flash)
    _render_header(username, acct, summ, trades, quotes, date_str, market_last, now)

    view = st.segmented_control("Chế độ xem", VIEWS, key="pt_view", label_visibility="collapsed") or VIEWS[0]
    if view == "Đặt lệnh":
        _render_order(username, stocks, trades, summ, scores, quotes, sessions, rs_map, ind_map, date_str, now)
    elif view == "Danh mục":
        _render_portfolio(trades, summ, quotes, sessions, rs_map, ind_map)
    elif view == "Lịch sử":
        _render_history(trades)
    else:
        _render_perf(start_cash, trades, stocks, vnindex, sessions, summ)


# ----------------------------------------------------------------------------- tạo / đặt lại tài khoản
def _cash_input(label: str, key: str) -> int:
    v = st.number_input(label, min_value=pe.MIN_START_CASH, max_value=pe.MAX_START_CASH,
                        value=pe.DEFAULT_START_CASH, step=10_000_000, format="%d", key=key)
    st.caption(f"= {_vnd(v)}" + (f" (~{v / 1e9:,.2f} tỷ)" if v >= 1e9 else f" (~{v / 1e6:,.0f} triệu)"))
    return int(v)


def _render_create(username: str, today: str) -> None:
    st.header("🎮 Giao dịch giả lập")
    with st.container(border=True, key="pt_create"):
        st.markdown("#### Tạo tài khoản giao dịch giả lập")
        st.caption("Tập mua bán bằng vốn ảo theo giá thị trường mới nhất, không dùng tiền thật.")
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


def _render_header(username, acct, summ, trades, quotes, date_str, market_last, now) -> None:
    c1, c2 = st.columns([4, 1], vertical_alignment="center")
    c1.header("🎮 Giao dịch giả lập")
    with c2.popover("⚙️ Tài khoản", width="stretch"):
        st.markdown("**Đặt lại tài khoản**")
        st.caption("Xoá toàn bộ lệnh và bắt đầu lại với số vốn mới. Không hoàn tác được.")
        cash = _cash_input("Vốn mới (đồng)", "pt_reset_cash")
        sure = st.checkbox("Tôi hiểu toàn bộ lệnh hiện tại sẽ bị xoá", key="pt_reset_sure")
        if st.button("Đặt lại", disabled=not sure, width="stretch", key="pt_reset_btn"):
            ok, msg = pe.validate_start_cash(cash)
            if not ok:
                st.error(msg)
            else:
                paper_store.create_account(username, cash, f"{now:%Y-%m-%d}")
                st.session_state["pt_flash"] = "Đã đặt lại tài khoản."
                st.rerun()

    day = pe.day_pnl(trades, quotes, date_str)
    equity = summ["equity"]
    _kpis([
        ("Tổng tài sản", _vnd(equity), f"Vốn ban đầu {_vnd(acct['start_cash'])}", _pct(summ["pnl_pct"]) + " từ đầu"),
        ("Lãi/lỗ hôm nay", _vnd(day), "Theo biến động giá của số cổ phiếu đang nắm từ cuối phiên trước",
         _pct(day / equity * 100) if equity else None),
        ("Lãi/lỗ tổng", _vnd(summ["pnl"]), f"Đã chốt {_vnd(summ['realized'])} · chưa chốt {_vnd(summ['unrealized'])}", None),
        ("Sức mua", _vnd(summ["cash"]), "Tiền mặt khả dụng để mua", None),
    ], "h")
    st.html(f'<div class="pt-bar"><i style="width:{min(max(summ["stock_pct"], 0), 100):.1f}%"></i></div>'
            f'<div class="pt-sub">Cổ phiếu {summ["stock_pct"]:.1f}% ({_vnd(summ["market_value"])}) · '
            f'Tiền mặt {summ["cash_pct"]:.1f}% · giá theo phiên {pd.Timestamp(market_last):%d/%m/%Y}'
            + (" · <b>đang giữa phiên, giá là nến CHƯA chốt</b>" if _midsession(date_str, now) else "") + "</div>")


# ----------------------------------------------------------------------------- Đặt lệnh
def _render_order(username, stocks, trades, summ, scores, quotes, sessions, rs_map, ind_map, date_str, now) -> None:
    tickers = sorted(quotes.index)
    tk = st.selectbox("Mã cổ phiếu", tickers, index=None, placeholder="Gõ mã để tìm, ví dụ FPT...", key="pt_ticker",
                      format_func=lambda t: f"{t} · {ind_map.get(t, '')}")
    if not tk:
        st.info("Chọn một mã để xem biểu đồ, thông tin và đặt lệnh.")
        if len(scores):
            top = scores.sort_values("RS", ascending=False).head(6)
            st.caption("Gợi ý: các mã có điểm RS cao nhất")
            cols = st.columns(len(top))
            for col, (_, r) in zip(cols, top.iterrows()):
                col.button(f"{r['ticker']} · RS {int(r['RS'])}", key=f"pt_pick_{r['ticker']}", width="stretch",
                           on_click=_goto_order, args=(r["ticker"], "Mua"))
        return

    q = quotes.loc[tk]
    info = pe.stock_info(stocks[stocks["ticker"] == tk])
    price = pe.to_vnd(q["close"])
    ok_trade, why = pe.check_tradable(q, quotes["last_date"].max())
    pos, _ = pe.positions(trades)
    held = pos.get(tk, {}).get("qty", 0)
    sellable = pe.sellable_qty(trades, tk, sessions)

    left, right = st.columns([3, 2], gap="medium")
    with left:
        _render_quote(tk, info, ind_map, rs_map, stocks)
    with right:
        with st.container(border=True, key="pt_ticket"):
            _render_ticket(username, tk, price, ok_trade, why, trades, summ, pos, held, sellable, sessions, date_str, now)


def _render_quote(tk: str, info: dict, ind_map: dict, rs_map: dict, stocks: pd.DataFrame) -> None:
    close, prev = info.get("close"), info.get("prev_close")
    chg = (close / prev - 1) * 100 if prev else 0.0
    col = _color(chg)
    rs = rs_map.get(tk)
    st.html(f'<div class="pt-quote"><span class="pt-code">{html.escape(tk)}</span>'
            f'<span class="pt-sub">{html.escape(str(ind_map.get(tk, "")))}</span>'
            + (f'<span class="pt-badge">RS {int(rs)}</span>' if rs is not None and not pd.isna(rs) else "")
            + f'</div><div><span class="pt-price" style="color:{col}">{_k(close)}</span> '
              f'<span style="color:{col};font-weight:800">{_pct(chg)}</span> '
              f'<span class="pt-sub">phiên {pd.Timestamp(info["date"]):%d/%m/%Y}</span></div>')

    ohlcv = engine.ohlcv_for(stocks, tk, "day")
    if ohlcv.empty:
        st.info("Chưa có dữ liệu để vẽ biểu đồ.")
    else:
        ui.price_chart(ohlcv.tail(250), tk, height=380)

    ceil, floor = pe.price_limits(prev) if prev else (None, None)
    vol, avg = info.get("volume"), info.get("avg_vol20")
    vratio = f"{vol / avg:.1f}x" if avg and not pd.isna(avg) and avg > 0 else "–"
    hi, lo = info.get("hi52"), info.get("lo52")
    pos52 = (close - lo) / (hi - lo) * 100 if hi is not None and hi > lo else None

    def cell(label, value, color=None):
        style = f' style="color:{color}"' if color else ""
        return f'<div class="pt-cell"><small>{label}</small><b{style}>{value}</b></div>'

    cells = [
        cell("Mở cửa", _k(info.get("open"))), cell("Cao nhất", _k(info.get("high")), UP), cell("Thấp nhất", _k(info.get("low")), DOWN),
        cell("Khối lượng", f"{vol:,.0f}" if vol is not None and not pd.isna(vol) else "–"),
        cell("Tham chiếu", _k(prev), REF), cell("Trần (±7%)", f"{ceil:,.0f}" if ceil else "–", CEIL),
        cell("Sàn (±7%)", f"{floor:,.0f}" if floor else "–", FLOOR), cell("KL / TB 20 phiên", vratio),
        cell("Đỉnh 52 tuần", _k(hi)), cell("Đáy 52 tuần", _k(lo)),
        cell("Vị trí trong biên 52T", f"{pos52:.0f}%" if pos52 is not None else "–"),
        cell("Điểm RS", f"{int(rs)}" if rs is not None and not pd.isna(rs) else "–"),
    ]
    st.html('<div class="pt-grid">' + "".join(cells) + "</div>")
    if pos52 is not None:
        st.html(f'<div class="pt-range"><i style="left:{min(max(pos52, 0), 100):.0f}%"></i></div>'
                f'<div class="pt-sub" style="display:flex;justify-content:space-between"><span>Đáy 52T {_k(lo)}</span>'
                f'<span>Đỉnh 52T {_k(hi)}</span></div>')
    st.caption("Trần/sàn tính theo biên độ ±7% áp chung cho mọi mã (chưa phân biệt HOSE, HNX, UPCOM).")


def _render_ticket(username, tk, price, ok_trade, why, trades, summ, pos, held, sellable, sessions, date_str, now) -> None:
    side_label = st.segmented_control("Chiều lệnh", ["Mua", "Bán"], key="pt_side", label_visibility="collapsed") or "Mua"
    side = "BUY" if side_label == "Mua" else "SELL"
    max_buy = int(summ["cash"] // (price * (1 + pe.FEE_RATE)) // pe.LOT * pe.LOT) if price > 0 else 0
    base = max_buy if side == "BUY" else sellable

    st.html(_row("Giá khớp (đóng cửa phiên mới nhất)", f"<b>{price:,.0f} đ</b>")
            + _row("Sức mua", _vnd(summ["cash"])) + _row("Mua tối đa", f"{max_buy:,} cp")
            + _row("Đang nắm / bán được ngay", f"{held:,} / {sellable:,} cp"))
    if not ok_trade:
        st.warning(why)

    cols = st.columns(4)
    for col, pct in zip(cols, (25, 50, 75, 100)):
        target = base if pct == 100 else int(base * pct / 100 // pe.LOT * pe.LOT)
        col.button(f"{pct}%", key=f"pt_pct_{pct}", width="stretch", on_click=_set_qty, args=(target,),
                   disabled=base <= 0)
    qty = int(st.number_input("Số lượng (cổ phiếu)", min_value=0, step=pe.LOT, key="pt_qty"))

    value = qty * price
    fee, tax = pe.calc_costs(side, value)
    rows = _row("Giá trị lệnh", _vnd(value)) + _row("Phí", _vnd(fee))
    if side == "SELL":
        rows += _row("Thuế bán", _vnd(tax))
        total = value - fee - tax
        rows += _row("Tiền nhận về", _vnd(total))
        cash_after = summ["cash"] + total
        if held and qty:
            avg = pos[tk]["avg_cost"]
            est = total - avg * qty
            rows += _row("Lãi/lỗ ước tính của lệnh", f'<span style="color:{_color(est)}">{est:+,.0f} đ</span>')
        new_qty = max(held - qty, 0)
        new_cost_avg = pos[tk]["avg_cost"] if tk in pos else 0
    else:
        total = value + fee
        rows += _row("Tiền cần", _vnd(total))
        cash_after = summ["cash"] - total
        new_qty = held + qty
        old_cost = pos[tk]["cost"] if tk in pos else 0.0
        new_cost_avg = (old_cost + total) / new_qty if new_qty else 0
    equity = summ["equity"] if side == "SELL" else summ["equity"] - fee
    weight = new_qty * price / equity * 100 if equity else 0
    rows += _row("Tiền mặt sau lệnh", _vnd(cash_after))
    rows += _row("Tỷ trọng mã sau lệnh", f"{weight:.1f}%")
    if new_qty:
        rows += _row("Giá vốn TB sau lệnh", f"{new_cost_avg:,.0f} đ")
    if side == "BUY" and qty:
        d, est = pe.settle_date(date_str, sessions)
        rows += _row("Bán được từ", ("~" if est else "") + f"{pd.Timestamp(d):%d/%m/%Y} (T+{pe.SETTLE_SESSIONS})")
    st.html(f'<div class="pt-rows">{rows}</div>')

    if st.button(f"Đặt lệnh {side_label.lower()} {tk}", type="primary", width="stretch", key="pt_submit",
                 disabled=not ok_trade or qty <= 0):
        if len(trades) >= pe.MAX_TRADES:
            st.error(f"Đã đủ {pe.MAX_TRADES} lệnh. Hãy đặt lại tài khoản để tiếp tục.")
            return
        ok, msg = pe.validate_order(side, qty, price, summ["cash"], held, sellable)
        if not ok:
            st.error(msg)
            return
        _confirm(username, len(trades), tk, side, qty, price, date_str, f"{now:%Y-%m-%d %H:%M:%S}",
                 _row("Mã", tk) + _row("Chiều", side_label) + _row("Số lượng", f"{qty:,}") + _row("Giá khớp", _vnd(price))
                 + _row("Giá trị", _vnd(value)) + _row("Phí", _vnd(fee))
                 + (_row("Thuế bán", _vnd(tax)) if side == "SELL" else "")
                 + _row("Tiền cần" if side == "BUY" else "Tiền nhận về", _vnd(total), "total"))


@st.dialog("Xác nhận lệnh")
def _confirm(username: str, n_trades: int, tk: str, side: str, qty: int, price: float, date_str: str, ts: str,
             summary_html: str) -> None:
    st.html(f'<div class="pt-rows">{summary_html}</div>')
    c1, c2 = st.columns(2)
    if c1.button("Xác nhận", type="primary", width="stretch", key="pt_ok"):
        trade = pe.make_trade(n_trades + 1, tk, side, qty, price, date_str, ts)
        ok, msg = paper_store.add_trade(username, trade, expected_len=n_trades)
        if not ok:
            st.error(msg)
            return
        st.session_state["pt_flash"] = f"Đã {'mua' if side == 'BUY' else 'bán'} {qty:,} {tk} giá {_vnd(price)}."
        st.rerun()
    if c2.button("Huỷ", width="stretch", key="pt_cancel"):
        st.rerun()


# ----------------------------------------------------------------------------- Danh mục
def _donut(labels: list, values: list, title: str) -> go.Figure:
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.58, sort=False, textinfo="label+percent"))
    fig.update_layout(height=280, margin=dict(l=10, r=10, t=36, b=10), title=dict(text=title, x=0.02), showlegend=False)
    return fig


def _render_portfolio(trades, summ, quotes, sessions, rs_map, ind_map) -> None:
    tbl = pe.portfolio_table(trades, quotes, sessions, ind_map, rs_map)
    if tbl.empty:
        st.info("Chưa có cổ phiếu nào trong danh mục. Chuyển sang \"Đặt lệnh\" để mua cổ phiếu đầu tiên.")
        return

    c1, c2 = st.columns(2)
    labels = list(tbl["Mã"]) + ["Tiền mặt"]
    values = list(tbl["Giá trị"]) + [max(summ["cash"], 0)]
    c1.plotly_chart(_donut(labels, values, "Phân bổ tài sản"), width="stretch")
    by_ind = tbl.assign(Ngành=tbl["Ngành"].replace("", "Khác")).groupby("Ngành")["Giá trị"].sum().sort_values(ascending=False)
    c2.plotly_chart(_donut(list(by_ind.index), list(by_ind.values), "Cổ phiếu theo ngành"), width="stretch")

    styler = tbl.style.format({"Số lượng": "{:,}", "Bán được": "{:,}", "Giá vốn TB": VND, "Giá hiện tại": VND,
                               "% hôm nay": "{:+.2f}%", "Giá trị": VND, "Tỷ trọng %": "{:.1f}%", "Lãi/lỗ": "{:+,.0f}",
                               "% lãi/lỗ": "{:+.2f}%", "RS": "{:.0f}"}, na_rep="–")
    styler = ui._cellmap(styler, ui._fg_sign, ["% hôm nay", "Lãi/lỗ", "% lãi/lỗ"])
    st.dataframe(styler, hide_index=True, width="stretch", column_config={"Mã": ui.CODE_COLUMN})
    st.caption("Giá vốn trung bình đã gồm phí mua. Lãi/lỗ chưa trừ phí và thuế bán sẽ phát sinh khi bán. "
               "\"Bán hết từ\" là ngày toàn bộ cổ phiếu về tài khoản (dấu ~ là ngày ước tính, chưa tính ngày nghỉ lễ).")

    st.markdown("**Thao tác nhanh**")
    a, b, c = st.columns([2, 1, 1], vertical_alignment="bottom")
    a.selectbox("Mã trong danh mục", list(tbl["Mã"]), key="pt_act_tk", label_visibility="collapsed")
    b.button("Mua thêm", width="stretch", key="pt_act_buy", on_click=_goto_from_select, args=("Mua",))
    c.button("Bán", width="stretch", key="pt_act_sell", on_click=_goto_from_select, args=("Bán",))


# ----------------------------------------------------------------------------- Lịch sử
def _render_history(trades) -> None:
    if not trades:
        st.info("Chưa có lệnh nào.")
        return
    pnl = pe.realized_by_sell(trades)
    df = pd.DataFrame(trades)
    df["Chiều"] = df["side"].map({"BUY": "Mua", "SELL": "Bán"})
    df["Giá trị"] = df["qty"] * df["price"]
    df["Lãi/lỗ chốt"] = df["id"].map(pnl)
    df = df.rename(columns={"id": "#", "date": "Phiên", "ts": "Đặt lúc", "ticker": "Mã", "qty": "Số lượng",
                            "price": "Giá", "fee": "Phí", "tax": "Thuế"})
    df = df[["#", "Phiên", "Đặt lúc", "Mã", "Chiều", "Số lượng", "Giá", "Giá trị", "Phí", "Thuế", "Lãi/lỗ chốt"]]

    f1, f2 = st.columns([3, 2], vertical_alignment="bottom")
    pick = f1.multiselect("Lọc theo mã", sorted(df["Mã"].unique()), key="pt_hist_tk", placeholder="Tất cả các mã")
    side = f2.segmented_control("Chiều", ["Tất cả", "Mua", "Bán"], key="pt_hist_side", default="Tất cả") or "Tất cả"
    if pick:
        df = df[df["Mã"].isin(pick)]
    if side != "Tất cả":
        df = df[df["Chiều"] == side]

    st.caption(f"{len(df):,} lệnh · phí {_vnd(df['Phí'].sum())} · thuế {_vnd(df['Thuế'].sum())}"
               + (f" · lãi/lỗ đã chốt {df['Lãi/lỗ chốt'].sum():+,.0f} đ" if df["Lãi/lỗ chốt"].notna().any() else ""))
    out = df.iloc[::-1]
    styler = out.style.format({"Số lượng": "{:,}", "Giá": VND, "Giá trị": VND, "Phí": VND, "Thuế": VND,
                               "Lãi/lỗ chốt": "{:+,.0f}"}, na_rep="")
    styler = ui._cellmap(styler, ui._fg_sign, ["Lãi/lỗ chốt"])
    st.dataframe(styler, hide_index=True, width="stretch", column_config={"Mã": ui.CODE_COLUMN})
    st.download_button("⬇️ Tải CSV", out.to_csv(index=False).encode("utf-8-sig"), file_name="lich_su_lenh.csv",
                       mime="text/csv", key="pt_dl")


# ----------------------------------------------------------------------------- Hiệu suất
def _render_perf(start_cash, trades, stocks, vnindex, sessions, summ) -> None:
    curve = pe.equity_curve(start_cash, trades, stocks, sessions)
    if curve.empty:
        st.info("Chưa có dữ liệu hiệu suất. Hãy đặt lệnh đầu tiên.")
        return
    vn = vnindex.sort_values("date").drop_duplicates("date", keep="last").set_index("date")["close"].reindex(curve.index).ffill()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=curve.index, y=curve.values, name="Tài khoản", mode="lines", line=dict(width=2)))
    vn_ret = None
    if vn.notna().any() and vn.iloc[0]:
        fig.add_trace(go.Scatter(x=vn.index, y=vn / vn.iloc[0] * start_cash, name="VNINDEX (quy đổi cùng vốn)",
                                 mode="lines", line=dict(width=1.5, dash="dot")))
        vn_ret = (vn.iloc[-1] / vn.iloc[0] - 1) * 100
    fig.update_layout(height=340, margin=dict(l=10, r=10, t=20, b=10), legend=dict(orientation="h", y=1.1),
                      yaxis=dict(tickformat=",.0f"), hovermode="x unified")
    st.plotly_chart(fig, width="stretch")

    dd = (curve / curve.cummax() - 1) * 100
    figd = go.Figure(go.Scatter(x=dd.index, y=dd.values, fill="tozeroy", mode="lines", line=dict(width=1, color=DOWN),
                                name="Sụt giảm từ đỉnh (%)"))
    figd.update_layout(height=160, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(ticksuffix="%"), showlegend=False)
    st.plotly_chart(figd, width="stretch")

    stt = pe.trade_stats(trades)
    mdd = pe.max_drawdown(curve)
    fmt = lambda v, f: "–" if v is None else f.format(v)          # noqa: E731
    _kpis([
        ("Lợi nhuận", _pct(summ["pnl_pct"]), "Tổng tài sản so với vốn ban đầu", None),
        ("VNINDEX cùng kỳ", fmt(vn_ret, "{:+.2f}%"), "Từ ngày có lệnh đầu tiên", None),
        ("Hơn/kém VNINDEX", fmt(None if vn_ret is None else summ["pnl_pct"] - vn_ret, "{:+.2f} điểm %"), None, None),
        ("Sụt giảm lớn nhất", fmt(mdd, "{:.2f}%"), "Mức giảm sâu nhất từ đỉnh tài sản", None),
    ], "p1")
    _kpis([
        ("Lệnh bán có lãi", fmt(stt["win_rate"], "{:.0f}%"), f"Trên {stt['n_sell']} lệnh bán đã chốt", None),
        ("Lãi trung bình", fmt(stt["avg_win"], "{:+,.0f} đ"), "Mỗi lệnh bán có lãi", None),
        ("Lỗ trung bình", fmt(stt["avg_loss"], "{:+,.0f} đ"), "Mỗi lệnh bán lỗ", None),
        ("Phí + thuế đã trả", _vnd(stt["fees"] + stt["taxes"]), f"Phí {_vnd(stt['fees'])} · thuế {_vnd(stt['taxes'])}", None),
    ], "p2")
    if stt["profit_factor"] is not None:
        st.caption(f"Hệ số lãi/lỗ (tổng lãi chia tổng lỗ): {stt['profit_factor']:.2f}")
