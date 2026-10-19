"""
Tính toán RS (khung Ngày/Tuần) và bộ lọc KLGD giảm dần — cùng công thức với bản trang tĩnh
(generate_report.py) để số liệu khớp nhau.
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

BLOCK_SIZE = 30
WEEKLY_BLOCK_SIZE = 20
BLOCK_WEIGHTS = [0.4, 0.3, 0.2, 0.1]
VOL_WINDOWS = [5, 10, 20, 40]
VN_TZ = timezone(timedelta(hours=7))


def load_prices(path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["date"], low_memory=False)
    df = df.sort_values("date").drop_duplicates(subset=["date", "ticker"], keep="last")
    df["date"] = df["date"].dt.tz_localize(None).dt.normalize()
    return df.reset_index(drop=True)


def split_index(df: pd.DataFrame):
    """Tách VNINDEX ra khỏi dữ liệu cổ phiếu."""
    return df[df["ticker"] != "VNINDEX"].copy(), df[df["ticker"] == "VNINDEX"].copy()


def block_return(prices: pd.Series, block_index: int, block_size: int) -> float:
    n = len(prices)
    end_idx = n - 1 - block_size * (block_index - 1)
    start_idx = n - 1 - block_size * block_index
    if start_idx < 0 or end_idx < 0:
        return np.nan
    return (prices.iloc[end_idx] - prices.iloc[start_idx]) / prices.iloc[start_idx] * 100


def raw_score_to_rs(raw: pd.Series) -> pd.Series:
    n = len(raw)
    rank = raw.rank(method="min", ascending=False)
    return (((n - rank) / n) * 99 + 1).round(0).astype(int)


def weekly_close(df: pd.DataFrame) -> pd.DataFrame:
    """Giá đóng cửa cuối tuần (tuần kết thúc thứ Sáu) cho từng mã."""
    d = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    return d.groupby("ticker").resample("W-FRI", on="date")["close"].last().dropna().reset_index()


def compute_rs(df: pd.DataFrame, frame: str = "day") -> pd.DataFrame:
    """Bảng RS cổ phiếu. frame: 'day' (30 phiên/khối) hoặc 'week' (20 tuần/khối).
    Cột: ticker, industry, pct_block1..4, raw_score, RS."""
    if frame == "week":
        src, block = weekly_close(df[["date", "ticker", "close"]]), WEEKLY_BLOCK_SIZE
    else:
        src, block = df[["date", "ticker", "close"]], BLOCK_SIZE
    records = []
    for ticker, g in src.groupby("ticker"):
        prices = g.sort_values("date")["close"].reset_index(drop=True)
        rets = [block_return(prices, i, block) for i in range(1, 5)]
        if any(pd.isna(r) for r in rets):
            continue
        rec = {"ticker": ticker, "raw_score": sum(w * r for w, r in zip(BLOCK_WEIGHTS, rets))}
        for i, r in enumerate(rets, 1):
            rec[f"pct_block{i}"] = r
        records.append(rec)
    out = pd.DataFrame(records)
    if out.empty:
        return out
    ind = df.drop_duplicates("ticker").set_index("ticker")["industry"]
    out["industry"] = out["ticker"].map(ind)
    out["RS"] = raw_score_to_rs(out["raw_score"])
    return out.sort_values("RS", ascending=False).reset_index(drop=True)


def industry_rs(scores: pd.DataFrame) -> pd.DataFrame:
    if scores.empty:
        return scores
    g = scores.groupby("industry")["raw_score"].mean().rename("raw_score").reset_index()
    g["RS_nganh"] = raw_score_to_rs(g["raw_score"])
    g["so_ma"] = g["industry"].map(scores.groupby("industry").size())
    return g.sort_values("RS_nganh", ascending=False).reset_index(drop=True)


# ----------------------------------------------------------------------------
# Lọc KLGD giảm dần
# ----------------------------------------------------------------------------

def _chain(v: np.ndarray):
    if len(v) < VOL_WINDOWS[-1]:
        return None
    mas = [float(np.mean(v[-w:])) for w in VOL_WINDOWS]
    tiers = 1
    for i in range(3):
        if mas[i] < mas[i + 1]:
            tiers += 1
        else:
            break
    return mas, tiers


def volume_screen(df: pd.DataFrame, rs_map: dict, now_vn: datetime | None = None, min_tiers: int = 3):
    """Trả về (bảng_ngày, bảng_tuần, mốc_ngày_cuối, mốc_tuần_cuối).
    Điều kiện đủ: TB5 < TB10 < TB20 < TB40 (4 mốc). 3 mốc = TB5<TB10<TB20 nhưng chưa < TB40.
    Bỏ phiên/tuần chưa kết thúc. Không lọc thanh khoản; GTGD TB20 chỉ để tham khảo."""
    now_vn = now_vn or datetime.now(VN_TZ)
    today, session_open = now_vn.date(), now_vn.hour < 15
    base = df[["date", "ticker", "close", "volume", "industry"]].dropna(subset=["volume"]).sort_values(["ticker", "date"])
    rows = {"day": [], "week": []}
    last_d, last_w = [], []
    for ticker, g in base.groupby("ticker"):
        g = g.reset_index(drop=True)
        if g["date"].iloc[-1].date() == today and session_open:
            g = g.iloc[:-1]
        if g.empty:
            continue
        last_d.append(g["date"].iloc[-1])
        vol = g["volume"].astype(float).values
        gtgd = float(np.mean(g["close"].astype(float).values[-20:] * 1000.0 * vol[-20:])) / 1e9 if len(g) >= 20 else None
        ind = g["industry"].iloc[-1]
        rs = rs_map.get(ticker)

        def add(frame, res):
            if res is None or res[1] < min_tiers:
                return
            mas, tiers = res
            rows[frame].append({
                "Mã": ticker, "Ngành": ind, "TB5": mas[0], "TB10": mas[1], "TB20": mas[2], "TB40": mas[3],
                "% TB5 so với TB40": (mas[0] / mas[3] - 1) * 100 if mas[3] else None,
                "Số mốc đạt": tiers,
                "GTGD TB20 (tỷ)": gtgd,
                "RS": rs,
            })

        add("day", _chain(vol))
        wk = g.set_index("date")["volume"].astype(float).resample("W-FRI").sum(min_count=1).dropna()
        if len(wk):
            wk_end = wk.index[-1].date()
            if wk_end > today or (wk_end == today and session_open):
                wk = wk.iloc[:-1]
        if len(wk):
            last_w.append(wk.index[-1])
            add("week", _chain(wk.values))
    day, week = pd.DataFrame(rows["day"]), pd.DataFrame(rows["week"])
    return (day, week,
            max(last_d).strftime("%d/%m/%Y") if last_d else None,
            max(last_w).strftime("%d/%m/%Y") if last_w else None)


# ----------------------------------------------------------------------------
# Dữ liệu cho biểu đồ nến
# ----------------------------------------------------------------------------

def ohlcv_for(df: pd.DataFrame, ticker: str, frame: str = "day") -> pd.DataFrame:
    g = df[df["ticker"] == ticker].sort_values("date")
    cols = [c for c in ["open", "high", "low", "close", "volume"] if c in g.columns]
    g = g.set_index("date")[cols]
    if frame == "week":
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        g = g.resample("W-FRI").agg({k: v for k, v in agg.items() if k in g.columns}).dropna(subset=["close"])
    return g


# ----------------------------------------------------------------------------
# Chỉ số dòng tiền (Money-flow Weighted Index) — cùng công thức generate_report.compute_index_series
# ----------------------------------------------------------------------------
INDEX_SMOOTH_WINDOW = 20


def money_flow_index(sub: pd.DataFrame, smooth: int = INDEX_SMOOTH_WINDOW) -> pd.DataFrame:
    """Chỉ số tổng hợp trọng số dòng tiền cho 1 rổ mã (toàn thị trường / 1 ngành / 1 nhóm), mốc 1000 điểm.

    T_i = SMA(giá × KL, smooth); W_i = T_i / ΣT; %ΔIndex = Σ W_i × %ΔP_i.
    Open(t) = Close(t-1); High/Low dùng cùng trọng số với %Δ(High/Low so với Close hôm trước).
    sub cần cột: date, ticker, close, volume (+ high, low nếu có).
    Trả về DataFrame index=date, cột: open, high, low, close, value (tổng GTGD mỗi phiên, tỷ đồng).
    """
    close = sub.pivot(index="date", columns="ticker", values="close").sort_index()
    vol = sub.pivot(index="date", columns="ticker", values="volume").sort_index()
    filled = close.ffill()
    prev = filled.shift(1)
    pct = filled.pct_change(fill_method=None)
    raw = close * vol
    smoothed = raw.rolling(window=smooth, min_periods=1).mean()
    valid = pct.notna() & smoothed.notna() & (smoothed > 0)
    t = smoothed.where(valid)
    w = t.div(t.sum(axis=1), axis=0)  # mã thiếu dữ liệu ngày nào thì bị loại khỏi trọng số ngày đó

    idx_close = 1000.0 * (1.0 + (w * pct).sum(axis=1)).cumprod()
    idx_open = idx_close.shift(1).fillna(1000.0)
    if {"high", "low"} <= set(sub.columns):
        hi = sub.pivot(index="date", columns="ticker", values="high").sort_index()
        lo = sub.pivot(index="date", columns="ticker", values="low").sort_index()
        idx_high = idx_open * (1.0 + (w * ((hi - prev) / prev).fillna(0.0)).sum(axis=1))
        idx_low = idx_open * (1.0 + (w * ((lo - prev) / prev).fillna(0.0)).sum(axis=1))
    else:
        idx_high, idx_low = idx_close.copy(), idx_close.copy()
    out = pd.DataFrame({
        "open": idx_open,
        "high": np.maximum.reduce([idx_high, idx_open, idx_close]),
        "low": np.minimum.reduce([idx_low, idx_open, idx_close]),
        "close": idx_close,
        # giá trong CSV tính theo nghìn đồng -> ×1000 rồi chia 1e9 ra tỷ đồng
        "value": raw.sum(axis=1, skipna=True) * 1000.0 / 1e9,
    })
    return out
