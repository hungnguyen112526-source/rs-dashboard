"""Kiểm thử bộ lọc ngày lẻ (engine.drop_non_sessions)."""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rs_app"))

from src import engine  # noqa: E402


def _market(dates, tickers=60):
    rows = [{"date": pd.Timestamp(d), "ticker": f"T{i}", "close": 10.0, "volume": 1000.0} for d in dates for i in range(tickers)]
    return pd.DataFrame(rows)


def test_drop_non_sessions_removes_weekend_and_orphan_weekday_rows():
    df = _market(["2026-11-19", "2026-11-20", "2026-11-23", "2026-11-25"])
    stray = pd.DataFrame([
        {"date": pd.Timestamp("2026-11-21"), "ticker": "NAF", "close": 48.0, "volume": 1.0},   # thứ Bảy
        {"date": pd.Timestamp("2026-11-24"), "ticker": "NAF", "close": 48.0, "volume": 1.0},   # thứ Ba chỉ có 1 mã
        {"date": pd.Timestamp("2026-11-26"), "ticker": "NAF", "close": 48.0, "volume": 1.0},   # ngày cuối chỉ có 1 mã
    ])
    out = engine.drop_non_sessions(pd.concat([df, stray], ignore_index=True))
    assert sorted(out["date"].dt.strftime("%Y-%m-%d").unique()) == ["2026-11-19", "2026-11-20", "2026-11-23", "2026-11-25"]
    assert len(out) == len(df)


def test_drop_non_sessions_keeps_early_history_with_few_tickers():
    df = _market(["2010-01-04", "2010-01-05", "2010-01-06"], tickers=5)   # đầu lịch sử: mỗi phiên chỉ vài mã vẫn là phiên thật
    assert len(engine.drop_non_sessions(df)) == len(df)
