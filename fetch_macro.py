"""
Script lấy dữ liệu vĩ mô từ FRED (Mỹ), World Bank (Việt Nam) và yfinance (tỷ giá
USD/VND + giá vàng thế giới). Lưu kết quả vào macro_data.json để generate_report.py
đọc và hiển thị trên dashboard.

Nguồn:
- FRED API (stlouisfed.org): DXY, 6 cặp tiền, CPI Mỹ, lãi suất Fed, GDP Mỹ, và
  dự báo SEP (Summary of Economic Projections) của Fed — xem fetch_fed_projections()
- World Bank API (không cần key): CPI VN, GDP VN, FDI VN, thất nghiệp, XNK, cán cân
  vãng lai, cung tiền M2, sản xuất công nghiệp — theo NĂM
- yfinance (không cần key): tỷ giá USD/VND (ticker VND=X) và giá vàng thế giới
  (ticker GC=F, USD/troy ounce) — theo NGÀY.

  Lưu ý quan trọng: trước đây thử lấy tỷ giá niêm yết Vietcombank + giá vàng SJC bằng
  cách gọi thẳng API của các trang này, nhưng IP của GitHub Actions liên tục bị chặn
  (403/lỗi kết nối ở MỌI lần gọi, không phải ngẫu nhiên) -> đã bỏ hẳn cách này, chuyển
  sang yfinance vì đây là nguồn quốc tế, không chặn IP datacenter. Đánh đổi: số liệu là
  tỷ giá/giá vàng THỊ TRƯỜNG QUỐC TẾ, không phải giá niêm yết Vietcombank/SJC trong nước.
  yfinance cho tải cả 1 khoảng thời gian dài trong 1 lần gọi (khác Vietcombank/SJC chỉ
  cho lấy từng ngày một) nên code ở đây đơn giản hơn nhiều — không cần cơ chế tích luỹ
  dần/circuit breaker phức tạp như bản cũ nữa.

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

# Số vintage (đợt công bố SEP) gần nhất giữ lại cho biểu đồ dự báo Fed — mỗi năm Fed
# họp 4 lần (3/6/9/12) và công bố lại dự báo mỗi lần, giữ 3 vintage gần nhất là đủ để
# so sánh xu hướng thay đổi dự báo qua các kỳ mà không làm biểu đồ quá rối.
FED_PROJECTION_VINTAGES_TO_KEEP = 3

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


# ============================================================
# Tỷ giá USD/VND + giá vàng thế giới (qua yfinance)
# ============================================================
YFINANCE_SERIES = {
    "USDVND": {
        "ticker"     : "VND=X",
        "label"      : "Tỷ giá USD/VND (thị trường quốc tế)",
        "group"      : "Tỷ giá & Vàng (Việt Nam)",
        "description": "Tỷ giá USD/VND tổng hợp từ thị trường quốc tế qua yfinance — "
                        "KHÔNG phải giá niêm yết tại quầy Vietcombank (nguồn cũ liên tục bị "
                        "chặn IP khi chạy trên GitHub Actions nên đã đổi sang nguồn này).",
    },
    "GOLD_WORLD": {
        "ticker"     : "GC=F",
        "label"      : "Giá vàng thế giới (USD/oz)",
        "group"      : "Tỷ giá & Vàng (Việt Nam)",
        "description": "Giá vàng giao sau (COMEX) thị trường thế giới, đơn vị USD/troy ounce — "
                        "KHÔNG phải giá vàng miếng SJC trong nước (yfinance không có dữ liệu này).",
    },
}


def fetch_yfinance_retail():
    """Lấy tỷ giá USD/VND và giá vàng thế giới qua yfinance.

    Khác hẳn cách gọi Vietcombank/SJC trước đây (chỉ trả về giá trị tại 1 ngày cụ thể,
    phải tích luỹ dần qua từng lần chạy + cần circuit breaker vì hay bị chặn IP),
    yfinance cho tải CẢ MỘT KHOẢNG THỜI GIAN DÀI trong 1 lần gọi duy nhất (giống cách
    lấy FRED) -> code đơn giản hơn nhiều, không cần tích luỹ/circuit breaker nữa."""
    try:
        import yfinance as yf
    except ImportError:
        print("  LỖI: Chưa cài yfinance. Chạy: pip install yfinance")
        return {}

    results = {}

    for key, meta in YFINANCE_SERIES.items():
        try:
            hist = yf.Ticker(meta["ticker"]).history(start=START_DATE, interval="1d")
            if hist is None or hist.empty:
                print(f"  yfinance [{key}]: không có dữ liệu")
                continue

            values = [
                [d.strftime("%Y-%m-%d"), round(float(v), 4)]
                for d, v in hist["Close"].items()
                if pd.notna(v)
            ]
            if not values:
                print(f"  yfinance [{key}]: dữ liệu rỗng sau khi lọc")
                continue

            results[key] = {
                "label"      : meta["label"],
                "group"      : meta["group"],
                "description": meta["description"],
                "freq"       : "daily",
                "values"     : values,
            }
            print(f"  yfinance [{key}]: OK ({len(values)} điểm, {values[0][0]} -> {values[-1][0]})")

        except Exception as e:
            print(f"  yfinance [{key}]: LỖI - {type(e).__name__}: {e}")

    return results


# ============================================================
# Dự báo kinh tế của Fed (Summary of Economic Projections - SEP)
# ============================================================
FED_PROJECTIONS_SERIES = {
    "fed_funds_rate": {
        "id"   : "FEDTARMD",
        "label": "Dự báo Fed Funds Rate",
        "unit" : "Percent",
    },
    "core_pce": {
        "id"   : "JCXFEMD",
        "label": "Dự báo Lạm phát Core PCE",
        "unit" : "Fourth Quarter to Fourth Quarter Percent Change",
    },
}


def fetch_fed_projections(api_key):
    """Lấy dữ liệu "Summary of Economic Projections" (SEP) của Fed — khác hẳn các
    series FRED thông thường: đây là dữ liệu dự báo công bố lại theo từng đợt họp FOMC
    (4 lần/năm: 3/6/9/12), mỗi đợt ("vintage") là 1 bộ dự báo riêng cho vài năm tới.

    Dùng get_series_all_releases() của fredapi để lấy TOÀN BỘ lịch sử các lần công bố
    (trả về cột 'date' = năm được dự báo, 'realtime_start' = ngày công bố đợt đó,
    'value' = giá trị dự báo), rồi nhóm theo 'realtime_start' để tách từng vintage,
    chỉ giữ lại FED_PROJECTION_VINTAGES_TO_KEEP vintage gần nhất — giống cách hiển thị
    nhiều cột màu chồng nhau theo từng đợt công bố (xem ảnh mẫu người dùng cung cấp)."""
    try:
        from fredapi import Fred
    except ImportError:
        print("  LỖI: Chưa cài fredapi.")
        return {}

    fred = Fred(api_key=api_key)
    results = {}

    for key, meta in FED_PROJECTIONS_SERIES.items():
        try:
            df = fred.get_series_all_releases(meta["id"])
            if df is None or df.empty:
                print(f"  Fed projection [{key}]: không có dữ liệu")
                continue

            df = df.copy()
            df["year"] = pd.to_datetime(df["date"]).dt.year
            df["realtime_start"] = pd.to_datetime(df["realtime_start"])

            all_vintages = sorted(df["realtime_start"].unique(), reverse=True)
            keep_vintages = sorted(all_vintages[:FED_PROJECTION_VINTAGES_TO_KEEP])  # tăng dần cho dễ đọc

            vintage_list = []
            for v in keep_vintages:
                sub = df[df["realtime_start"] == v]
                data_by_year = {
                    str(int(row["year"])): round(float(row["value"]), 4)
                    for _, row in sub.iterrows()
                    if pd.notna(row["value"])
                }
                if data_by_year:
                    vintage_list.append({
                        "vintage": pd.Timestamp(v).strftime("%Y-%m-%d"),
                        "data"   : data_by_year,
                    })

            if not vintage_list:
                print(f"  Fed projection [{key}]: không có vintage hợp lệ")
                continue

            results[key] = {
                "label"   : meta["label"],
                "unit"    : meta["unit"],
                "vintages": vintage_list,
            }
            print(f"  Fed projection [{key}]: OK ({len(vintage_list)} vintage: "
                  f"{', '.join(v['vintage'] for v in vintage_list)})")

        except Exception as e:
            print(f"  Fed projection [{key}]: LỖI - {type(e).__name__}: {e}")

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

    print("\n[3] yfinance (tỷ giá USD/VND + giá vàng thế giới)...")
    yf_data = fetch_yfinance_retail()

    print("\n[4] Dự báo Fed - Summary of Economic Projections (Mỹ)...")
    fed_projections = fetch_fed_projections(FRED_API_KEY)

    # Gộp lại
    all_data = {**fred_data, **wb_data, **yf_data}

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
        "updated_at"     : datetime.now(timezone.utc).astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M"),
        "groups"         : groups,
        "series"         : all_data,
        "fed_projections": fed_projections,  # cấu trúc riêng (theo vintage), không nằm trong "series"
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nĐã lưu {OUTPUT_FILE} ({len(all_data)} series, {len(groups)} nhóm, "
          f"{len(fed_projections)} chỉ số dự báo Fed)")


if __name__ == "__main__":
    main()
