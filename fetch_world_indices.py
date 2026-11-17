"""
Lấy chỉ số chứng khoán các nước (nến NGÀY, đủ OHLC) từ TradingView qua thư viện tvdatafeed
-> world_indices.json, để app Streamlit (rs_app) vẽ thẻ "Chỉ số chứng khoán thế giới" trên trang Vĩ mô.

- Mỗi chỉ số có danh sách (mã, sàn) ứng viên; thử lần lượt cho tới khi có dữ liệu (tên mã/sàn của TradingView
  đôi khi khác kỳ vọng). Mã nào dùng được sẽ được ghi vào JSON (trường "tv") để lần sau biết.
- Lỗi ở 1 chỉ số không ảnh hưởng các chỉ số khác. Chỉ số nào lần này không lấy được -> giữ nguyên dữ liệu cũ.
- Dữ liệu mới được GỘP vào dữ liệu cũ theo ngày (ngày trùng -> lấy bản mới), nên lịch sử không bị ngắn đi
  nếu 1 lần chạy ẩn danh chỉ trả về ít nến.

Biến môi trường (tuỳ chọn): TV_USERNAME / TV_PASSWORD (đăng nhập TradingView thay vì ẩn danh), WORLD_BARS.
Chạy thử trên máy có mạng: `python fetch_world_indices.py` (in ra mã/sàn nào dùng được cho từng chỉ số).
"""
import json
import os
import time
from datetime import datetime, timezone, timedelta

OUTPUT_FILE = "world_indices.json"
N_BARS = int(os.environ.get("WORLD_BARS", "2500"))   # ~10 năm nến ngày
KEEP_ROWS = 3500                                      # giới hạn số dòng giữ lại cho mỗi chỉ số
VN_TZ = timezone(timedelta(hours=7))

# (khoá, nhãn hiển thị, khu vực, [(mã TradingView, sàn), ...] ứng viên theo thứ tự thử)
INDICES = [
    # --- Mỹ ---
    ("SPX",    "S&P 500",            "Mỹ",         [("SPX", "SP"), ("SPX", "TVC")]),
    ("IXIC",   "Nasdaq Composite",   "Mỹ",         [("IXIC", "NASDAQ"), ("IXIC", "TVC")]),
    ("NDX",    "Nasdaq 100",         "Mỹ",         [("NDX", "NASDAQ"), ("NDX", "TVC")]),
    ("DJI",    "Dow Jones",          "Mỹ",         [("DJI", "DJ"), ("DJI", "TVC")]),
    ("VIX",    "VIX (biến động)",    "Mỹ",         [("VIX", "CBOE"), ("VIX", "TVC")]),
    # --- Châu Á ---
    ("NI225",  "Nikkei 225 (Nhật)",  "Châu Á",     [("NI225", "TVC"), ("NKY", "TVC")]),
    ("HSI",    "Hang Seng (HK)",     "Châu Á",     [("HSI", "HSI"), ("HSI", "TVC")]),
    ("SHCOMP", "Thượng Hải (TQ)",    "Châu Á",     [("000001", "SSE"), ("SHCOMP", "SSE")]),
    ("CSI300", "CSI 300 (TQ)",       "Châu Á",     [("000300", "SSE"), ("CSI300", "SSE")]),
    ("KOSPI",  "KOSPI (Hàn Quốc)",   "Châu Á",     [("KOSPI", "KRX"), ("KS11", "TVC")]),
    ("TWII",   "TAIEX (Đài Loan)",   "Châu Á",     [("TWII", "TWSE"), ("TAIEX", "TWSE")]),
    ("NIFTY",  "Nifty 50 (Ấn Độ)",   "Châu Á",     [("NIFTY", "NSE"), ("NIFTY", "TVC")]),
    ("SENSEX", "Sensex (Ấn Độ)",     "Châu Á",     [("SENSEX", "BSE"), ("SENSEX", "TVC")]),
    # --- Đông Nam Á ---
    ("JCI",    "Jakarta (Indonesia)", "Đông Nam Á", [("COMPOSITE", "IDX"), ("JCI", "IDX")]),
    ("STI",    "Straits Times (Singapore)", "Đông Nam Á", [("STI", "TVC"), ("STI", "SGX")]),
    ("SET",    "SET (Thái Lan)",     "Đông Nam Á", [("SET", "SET"), ("SET", "TVC")]),
    ("KLCI",   "FBM KLCI (Malaysia)", "Đông Nam Á", [("FBMKLCI", "MYX"), ("KLCI", "MYX")]),
    ("PSEI",   "PSEi (Philippines)", "Đông Nam Á", [("PSEI", "PSE"), ("PSEI", "TVC")]),
    # --- Châu Âu ---
    ("UKX",    "FTSE 100 (Anh)",     "Châu Âu",    [("UKX", "TVC"), ("UKX", "FTSE")]),
    ("DAX",    "DAX (Đức)",          "Châu Âu",    [("DAX", "XETR"), ("DAX", "TVC")]),
    ("CAC40",  "CAC 40 (Pháp)",      "Châu Âu",    [("CAC40", "TVC"), ("PX1", "EURONEXT")]),
    ("SX5E",   "Euro Stoxx 50",      "Châu Âu",    [("SX5E", "TVC"), ("SX5E", "EUREX")]),
    # --- Châu Đại Dương ---
    ("XJO",    "ASX 200 (Úc)",       "Châu Đại Dương", [("XJO", "ASX"), ("XJO", "TVC")]),
]


def _rows(df):
    """DataFrame tvdatafeed -> [[YYYY-MM-DD, open, high, low, close], ...] (bỏ dòng thiếu giá)."""
    out = []
    for idx, r in df[["open", "high", "low", "close"]].dropna().iterrows():
        out.append([idx.strftime("%Y-%m-%d")] + [round(float(r[c]), 2) for c in ("open", "high", "low", "close")])
    return out


def fetch_one(tv, Interval, key, candidates):
    """Thử lần lượt từng (mã, sàn); trả (rows, 'SÀN:MÃ') hoặc (None, None)."""
    for symbol, exchange in candidates:
        for attempt in range(2):
            try:
                df = tv.get_hist(symbol=symbol, exchange=exchange, interval=Interval.in_daily, n_bars=N_BARS)
                if df is not None and not df.empty:
                    rows = _rows(df)
                    if rows:
                        return rows, f"{exchange}:{symbol}"
                break  # trả rỗng -> không retry cùng mã, sang ứng viên kế
            except Exception as e:  # noqa: BLE001
                print(f"  {key} {exchange}:{symbol}: lỗi lần {attempt + 1} - {type(e).__name__}: {e}")
                time.sleep(3)
    return None, None


def merge(old_rows, new_rows):
    d = {r[0]: r for r in (old_rows or [])}
    d.update({r[0]: r for r in new_rows})
    return [d[k] for k in sorted(d)][-KEEP_ROWS:]


def main():
    from tvDatafeed import TvDatafeed, Interval
    user, pwd = os.environ.get("TV_USERNAME"), os.environ.get("TV_PASSWORD")
    tv = TvDatafeed(user, pwd) if user and pwd else TvDatafeed()
    print(f"TradingView: {'đã đăng nhập' if user and pwd else 'ẩn danh'}; {len(INDICES)} chỉ số, {N_BARS} nến/chỉ số")

    try:
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            old = (json.load(f) or {}).get("indices", {})
    except (OSError, ValueError):
        old = {}

    out, ok, fail = {}, 0, []
    for key, label, region, candidates in INDICES:
        rows, tvsym = fetch_one(tv, Interval, key, candidates)
        prev = old.get(key) or {}
        if rows:
            data = merge(prev.get("data"), rows)
            out[key] = {"label": label, "region": region, "tv": tvsym, "data": data}
            ok += 1
            print(f"  {key} ({label}) <- {tvsym}: {len(rows)} nến mới, tổng {len(data)}, gần nhất {data[-1]}")
        else:
            fail.append(key)
            print(f"  {key} ({label}): không lấy được" + (" - giữ dữ liệu cũ" if prev.get("data") else ""))
            if prev.get("data"):
                out[key] = {**prev, "label": label, "region": region}
        time.sleep(1)

    if not out:
        print("CẢNH BÁO: không có dữ liệu nào - giữ nguyên file cũ (nếu có).")
        return

    payload = {"updated_at": datetime.now(VN_TZ).strftime("%d/%m/%Y %H:%M"), "indices": out}
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Đã lưu {OUTPUT_FILE}: {ok}/{len(INDICES)} chỉ số cập nhật mới"
          + (f"; lỗi: {', '.join(fail)}" if fail else ""))


if __name__ == "__main__":
    main()
