"""
Script trích xuất dữ liệu giá cho toàn bộ mã trong danh_sach_ma_theo_nganh.csv (+ VNINDEX),
chạy tự động (GitHub Actions) — không cần nhập API key tương tác.

Nguồn dữ liệu (xem price_sources.py):
  - Chính: TradingView qua tvdatafeed (không cần khoá; chạy thường chỉ lấy ~TV_BARS nến gần nhất rồi gộp phần đuôi
    vào CSV hiện có, sau khi đối chiếu khớp với lịch sử đang có).
  - FULL_REFRESH=1: cũng dùng TradingView nhưng xin tối đa 5000 nến ngày (toàn bộ lịch sử) và ghi toàn bộ số nến đó
    (vẫn phải qua bước đối chiếu 20 phiên gần nhất) để "tự chữa" các lần điều chỉnh giá.
  - Dự phòng: vnstock (cần VNSTOCK_API_KEY) cho mã nào TradingView lỗi/không khớp, hoặc mã mới chưa có lịch sử
    (các mã này lấy toàn bộ lịch sử từ HISTORY_START khi FULL_REFRESH=1).

Biến môi trường:
  PRICE_SOURCE    auto (mặc định: TradingView rồi vnstock) | tv (chỉ TradingView) | vnstock (như cách cũ)
  FULL_REFRESH    1/true -> lấy toàn bộ lịch sử (TradingView tối đa 5000 nến, ghi toàn bộ; lỗi/không khớp -> vnstock).
                  Muốn lấy toàn bộ bằng vnstock như trước: PRICE_SOURCE=vnstock + FULL_REFRESH=1
  TV_BARS         số nến ngày gần nhất lấy từ TradingView khi chạy thường (mặc định 150)
  TV_USERNAME / TV_PASSWORD   (tuỳ chọn) đăng nhập TradingView thay vì ẩn danh
  VNSTOCK_API_KEY             chỉ cần khi phải dùng vnstock
  VN_RPM          số request/phút tối đa gửi vnstock (mặc định 55, gói cộng đồng giới hạn 60)
  VN_CALLS_PER_FETCH  số request vnstock thực tế tốn cho 1 mã (mặc định 2; hạ về 1 nếu log cho thấy không bị vượt hạn mức)
  HISTORY_START   ngày bắt đầu lịch sử khi lấy từ vnstock (mặc định 2015-01-01)

Đầu ra: gia_lich_su_rs.csv (như cũ), price_source_log.json (mỗi mã lấy từ nguồn nào), tv_exchange_map.json.
"""

import os
import sys
import time

import pandas as pd

from price_sources import PriceFetcher, RateLimiter, SourceError, load_history, load_json, save_json

API_KEY = os.environ.get("VNSTOCK_API_KEY")
SYMBOLS_FILE = "danh_sach_ma_theo_nganh.csv"
OUTPUT_FILE = "gia_lich_su_rs.csv"
SOURCE_LOG_FILE = "price_source_log.json"
EXCHANGE_MAP_FILE = "tv_exchange_map.json"

HISTORY_START = os.environ.get("HISTORY_START", "2015-01-01")
MIN_SESSIONS_REQUIRED = 120          # công thức RS cần tối thiểu 120 phiên
PRICE_SOURCE = os.environ.get("PRICE_SOURCE", "auto").strip().lower()
FULL_REFRESH = os.environ.get("FULL_REFRESH", "").strip().lower() in ("1", "true", "yes")
TV_BARS = int(os.environ.get("TV_BARS", "150") or 150)
VN_RPM = float(os.environ.get("VN_RPM", "55") or 55)   # số request/phút tối đa gửi vnstock (giới hạn gói cộng đồng: 60)
VN_CALLS_PER_FETCH = int(os.environ.get("VN_CALLS_PER_FETCH", "2") or 2)   # số request vnstock thực tế tốn cho 1 mã
WARN_FRESH_RATIO = 0.90              # < 90% số mã lấy được thì cảnh báo trên GitHub Actions


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


# ----------------------------------------------------------------------------
# Khởi tạo nguồn (nhập thư viện muộn: chỉ cần cài thứ thật sự dùng tới)
# ----------------------------------------------------------------------------

def make_tv():
    from tvDatafeed import TvDatafeed
    user, pwd = os.environ.get("TV_USERNAME"), os.environ.get("TV_PASSWORD")
    return TvDatafeed(user, pwd) if user and pwd else TvDatafeed()


def make_vnstock():
    if not API_KEY:
        raise SourceError("thiếu VNSTOCK_API_KEY")
    import vnai
    from vnstock import Market
    vnai.setup_api_key(API_KEY)
    return Market()


def fetch_all(fetcher, tickers, label=""):
    """Lấy tuần tự cho danh sách mã. Nghỉ ngắn sau khi dùng TradingView, nghỉ lâu hơn sau vnstock (tránh giới hạn
    API gói Free). Trả về (frames, errors)."""
    frames, errors = [], []
    vn_errors_streak = 0
    total = len(tickers)
    for i, t in enumerate(tickers):
        prefix = f"{label}[{i + 1}/{total}]" if label else f"[{i + 1}/{total}]"
        res = fetcher.fetch(t)
        if res.df is None:
            print(f"{prefix} {t}: KHÔNG LẤY ĐƯỢC - {res.note}")
            errors.append(t)
            vn_errors_streak += 1 if res.source == "none" and "vnstock" in res.note else 0
        else:
            frames.append(res.df)
            print(f"{prefix} {t}: OK [{res.source}] {len(res.df)} dòng - {res.note}")
            vn_errors_streak = 0
        if vn_errors_streak >= 3:
            print("   >> Nghi ngờ bị giới hạn API vnstock, tạm nghỉ 60 giây...")
            time.sleep(60)
            vn_errors_streak = 0
        elif res.source == "tv":
            time.sleep(fetcher.tv_sleep)
        # vnstock: không sleep cố định nữa - RateLimiter trong PriceFetcher tự giãn cách theo VN_RPM
    return frames, errors


def main():
    if PRICE_SOURCE not in ("auto", "tv", "vnstock"):
        print(f"LỖI: PRICE_SOURCE='{PRICE_SOURCE}' không hợp lệ (auto | tv | vnstock).")
        sys.exit(1)

    symbols_df = pd.read_csv(SYMBOLS_FILE)
    symbols_df = symbols_df.rename(columns={"symbol": "ticker", "nganh": "industry"})
    tickers = symbols_df["ticker"].dropna().unique().tolist()
    print(f"Tổng số mã cần lấy: {len(tickers)} | nguồn: {PRICE_SOURCE}"
          f"{' | FULL_REFRESH' if FULL_REFRESH else ''} | TV_BARS={TV_BARS}")

    history = load_history(OUTPUT_FILE)
    print(f"Lịch sử hiện có để đối chiếu: {len(history)} mã")

    fetcher = PriceFetcher(
        mode=PRICE_SOURCE, history=history, history_start=HISTORY_START,
        tv_factory=make_tv, vn_factory=make_vnstock,
        exchange_map=load_json(EXCHANGE_MAP_FILE, {}) or {},
        tv_bars=TV_BARS, full_refresh=FULL_REFRESH,
        vn_limiter=RateLimiter(VN_RPM), vn_calls_per_fetch=VN_CALLS_PER_FETCH,
    )

    # --- Vòng chính + thử lại 1 lần cho mã lỗi ---
    frames, errors = fetch_all(fetcher, tickers)
    if errors:
        print(f"\nThử lại {len(errors)} mã lỗi ở vòng đầu...")
        retry_frames, errors = fetch_all(fetcher, errors, label="[retry]")
        frames.extend(retry_frames)

    if not frames:
        print("LỖI: Không lấy được dữ liệu cho mã nào cả.")
        save_json(SOURCE_LOG_FILE, fetcher.summary())
        sys.exit(1)

    price_df = pd.concat(frames, ignore_index=True)
    price_df["date"] = pd.to_datetime(price_df["date"])
    merge_cols = ["ticker", "industry"]
    if "nhom" in symbols_df.columns:
        merge_cols.append("nhom")
    price_df = price_df.merge(symbols_df[merge_cols], on="ticker", how="left")

    # --- VNINDEX làm chỉ số tham chiếu (không phải cổ phiếu, không thuộc ngành nào) ---
    print("\nLấy dữ liệu chỉ số tham chiếu VNINDEX...")
    vn_res = fetcher.fetch("VNINDEX", is_index=True)
    if vn_res.df is not None:
        vnindex_df = vn_res.df.copy()
        vnindex_df["date"] = pd.to_datetime(vnindex_df["date"])
        vnindex_df["industry"] = None
        if "nhom" in symbols_df.columns:
            vnindex_df["nhom"] = None
        price_df = pd.concat([price_df, vnindex_df], ignore_index=True)
        print(f"Đã thêm VNINDEX [{vn_res.source}] ({len(vnindex_df)} phiên) - {vn_res.note}")
    else:
        print(f"CẢNH BÁO: Không lấy được dữ liệu VNINDEX ({vn_res.note}) - biểu đồ sẽ thiếu đường tham chiếu.")

    got = price_df[price_df["ticker"] != "VNINDEX"]["ticker"].nunique()
    print(f"\nLấy thành công {got}/{len(tickers)} mã")
    if errors:
        print("Mã lỗi/không lấy được (kể cả sau khi thử lại):", errors)

    # --- Gộp với file cũ + loại dòng trùng (cùng ngày + cùng mã) rồi lưu ---
    before_dedup = len(price_df)
    price_df = merge_with_existing(price_df, OUTPUT_FILE)
    print(f"\nSau khi gộp với file cũ + loại trùng: {len(price_df)} dòng (chênh {len(price_df) - before_dedup:+d} so với dữ liệu vừa lấy).")
    price_df.to_csv(OUTPUT_FILE, index=False)
    print(f"Đã lưu file {OUTPUT_FILE}")

    # --- Cảnh báo mã không đủ phiên để tính RS (tính trên dữ liệu đã gộp, không phải phần vừa lấy) ---
    session_counts = price_df[price_df["ticker"] != "VNINDEX"].groupby("ticker").size()
    insufficient = session_counts[session_counts < MIN_SESSIONS_REQUIRED]
    if not insufficient.empty:
        print(f"\nCẢNH BÁO: {len(insufficient)} mã có ít hơn {MIN_SESSIONS_REQUIRED} phiên "
              f"(sẽ bị loại khỏi bảng xếp hạng RS vì không đủ tính 4 khối):")
        for t, n in insufficient.items():
            print(f"  - {t}: {n} phiên")

    # --- Nhật ký nguồn + bản đồ sàn ---
    summary = fetcher.summary()
    save_json(SOURCE_LOG_FILE, summary)
    save_json(EXCHANGE_MAP_FILE, fetcher.exchange_map)
    c = summary["counts"]
    print(f"\nNguồn giá: TradingView {c['tv']} | vnstock {c['vnstock']} | không lấy được {c['none']}"
          + (f" | TradingView tắt: {summary['tv_disabled_reason']}" if summary["tv_disabled"] else ""))
    if got < WARN_FRESH_RATIO * len(tickers):
        print(f"::warning::Chỉ lấy được {got}/{len(tickers)} mã giá mới (dưới {WARN_FRESH_RATIO:.0%}).")
    if summary["tv_disabled"] and PRICE_SOURCE == "auto":
        print(f"::warning::TradingView bị tắt trong lần chạy này ({summary['tv_disabled_reason']}); đã dùng vnstock.")


if __name__ == "__main__":
    main()
