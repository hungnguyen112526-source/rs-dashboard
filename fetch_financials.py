"""
Script lấy dữ liệu báo cáo tài chính (BCTC) cho toàn bộ mã trong danh_sach_ma_theo_nganh.csv:
- Kết quả kinh doanh (income_statement)
- Cân đối kế toán (balance_sheet)
- Lưu chuyển tiền tệ (cash_flow)
- Chỉ số tài chính (ratio)

Dùng để chạy tự động (GitHub Actions) — không cần nhập API key tương tác, cùng cơ chế
với fetch_data.py (VNSTOCK_API_KEY lấy từ biến môi trường / GitHub Secret).

Lưu ý quan trọng: vì đây là trang web tĩnh (không có server chạy API theo yêu cầu),
toàn bộ dữ liệu BCTC cho TẤT CẢ các mã phải được lấy sẵn ở đây và nhúng vào
financials_data.json, rồi generate_report.py mới đọc file này để render trang
docs/financials.html. Số lượng lệnh gọi API vì vậy khá lớn (số mã x 4 loại báo cáo)
-> script có nghỉ giữa các lần gọi để tránh bị giới hạn API, và lỗi ở từng mã/báo cáo
không làm hỏng toàn bộ kết quả (bỏ qua mã/báo cáo đó, các mã khác vẫn chạy tiếp).

Cấu trúc file output (financials_data.json):
{
  "updated_at": "dd/mm/YYYY HH:MM",
  "period": "quarter",
  "tickers": {
    "<MA_CO_PHIEU>": {
      "income_statement": {"columns": [...], "rows": [[...], ...]},
      "balance_sheet":    {"columns": [...], "rows": [[...], ...]},
      "cash_flow":        {"columns": [...], "rows": [[...], ...]},
      "ratio":            {"columns": [...], "rows": [[...], ...]}
    },
    ...
  }
}
Mỗi báo cáo lưu dạng "columns" + "rows" (thay vì list các dict lặp lại tên cột) để file
JSON nhỏ gọn hơn. Hàng đầu tiên trong "rows" là kỳ báo cáo gần nhất (đã sắp xếp giảm dần
theo năm/quý khi xác định được cột năm/quý trong dữ liệu trả về).
"""

import os
import sys
import time
import json

import numpy as np
import pandas as pd
import vnai
from vnstock import Finance

API_KEY = os.environ.get("VNSTOCK_API_KEY")
SYMBOLS_FILE = "danh_sach_ma_theo_nganh.csv"
OUTPUT_FILE = "financials_data.json"

FIN_SOURCE = "VCI"          # nguồn dữ liệu BCTC (xem vnstocks.com/docs/vnstock/bao-cao-tai-chinh)
FIN_PERIOD = "quarter"      # "quarter" hoặc "year" - lấy theo quý để thấy biến động gần nhất
MAX_PERIODS = 12            # chỉ giữ lại tối đa 12 kỳ gần nhất mỗi báo cáo (đỡ nặng JSON)

REPORT_METHODS = {
    "income_statement": "income_statement",
    "balance_sheet": "balance_sheet",
    "cash_flow": "cash_flow",
    "ratio": "ratio",
}

SLEEP_BETWEEN_REPORTS = 0.6   # nghỉ giữa các lần gọi report trong cùng 1 mã
SLEEP_BETWEEN_TICKERS = 1.5   # nghỉ giữa các mã


def to_jsonable(v):
    """Chuyển 1 giá trị (có thể là numpy/pandas type) thành kiểu JSON serialize được."""
    if v is None:
        return None
    try:
        if isinstance(v, (float, np.floating)) and pd.isna(v):
            return None
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating,)):
            return float(v)
        if isinstance(v, (np.bool_,)):
            return bool(v)
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (pd.Timestamp,)):
        return str(v.date())
    return v


META_COLS = ("item", "item_en", "item_id")


def trim_wide(df: pd.DataFrame, max_periods: int = MAX_PERIODS) -> pd.DataFrame:
    """Định dạng vnstock 4.x: MỖI DÒNG là 1 chỉ tiêu (item/item_en/item_id), MỖI CỘT là 1 kỳ
    (vd '2026-Q2'). Giữ TOÀN BỘ dòng chỉ tiêu, chỉ cắt bớt số cột kỳ: giữ max_periods kỳ mới nhất,
    xếp kỳ mới nhất sang trái. (Nhãn kỳ dạng 'YYYY-Qn'/'YYYY' sắp theo chữ cũng là sắp theo thời gian.)"""
    meta = [c for c in df.columns if c in META_COLS]
    periods = sorted((c for c in df.columns if c not in META_COLS), key=str, reverse=True)[:max_periods]
    return df[meta + periods]


def trim_and_sort(df: pd.DataFrame, max_rows: int = MAX_PERIODS) -> pd.DataFrame:
    """Sắp các kỳ báo cáo gần nhất lên đầu (nếu nhận ra được cột năm/quý), rồi chỉ giữ
    lại tối đa max_rows kỳ gần nhất. Không rõ cấu trúc cột -> giữ nguyên thứ tự gốc,
    chỉ cắt bớt để không phình JSON quá mức.

    Lưu ý: với bảng dạng 'chỉ tiêu theo dòng, kỳ theo cột' (có cột item_id) thì phải cắt theo CỘT
    (trim_wide); cắt theo dòng như dưới đây sẽ vứt mất các chỉ tiêu cuối bảng (vd lợi nhuận sau thuế)."""
    if df is None or df.empty:
        return df
    if "item_id" in df.columns:
        return trim_wide(df, max_rows)
    year_cols = [c for c in df.columns if "year" in str(c).lower()]
    sort_cols = []
    if year_cols:
        sort_cols.append(year_cols[0])
        q_cols = [
            c for c in df.columns
            if str(c).lower() in ("quarter", "lengthreport", "length_report", "period")
        ]
        if q_cols:
            sort_cols.append(q_cols[0])
    if sort_cols:
        try:
            df = df.sort_values(sort_cols, ascending=False)
        except Exception:
            pass
    return df.head(max_rows)


def df_to_table(df: pd.DataFrame) -> dict:
    """DataFrame -> {"columns": [...], "rows": [[...], ...]} (JSON-safe)."""
    df = trim_and_sort(df)
    columns = [str(c) for c in df.columns]
    rows = [[to_jsonable(v) for v in row] for row in df.itertuples(index=False, name=None)]
    return {"columns": columns, "rows": rows}


def fetch_ticker_financials(ticker: str) -> dict:
    """Lấy cả 4 loại báo cáo cho 1 mã. Mỗi báo cáo lỗi riêng lẻ bị bỏ qua (không chặn
    các báo cáo còn lại của mã đó)."""
    result = {}
    try:
        finance = Finance(symbol=ticker, source=FIN_SOURCE)
    except Exception as e:
        print(f"  {ticker}: LỖI khởi tạo Finance - {type(e).__name__}")
        return result

    for key, method_name in REPORT_METHODS.items():
        try:
            method = getattr(finance, method_name)
            df = method(period=FIN_PERIOD)
            if df is not None and not df.empty:
                result[key] = df_to_table(df)
            else:
                print(f"  {ticker}.{key}: không có dữ liệu")
        except Exception as e:
            print(f"  {ticker}.{key}: LỖI - {type(e).__name__}")
        time.sleep(SLEEP_BETWEEN_REPORTS)

    return result


def main():
    if not API_KEY:
        print("LỖI: Không tìm thấy VNSTOCK_API_KEY trong biến môi trường.")
        sys.exit(1)

    vnai.setup_api_key(API_KEY)

    symbols_df = pd.read_csv(SYMBOLS_FILE)
    symbols_df = symbols_df.rename(columns={"symbol": "ticker"})
    tickers = symbols_df["ticker"].dropna().unique().tolist()
    total = len(tickers)
    print(f"Tổng số mã cần lấy BCTC: {total}")

    tickers_out = {}
    ok_count = 0
    consecutive_errors = 0

    for i, t in enumerate(tickers):
        prefix = f"[{i+1}/{total}]"
        try:
            data = fetch_ticker_financials(t)
        except Exception as e:
            print(f"{prefix} {t}: LỖI toàn bộ - {type(e).__name__}")
            data = {}

        if data:
            tickers_out[t] = data
            ok_count += 1
            consecutive_errors = 0
            print(f"{prefix} {t}: OK ({len(data)}/4 báo cáo)")
        else:
            consecutive_errors += 1
            print(f"{prefix} {t}: không lấy được báo cáo nào")

        if consecutive_errors >= 5:
            print("   >> Nghi ngờ bị giới hạn API, tạm nghỉ 60 giây...")
            time.sleep(60)
            consecutive_errors = 0
        else:
            time.sleep(SLEEP_BETWEEN_TICKERS)

    if not tickers_out:
        print("CẢNH BÁO: Không lấy được BCTC cho mã nào cả — giữ nguyên file cũ (nếu có), không ghi đè.")
        # Không sys.exit(1): BCTC là phần phụ trợ, không nên chặn cả workflow (giống fetch_macro.py)
        return

    output = {
        "updated_at": pd.Timestamp.now(tz="Asia/Ho_Chi_Minh").strftime("%d/%m/%Y %H:%M"),
        "period": FIN_PERIOD,
        "tickers": tickers_out,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)

    print(f"\nLấy thành công BCTC cho {ok_count}/{total} mã -> đã lưu {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
