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

# Không dùng ngày cố định (start=...) nữa. Thay vào đó lấy đúng N phiên gần nhất
# tính đến ngày chạy script -> mỗi lần chạy tự động "trượt" theo ngày hiện tại.
# Công thức RS cần tối thiểu 120 phiên (30 phiên x 4 khối); lấy dư ra 150 để an toàn
# (một số phiên có thể bị thiếu do nghỉ lễ/dữ liệu lỗi ở nguồn).
SESSIONS_TO_FETCH = 150
MIN_SESSIONS_REQUIRED = 120


def fetch_one(market, ticker):
    """Lấy dữ liệu giá cho 1 mã. Trả về DataFrame (date, open, high, low, close, volume, ticker)
    hoặc None nếu lỗi."""
    df = market.equity(symbol=ticker).ohlcv(count=SESSIONS_TO_FETCH, interval="1D")
    if df is None or df.empty:
        return None
    df = df.rename(columns={c: c.lower() for c in df.columns})
    date_col = "time" if "time" in df.columns else "date"
    keep_cols = [c for c in [date_col, "open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep_cols].rename(columns={date_col: "date"})
    df["ticker"] = ticker
    return df


def fetch_batch(market, tickers, label=""):
    """Lấy dữ liệu tuần tự cho danh sách mã, có nghỉ giữa các lần gọi để tránh bị
    giới hạn API (gói Free). Trả về (frames, errors)."""
    frames = []
    errors = []
    consecutive_errors = 0
    total = len(tickers)

    for i, t in enumerate(tickers):
        prefix = f"{label}[{i+1}/{total}]" if label else f"[{i+1}/{total}]"
        try:
            df = fetch_one(market, t)
            if df is None:
                print(f"{prefix} {t}: không có dữ liệu")
                errors.append(t)
                consecutive_errors += 1
            else:
                frames.append(df)
                print(f"{prefix} {t}: OK ({len(df)} dòng)")
                consecutive_errors = 0
        except Exception as e:
            print(f"{prefix} {t}: LỖI - {type(e).__name__}")
            errors.append(t)
            consecutive_errors += 1

        if consecutive_errors >= 3:
            print("   >> Nghi ngờ bị giới hạn API, tạm nghỉ 60 giây...")
            time.sleep(60)
            consecutive_errors = 0
        else:
            time.sleep(5)

    return frames, errors


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

    # --- Vòng lấy dữ liệu chính ---
    frames, errors = fetch_batch(market, tickers)

    # --- Retry: thử lại 1 lần nữa cho các mã bị lỗi ở vòng đầu ---
    if errors:
        print(f"\nThử lại {len(errors)} mã bị lỗi ở vòng đầu...")
        retry_frames, still_errors = fetch_batch(market, errors, label="[retry]")
        frames.extend(retry_frames)
        errors = still_errors

    if not frames:
        print("LỖI: Không lấy được dữ liệu cho mã nào cả.")
        sys.exit(1)

    price_df = pd.concat(frames, ignore_index=True)
    price_df["date"] = pd.to_datetime(price_df["date"])
    merge_cols = ["ticker", "industry"]
    if "nhom" in symbols_df.columns:
        merge_cols.append("nhom")
    price_df = price_df.merge(symbols_df[merge_cols], on="ticker", how="left")

    print(f"\nLấy thành công {price_df['ticker'].nunique()}/{len(tickers)} mã")
    if errors:
        print("Mã lỗi/không lấy được (kể cả sau khi thử lại):", errors)

    # --- Cảnh báo mã không đủ dữ liệu để tính RS (vd: mã mới niêm yết) ---
    session_counts = price_df.groupby("ticker").size()
    insufficient = session_counts[session_counts < MIN_SESSIONS_REQUIRED]
    if not insufficient.empty:
        print(
            f"\nCẢNH BÁO: {len(insufficient)} mã có ít hơn {MIN_SESSIONS_REQUIRED} phiên "
            f"(sẽ bị loại khỏi bảng xếp hạng RS vì không đủ tính đủ 4 khối):"
        )
        for t, n in insufficient.items():
            print(f"  - {t}: {n} phiên")

    price_df.to_csv(OUTPUT_FILE, index=False)
    print(f"\nĐã lưu file {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
