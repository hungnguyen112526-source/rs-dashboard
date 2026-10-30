"""Kiểm thử lớp nguồn giá bằng nguồn GIẢ (không cần mạng, không cần cài tvdatafeed/vnstock).
Chạy từ thư mục gốc repo:  python -m pytest tests -q
"""
import os
import sys
import types

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# tvDatafeed giả (price_sources nhập Interval muộn)
_fake = types.ModuleType("tvDatafeed")
_fake.Interval = types.SimpleNamespace(in_daily="1D")
sys.modules.setdefault("tvDatafeed", _fake)

import fetch_data  # noqa: E402
import price_sources  # noqa: E402
from price_sources import PriceFetcher, calibrate, tv_raw_to_frame  # noqa: E402

DAYS = pd.bdate_range("2026-06-01", periods=60)      # 60 phiên
RNG = np.random.default_rng(1)


def make_old(close_start=40.0, vol=1_000_000):
    close = close_start * (1 + RNG.normal(0, 0.01, len(DAYS))).cumprod()
    return pd.DataFrame({"close": close, "volume": vol * (1 + RNG.random(len(DAYS)))}, index=DAYS)


def tv_from(old, scale=1.0, shift_hours=0, vol_mult=1.0, drop_last=0):
    idx = old.index + pd.Timedelta(hours=shift_hours)
    c, v = old["close"].values * scale, old["volume"].values * vol_mult      # .values: tránh pandas tự căn theo index cũ
    df = pd.DataFrame({"symbol": "X", "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": v}, index=idx)
    df.index.name = "datetime"
    return df.iloc[: len(df) - drop_last] if drop_last else df


class FakeTV:
    def __init__(self, data=None, fail=False):
        self.data, self.fail, self.calls, self.bars = data or {}, fail, [], []

    def get_hist(self, symbol, exchange, interval, n_bars):
        self.calls.append((symbol, exchange))
        self.bars.append(n_bars)
        if self.fail:
            raise RuntimeError("tv down")
        return self.data.get((symbol, exchange))


class FakeVN:
    def __init__(self):
        self.calls, self.starts = [], []

    def _obj(self, symbol):
        outer = self

        class O:
            def ohlcv(self, start, end, interval):
                outer.starts.append(start)
                d = pd.bdate_range("2026-08-20", periods=5)
                return pd.DataFrame({"time": d, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10})
        return O()

    def equity(self, symbol):
        self.calls.append(symbol)
        return self._obj(symbol)

    def index(self, symbol):
        self.calls.append(symbol)
        return self._obj(symbol)


def fetcher(tv, vn, history, mode="auto", **kw):
    return PriceFetcher(mode=mode, history=history, tv_factory=lambda: tv, vn_factory=lambda: vn,
                        sleep=lambda s: None, tv_sleep=0, **kw)


def test_calibrate_detects_unit_and_date_shift():
    old = make_old()
    # TradingView: giá theo đồng (x1000) và nến ngày gán 00:00 giờ VN = 17:00 UTC hôm trước
    new = tv_raw_to_frame(tv_from(old, scale=1000, shift_hours=-7))
    cal = calibrate(new, old)
    assert cal and cal.scale == 0.001 and cal.shift_days == 1 and cal.match == 1.0


def test_tv_primary_and_normalised_output():
    old = make_old()
    tv = FakeTV({("AAA", "HOSE"): tv_from(old, scale=1000, shift_hours=-7)})
    vn = FakeVN()
    f = fetcher(tv, vn, {"AAA": old})
    res = f.fetch("AAA")
    assert res.source == "tv" and res.exchange == "HOSE" and not vn.calls
    out = res.df
    assert list(out.columns) == ["date", "open", "high", "low", "close", "volume", "ticker"]
    tail = old.loc[old.index >= old.index.max() - pd.Timedelta(days=price_sources.MERGE_BACK_DAYS)]
    assert (out["date"].dt.normalize().values == tail.index.values).all()      # chỉ nối phần đuôi, ngày khớp lịch sử
    assert (out["date"].dt.hour == 7).all()                                  # cùng dạng 07:00:00 như CSV cũ
    assert np.allclose(out["close"].values, tail["close"].values, rtol=1e-3)  # đã chia 1000
    assert f.exchange_map["AAA"] == "HOSE"


def test_exchange_discovery_order_and_cache():
    old = make_old()
    tv = FakeTV({("AAA", "UPCOM"): tv_from(old)})
    f = fetcher(tv, FakeVN(), {"AAA": old})
    assert f.fetch("AAA").source == "tv"
    assert [c[1] for c in tv.calls] == ["HOSE", "HNX", "UPCOM"]
    tv.calls.clear()
    f.fetch("AAA")
    assert [c[1] for c in tv.calls] == ["UPCOM"]                              # lần sau đi thẳng sàn đã nhớ


def test_tv_exception_falls_back_to_vnstock():
    old = make_old()
    vn = FakeVN()
    res = fetcher(FakeTV(fail=True), vn, {"AAA": old}).fetch("AAA")
    assert res.source == "vnstock" and "TV lỗi" in res.note and vn.calls == ["AAA"]


def test_mismatching_prices_rejected():
    old = make_old()
    bad = tv_from(old)
    bad["close"] = bad["close"] * 1.2                      # lệch 20% (vd khác cách điều chỉnh giá)
    res = fetcher(FakeTV({("AAA", "HOSE"): bad}), FakeVN(), {"AAA": old}).fetch("AAA")
    assert res.source == "vnstock" and "không khớp" in res.note


def test_volume_scale_mismatch_rejected():
    old = make_old()
    res = fetcher(FakeTV({("AAA", "HOSE"): tv_from(old, vol_mult=100)}), FakeVN(), {"AAA": old}).fetch("AAA")
    assert res.source == "vnstock"


def test_stale_tv_rejected():
    old = make_old()
    res = fetcher(FakeTV({("AAA", "HOSE"): tv_from(old, drop_last=2)}), FakeVN(), {"AAA": old}).fetch("AAA")
    assert res.source == "vnstock" and "cũ hơn" in res.note


def test_new_ticker_without_history_uses_vnstock_full_and_not_a_breaker_failure():
    vn, tv = FakeVN(), FakeTV()
    f = fetcher(tv, vn, {}, history_start="2015-01-01", breaker=2)
    for t in ("N1", "N2", "N3"):
        assert f.fetch(t).source == "vnstock"
    assert vn.starts == ["2015-01-01"] * 3 and not tv.calls and not f.tv_disabled


def test_circuit_breaker_switches_everything_to_vnstock():
    old = make_old()
    tv, vn = FakeTV(fail=True), FakeVN()
    hist = {f"T{i}": old for i in range(8)}
    f = fetcher(tv, vn, hist, breaker=3)
    srcs = [f.fetch(f"T{i}").source for i in range(8)]
    assert srcs == ["vnstock"] * 8 and f.tv_disabled
    n_tv_calls = len({c[0] for c in tv.calls})
    assert n_tv_calls == 3                                  # sau 3 lần lỗi liên tiếp không gọi TradingView nữa
    assert "ngắt mạch" in f.summary()["tv_disabled_reason"]


def test_success_resets_breaker_streak():
    old = make_old()
    good = tv_from(old)
    tv = FakeTV({("G", "HOSE"): good})
    f = fetcher(tv, FakeVN(), {"G": old, "B1": old, "B2": old}, breaker=3)
    for t in ("B1", "B2", "G", "B1", "B2"):
        f.fetch(t)
    assert not f.tv_disabled                                # lỗi bị ngắt quãng bởi 1 lần thành công -> không ngắt mạch


def test_vnstock_mode_never_touches_tradingview():
    old = make_old()
    tv, vn = FakeTV({("AAA", "HOSE"): tv_from(old)}), FakeVN()
    res = fetcher(tv, vn, {"AAA": old}, mode="vnstock").fetch("AAA")
    assert res.source == "vnstock" and not tv.calls


def test_tv_mode_has_no_fallback():
    old = make_old()
    vn = FakeVN()
    res = fetcher(FakeTV(fail=True), vn, {"AAA": old}, mode="tv").fetch("AAA")
    assert res.df is None and not vn.calls


def test_full_refresh_uses_tradingview_with_max_bars_and_writes_whole_history():
    old = make_old()
    tv, vn = FakeTV({("AAA", "HOSE"): tv_from(old)}), FakeVN()
    f = fetcher(tv, vn, {"AAA": old}, full_refresh=True, history_start="2015-01-01")
    assert not f.tv_disabled
    res = f.fetch("AAA")
    assert res.source == "tv" and not vn.calls
    assert tv.bars == [price_sources.FULL_REFRESH_BARS]               # xin tối đa số nến
    assert len(res.df) == len(old)                                      # ghi toàn bộ, không chỉ phần đuôi 5 ngày
    assert (res.df["date"].dt.normalize().values == old.index.values).all()


def test_normal_run_still_writes_only_the_tail():
    old = make_old()
    tv = FakeTV({("AAA", "HOSE"): tv_from(old)})
    res = fetcher(tv, FakeVN(), {"AAA": old}, tv_bars=150).fetch("AAA")
    assert tv.bars == [150] and 0 < len(res.df) < len(old)


def test_full_refresh_mismatch_falls_back_to_vnstock_from_history_start():
    old = make_old()
    bad = tv_from(old)
    bad["close"] = bad["close"] * 1.2                                   # TradingView không khớp -> không được ghi đè lịch sử
    tv, vn = FakeTV({("AAA", "HOSE"): bad}), FakeVN()
    res = fetcher(tv, vn, {"AAA": old}, full_refresh=True, history_start="2015-01-01").fetch("AAA")
    assert res.source == "vnstock" and vn.starts == ["2015-01-01"] and "không khớp" in res.note


def test_full_refresh_with_vnstock_mode_goes_to_vnstock_from_history_start():
    old = make_old()
    tv, vn = FakeTV({("AAA", "HOSE"): tv_from(old)}), FakeVN()
    res = fetcher(tv, vn, {"AAA": old}, mode="vnstock", full_refresh=True, history_start="2015-01-01").fetch("AAA")
    assert res.source == "vnstock" and vn.starts == ["2015-01-01"] and not tv.calls


def test_vnstock_fallback_is_incremental_for_known_ticker():
    old = make_old()
    vn = FakeVN()
    fetcher(FakeTV(fail=True), vn, {"AAA": old}, history_start="2015-01-01").fetch("AAA")
    expected = str((old.index.max() - pd.Timedelta(days=45)).date())
    assert vn.starts == [expected]


def test_index_never_rescaled_and_uses_hose():
    old = make_old(close_start=1700)
    tv = FakeTV({("VNINDEX", "HOSE"): tv_from(old)})
    res = fetcher(tv, FakeVN(), {"VNINDEX": old}).fetch("VNINDEX", is_index=True)
    assert res.source == "tv" and np.allclose(res.df["close"].values, old["close"].values[-len(res.df):], rtol=1e-6)
    assert {c[1] for c in tv.calls} == {"HOSE"}


def test_vnstock_failure_without_key_is_reported_not_raised():
    def boom():
        raise fetch_data.SourceError("thiếu VNSTOCK_API_KEY")
    f = PriceFetcher(mode="vnstock", history={}, vn_factory=boom, sleep=lambda s: None)
    res = f.fetch("AAA")
    assert res.df is None and "vnstock lỗi" in res.note


def test_summary_counts():
    old = make_old()
    f = fetcher(FakeTV({("A", "HOSE"): tv_from(old)}), FakeVN(), {"A": old, "B": {}.get("B", old)})
    f.fetch("A")
    f.tv_disabled = True
    f.fetch("B")
    s = f.summary()
    assert s["counts"] == {"tv": 1, "vnstock": 1, "none": 0} and s["tickers"]["A"]["source"] == "tv"


def test_merge_with_existing_new_wins_and_old_kept(tmp_path):
    p = tmp_path / "p.csv"
    old = pd.DataFrame({"date": pd.to_datetime(["2026-10-01 07:00:00", "2026-10-02 07:00:00"]), "open": 1, "high": 1, "low": 1,
                        "close": [10.0, 11.0], "volume": 5, "ticker": "A", "industry": "X", "nhom": None})
    old.to_csv(p, index=False)
    new = pd.DataFrame({"date": pd.to_datetime(["2026-10-02 07:00:00", "2026-10-03 07:00:00"]), "open": 1, "high": 1, "low": 1,
                        "close": [11.5, 12.0], "volume": 6, "ticker": "A", "industry": "X", "nhom": None})
    m = fetch_data.merge_with_existing(new, str(p))
    assert list(m["close"]) == [10.0, 11.5, 12.0]


def test_old_price_adjustment_does_not_block_recent_match():
    """Giá cũ bị điều chỉnh (cổ tức...) khác CSV nhưng 20 phiên gần nhất khớp -> vẫn nhận."""
    old = make_old()
    raw = tv_from(old, scale=1000)
    raw.iloc[:-30, raw.columns.get_loc("close")] *= 0.9
    cal, info = price_sources.diagnose(price_sources.tv_raw_to_frame(raw), old)
    assert cal is not None and cal.match >= 0.99 and cal.match_all < 0.9


def test_diagnose_reports_reason():
    old = make_old()
    raw = tv_from(old, scale=1000)
    raw["close"] *= 1.2
    cal, info = price_sources.diagnose(price_sources.tv_raw_to_frame(raw), old)
    assert cal is None and "khớp" in info["reason"] and info["best"] is not None


def test_rejected_data_does_not_trip_breaker_and_good_tickers_still_use_tv():
    """Vài mã liên tiếp bị loại vì khối lượng lệch thang (vd MWG, FRT) chỉ chuyển riêng các mã đó sang vnstock,
    không được tắt TradingView cho những mã dữ liệu tốt phía sau."""
    old = make_old()
    bad = tv_from(old, vol_mult=1.5)
    good = tv_from(old)
    data = {(f"B{i}", "HOSE"): bad for i in range(6)}
    data[("G", "HOSE")] = good
    tv, vn = FakeTV(data), FakeVN()
    hist = {f"B{i}": old for i in range(6)}
    hist["G"] = old
    f = fetcher(tv, vn, hist, breaker=3, exchange_map={k[0]: "HOSE" for k in data})
    assert [f.fetch(f"B{i}").source for i in range(6)] == ["vnstock"] * 6
    assert not f.tv_disabled
    assert f.fetch("G").source == "tv"


def test_rs_scale_is_capped_to_1_99():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rs_app"))
    from src.engine import raw_score_to_rs
    rs = raw_score_to_rs(pd.Series(np.arange(300, dtype=float)))
    assert rs.max() == 99 and rs.min() == 1
