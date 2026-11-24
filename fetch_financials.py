"""
Script lấy dữ liệu báo cáo tài chính (BCTC) cho toàn bộ mã trong danh_sach_ma_theo_nganh.csv:
- Kết quả kinh doanh (income_statement)
- Cân đối kế toán (balance_sheet)
- Lưu chuyển tiền tệ (cash_flow)
(Bảng "ratio" KHÔNG còn lấy ở đây: vnstock 6 chỉ có ratio() ở nguồn fhsc với cấu trúc khác, hoặc tự tính bằng
 vnstock_quant.fa. Xem FIN_KEEP_OLD_RATIO bên dưới.)

VNSTOCK THẾ HỆ 6: nguồn khai báo bằng biến môi trường FIN_SOURCE (hoặc VNSTOCK_SOURCE), không có mặc định.
Theo tài liệu 6.0.1, báo cáo tài chính (Fundamental) hiện chỉ có ở nguồn `fhsc`; nguồn khác (vd tcbs) sẽ báo
VNSTOCK_ROUTE_UNSUPPORTED và script dừng sớm với thông báo rõ ràng. Khoá nguồn/khoá tài khoản đặt bằng
`vnstock keys set <nguồn>` / `vnstock login` trên máy, hoặc <NGUỒN>_API_KEY / VNSTOCK_API_KEY trong GitHub Secrets.
FIN_LIMIT=N: chỉ lấy N mã đầu và ghi ra financials_data.sample.json (chạy thử, KHÔNG đụng financials_data.json).
Biến môi trường tuỳ chọn: FIN_KEEP_OLD_RATIO=1 -> giữ nguyên bảng ratio CŨ trong financials_data.json cho các mã
(số liệu cũ, không cập nhật); mặc định không giữ.

Lưu ý quan trọng: app Streamlit chỉ đọc file dữ liệu có sẵn (không gọi API theo yêu cầu),
nên toàn bộ dữ liệu BCTC cho TẤT CẢ các mã phải được lấy sẵn ở đây và ghi vào
financials_data.json (rs_app đọc file này ở trang BCTC). Số lượng lệnh gọi API vì vậy khá lớn (số mã x 4 loại báo cáo)
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

from vnstock_adapter import (
    FIN_SOURCE_ENV, SOURCE_ENV, SourceNotConfigured, error_code, get_source, is_unsupported, make_fundamental,
)

SYMBOLS_FILE = "danh_sach_ma_theo_nganh.csv"
OUTPUT_FILE = "financials_data.json"

FIN_PERIOD = "quarter"      # "quarter" hoặc "year" - lấy theo quý để thấy biến động gần nhất
MAX_PERIODS = 12            # chỉ giữ lại tối đa 12 kỳ gần nhất mỗi báo cáo (đỡ nặng JSON)

REPORT_METHODS = {
    "income_statement": "income_statement",
    "balance_sheet": "balance_sheet",
    "cash_flow": "cash_flow",
}
KEEP_OLD_RATIO = os.environ.get("FIN_KEEP_OLD_RATIO", "").strip().lower() in ("1", "true", "yes")
MAX_UNSUPPORTED_STREAK = 3   # nguồn không hỗ trợ BCTC: dừng sớm sau ngần này lần lỗi liên tiếp thay vì lặp hết các mã

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


def to_legacy_wide(df: pd.DataFrame) -> pd.DataFrame:
    """Bảng `format="wide"` của vnstock 6 (hồ sơ v5: id, item, order, level, unit, line_code + các cột kỳ)
    -> cấu trúc đang lưu trong financials_data.json: item_id, item + các cột kỳ ('2026-Q2').
    Cột phụ (order, level, unit, line_code) bỏ đi vì app không dùng; `item_en` không còn (chỉ có tên tiếng Việt)."""
    df = df.rename(columns={"id": "item_id", "item_name": "item", "item_id": "item_id"})
    cols = [c for c in df.columns if c in META_COLS]
    if "item" not in cols or "item_id" not in cols:
        raise ValueError(f"bảng BCTC thiếu cột item/item_id (có: {list(df.columns)[:8]})")
    drop = {"order", "level", "unit", "line_code", "off_balance", "item_order", "item_level", "item_unit"}
    periods = [c for c in df.columns if c not in META_COLS and c not in drop]
    return df[["item", "item_id"] + periods].copy()


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


def fetch_ticker_financials(ticker: str, source: str, fundamental) -> tuple:
    """Lấy 3 loại báo cáo cho 1 mã. Mỗi báo cáo lỗi riêng lẻ bị bỏ qua (không chặn các báo cáo còn lại).
    Trả (kết quả, số_lần_lỗi_nguồn_không_hỗ_trợ)."""
    result = {}
    unsupported = 0
    equity = fundamental.equity(ticker)
    for key, method_name in REPORT_METHODS.items():
        try:
            method = getattr(equity, method_name)
            df = method(period=FIN_PERIOD, format="wide", source=source)
            if df is not None and not df.empty:
                result[key] = df_to_table(to_legacy_wide(df))
            else:
                print(f"  {ticker}.{key}: không có dữ liệu")
        except Exception as e:  # noqa: BLE001
            if is_unsupported(e):
                unsupported += 1
            print(f"  {ticker}.{key}: LỖI - {type(e).__name__} {error_code(e)}".rstrip())
        time.sleep(SLEEP_BETWEEN_REPORTS)

    return result, unsupported


def main():
    try:
        source = get_source(FIN_SOURCE_ENV, fallback_env=SOURCE_ENV)
    except SourceNotConfigured as e:
        print(f"LỖI: {e}")
        sys.exit(1)

    fundamental = make_fundamental()
    print(f"Nguồn BCTC: {source}")

    output_file = OUTPUT_FILE
    limit = int(os.environ.get("FIN_LIMIT", "0") or 0)
    symbols_df = pd.read_csv(SYMBOLS_FILE)
    symbols_df = symbols_df.rename(columns={"symbol": "ticker"})
    tickers = symbols_df["ticker"].dropna().unique().tolist()
    if limit > 0:
        tickers = tickers[:limit]
        output_file = "financials_data.sample.json"
        print(f"FIN_LIMIT={limit}: chạy thử, kết quả ghi vào {output_file}")
    total = len(tickers)
    print(f"Tổng số mã cần lấy BCTC: {total}")

    tickers_out = {}
    ok_count = 0
    consecutive_errors = 0
    unsupported_streak = 0

    for i, t in enumerate(tickers):
        prefix = f"[{i+1}/{total}]"
        try:
            data, unsupported = fetch_ticker_financials(t, source, fundamental)
        except Exception as e:  # noqa: BLE001
            print(f"{prefix} {t}: LỖI toàn bộ - {type(e).__name__} {error_code(e)}".rstrip())
            data, unsupported = {}, 0

        if data:
            tickers_out[t] = data
            ok_count += 1
            consecutive_errors = 0
            unsupported_streak = 0
            print(f"{prefix} {t}: OK ({len(data)}/{len(REPORT_METHODS)} báo cáo)")
        else:
            consecutive_errors += 1
            print(f"{prefix} {t}: không lấy được báo cáo nào")
            unsupported_streak = unsupported_streak + 1 if unsupported else 0

        if unsupported_streak >= MAX_UNSUPPORTED_STREAK:
            print(f"LỖI: nguồn '{source}' không hỗ trợ báo cáo tài chính (VNSTOCK_ROUTE_UNSUPPORTED). "
                  "Theo tài liệu vnstock 6.0.1 chỉ nguồn fhsc có Fundamental; đặt FIN_SOURCE=<nguồn khác>. Dừng sớm.")
            break

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

    if KEEP_OLD_RATIO and os.path.exists(OUTPUT_FILE):    # luôn đọc bản chính, kể cả khi chạy thử
        try:
            with open(OUTPUT_FILE, encoding="utf-8") as f:
                old = json.load(f).get("tickers", {})
            kept = 0
            for t, tables in tickers_out.items():
                if "ratio" in old.get(t, {}):
                    tables["ratio"] = old[t]["ratio"]   # số liệu CŨ, không cập nhật
                    kept += 1
            print(f"FIN_KEEP_OLD_RATIO: giữ bảng ratio CŨ (không cập nhật) cho {kept} mã")
        except (OSError, ValueError) as e:
            print(f"CẢNH BÁO: không đọc được {OUTPUT_FILE} để giữ ratio cũ ({type(e).__name__})")

    output = {
        "updated_at": pd.Timestamp.now(tz="Asia/Ho_Chi_Minh").strftime("%d/%m/%Y %H:%M"),
        "period": FIN_PERIOD,
        "tickers": tickers_out,
    }
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)

    print(f"\nLấy thành công BCTC cho {ok_count}/{total} mã -> đã lưu {output_file}")


if __name__ == "__main__":
    main()
