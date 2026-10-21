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

# Lấy TOÀN BỘ lịch sử từ HISTORY_START đến hôm nay (đổi bằng biến môi trường HISTORY_START,
# vd "2010-01-01"). Dùng start/end thay cho count vì count=<số rất lớn> bị nguồn tự giới hạn
# ở ~1245 phiên (5 năm gần nhất), làm lịch sử cũ bị mất dần theo thời gian.
# Lưu ý dung lượng: càng lùi xa file CSV càng lớn (GitHub chặn file > 100 MB).
HISTORY_START = os.environ.get("HISTORY_START", "2015-01-01")
# Chỉ dùng khi API không nhận start/end (dự phòng). Công thức RS cần tối thiểu 120 phiên.
SESSIONS_TO_FETCH = 1300
MIN_SESSIONS_REQUIRED = 120


def _ohlcv_full(obj):
    """Gọi ohlcv() lấy toàn bộ lịch sử từ HISTORY_START; nếu API không nhận start/end thì dùng count."""
    end = pd.Timestamp.today().strftime("%Y-%m-%d")
    try:
        return obj.ohlcv(start=HISTORY_START, end=end, interval="1D")
    except TypeError:
        return obj.ohlcv(count=SESSIONS_TO_FETCH, interval="1D")


def merge_with_existing(new_df, path):
    """Gộp dữ liệu mới vào file CSV cũ (nếu có): giữ các phiên cũ mà nguồn không còn trả về,
    phiên trùng (cùng mã + cùng ngày) lấy bản mới. Nhờ vậy lịch sử chỉ dài thêm, không bị cắt mất."""
    if os.path.exists(path):
        try:
            old = pd.read_csv(path, low_memory=False)
            old["date"] = pd.to_datetime(old["date"])
            new_df = pd.concat([old, new_df], ignore_index=True)
        except Exception as e:
            print(f"CẢNH BÁO: không đọc được file cũ để gộp ({type(e).__name__}) - chỉ lưu dữ liệu mới.")
    new_df["_d"] = new_df["date"].dt.normalize()
    new_df = (new_df.sort_values("date", kind="stable")
                    .drop_duplicates(subset=["_d", "ticker"], keep="last")
                    .drop(columns="_d"))
    return new_df


def fetch_one(market, ticker):
    """Lấy dữ liệu giá cho 1 mã. Trả về DataFrame (date, open, high, low, close, volume, ticker)
    hoặc None nếu lỗi."""
    df = _ohlcv_full(market.equity(symbol=ticker))
    if df is None or df.empty:
        return None
    df = df.rename(columns={c: c.lower() for c in df.columns})
    date_col = "time" if "time" in df.columns else "date"
    keep_cols = [c for c in [date_col, "open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep_cols].rename(columns={date_col: "date"})
    df["ticker"] = ticker
    return df


def fetch_index(market, symbol="VNINDEX"):
    """Lấy dữ liệu OHLCV cho 1 chỉ số thị trường (VNINDEX...) - dùng market.index() thay vì
    market.equity() vì đây không phải cổ phiếu riêng lẻ. Trả về DataFrame hoặc None nếu lỗi."""
    try:
        df = _ohlcv_full(market.index(symbol=symbol))
    except Exception as e:
        print(f"Lỗi lấy chỉ số {symbol}: {type(e).__name__}")
        return None
    if df is None or df.empty:
        return None
    df = df.rename(columns={c: c.lower() for c in df.columns})
    date_col = "time" if "time" in df.columns else "date"
    keep_cols = [c for c in [date_col, "open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep_cols].rename(columns={date_col: "date"})
    df["ticker"] = symbol
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

    # --- Lấy thêm VNINDEX làm chỉ số tham chiếu (không phải cổ phiếu, không thuộc ngành nào) ---
    print("\nLấy dữ liệu chỉ số tham chiếu VNINDEX...")
    vnindex_df = fetch_index(market, "VNINDEX")
    if vnindex_df is not None:
        vnindex_df["date"] = pd.to_datetime(vnindex_df["date"])
        vnindex_df["industry"] = None
        if "nhom" in symbols_df.columns:
            vnindex_df["nhom"] = None
        price_df = pd.concat([price_df, vnindex_df], ignore_index=True)
        print(f"Đã thêm VNINDEX ({len(vnindex_df)} phiên).")
    else:
        print("CẢNH BÁO: Không lấy được dữ liệu VNINDEX - biểu đồ sẽ thiếu đường tham chiếu.")

    print(f"\nLấy thành công {price_df['ticker'].nunique()}/{len(tickers)} mã")
    if errors:
        print("Mã lỗi/không lấy được (kể cả sau khi thử lại):", errors)

    # --- Cảnh báo mã không đủ dữ liệu để tính RS (vd: mã mới niêm yết) ---
    # Loại VNINDEX ra khỏi cảnh báo này vì nó không phải cổ phiếu, không cần tính RS.
    session_counts = price_df[price_df["ticker"] != "VNINDEX"].groupby("ticker").size()
    insufficient = session_counts[session_counts < MIN_SESSIONS_REQUIRED]
    if not insufficient.empty:
        print(
            f"\nCẢNH BÁO: {len(insufficient)} mã có ít hơn {MIN_SESSIONS_REQUIRED} phiên "
            f"(sẽ bị loại khỏi bảng xếp hạng RS vì không đủ tính đủ 4 khối):"
        )
        for t, n in insufficient.items():
            print(f"  - {t}: {n} phiên")

    # --- Gộp với file cũ + loại dòng trùng lặp (cùng ngày + cùng mã) trước khi lưu ---
    # Một số nguồn dữ liệu đôi khi trả về 2 dòng cho cùng 1 phiên (vd: dữ liệu "tạm"
    # lúc thị trường chưa đóng cửa rồi được cập nhật lại) -> gây lỗi khi tính toán sau này.
    before_dedup = len(price_df)
    price_df = merge_with_existing(price_df, OUTPUT_FILE)
    removed = before_dedup - len(price_df)
    print(f"\nSau khi gộp với file cũ + loại trùng: {len(price_df)} dòng (chênh {removed:+d} so với dữ liệu vừa lấy).")

    price_df.to_csv(OUTPUT_FILE, index=False)
    print(f"\nĐã lưu file {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
