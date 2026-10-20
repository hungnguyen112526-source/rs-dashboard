"""
Lấy LỊCH KINH TẾ từ TradingView -> calendar_data.json (đọc bởi trang "Lịch kinh tế" của app Streamlit).

Lưu ý: thư viện tvdatafeed CHỈ lấy giá nến, không có lịch kinh tế. Lịch nằm ở endpoint công khai nhưng
không chính thức mà trang lịch của TradingView tự dùng (economic-calendar.tradingview.com/events), nên
script gọi thẳng bằng requests. Endpoint này có thể đổi hoặc bị chặn bất cứ lúc nào:
- Lỗi mạng / không có sự kiện nào -> KHÔNG ghi đè file cũ, thoát với mã lỗi 1 để workflow báo đỏ.
- Từng sự kiện thiếu trường -> bỏ qua trường đó, không làm hỏng cả file.

Cách chạy: python fetch_calendar.py   (không cần API key)
"""
import json
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

OUTPUT_FILE = "calendar_data.json"
URL = "https://economic-calendar.tradingview.com/events"
# Mã quốc gia ISO-2 theo TradingView ("EU" = khu vực đồng euro)
COUNTRIES = ["VN", "US", "CN", "EU", "JP", "GB", "DE", "KR"]
DAYS_BACK = 7      # giữ lại kết quả đã công bố của 7 ngày qua
DAYS_AHEAD = 30    # lịch dự kiến 30 ngày tới
VN_TZ = timezone(timedelta(hours=7))
HEADERS = {
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}


def _num(v):
    """Giá trị số nếu đọc được; không thì None (giữ chuỗi nếu là chữ có nghĩa)."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return str(v)


def normalize(ev: dict):
    """1 sự kiện thô của TradingView -> bản gọn. Thiếu ngày/tên thì bỏ (trả None)."""
    date, title = ev.get("date"), ev.get("title") or ev.get("indicator")
    if not date or not title:
        return None
    try:
        imp = int(ev.get("importance", 0))
    except (TypeError, ValueError):
        imp = 0
    return {
        "id": str(ev.get("id", "")),
        "date": str(date),                      # ISO, UTC (vd 2026-10-21T12:30:00.000Z)
        "country": str(ev.get("country") or "").upper(),
        "title": str(title),
        "period": ev.get("period") or "",
        "importance": max(-1, min(1, imp)),     # -1 thấp, 0 trung bình, 1 cao
        "actual": _num(ev.get("actual")),
        "forecast": _num(ev.get("forecast")),
        "previous": _num(ev.get("previous")),
        "unit": ev.get("unit") or "",
        "scale": ev.get("scale") or "",
    }


def fetch(start: datetime, end: datetime):
    params = {
        "from": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "to": end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "countries": ",".join(COUNTRIES),
    }
    last_err = None
    for attempt in range(3):
        try:
            r = requests.get(URL, params=params, headers=HEADERS, timeout=30)
            r.raise_for_status()
            data = r.json()
            result = data.get("result") if isinstance(data, dict) else data
            if isinstance(result, list):
                return result
            last_err = f"định dạng lạ: {str(data)[:200]}"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        print(f"  lần {attempt + 1} lỗi - {last_err}")
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(last_err)


def main():
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=DAYS_BACK)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = (now + timedelta(days=DAYS_AHEAD)).replace(hour=23, minute=59, second=59, microsecond=0)
    print(f"Lấy lịch kinh tế {start:%Y-%m-%d} -> {end:%Y-%m-%d}, quốc gia: {', '.join(COUNTRIES)}")
    try:
        raw = fetch(start, end)
    except Exception as e:
        print(f"LỖI: không lấy được lịch ({e}) - giữ nguyên file cũ (nếu có).")
        sys.exit(1)

    events = [e for e in (normalize(x) for x in raw if isinstance(x, dict)) if e]
    if not events:
        print("LỖI: endpoint trả về 0 sự kiện - giữ nguyên file cũ (nếu có).")
        sys.exit(1)
    events.sort(key=lambda e: (e["date"], -e["importance"], e["country"]))

    payload = {
        "updated_at": datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M"),
        "source": "TradingView economic calendar (không chính thức)",
        "range": {"from": start.strftime("%Y-%m-%d"), "to": end.strftime("%Y-%m-%d")},
        "countries": COUNTRIES,
        "events": events,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    by_country = {}
    for e in events:
        by_country[e["country"]] = by_country.get(e["country"], 0) + 1
    print(f"Đã ghi {len(events)} sự kiện vào {OUTPUT_FILE}: {by_country}")


if __name__ == "__main__":
    main()
