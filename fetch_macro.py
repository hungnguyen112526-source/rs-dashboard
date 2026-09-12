"""
Script lấy dữ liệu vĩ mô từ FRED (Mỹ) và World Bank (Việt Nam).
Lưu kết quả vào macro_data.json để generate_report.py đọc và hiển thị trên dashboard.

Nguồn:
- FRED API (stlouisfed.org): DXY, 6 cặp tiền, CPI Mỹ, lãi suất Fed, GDP Mỹ
- World Bank API (không cần key): CPI VN, GDP VN, FDI

Cách dùng:
- Local : đặt biến môi trường FRED_API_KEY rồi chạy `python fetch_macro.py`
- GitHub Actions: đọc key từ GitHub Secret FRED_API_KEY
"""

import os
import sys
import json
from datetime import datetime, timezone, timedelta

import pandas as pd

FRED_API_KEY = os.environ.get("FRED_API_KEY")
OUTPUT_FILE  = "macro_data.json"
VN_TZ        = timezone(timedelta(hours=7))

# ============================================================
# Danh sách series FRED cần lấy
# ============================================================
FRED_SERIES = {
    # --- Chỉ số Dollar & Tỷ giá ---
    "DXY": {
        "id"         : "DTWEXBGS",
        "label"      : "DXY (Dollar Index)",
        "group"      : "Tỷ giá & Dollar",
        "freq"       : "daily",
        "description": "Chỉ số sức mạnh đồng Dollar Mỹ so với rổ 6 đồng tiền chính",
    },
    "EUR/USD": {
        "id"         : "DEXUSEU",
        "label"      : "EUR/USD",
        "group"      : "Tỷ giá & Dollar",
        "freq"       : "daily",
        "description": "Tỷ giá Euro / Đô la Mỹ (trọng số 57.6% trong DXY)",
    },
    "USD/JPY": {
        "id"         : "DEXJPUS",
        "label"      : "USD/JPY",
        "group"      : "Tỷ giá & Dollar",
        "freq"       : "daily",
        "description": "Tỷ giá Đô la Mỹ / Yên Nhật (trọng số 13.6% trong DXY)",
    },
    "GBP/USD": {
        "id"         : "DEXUSUK",
        "label"      : "GBP/USD",
        "group"      : "Tỷ giá & Dollar",
        "freq"       : "daily",
        "description": "Tỷ giá Bảng Anh / Đô la Mỹ (trọng số 11.9% trong DXY)",
    },
    "USD/CAD": {
        "id"         : "DEXCAUS",
        "label"      : "USD/CAD",
        "group"      : "Tỷ giá & Dollar",
        "freq"       : "daily",
        "description": "Tỷ giá Đô la Mỹ / Đô la Canada (trọng số 9.1% trong DXY)",
    },
    "USD/SEK": {
        "id"         : "DEXSDUS",
        "label"      : "USD/SEK",
        "group"      : "Tỷ giá & Dollar",
        "freq"       : "daily",
        "description": "Tỷ giá Đô la Mỹ / Krona Thụy Điển (trọng số 4.2% trong DXY)",
    },
    "USD/CHF": {
        "id"         : "DEXSZUS",
        "label"      : "USD/CHF",
        "group"      : "Tỷ giá & Dollar",
        "freq"       : "daily",
        "description": "Tỷ giá Đô la Mỹ / Franc Thụy Sĩ (trọng số 3.6% trong DXY)",
    },
    # --- Lãi suất & Tiền tệ Mỹ ---
    "FedFunds": {
        "id"         : "FEDFUNDS",
        "label"      : "Lãi suất Fed (%)",
        "group"      : "Lãi suất & Tiền tệ Mỹ",
        "freq"       : "monthly",
        "description": "Lãi suất quỹ liên bang Mỹ (Federal Funds Rate) — công cụ chính sách tiền tệ của Fed",
    },
    "US10Y": {
        "id"         : "DGS10",
        "label"      : "Lợi suất TPCP Mỹ 10Y (%)",
        "group"      : "Lãi suất & Tiền tệ Mỹ",
        "freq"       : "daily",
        "description": "Lợi suất trái phiếu Chính phủ Mỹ kỳ hạn 10 năm — thước đo kỳ vọng lãi suất dài hạn",
    },
    # --- Lạm phát Mỹ ---
    "CPI_US": {
        "id"         : "CPIAUCSL",
        "label"      : "CPI Mỹ (YoY %)",
        "group"      : "Lạm phát",
        "freq"       : "monthly",
        "description": "Chỉ số giá tiêu dùng Mỹ — thước đo lạm phát chính của Mỹ",
        "transform"  : "yoy_pct",   # tính % thay đổi so với cùng kỳ năm trước
    },
    "PCE": {
        "id"         : "PCEPI",
        "label"      : "PCE Mỹ (YoY %)",
        "group"      : "Lạm phát",
        "freq"       : "monthly",
        "description": "Chi tiêu tiêu dùng cá nhân — thước đo lạm phát Fed ưa thích",
        "transform"  : "yoy_pct",
    },
}

# ============================================================
# Danh sách series World Bank cần lấy (Việt Nam)
# ============================================================
WORLDBANK_SERIES = {
    "CPI_VN": {
        "id"         : "FP.CPI.TOTL.ZG",
        "label"      : "CPI Việt Nam (YoY %)",
        "group"      : "Lạm phát",
        "description": "Tỷ lệ lạm phát hàng năm của Việt Nam (nguồn World Bank)",
    },
    "GDP_VN": {
        "id"         : "NY.GDP.MKTP.KD.ZG",
        "label"      : "GDP Việt Nam (tăng trưởng %)",
        "group"      : "Kinh tế Việt Nam",
        "description": "Tốc độ tăng trưởng GDP thực của Việt Nam hàng năm",
    },
    "FDI_VN": {
        "id"         : "BX.KLT.DINV.CD.WD",
        "label"      : "FDI Việt Nam (USD)",
        "group"      : "Kinh tế Việt Nam",
        "description": "Vốn đầu tư trực tiếp nước ngoài vào Việt Nam",
    },
}

START_DATE = "2018-01-01"   # lấy từ năm 2018 để có đủ lịch sử


def fetch_fred(api_key):
    """Lấy toàn bộ series FRED, trả về dict {key: {meta, values}}"""
    try:
        from fredapi import Fred
    except ImportError:
        print("LỖI: Chưa cài fredapi. Chạy: pip install fredapi")
        return {}

    fred    = Fred(api_key=api_key)
    results = {}

    for key, meta in FRED_SERIES.items():
        try:
            series = fred.get_series(meta["id"], observation_start=START_DATE)
            series = series.dropna()

            # Chuyển đổi nếu cần
            if meta.get("transform") == "yoy_pct":
                series = series.pct_change(periods=12) * 100  # 12 tháng
                series = series.dropna()

            values = [
                [d.strftime("%Y-%m-%d"), round(float(v), 4)]
                for d, v in series.items()
            ]

            results[key] = {
                "label"      : meta["label"],
                "group"      : meta["group"],
                "description": meta["description"],
                "freq"       : meta.get("freq", "daily"),
                "values"     : values,
            }
            print(f"  FRED [{key}]: OK ({len(values)} điểm)")

        except Exception as e:
            print(f"  FRED [{key}]: LỖI - {e}")

    return results


def fetch_worldbank():
    """Lấy dữ liệu Việt Nam từ World Bank API (không cần key), trả về dict"""
    try:
        import wbgapi as wb
    except ImportError:
        print("LỖI: Chưa cài wbgapi. Chạy: pip install wbgapi")
        return {}

    results = {}
    start_year = int(START_DATE[:4])

    for key, meta in WORLDBANK_SERIES.items():
        try:
            df = wb.data.DataFrame(meta["id"], "VNM", mrv=30)
            if df.empty:
                print(f"  WorldBank [{key}]: Không có dữ liệu")
                continue

            # df có index là mã chỉ tiêu, cột là năm dạng "YR2020"
            row = df.iloc[0]
            values = []
            for col, val in row.items():
                year_str = str(col).replace("YR", "")
                try:
                    year = int(year_str)
                except ValueError:
                    continue
                if year < start_year:
                    continue
                if pd.notna(val):
                    values.append([f"{year}-01-01", round(float(val), 4)])

            values.sort(key=lambda x: x[0])

            results[key] = {
                "label"      : meta["label"],
                "group"      : meta["group"],
                "description": meta["description"],
                "freq"       : "yearly",
                "values"     : values,
            }
            print(f"  WorldBank [{key}]: OK ({len(values)} điểm)")

        except Exception as e:
            print(f"  WorldBank [{key}]: LỖI - {e}")

    return results


def main():
    if not FRED_API_KEY:
        print("LỖI: Không tìm thấy FRED_API_KEY trong biến môi trường.")
        sys.exit(1)

    print("=== Lấy dữ liệu vĩ mô ===")

    print("\n[1] FRED API (Mỹ)...")
    fred_data = fetch_fred(FRED_API_KEY)

    print("\n[2] World Bank API (Việt Nam)...")
    wb_data = fetch_worldbank()

    # Gộp lại
    all_data = {**fred_data, **wb_data}

    if not all_data:
        print("\nCẢNH BÁO: Không lấy được dữ liệu nào — giữ nguyên file cũ nếu có.")
        sys.exit(0)

    # Nhóm các series theo group để hiển thị trên dashboard
    groups = {}
    for key, meta in all_data.items():
        g = meta["group"]
        if g not in groups:
            groups[g] = []
        groups[g].append(key)

    output = {
        "updated_at": datetime.now(timezone.utc).astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M"),
        "groups"    : groups,
        "series"    : all_data,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nĐã lưu {OUTPUT_FILE} ({len(all_data)} series, {len(groups)} nhóm)")


if __name__ == "__main__":
    main()
