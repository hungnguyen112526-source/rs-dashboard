"""Chạy thử toàn bộ fetch_data.main() với vnstock GIẢ trong thư mục tạm: ra CSV + nhật ký nguồn, không đụng TradingView."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fetch_data  # noqa: E402


class FakeMarket:
    def _obj(self, base):
        class O:
            def ohlcv(self, start, end, interval):
                d = pd.bdate_range("2026-11-16", periods=5)
                return pd.DataFrame({"time": d.tz_localize("Asia/Ho_Chi_Minh") + pd.Timedelta(hours=7), "open": base, "high": base * 1.01,
                                     "low": base * 0.99, "close": base, "volume": 1000})
        return O()

    def equity(self, symbol):
        return self._obj(25.0)

    def index(self, symbol):
        return self._obj(1700.0)


def test_main_writes_csv_and_log_with_vnstock_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pd.DataFrame({"symbol": ["AAA", "BBB"], "nganh": ["X", "Y"]}).to_csv("danh_sach_ma_theo_nganh.csv", index=False)
    monkeypatch.setattr(fetch_data, "make_vnstock", lambda: FakeMarket())
    monkeypatch.setattr(fetch_data, "VN_RPM", 100000.0)
    fetch_data.main()
    df = pd.read_csv("gia_lich_su_rs.csv")
    assert set(df["ticker"]) == {"AAA", "BBB", "VNINDEX"} and len(df) == 15
    log = fetch_data.load_json("price_source_log.json")
    assert log["counts"] == {"vnstock": 3, "none": 0} and "tv" not in log["counts"]
    assert not os.path.exists("tv_exchange_map.json")
