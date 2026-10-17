"""
Lấy lợi suất trái phiếu chính phủ 30 năm của nhiều quốc gia từ TradingView qua thư viện
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

# (mã TradingView, sàn, nhãn hiển thị)
BONDS = [
    ("US30Y", "TVC", "Mỹ"),
    ("JP30Y", "TVC", "Nhật"),
    ("GB30Y", "TVC", "Anh"),
    ("DE30Y", "TVC", "Đức"),
    ("FR30Y", "TVC", "Pháp"),
    ("KR30Y", "TVC", "Hàn Quốc"),
    ("AU30Y", "TVC", "Úc"),
    ("NL30Y", "TVC", "Hà Lan"),
    ("CN30Y", "TVC", "Trung Quốc"),
]


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
    series = {}
    for symbol, exchange, label in BONDS:
        data = fetch_one(tv, symbol, exchange)
        if data:
            series[symbol] = {"label": label, "data": data}
            print(f"  {symbol} ({label}): {len(data)} tuần, gần nhất {data[-1]}")
        else:
            print(f"  {symbol} ({label}): không lấy được")
        time.sleep(1)

    if not series:
        print("CẢNH BÁO: không lấy được nước nào - giữ nguyên file cũ (nếu có).")
        return

    out = {"updated_at": datetime.now(VN_TZ).strftime("%d/%m/%Y %H:%M"), "series": series}
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Đã lưu {OUTPUT_FILE} ({len(series)}/{len(BONDS)} nước)")


if __name__ == "__main__":
    main()
