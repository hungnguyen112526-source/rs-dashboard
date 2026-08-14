"""
Script trích xuất dữ liệu giá cho toàn bộ mã trong danh_sach_ma_theo_nganh.csv,
dùng để chạy tự động (GitHub Actions) — không cần nhập API key tương tác.

Cách dùng:
- Local: đặt biến môi trường VNSTOCK_API_KEY rồi chạy `python fetch_data.py`
- GitHub Actions: đọc key từ GitHub Secret, xem file .github/workflows/update_data.yml
"""

import os
import sys
import time

import pandas as pd
import vnai
from vnstock import Market

API_KEY = os.environ.get("VNSTOCK_API_KEY")
SYMBOLS_FILE = "danh_sach_ma_theo_nganh.csv"
OUTPUT_FILE = "gia_lich_su_rs.csv"
START_DATE = "2025-08-01"  # đủ xa để tính RS 4/8/12 tuần, có thể chỉnh lại theo nhu cầu

def main():
    if not API_KEY:
        print("LỖI: Không tìm thấy VNSTOCK_API_KEY trong biến môi trường.")
        sys.exit(1)

    # Cấu hình API key tự động, không cần nhập tương tác
    vnai.setup_api_key(API_KEY)

    symbols_df = pd.read_csv(SYMBOLS_FILE)
    symbols_df = symbols_df.rename(columns={"symbol": "ticker", "nganh": "industry"})
    tickers = symbols_df["ticker"].dropna().unique().tolist()

    print(f"Tổng số mã cần lấy: {len(tickers)}")

    market = Market()
    frames = []
    errors = []
    consecutive_errors = 0

    for i, t in enumerate(tickers):
        try:
            df = market.equity(symbol=t).ohlcv(start=START_DATE, interval="1W")
            if df is None or df.empty:
                print(f"[{i+1}/{len(tickers)}] {t}: không có dữ liệu")
                errors.append(t)
                consecutive_errors += 1
            else:
                df = df.rename(columns={c: c.lower() for c in df.columns})
                date_col = "time" if "time" in df.columns else "date"
                df = df[[date_col, "close"]].rename(columns={date_col: "date"})
                df["ticker"] = t
                frames.append(df)
                print(f"[{i+1}/{len(tickers)}] {t}: OK ({len(df)} dòng)")
                consecutive_errors = 0
        except Exception as e:
            print(f"[{i+1}/{len(tickers)}] {t}: LỖI - {type(e).__name__}")
            errors.append(t)
            consecutive_errors += 1

        if consecutive_errors >= 3:
            print("   >> Nghi ngờ bị giới hạn API, tạm nghỉ 60 giây...")
            time.sleep(60)
            consecutive_errors = 0
        else:
            time.sleep(5)

    if not frames:
        print("LỖI: Không lấy được dữ liệu cho mã nào cả.")
        sys.exit(1)

    price_df = pd.concat(frames, ignore_index=True)
    price_df["date"] = pd.to_datetime(price_df["date"])
    price_df = price_df.merge(symbols_df[["ticker", "industry"]], on="ticker", how="left")

    print(f"\nLấy thành công {price_df['ticker'].nunique()}/{len(tickers)} mã")
    if errors:
        print("Mã lỗi/không lấy được:", errors)

    price_df.to_csv(OUTPUT_FILE, index=False)
    print(f"Đã lưu file {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
