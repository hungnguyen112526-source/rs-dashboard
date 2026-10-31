"""
Giao dịch giả lập (paper trading) — logic thuần, KHÔNG phụ thuộc Streamlit (để kiểm thử được).

Nguyên tắc: chỉ lưu danh sách lệnh đã khớp; tiền mặt, vị thế, lãi lỗ đều TÍNH NGƯỢC từ danh sách đó.
Giá trong gia_lich_su_rs.csv tính bằng NGHÌN đồng (30,85 = 30.850 đ); mọi số tiền ở đây tính bằng đồng.
"""
from __future__ import annotations

from bisect import bisect_left

import pandas as pd

LOT = 100                       # lô chẵn
PRICE_UNIT = 1000               # CSV: nghìn đồng -> đồng
FEE_RATE = 0.0015               # phí môi giới mỗi chiều (0,15%)
SELL_TAX_RATE = 0.001           # thuế bán (0,1%)
SETTLE_SESSIONS = 2             # T+2: mua phiên T, bán được từ phiên T+2
DEFAULT_START_CASH = 1_000_000_000
MIN_START_CASH = 1_000_000            # vốn ban đầu tự nhập: từ 1 triệu
MAX_START_CASH = 1_000_000_000_000    # đến 1.000 tỷ
PRICE_BAND = 0.07                # biên độ trần/sàn giả định chung (chưa có cột sàn HOSE/HNX/UPCOM)
MAX_TRADES = 3000               # chặn để dữ liệu mỗi người không vượt giới hạn 1MB/lệnh của Redis REST


def validate_start_cash(value) -> tuple[bool, str]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False, "Vốn ban đầu không hợp lệ."
    if v < MIN_START_CASH:
        return False, f"Vốn tối thiểu {MIN_START_CASH:,.0f} đ."
    if v > MAX_START_CASH:
        return False, f"Vốn tối đa {MAX_START_CASH:,.0f} đ."
    return True, ""


def to_vnd(price_k: float) -> float:
    """Giá trong CSV (nghìn đồng) -> đồng."""
    return float(price_k) * PRICE_UNIT


def calc_costs(side: str, value: float) -> tuple[int, int]:
    """(phí, thuế) bằng đồng, làm tròn. Thuế chỉ tính khi bán."""
    fee = int(round(value * FEE_RATE))
    tax = int(round(value * SELL_TAX_RATE)) if side == "SELL" else 0
    return fee, tax


def make_trade(trade_id: int, ticker: str, side: str, qty: int, price: float, date_str: str, ts: str) -> dict:
    """price: đồng/cổ phiếu. date_str: ngày PHIÊN khớp (YYYY-MM-DD). ts: thời điểm đặt lệnh."""
    fee, tax = calc_costs(side, qty * price)
    return {"id": int(trade_id), "date": date_str, "ts": ts, "ticker": ticker.upper(), "side": side,
            "qty": int(qty), "price": float(price), "fee": fee, "tax": tax}


# ----------------------------------------------------------------------------- tính ngược từ danh sách lệnh
def cash_balance(start_cash: float, trades: list[dict]) -> float:
    cash = float(start_cash)
    for t in trades:
        value = t["qty"] * t["price"]
        cash += -(value + t["fee"]) if t["side"] == "BUY" else (value - t["fee"] - t["tax"])
    return cash


def positions(trades: list[dict]) -> tuple[dict, float]:
    """({mã: {qty, cost, avg_cost}}, lãi đã chốt). Giá vốn bình quân, đã gồm phí mua."""
    pos: dict[str, dict] = {}
    realized = 0.0
    for t in trades:
        p = pos.setdefault(t["ticker"], {"qty": 0, "cost": 0.0})
        value = t["qty"] * t["price"]
        if t["side"] == "BUY":
            p["qty"] += t["qty"]
            p["cost"] += value + t["fee"]
        else:
            basis = (p["cost"] / p["qty"] if p["qty"] else 0.0) * t["qty"]
            realized += (value - t["fee"] - t["tax"]) - basis
            p["qty"] -= t["qty"]
            p["cost"] -= basis
            if p["qty"] <= 0:
                p["qty"], p["cost"] = 0, 0.0
    out = {}
    for k, p in pos.items():
        if p["qty"] > 0:
            out[k] = {"qty": p["qty"], "cost": p["cost"], "avg_cost": p["cost"] / p["qty"]}
    return out, realized


def _session_index(sessions: list[str], date_str: str) -> int:
    return bisect_left(sessions, date_str)   # sessions là chuỗi ISO đã sắp xếp


def sellable_qty(trades: list[dict], ticker: str, sessions: list[str], settle: int = SETTLE_SESSIONS) -> int:
    """Số cổ phiếu bán được ngay: phần đã qua đủ `settle` phiên kể từ phiên mua, trừ số đã bán."""
    if not sessions:
        return 0
    last = len(sessions) - 1
    settled = sold = 0
    for t in trades:
        if t["ticker"] != ticker.upper():
            continue
        if t["side"] == "SELL":
            sold += t["qty"]
        elif last - _session_index(sessions, t["date"]) >= settle:
            settled += t["qty"]
    return max(0, settled - sold)


def validate_order(side: str, qty: int, price: float, cash: float, held: int, sellable: int) -> tuple[bool, str]:
    if side not in ("BUY", "SELL"):
        return False, "Chiều lệnh không hợp lệ."
    if qty <= 0:
        return False, "Số lượng phải lớn hơn 0."
    if price <= 0:
        return False, "Không có giá hợp lệ để khớp lệnh."
    if qty % LOT and not (side == "SELL" and qty == held):
        return False, f"Số lượng phải là bội số của {LOT} (lô chẵn)."
    fee, tax = calc_costs(side, qty * price)
    if side == "BUY":
        need = qty * price + fee
        if need > cash:
            return False, f"Không đủ tiền: cần {need:,.0f} đ, đang có {cash:,.0f} đ."
        return True, ""
    if qty > held:
        return False, f"Chỉ đang nắm {held:,} cổ phiếu."
    if qty > sellable:
        return False, f"Chỉ bán được {sellable:,} cổ phiếu ngay; phần còn lại chưa về tài khoản (T+{SETTLE_SESSIONS})."
    return True, ""


# ----------------------------------------------------------------------------- giá
def quote_table(stocks: pd.DataFrame) -> pd.DataFrame:
    """Mỗi mã 1 dòng (index = mã): last_date, close, prev_close (nghìn đồng), volume của phiên cuối."""
    d = stocks[["ticker", "date", "close", "volume"]].sort_values(["ticker", "date"])
    d["prev_close"] = d.groupby("ticker")["close"].shift(1)
    last = d.groupby("ticker").tail(1).set_index("ticker")
    return last.rename(columns={"date": "last_date"})


def check_tradable(quote: pd.Series | None, market_last_date) -> tuple[bool, str]:
    """Chặn mã không có phiên mới nhất (tạm ngưng/hủy niêm yết) hoặc phiên cuối không có khớp lệnh."""
    if quote is None:
        return False, "Không có dữ liệu giá của mã này."
    if pd.Timestamp(quote["last_date"]) < pd.Timestamp(market_last_date):
        return False, "Mã chưa có phiên mới nhất (có thể đang tạm ngưng giao dịch)."
    vol = quote.get("volume")
    if pd.isna(vol) or float(vol) <= 0:
        return False, "Phiên mới nhất không có khớp lệnh nào, chưa thể giao dịch."
    return True, ""


def sessions_from(vnindex: pd.DataFrame, stocks: pd.DataFrame | None = None) -> list[str]:
    src = vnindex if len(vnindex) else (stocks if stocks is not None else vnindex)
    if not len(src):
        return []
    return sorted(pd.to_datetime(src["date"]).dt.strftime("%Y-%m-%d").unique())


# ----------------------------------------------------------------------------- bảng & tổng hợp
def first_buy_date(trades: list[dict], ticker: str) -> str | None:
    for t in trades:
        if t["ticker"] == ticker.upper() and t["side"] == "BUY":
            return t["date"]
    return None


def settle_date(date_str: str, sessions: list[str], settle: int = SETTLE_SESSIONS) -> tuple[str, bool]:
    """(ngày bán được, có phải ước tính?). Ngày tương lai ước tính bằng cách bỏ thứ 7, CN (chưa biết ngày lễ)."""
    if not sessions:
        return date_str, True
    last = len(sessions) - 1
    j = _session_index(sessions, date_str) + settle
    if j <= last:
        return sessions[j], False
    d = pd.Timestamp(sessions[-1])
    extra = j - last
    while extra > 0:
        d += pd.Timedelta(days=1)
        if d.weekday() < 5:
            extra -= 1
    return f"{d:%Y-%m-%d}", True


def _last_price(quotes: pd.DataFrame, tk: str, fallback: float) -> float:
    if tk in quotes.index and pd.notna(quotes.at[tk, "close"]):
        return to_vnd(quotes.at[tk, "close"])
    return fallback


def portfolio_table(trades: list[dict], quotes: pd.DataFrame, sessions: list[str],
                    ind_map: dict | None = None, rs_map: dict | None = None) -> pd.DataFrame:
    pos, _ = positions(trades)
    ind_map, rs_map = ind_map or {}, rs_map or {}
    total_value = sum(p["qty"] * _last_price(quotes, tk, p["avg_cost"]) for tk, p in pos.items())
    last_buy = {}
    for t in trades:
        if t["side"] == "BUY":
            last_buy[t["ticker"]] = t["date"]
    rows = []
    for tk, p in sorted(pos.items()):
        last = _last_price(quotes, tk, p["avg_cost"])
        value = p["qty"] * last
        pnl = value - p["cost"]
        can_sell = sellable_qty(trades, tk, sessions)
        chg = None
        if tk in quotes.index and pd.notna(quotes.at[tk, "prev_close"]) and quotes.at[tk, "prev_close"]:
            chg = (quotes.at[tk, "close"] / quotes.at[tk, "prev_close"] - 1) * 100
        if can_sell >= p["qty"]:
            free_from = "Bán được hết"
        else:
            d, est = settle_date(last_buy[tk], sessions)
            free_from = ("~" if est else "") + f"{pd.Timestamp(d):%d/%m}"
        first = first_buy_date(trades, tk)
        held_days = (pd.Timestamp(sessions[-1] if sessions else first) - pd.Timestamp(first)).days if first else 0
        rows.append({"Mã": tk, "Ngành": ind_map.get(tk, ""), "RS": rs_map.get(tk),
                     "Số lượng": p["qty"], "Bán được": can_sell, "Giá vốn TB": p["avg_cost"], "Giá hiện tại": last,
                     "% hôm nay": chg, "Giá trị": value, "Tỷ trọng %": value / total_value * 100 if total_value else 0.0,
                     "Lãi/lỗ": pnl, "% lãi/lỗ": pnl / p["cost"] * 100 if p["cost"] else 0.0,
                     "Bán hết từ": free_from, "Mua đầu": first, "Nắm giữ (ngày)": held_days})
    cols = ["Mã", "Ngành", "RS", "Số lượng", "Bán được", "Giá vốn TB", "Giá hiện tại", "% hôm nay", "Giá trị",
            "Tỷ trọng %", "Lãi/lỗ", "% lãi/lỗ", "Bán hết từ", "Mua đầu", "Nắm giữ (ngày)"]
    return pd.DataFrame(rows, columns=cols)


def day_pnl(trades: list[dict], quotes: pd.DataFrame, last_date: str) -> float:
    """Lãi/lỗ trong phiên mới nhất = số cổ phiếu đang nắm TỪ CUỐI PHIÊN TRƯỚC x (đóng cửa - đóng cửa phiên trước)."""
    pos, _ = positions([t for t in trades if t["date"] < last_date])
    total = 0.0
    for tk, p in pos.items():
        if tk in quotes.index and pd.notna(quotes.at[tk, "prev_close"]) and pd.notna(quotes.at[tk, "close"]):
            total += p["qty"] * (quotes.at[tk, "close"] - quotes.at[tk, "prev_close"]) * PRICE_UNIT
    return total


def realized_by_sell(trades: list[dict]) -> dict[int, float]:
    """{id lệnh bán: lãi/lỗ đã chốt sau phí và thuế, theo giá vốn bình quân}."""
    pos: dict[str, dict] = {}
    out: dict[int, float] = {}
    for t in trades:
        p = pos.setdefault(t["ticker"], {"qty": 0, "cost": 0.0})
        value = t["qty"] * t["price"]
        if t["side"] == "BUY":
            p["qty"] += t["qty"]
            p["cost"] += value + t["fee"]
        else:
            basis = (p["cost"] / p["qty"] if p["qty"] else 0.0) * t["qty"]
            out[t["id"]] = (value - t["fee"] - t["tax"]) - basis
            p["qty"] -= t["qty"]
            p["cost"] -= basis
            if p["qty"] <= 0:
                p["qty"], p["cost"] = 0, 0.0
    return out


def trade_stats(trades: list[dict]) -> dict:
    pnl = list(realized_by_sell(trades).values())
    wins = [x for x in pnl if x > 0]
    losses = [x for x in pnl if x < 0]
    return {"n_buy": sum(t["side"] == "BUY" for t in trades), "n_sell": len(pnl),
            "win_rate": len(wins) / len(pnl) * 100 if pnl else None,
            "avg_win": sum(wins) / len(wins) if wins else None,
            "avg_loss": sum(losses) / len(losses) if losses else None,
            "profit_factor": (sum(wins) / -sum(losses)) if losses and wins else None,
            "fees": float(sum(t["fee"] for t in trades)), "taxes": float(sum(t["tax"] for t in trades))}


def max_drawdown(curve: pd.Series) -> float | None:
    """Mức sụt giảm lớn nhất từ đỉnh (số âm, %)."""
    if curve is None or curve.empty:
        return None
    return float((curve / curve.cummax() - 1).min() * 100)


def _tick(price: float) -> int:
    return 10 if price < 10_000 else (50 if price < 50_000 else 100)


def price_limits(ref_k: float, band: float = PRICE_BAND) -> tuple[float, float]:
    """(trần, sàn) bằng đồng từ giá tham chiếu (nghìn đồng), làm tròn theo bước giá HOSE."""
    ref = to_vnd(ref_k)
    tick = _tick(ref)
    ceil = int(ref * (1 + band) // tick * tick)
    floor = -int(-(ref * (1 - band)) // tick * tick)
    return float(ceil), float(floor)


def stock_info(one: pd.DataFrame) -> dict:
    """Thông tin phiên mới nhất của 1 mã từ bảng giá (cột date, open, high, low, close, volume). Giá: nghìn đồng."""
    d = one.sort_values("date").tail(260)
    if d.empty:
        return {}
    last = d.iloc[-1]
    prev = d.iloc[-2]["close"] if len(d) > 1 else None
    avg20 = d["volume"].tail(21).iloc[:-1].mean() if len(d) > 1 else None
    return {"date": last["date"], "open": last["open"], "high": last["high"], "low": last["low"], "close": last["close"],
            "prev_close": prev, "volume": last["volume"], "avg_vol20": avg20,
            "hi52": d["high"].max(), "lo52": d["low"].min()}


def account_summary(start_cash: float, trades: list[dict], quotes: pd.DataFrame) -> dict:
    cash = cash_balance(start_cash, trades)
    pos, realized = positions(trades)
    market = 0.0
    for tk, p in pos.items():
        last = to_vnd(quotes.at[tk, "close"]) if tk in quotes.index and pd.notna(quotes.at[tk, "close"]) else p["avg_cost"]
        market += p["qty"] * last
    equity = cash + market
    return {"cash": cash, "market_value": market, "equity": equity, "pnl": equity - start_cash,
            "stock_pct": market / equity * 100 if equity else 0.0, "cash_pct": cash / equity * 100 if equity else 0.0,
            "pnl_pct": (equity / start_cash - 1) * 100 if start_cash else 0.0,
            "realized": realized, "unrealized": market - sum(p["cost"] for p in pos.values())}


def equity_curve(start_cash: float, trades: list[dict], stocks: pd.DataFrame, sessions: list[str]) -> pd.Series:
    """Giá trị tài khoản (tiền + cổ phiếu theo giá đóng cửa) tại mỗi phiên kể từ lệnh đầu tiên."""
    if not trades or not sessions:
        return pd.Series(dtype=float)
    idx = pd.to_datetime(pd.Index(sessions))
    idx = idx[idx >= pd.Timestamp(min(t["date"] for t in trades))]
    if not len(idx):
        return pd.Series(dtype=float)
    tickers = sorted({t["ticker"] for t in trades})
    px = (stocks[stocks["ticker"].isin(tickers)]
          .pivot_table(index="date", columns="ticker", values="close", aggfunc="last") * PRICE_UNIT)
    px = px.reindex(index=idx, columns=tickers).ffill()
    col = {tk: i for i, tk in enumerate(tickers)}
    qty = pd.DataFrame(0.0, index=idx, columns=tickers)
    cash = pd.Series(0.0, index=idx)
    for t in trades:
        pos_i = min(int(idx.searchsorted(pd.Timestamp(t["date"]))), len(idx) - 1)
        value = t["qty"] * t["price"]
        if t["side"] == "BUY":
            qty.iat[pos_i, col[t["ticker"]]] += t["qty"]
            cash.iat[pos_i] -= value + t["fee"]
        else:
            qty.iat[pos_i, col[t["ticker"]]] -= t["qty"]
            cash.iat[pos_i] += value - t["fee"] - t["tax"]
    equity = start_cash + cash.cumsum() + (qty.cumsum() * px.fillna(0.0)).sum(axis=1)
    equity.name = "Tài sản"
    return equity
