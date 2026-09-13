"""
Script lấy dữ liệu vĩ mô từ FRED (Mỹ), World Bank (Việt Nam) và vnstock (Việt Nam).
Lưu kết quả vào macro_data.json để generate_report.py đọc và hiển thị trên dashboard.

Nguồn:
- FRED API (stlouisfed.org): DXY, 6 cặp tiền, CPI Mỹ, lãi suất Fed, GDP Mỹ
- World Bank API (không cần key): CPI VN, GDP VN, FDI VN, thất nghiệp, XNK, cán cân
  vãng lai, cung tiền M2, sản xuất công nghiệp — theo NĂM
- vnstock (không cần key riêng, dùng chung VNSTOCK_API_KEY): tỷ giá USD/VND
  (Vietcombank) và giá vàng SJC — theo NGÀY. Vì 2 hàm này của vnstock chỉ trả về
  giá trị tại 1 ngày cụ thể (không có sẵn "start/end" như FRED), lịch sử được xây
  dần: mỗi lần script chạy sẽ đọc lại macro_data.json cũ, chỉ tải bù các ngày còn
  thiếu (từ ngày cuối cùng đã có tới hôm nay) rồi nối vào, thay vì tải lại từ đầu.

Cách dùng:
- Local : đặt biến môi trường FRED_API_KEY và VNSTOCK_API_KEY rồi chạy `python fetch_macro.py`
- GitHub Actions: đọc key từ GitHub Secret FRED_API_KEY / VNSTOCK_API_KEY
"""

import os
import sys
import json
import time
from datetime import datetime, timezone, timedelta

import pandas as pd

FRED_API_KEY    = os.environ.get("FRED_API_KEY")
VNSTOCK_API_KEY = os.environ.get("VNSTOCK_API_KEY")
OUTPUT_FILE     = "macro_data.json"
VN_TZ           = timezone(timedelta(hours=7))

# Số ngày tối đa tải bù (backfill) trong 1 lần chạy cho dữ liệu vnstock (tỷ giá/vàng).
# Lần chạy đầu tiên (chưa có lịch sử) sẽ backfill BOOTSTRAP_DAYS ngày gần nhất.
# Các lần chạy sau chỉ tải bù đúng số ngày còn thiếu (thường chỉ 1 ngày/lần chạy
# hàng ngày), MAX_BACKFILL_DAYS chỉ là chặn trên đề phòng script bị gián đoạn lâu ngày.
BOOTSTRAP_DAYS    = 60
MAX_BACKFILL_DAYS = 90
MAX_HISTORY_POINTS = 500  # giới hạn số điểm lưu lại cho mỗi series vnstock, tránh phình file mãi

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
    "UNEMPLOYMENT_VN": {
        "id"         : "SL.UEM.TOTL.ZS",
        "label"      : "Tỷ lệ thất nghiệp Việt Nam (%)",
        "group"      : "Kinh tế Việt Nam",
        "description": "Tỷ lệ thất nghiệp trên tổng lực lượng lao động của Việt Nam",
    },
    "EXPORT_VN": {
        "id"         : "NE.EXP.GNFS.ZS",
        "label"      : "Xuất khẩu hàng hóa & dịch vụ (%GDP)",
        "group"      : "Xuất nhập khẩu",
        "description": "Giá trị xuất khẩu hàng hóa và dịch vụ, tính theo % GDP",
    },
    "IMPORT_VN": {
        "id"         : "NE.IMP.GNFS.ZS",
        "label"      : "Nhập khẩu hàng hóa & dịch vụ (%GDP)",
        "group"      : "Xuất nhập khẩu",
        "description": "Giá trị nhập khẩu hàng hóa và dịch vụ, tính theo % GDP",
    },
    "CURRENT_ACCOUNT_VN": {
        "id"         : "BN.CAB.XOKA.GD.ZS",
        "label"      : "Cán cân vãng lai (%GDP)",
        "group"      : "Xuất nhập khẩu",
        "description": "Cán cân vãng lai của Việt Nam, tính theo % GDP (dương = thặng dư)",
    },
    "M2_GROWTH_VN": {
        "id"         : "FM.LBL.BMNY.ZG",
        "label"      : "Tăng trưởng cung tiền M2 (%)",
        "group"      : "Kinh tế Việt Nam",
        "description": "Tốc độ tăng trưởng cung tiền rộng (M2) hàng năm của Việt Nam",
    },
    "INDPROD_VN": {
        "id"         : "NV.IND.TOTL.KD.ZG",
        "label"      : "Tăng trưởng sản xuất công nghiệp (%)",
        "group"      : "Kinh tế Việt Nam",
        "description": "Tốc độ tăng trưởng giá trị gia tăng ngành công nghiệp của Việt Nam",
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


def load_existing_macro():
    """Đọc lại macro_data.json cũ (nếu có) để lấy lịch sử series vnstock (tỷ giá/vàng)
    đã tích luỹ từ các lần chạy trước — vì 2 hàm này chỉ trả giá trị tại 1 ngày,
    không có sẵn "start/end" như FRED nên phải tự nối dần theo thời gian."""
    if not os.path.exists(OUTPUT_FILE):
        return {}
    try:
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            old = json.load(f)
        return old.get("series", {})
    except Exception as e:
        print(f"  CẢNH BÁO: Không đọc được {OUTPUT_FILE} cũ để lấy lịch sử vnstock: {e}")
        return {}


def _missing_dates(existing_values, bootstrap_days=BOOTSTRAP_DAYS, max_backfill_days=MAX_BACKFILL_DAYS):
    """Tính danh sách ngày (chuỗi YYYY-MM-DD) còn thiếu, cần tải bù, dựa trên điểm dữ liệu
    cuối cùng đã có. Nếu chưa có dữ liệu nào (lần chạy đầu) -> backfill bootstrap_days ngày
    gần nhất. Nếu đã có -> chỉ tải từ ngày sau điểm cuối tới hôm nay (chặn trên
    max_backfill_days đề phòng script bị gián đoạn lâu ngày không chạy)."""
    today = datetime.now(VN_TZ).date()

    if not existing_values:
        start = today - timedelta(days=bootstrap_days)
    else:
        last_date_str = max(v[0] for v in existing_values)
        last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
        start = last_date + timedelta(days=1)
        earliest_allowed = today - timedelta(days=max_backfill_days)
        if start < earliest_allowed:
            start = earliest_allowed

    if start > today:
        return []

    n_days = (today - start).days + 1
    return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n_days)]


def fetch_vnstock_retail(existing_series):
    """Lấy tỷ giá USD/VND (Vietcombank) và giá vàng SJC qua vnstock (dùng chung
    VNSTOCK_API_KEY, không cần license riêng). 2 hàm này chỉ trả về giá trị tại
    1 ngày cụ thể -> lịch sử được tích luỹ dần qua từng lần chạy (xem _missing_dates).
    Trả về dict {key: {meta, values}}, đã gộp với lịch sử cũ."""
    try:
        from vnstock import Retail
    except ImportError:
        print("  LỖI: Chưa cài vnstock. Chạy: pip install vnstock")
        return {}

    if VNSTOCK_API_KEY:
        try:
            import vnai
            vnai.setup_api_key(VNSTOCK_API_KEY)
        except Exception as e:
            print(f"  CẢNH BÁO: Không setup được VNSTOCK_API_KEY ({e}), vẫn thử chạy tiếp vì "
                  f"tỷ giá/vàng không bắt buộc cần key.")

    retail = Retail()
    results = {}

    # --- Tỷ giá USD/VND (Vietcombank) ---
    old_values = existing_series.get("USDVND", {}).get("values", [])
    dates_to_fetch = _missing_dates(old_values)
    new_points = []
    for d in dates_to_fetch:
        try:
            df = retail.exchange_rate(date=d)
            if df is None or df.empty:
                continue
            row = df[df["currency_code"].astype(str).str.upper() == "USD"]
            if row.empty:
                continue
            sell = row.iloc[0]["sell"]
            if pd.notna(sell):
                new_points.append([d, round(float(sell), 2)])
        except Exception as e:
            print(f"  vnstock [USDVND] {d}: bỏ qua ({type(e).__name__})")
        time.sleep(1)  # lịch sự với server Vietcombank, tránh gọi dồn dập

    merged = {v[0]: v[1] for v in old_values}
    merged.update({p[0]: p[1] for p in new_points})
    values = sorted(merged.items())[-MAX_HISTORY_POINTS:]
    values = [[d, v] for d, v in values]
    results["USDVND"] = {
        "label"      : "Tỷ giá USD/VND (Vietcombank, bán ra)",
        "group"      : "Tỷ giá & Vàng (Việt Nam)",
        "description": "Tỷ giá bán USD/VND niêm yết tại Vietcombank (qua vnstock)",
        "freq"       : "daily",
        "values"     : values,
    }
    print(f"  vnstock [USDVND]: OK ({len(new_points)} điểm mới, {len(values)} điểm tổng)")

    # --- Giá vàng SJC ---
    old_values_gold = existing_series.get("GOLD_SJC", {}).get("values", [])
    dates_to_fetch_gold = _missing_dates(old_values_gold)
    new_points_gold = []
    for d in dates_to_fetch_gold:
        try:
            df = retail.gold(source="sjc", date=d)
            if df is None or df.empty:
                continue
            # Ưu tiên dòng "SJC 1L" (vàng miếng 1 lượng, chuẩn tham chiếu phổ biến nhất);
            # nếu không tìm thấy tên khớp thì lấy dòng đầu tiên trả về.
            mask = df["name"].astype(str).str.contains("1L", case=False, na=False)
            row = df[mask].iloc[0] if mask.any() else df.iloc[0]
            sell = row["sell_price"]
            if pd.notna(sell):
                new_points_gold.append([d, round(float(sell), 2)])
        except Exception as e:
            print(f"  vnstock [GOLD_SJC] {d}: bỏ qua ({type(e).__name__})")
        time.sleep(1)

    merged_gold = {v[0]: v[1] for v in old_values_gold}
    merged_gold.update({p[0]: p[1] for p in new_points_gold})
    values_gold = sorted(merged_gold.items())[-MAX_HISTORY_POINTS:]
    values_gold = [[d, v] for d, v in values_gold]
    results["GOLD_SJC"] = {
        "label"      : "Giá vàng SJC (nghìn đồng/lượng, bán ra)",
        "group"      : "Tỷ giá & Vàng (Việt Nam)",
        "description": "Giá bán vàng miếng SJC 1 lượng (qua vnstock)",
        "freq"       : "daily",
        "values"     : values_gold,
    }
    print(f"  vnstock [GOLD_SJC]: OK ({len(new_points_gold)} điểm mới, {len(values_gold)} điểm tổng)")

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

    print("\n[3] vnstock - Vietcombank & SJC (Việt Nam)...")
    if not VNSTOCK_API_KEY:
        print("  Bỏ qua: không tìm thấy VNSTOCK_API_KEY trong biến môi trường.")
        vnstock_data = {}
    else:
        existing_series = load_existing_macro()
        vnstock_data = fetch_vnstock_retail(existing_series)

    # Gộp lại
    all_data = {**fred_data, **wb_data, **vnstock_data}

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
