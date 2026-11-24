"""Kiểm thử lớp tương thích vnstock thế hệ 6 bằng dữ liệu GIẢ (không cần mạng, không cần cài vnstock).
Chạy từ thư mục gốc repo:  python -m pytest tests -q
"""
import os
import sys
import types

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_fake = types.ModuleType("tvDatafeed")
_fake.Interval = types.SimpleNamespace(in_daily="1D")
sys.modules.setdefault("tvDatafeed", _fake)

import fetch_data  # noqa: E402
import fetch_financials  # noqa: E402
import price_sources  # noqa: E402
import vnstock_adapter as va  # noqa: E402


class CodedError(Exception):
    def __init__(self, code, msg=""):
        super().__init__(msg or code)
        self.code = code


# ---- nguồn khai báo một chỗ ----------------------------------------------------------------------
def test_get_source_requires_explicit_value(monkeypatch):
    monkeypatch.delenv("VNSTOCK_SOURCE", raising=False)
    with pytest.raises(va.SourceNotConfigured):
        va.get_source()


def test_get_source_normalizes_and_supports_fallback(monkeypatch):
    monkeypatch.setenv("VNSTOCK_SOURCE", "  TCBS ")
    monkeypatch.delenv("FIN_SOURCE", raising=False)
    assert va.get_source() == "tcbs"
    assert va.get_source("FIN_SOURCE", fallback_env="VNSTOCK_SOURCE") == "tcbs"
    monkeypatch.setenv("FIN_SOURCE", "fhsc")
    assert va.get_source("FIN_SOURCE", fallback_env="VNSTOCK_SOURCE") == "fhsc"


def test_make_vnstock_without_source_is_reported_as_source_error(monkeypatch):
    monkeypatch.delenv("VNSTOCK_SOURCE", raising=False)
    with pytest.raises(price_sources.SourceError, match="VNSTOCK_SOURCE"):
        fetch_data.make_vnstock()


# ---- nhận diện lỗi -------------------------------------------------------------------------------
def test_error_code_from_attribute_and_message():
    assert va.error_code(CodedError("VNSTOCK_INPUT_SOURCE")) == "VNSTOCK_INPUT_SOURCE"
    assert va.error_code(RuntimeError("lỗi VNSTOCK_SOURCE_UNAVAILABLE: bảo trì")) == "VNSTOCK_SOURCE_UNAVAILABLE"
    assert va.error_code(RuntimeError("không có mã")) == ""


def test_rate_limit_and_unsupported_detection():
    assert va.is_rate_limited(RuntimeError("HTTP 429 Too Many Requests"))
    assert va.is_rate_limited(CodedError("VNSTOCK_SOURCE_RATE_LIMITED"))
    assert not va.is_rate_limited(CodedError("VNSTOCK_INPUT_PARAM"))
    assert va.is_unsupported(CodedError("VNSTOCK_ROUTE_UNSUPPORTED"))
    assert va.is_unsupported(CodedError("VNSTOCK_INPUT_SOURCE"))
    assert not va.is_unsupported(CodedError("VNSTOCK_SOURCE_UNAVAILABLE"))


# ---- chuẩn hoá nến vnstock 6 ---------------------------------------------------------------------
def test_vnstock_frame_handles_tz_aware_unsorted_int64():
    t = pd.to_datetime(["2026-06-03 07:00", "2026-06-01 07:00", "2026-06-02 07:00"]).tz_localize("Asia/Ho_Chi_Minh")
    df = pd.DataFrame({"time": t, "open": [3.0, 1.0, 2.0], "high": [3.1, 1.1, 2.1], "low": [2.9, 0.9, 1.9],
                       "close": [3.0, 1.0, 2.0], "volume": pd.array([300, 100, 200], dtype="Int64")})
    out = price_sources.vnstock_frame(df, "FPT")
    assert list(out["close"]) == [1.0, 2.0, 3.0]                       # tăng dần theo ngày
    assert out["date"].dt.tz is None and out["date"].dt.hour.eq(7).all()  # bỏ múi giờ, giữ 07:00
    assert list(out["volume"]) == [100, 200, 300] and (out["ticker"] == "FPT").all()


def test_vnstock_frame_drops_duplicate_dates_and_empty():
    assert price_sources.vnstock_frame(pd.DataFrame(), "X") is None
    d = pd.to_datetime(["2026-06-01 07:00", "2026-06-01 07:00"])
    out = price_sources.vnstock_frame(pd.DataFrame({"time": d, "close": [1.0, 2.0], "volume": [1, 2]}), "X")
    assert len(out) == 1 and out["close"].iloc[0] == 2.0


def test_vnstock_ohlcv_uses_documented_signature_only():
    class Obj:
        def ohlcv(self, start, end, interval):
            self.args = (start, interval)
            return "ok"
    o = Obj()
    assert price_sources.vnstock_ohlcv(o, "2026-01-01") == "ok" and o.args == ("2026-01-01", "1D")


def test_rate_limited_error_retries_then_succeeds():
    calls = {"n": 0}

    class Obj:
        def ohlcv(self, start, end, interval):
            calls["n"] += 1
            if calls["n"] == 1:
                raise CodedError("VNSTOCK_SOURCE_RATE_LIMITED", "vượt hạn mức")
            return pd.DataFrame({"time": pd.to_datetime(["2026-06-01 07:00"]), "close": [1.0], "volume": [1]})

    class Market:
        def equity(self, symbol):
            return Obj()
        def index(self, symbol):
            return Obj()

    f = price_sources.PriceFetcher(mode="vnstock", history={}, vn_factory=lambda: Market(), sleep=lambda s: None)
    res = f.fetch("AAA")
    assert res.source == "vnstock" and calls["n"] == 2


def test_non_rate_limit_error_is_not_retried():
    calls = {"n": 0}

    class Obj:
        def ohlcv(self, start, end, interval):
            calls["n"] += 1
            raise CodedError("VNSTOCK_INPUT_PARAM")

    class Market:
        def equity(self, symbol):
            return Obj()

    f = price_sources.PriceFetcher(mode="vnstock", history={}, vn_factory=lambda: Market(), sleep=lambda s: None)
    res = f.fetch("AAA")
    assert res.df is None and calls["n"] == 1


# ---- báo cáo tài chính -------------------------------------------------------------------------
def v5_wide():
    return pd.DataFrame({
        "id": ["BS_SHORT_TERM_ASSETS", "BS_TOTAL_ASSETS"], "item": ["TÀI SẢN NGẮN HẠN", "TỔNG TÀI SẢN"],
        "order": [1, 2], "level": [1, 1], "unit": ["VNĐ", "VNĐ"], "line_code": ["100", "270"],
        "2025-Q3": [1.0e13, 2.0e13], "2025-Q4": [1.1e13, 2.1e13],
    })


def test_to_legacy_wide_maps_v5_columns():
    out = fetch_financials.to_legacy_wide(v5_wide())
    assert list(out.columns) == ["item", "item_id", "2025-Q3", "2025-Q4"]
    assert list(out["item_id"]) == ["BS_SHORT_TERM_ASSETS", "BS_TOTAL_ASSETS"]


def test_to_legacy_wide_rejects_unknown_shape():
    with pytest.raises(ValueError):
        fetch_financials.to_legacy_wide(pd.DataFrame({"a": [1]}))


class FakeEquity:
    def __init__(self, fail_code=None):
        self.fail_code = fail_code
    def _call(self, **kw):
        if self.fail_code:
            raise CodedError(self.fail_code)
        assert kw["format"] == "wide" and kw["period"] == "quarter" and kw["source"] == "fhsc"
        return v5_wide()
    income_statement = balance_sheet = cash_flow = lambda self, **kw: self._call(**kw)


class FakeFundamental:
    def __init__(self, fail_code=None):
        self.fail_code = fail_code
    def equity(self, ticker):
        return FakeEquity(self.fail_code)


def test_fetch_ticker_financials_ok_and_unsupported(monkeypatch):
    monkeypatch.setattr(fetch_financials.time, "sleep", lambda s: None)
    res, uns = fetch_financials.fetch_ticker_financials("FPT", "fhsc", FakeFundamental())
    assert set(res) == {"income_statement", "balance_sheet", "cash_flow"} and uns == 0
    assert res["balance_sheet"]["columns"][:2] == ["item", "item_id"]
    res, uns = fetch_financials.fetch_ticker_financials("FPT", "fhsc", FakeFundamental("VNSTOCK_ROUTE_UNSUPPORTED"))
    assert res == {} and uns == 3


def test_fin_limit_writes_sample_file_not_the_real_one(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    pd.DataFrame({"symbol": ["AAA", "BBB", "CCC"]}).to_csv("danh_sach_ma_theo_nganh.csv", index=False)
    monkeypatch.setenv("VNSTOCK_SOURCE", "fhsc")
    monkeypatch.setenv("FIN_LIMIT", "2")
    monkeypatch.setattr(fetch_financials, "make_fundamental", lambda: FakeFundamental())
    monkeypatch.setattr(fetch_financials.time, "sleep", lambda s: None)
    fetch_financials.main()
    import json
    sample = json.load(open("financials_data.sample.json", encoding="utf-8"))
    assert list(sample["tickers"]) == ["AAA", "BBB"]
    assert not os.path.exists("financials_data.json")


def test_financials_stops_early_when_source_has_no_fundamental(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    pd.DataFrame({"symbol": [f"T{i}" for i in range(10)]}).to_csv("danh_sach_ma_theo_nganh.csv", index=False)
    monkeypatch.setenv("VNSTOCK_SOURCE", "tcbs")
    monkeypatch.delenv("FIN_LIMIT", raising=False)
    monkeypatch.setattr(fetch_financials, "make_fundamental", lambda: FakeFundamental("VNSTOCK_ROUTE_UNSUPPORTED"))
    monkeypatch.setattr(fetch_financials.time, "sleep", lambda s: None)
    fetch_financials.main()
    out = capsys.readouterr().out
    assert "không hỗ trợ báo cáo tài chính" in out and "[4/10]" not in out
    assert not os.path.exists("financials_data.json")
