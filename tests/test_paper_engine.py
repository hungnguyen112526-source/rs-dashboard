"""Kiểm thử logic giao dịch giả lập (không cần Streamlit/Redis).
Chạy từ thư mục gốc repo:  python -m pytest tests -q
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rs_app"))

from src import paper_engine as pe  # noqa: E402

SESSIONS = ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]


def _buy(i, tk, qty, price, date):
    return pe.make_trade(i, tk, "BUY", qty, price, date, "ts")


def _sell(i, tk, qty, price, date):
    return pe.make_trade(i, tk, "SELL", qty, price, date, "ts")


def test_costs_buy_has_fee_no_tax_sell_has_tax():
    assert pe.calc_costs("BUY", 10_000_000) == (15_000, 0)
    assert pe.calc_costs("SELL", 10_000_000) == (15_000, 10_000)


def test_cash_after_buy_and_sell():
    t1 = _buy(1, "FPT", 100, 100_000, "2026-10-26")      # 10.000.000 + phí 15.000
    assert pe.cash_balance(1_000_000_000, [t1]) == 1_000_000_000 - 10_015_000
    t2 = _sell(2, "FPT", 100, 110_000, "2026-10-29")     # 11.000.000 - phí 16.500 - thuế 11.000
    assert pe.cash_balance(1_000_000_000, [t1, t2]) == 1_000_000_000 - 10_015_000 + 11_000_000 - 16_500 - 11_000


def test_average_cost_includes_fee_and_realized_pnl():
    trades = [_buy(1, "FPT", 100, 100_000, "2026-10-26"), _buy(2, "FPT", 100, 120_000, "2026-10-27")]
    pos, realized = pe.positions(trades)
    assert pos["FPT"]["qty"] == 200
    assert round(pos["FPT"]["avg_cost"]) == round((10_000_000 + 15_000 + 12_000_000 + 18_000) / 200)
    assert realized == 0
    trades.append(_sell(3, "FPT", 100, 130_000, "2026-10-30"))
    pos, realized = pe.positions(trades)
    assert pos["FPT"]["qty"] == 100
    basis = (22_033_000 / 200) * 100
    assert abs(realized - ((13_000_000 - 19_500 - 13_000) - basis)) < 1e-6


def test_fully_sold_position_disappears():
    trades = [_buy(1, "VNM", 100, 60_000, "2026-10-26"), _sell(2, "VNM", 100, 61_000, "2026-10-29")]
    pos, _ = pe.positions(trades)
    assert "VNM" not in pos


def test_t_plus_2_settlement():
    t = [_buy(1, "FPT", 100, 100_000, "2026-10-28")]
    assert pe.sellable_qty(t, "FPT", SESSIONS) == 100          # 28 -> 30 là T+2
    t = [_buy(1, "FPT", 100, 100_000, "2026-10-29")]
    assert pe.sellable_qty(t, "FPT", SESSIONS) == 0
    t = [_buy(1, "FPT", 100, 100_000, "2026-10-30")]
    assert pe.sellable_qty(t, "FPT", SESSIONS) == 0


def test_sellable_subtracts_sold_and_ignores_other_tickers():
    t = [_buy(1, "FPT", 300, 100_000, "2026-10-26"), _buy(2, "VNM", 500, 60_000, "2026-10-26"),
         _sell(3, "FPT", 100, 101_000, "2026-10-29"), _buy(4, "FPT", 200, 102_000, "2026-10-30")]
    assert pe.sellable_qty(t, "FPT", SESSIONS) == 200          # 300 đã về - 100 đã bán; 200 mới mua chưa về


def test_validate_buy():
    ok, _ = pe.validate_order("BUY", 100, 100_000, 20_000_000, 0, 0)
    assert ok
    ok, msg = pe.validate_order("BUY", 100, 100_000, 5_000_000, 0, 0)
    assert not ok and "Không đủ tiền" in msg
    ok, msg = pe.validate_order("BUY", 150, 100_000, 99_000_000, 0, 0)
    assert not ok and "bội số" in msg
    # đúng bằng số tiền cần (gồm phí) thì vẫn được
    need = 100 * 100_000 + pe.calc_costs("BUY", 100 * 100_000)[0]
    assert pe.validate_order("BUY", 100, 100_000, need, 0, 0)[0]
    assert not pe.validate_order("BUY", 100, 100_000, need - 1, 0, 0)[0]


def test_validate_sell():
    assert pe.validate_order("SELL", 100, 100_000, 0, 200, 100)[0]
    ok, msg = pe.validate_order("SELL", 200, 100_000, 0, 200, 100)
    assert not ok and "T+" in msg
    ok, msg = pe.validate_order("SELL", 300, 100_000, 0, 200, 200)
    assert not ok and "đang nắm" in msg
    assert not pe.validate_order("SELL", 0, 100_000, 0, 200, 200)[0]
    assert not pe.validate_order("BUY", 100, 0, 1e9, 0, 0)[0]
    # lô lẻ chỉ được bán khi bán hết
    assert pe.validate_order("SELL", 50, 100_000, 0, 50, 50)[0]
    assert not pe.validate_order("SELL", 50, 100_000, 0, 150, 150)[0]


def _stocks():
    rows = []
    for d, c in zip(SESSIONS, [10.0, 10.5, 11.0, 10.0, 12.0]):
        rows.append({"ticker": "AAA", "date": pd.Timestamp(d), "close": c, "volume": 1000})
    for d, c in zip(SESSIONS[:4], [20.0, 20.0, 20.0, 20.0]):     # BBB thiếu phiên cuối
        rows.append({"ticker": "BBB", "date": pd.Timestamp(d), "close": c, "volume": 1000})
    rows.append({"ticker": "CCC", "date": pd.Timestamp("2026-10-30"), "close": 5.0, "volume": 0})
    return pd.DataFrame(rows)


def test_quote_table_and_tradable():
    q = pe.quote_table(_stocks())
    assert q.at["AAA", "close"] == 12.0 and q.at["AAA", "prev_close"] == 10.0
    last = pd.Timestamp("2026-10-30")
    assert pe.check_tradable(q.loc["AAA"], last)[0]
    ok, msg = pe.check_tradable(q.loc["BBB"], last)
    assert not ok and "tạm ngưng" in msg
    ok, msg = pe.check_tradable(q.loc["CCC"], last)
    assert not ok and "khớp lệnh" in msg
    assert not pe.check_tradable(None, last)[0]


def test_portfolio_and_summary_use_vnd_units():
    q = pe.quote_table(_stocks())
    trades = [_buy(1, "AAA", 1000, 10_000, "2026-10-26")]       # mua 1000 cp giá 10.000 đ
    tbl = pe.portfolio_table(trades, q, SESSIONS)
    row = tbl.iloc[0]
    assert row["Giá hiện tại"] == 12_000 and row["Bán được"] == 1000
    assert row["Giá trị"] == 12_000_000
    s = pe.account_summary(100_000_000, trades, q)
    assert s["market_value"] == 12_000_000
    assert s["cash"] == 100_000_000 - 10_000_000 - 15_000
    assert abs(s["equity"] - (s["cash"] + 12_000_000)) < 1e-6
    assert abs(s["pnl"] - (s["equity"] - 100_000_000)) < 1e-6


def test_empty_account():
    q = pe.quote_table(_stocks())
    s = pe.account_summary(1e9, [], q)
    assert s["equity"] == 1e9 and s["pnl"] == 0 and pe.portfolio_table([], q, SESSIONS).empty
    assert pe.equity_curve(1e9, [], _stocks(), SESSIONS).empty


def test_equity_curve_tracks_prices_and_cash():
    trades = [_buy(1, "AAA", 1000, 10_500, "2026-10-27")]
    c = pe.equity_curve(100_000_000, trades, _stocks(), SESSIONS)
    assert list(c.index.strftime("%Y-%m-%d")) == SESSIONS[1:]
    cash = 100_000_000 - 10_500_000 - 15_750
    assert abs(c.iloc[0] - (cash + 1000 * 10_500)) < 1e-6      # 27/10 giá 10,5 -> đúng giá mua
    assert abs(c.iloc[-1] - (cash + 1000 * 12_000)) < 1e-6      # 30/10 giá 12


def test_sessions_from_prefers_vnindex():
    vn = pd.DataFrame({"date": pd.to_datetime(SESSIONS)})
    assert pe.sessions_from(vn) == SESSIONS
    assert pe.sessions_from(pd.DataFrame({"date": []}), _stocks())[0] == "2026-10-26"
