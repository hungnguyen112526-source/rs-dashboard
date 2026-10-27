"""
Lấy lợi suất trái phiếu chính phủ kỳ hạn 2, 10 và 30 năm của nhiều quốc gia từ TradingView qua thư viện
tvdatafeed (không chính thức, đăng nhập ẩn danh) -> bond_yields.json, để generate_report.py
vẽ biểu đồ so sánh trên trang Vĩ mô.

Lấy dữ liệu theo TUẦN (800 tuần ~ 15 năm) cho nhẹ. Lỗi ở từng quốc gia không làm hỏng các
nước còn lại. Nếu không lấy được nước nào -> giữ nguyên file cũ, không ghi đè.
"""
import json
import time
from datetime import datetime, timezone, timedelta

from tvDatafeed import TvDatafeed, Interval

OUTPUT_FILE = "bond_yields.json"
N_BARS = 800
VN_TZ = timezone(timedelta(hours=7))

# (mã quốc gia TradingView, sàn, nhãn hiển thị); mã trái phiếu = <mã nước><kỳ hạn>Y, vd US10Y, GB02Y
COUNTRIES = [("US", "TVC", "Mỹ"), ("JP", "TVC", "Nhật"), ("GB", "TVC", "Anh"), ("DE", "TVC", "Đức"),
             ("FR", "TVC", "Pháp"), ("KR", "TVC", "Hàn Quốc"), ("AU", "TVC", "Úc"), ("NL", "TVC", "Hà Lan"),
             ("CN", "TVC", "Trung Quốc")]
# khoá trong JSON -> kỳ hạn. "series" (30 năm) giữ nguyên tên để generate_report.py (trang tĩnh) không bị ảnh hưởng.
TENORS = {"series": "30", "series_10y": "10", "series_2y": "02"}


def fetch_one(tv, symbol, exchange):
    for attempt in range(3):
        try:
            df = tv.get_hist(symbol=symbol, exchange=exchange, interval=Interval.in_weekly, n_bars=N_BARS)
            if df is not None and not df.empty:
                df = df[["close"]].dropna()
                return [[idx.strftime("%Y-%m-%d"), round(float(v), 3)] for idx, v in df["close"].items()]
        except Exception as e:
            print(f"  {symbol}: lỗi lần {attempt + 1} - {type(e).__name__}: {e}")
        time.sleep(3)
    return None


def main():
    tv = TvDatafeed()  # ẩn danh: đủ cho dữ liệu TVC, có thể bị giới hạn số nến
    try:
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = {}
    out = {}
    for key, ten in TENORS.items():
        series = {}
        for cc, exchange, label in COUNTRIES:
            symbol = f"{cc}{ten}Y"
            data = fetch_one(tv, symbol, exchange)
            if data:
                series[symbol] = {"label": label, "data": data}
                print(f"  {symbol} ({label}): {len(data)} tuần, gần nhất {data[-1]}")
            else:
                print(f"  {symbol} ({label}): không lấy được")
            time.sleep(1)
        # kỳ hạn nào lần này không lấy được gì thì giữ dữ liệu cũ, không ghi đè bằng rỗng
        out[key] = series or old.get(key) or {}

    if not any(out.values()):
        print("CẢNH BÁO: không lấy được gì - giữ nguyên file cũ (nếu có).")
        return

    out = {"updated_at": datetime.now(VN_TZ).strftime("%d/%m/%Y %H:%M"), **{k: v for k, v in out.items() if v}}
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("Đã lưu " + OUTPUT_FILE + ": " + ", ".join(f"{k}={len(v)} nước" for k, v in out.items() if k != "updated_at"))


if __name__ == "__main__":
    main()
