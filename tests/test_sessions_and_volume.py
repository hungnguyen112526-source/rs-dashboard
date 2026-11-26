"""Kiểm thử: bỏ dòng ngoài phiên giao dịch (nguyên nhân biểu đồ dòng tiền bị cách ngày) và lọc KLGD tăng/giảm dần.
Chạy từ thư mục gốc repo:  python -m pytest tests -q
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rs_app"))

import price_sources  # noqa: E402
from src import engine  # noqa: E402


def _market(n_days=80, n_tickers=40):
    days = pd.bdate_range("2026-01-05", periods=n_days)
    rows = [{"date": d, "ticker": f"T{i:02d}", "close": 10.0 + i, "volume": 1000.0}
            for d in days for i in range(n_tickers)]
    return pd.DataFrame(rows), days


def _with_strays(df, days):
    sat = days[10] + pd.Timedelta(days=5 - days[10].dayofweek)   # thứ Bảy của tuần đó
    gap_day = days[30]                              # ngày thật nhưng chỉ còn 1 mã (dòng ma)
    future = days[-1] + pd.Timedelta(days=1)        # ngày chưa tới
    df = df[df["date"] != gap_day]
    extra = pd.DataFrame([{"date": d, "ticker": "T00", "close": 10.0, "volume": 5.0} for d in (sat, gap_day, future)])
    return pd.concat([df, extra], ignore_index=True), (sat, gap_day, future)


@pytest.mark.parametrize("fn", [engine.drop_non_sessions, price_sources.drop_non_sessions])
def test_drop_non_sessions_removes_stray_single_ticker_days(fn):
    df, days = _market()
    dirty, strays = _with_strays(df, days)
    out = fn(dirty)
    got = set(pd.to_datetime(out["date"]).dt.normalize())
    for d in strays:
        assert d not in got
    # mọi phiên bình thường còn nguyên
    normal = set(days) - {days[30]}
    assert normal <= got
    assert len(out) == len(df[df["date"] != days[30]])


def test_both_copies_identical():
    df, days = _market()
    dirty, _ = _with_strays(df, days)
    a, b = engine.drop_non_sessions(dirty), price_sources.drop_non_sessions(dirty)
    pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))


def test_clean_data_untouched_and_empty_ok():
    df, _ = _market(n_days=30, n_tickers=5)
    assert len(engine.drop_non_sessions(df)) == len(df)
    assert engine.drop_non_sessions(df.iloc[0:0]).empty


def test_money_flow_has_no_flat_gap_candles_after_cleaning():
    df, days = _market()
    df["high"] = df["close"] * 1.01
    df["low"] = df["close"] * 0.99
    dirty, _ = _with_strays(df, days)
    n_dirty = len(engine.money_flow_index(dirty))
    n_clean = len(engine.money_flow_index(engine.drop_non_sessions(dirty)))
    assert n_dirty > n_clean                       # trước khi lọc: thừa ngày ma (thứ Bảy, ngày chưa tới)
    assert n_clean == len(days) - 1                # sau khi lọc: đúng số phiên thật (ngày bị thiếu hẳn vẫn thiếu)


# ---------------------------------------------------------------- KLGD tăng/giảm dần
def _vol_df(vols, ticker="AAA"):
    days = pd.bdate_range(end="2026-11-20", periods=len(vols))
    return pd.DataFrame({"date": days, "ticker": ticker, "close": 10.0, "volume": np.asarray(vols, float),
                         "industry": "Ngành X"})


NOW = pd.Timestamp("2026-11-27 16:00", tz="Asia/Ho_Chi_Minh").to_pydatetime()


def test_chain_directions():
    shrinking = np.linspace(2000, 100, 60)         # KL giảm dần theo thời gian -> TB10 < TB20 < TB30 < TB50
    growing = shrinking[::-1].copy()
    mas, tiers = engine._chain(shrinking, "down")
    assert tiers == 4 and mas[0] < mas[1] < mas[2] < mas[3]
    assert engine._chain(shrinking, "up")[1] == 1
    mas, tiers = engine._chain(growing, "up")
    assert tiers == 4 and mas[0] > mas[1] > mas[2] > mas[3]
    assert engine._chain(growing, "down")[1] == 1
    with pytest.raises(ValueError):
        engine._chain(growing, "sideways")


def test_volume_screen_and_hits_follow_direction():
    up = _vol_df(np.linspace(100, 2000, 70), "UP")
    down = _vol_df(np.linspace(2000, 100, 70), "DN")
    df = pd.concat([up, down], ignore_index=True)
    rs = {"UP": 80, "DN": 70}
    d_day, _, _, _ = engine.volume_screen(df, rs, NOW, direction="down")
    u_day, _, _, _ = engine.volume_screen(df, rs, NOW, direction="up")
    assert list(d_day["Mã"]) == ["DN"] and list(u_day["Mã"]) == ["UP"]
    assert u_day[engine.PCT_COL].iloc[0] > 0 > d_day[engine.PCT_COL].iloc[0]
    start, end = "2026-10-01", "2026-11-20"
    assert list(engine.volume_hits(df, rs, start, end, False, NOW, direction="up")["Mã"]) == ["UP"]
    assert list(engine.volume_hits(df, rs, start, end, False, NOW)["Mã"]) == ["DN"]       # mặc định = giảm dần
