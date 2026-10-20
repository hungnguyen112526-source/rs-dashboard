"""
Script tổng hợp tin tức tài chính/chứng khoán từ các nguồn RSS công khai (CafeF, Vietstock,
Investing.com) -> news_data.json, để generate_report.py render thành trang docs/news.html.

Khác với fetch_data.py/fetch_financials.py (cần VNSTOCK_API_KEY), script này CHỈ đọc RSS công
khai -> không cần API key. Chạy ở workflow riêng (update_news.yml), tần suất dày hơn các
script khác (vd mỗi 1-2 tiếng) vì tin tức cần mới liên tục trong ngày.

Cách phân loại:
- Mỗi nguồn RSS được gán sẵn 1 "category" (chủ đề) trong RSS_SOURCES bên dưới - đây là phân
  loại THEO CHỦ ĐỀ của chuyên mục nguồn tin (Chứng khoán VN, Doanh nghiệp VN, Vĩ mô VN,
  Bất động sản VN, Tài chính - Ngân hàng VN, Thế giới/Quốc tế), KHÔNG PHẢI theo đúng 27 ngành
  trong danh_sach_ma_theo_nganh.csv (RSS không có đủ thông tin để map chính xác sang từng
  ngành cụ thể của dashboard).
- Mỗi bài viết còn được gắn thêm tag MÃ CỔ PHIẾU nếu tiêu đề/tóm tắt có nhắc tới mã đó
  (match nguyên từ, phân biệt hoa/thường - chỉ match khi mã viết HOA, vì báo VN thường viết
  mã dạng in hoa khi nhắc tới). Đây là heuristic đơn giản (tìm chuỗi ký tự), không hiểu ngữ
  nghĩa, nên có thể thỉnh thoảng bỏ sót hoặc nhận nhầm với mã có nghĩa trùng từ thông dụng.
"""

import os
import re
import json
from datetime import datetime, timezone, timedelta

import feedparser
import pandas as pd

SYMBOLS_FILE = "danh_sach_ma_theo_nganh.csv"
OUTPUT_FILE = "news_data.json"

VN_TZ = timezone(timedelta(hours=7))

MAX_ARTICLES_PER_FEED = 40   # chỉ giữ N bài mới nhất mỗi feed (feed RSS thường tự giới hạn sẵn)
MAX_TOTAL_ARTICLES = 500     # giới hạn tổng số bài giữ lại trong news_data.json

RSS_SOURCES = [
    # --- CafeF ---
    {"url": "https://cafef.vn/thi-truong-chung-khoan.rss", "source": "CafeF", "category": "Chứng khoán VN"},
    {"url": "https://cafef.vn/doanh-nghiep.rss", "source": "CafeF", "category": "Doanh nghiệp VN"},
    {"url": "https://cafef.vn/tai-chinh-ngan-hang.rss", "source": "CafeF", "category": "Tài chính - Ngân hàng VN"},
    {"url": "https://cafef.vn/vi-mo-dau-tu.rss", "source": "CafeF", "category": "Vĩ mô VN"},
    {"url": "https://cafef.vn/bat-dong-san.rss", "source": "CafeF", "category": "Bất động sản VN"},
    {"url": "https://cafef.vn/tai-chinh-quoc-te.rss", "source": "CafeF", "category": "Thế giới / Quốc tế"},
    # --- Vietstock ---
    {"url": "https://vietstock.vn/830/chung-khoan/co-phieu.rss", "source": "Vietstock", "category": "Chứng khoán VN"},
    {"url": "https://vietstock.vn/737/doanh-nghiep/hoat-dong-kinh-doanh.rss", "source": "Vietstock", "category": "Doanh nghiệp VN"},
    {"url": "https://vietstock.vn/757/tai-chinh/ngan-hang.rss", "source": "Vietstock", "category": "Tài chính - Ngân hàng VN"},
    {"url": "https://vietstock.vn/761/kinh-te/vi-mo.rss", "source": "Vietstock", "category": "Vĩ mô VN"},
    {"url": "https://vietstock.vn/772/the-gioi/tai-chinh-quoc-te.rss", "source": "Vietstock", "category": "Thế giới / Quốc tế"},
    {"url": "https://vietstock.vn/773/the-gioi/chung-khoan-the-gioi.rss", "source": "Vietstock", "category": "Thế giới / Quốc tế"},
    # --- Quốc tế ---
    {"url": "https://www.investing.com/rss/news.rss", "source": "Investing.com", "category": "Thế giới / Quốc tế"},
    # investingLive = ForexLive cũ (đổi tên 21/07/2025). Feed chính thức: https://investinglive.com/rss/
    {"url": "https://investinglive.com/feed/news/", "source": "investingLive", "category": "Thế giới / Quốc tế"},
    {"url": "https://investinglive.com/feed/centralbank/", "source": "investingLive", "category": "Thế giới / Quốc tế"},
]

CATEGORY_ORDER = [
    "Chứng khoán VN",
    "Doanh nghiệp VN",
    "Tài chính - Ngân hàng VN",
    "Vĩ mô VN",
    "Bất động sản VN",
    "Thế giới / Quốc tế",
]


def load_tickers():
    try:
        df = pd.read_csv(SYMBOLS_FILE)
        return sorted(set(df["symbol"].dropna().astype(str).str.upper().tolist()))
    except Exception as e:
        print(f"CẢNH BÁO: không đọc được {SYMBOLS_FILE} để gắn tag mã: {type(e).__name__}")
        return []


def build_ticker_patterns(tickers):
    """Mỗi mã -> regex match nguyên từ, chỉ khi viết HOA (giảm nhận nhầm với từ thường)."""
    patterns = {}
    for t in tickers:
        if not t or not t.isalpha():
            continue
        patterns[t] = re.compile(r"(?<![A-ZÀ-Ỹ0-9])" + re.escape(t) + r"(?![A-ZÀ-Ỹa-zà-ỹ0-9])")
    return patterns


def tag_tickers(text, patterns):
    if not text:
        return []
    found = [t for t, pat in patterns.items() if pat.search(text)]
    return sorted(found)


def parse_published(entry):
    """Lấy thời gian đăng bài, chuẩn hoá về giờ VN. feedparser đã tự parse hầu hết định dạng
    pubDate phổ biến (kể cả không chuẩn RFC822) vào struct_time UTC qua *_parsed."""
    for key in ("published_parsed", "updated_parsed"):
        tm = entry.get(key)
        if tm:
            try:
                dt_utc = datetime(*tm[:6], tzinfo=timezone.utc)
                return dt_utc.astimezone(VN_TZ)
            except Exception:
                continue
    return None


def clean_summary(entry):
    raw = entry.get("summary", "") or entry.get("description", "")
    # Bỏ thẻ HTML đơn giản (feed có thể nhúng <p>, <img>...) - không cần parser HTML đầy đủ
    # cho use-case tóm tắt ngắn gọn ở đây.
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:280]


def fetch_feed(src, patterns):
    articles = []
    try:
        feed = feedparser.parse(src["url"])
    except Exception as e:
        print(f"  LỖI parse {src['url']}: {type(e).__name__}")
        return articles

    if getattr(feed, "bozo", False) and not feed.entries:
        print(f"  CẢNH BÁO: feed lỗi/không có bài nào - {src['url']} ({feed.get('bozo_exception')})")
        return articles

    for entry in feed.entries[:MAX_ARTICLES_PER_FEED]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        summary = clean_summary(entry)
        published = parse_published(entry)
        tickers = tag_tickers(title + " " + summary, patterns)
        articles.append({
            "title": title,
            "link": link,
            "source": src["source"],
            "category": src["category"],
            "summary": summary,
            "published_at": published.strftime("%Y-%m-%d %H:%M") if published else None,
            "tickers": tickers,
        })
    return articles


def main():
    tickers = load_tickers()
    patterns = build_ticker_patterns(tickers)
    print(f"Đã nạp {len(tickers)} mã để gắn tag tin tức.")

    all_articles = []
    ok_feeds = 0
    for src in RSS_SOURCES:
        arts = fetch_feed(src, patterns)
        if arts:
            ok_feeds += 1
            all_articles.extend(arts)
            print(f"  {src['source']} - {src['category']}: {len(arts)} bài ({src['url']})")
        else:
            print(f"  {src['source']} - {src['category']}: 0 bài (lỗi hoặc rỗng) ({src['url']})")

    if not all_articles:
        print("CẢNH BÁO: Không lấy được tin nào từ bất kỳ nguồn nào - giữ nguyên file cũ (nếu có), không ghi đè.")
        return

    # Loại trùng theo link (nhiều feed có thể trùng bài)
    seen_links = set()
    deduped = []
    for a in all_articles:
        if a["link"] in seen_links:
            continue
        seen_links.add(a["link"])
        deduped.append(a)

    # Sắp mới nhất lên đầu (bài không xác định được thời gian xếp cuối), rồi cắt bớt tổng số
    deduped.sort(key=lambda a: a["published_at"] or "0000-00-00 00:00", reverse=True)
    deduped = deduped[:MAX_TOTAL_ARTICLES]

    output = {
        "updated_at": datetime.now(VN_TZ).strftime("%d/%m/%Y %H:%M"),
        "categories": CATEGORY_ORDER,
        "articles": deduped,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)

    print(f"\nLấy thành công {len(deduped)} bài (từ {ok_feeds}/{len(RSS_SOURCES)} nguồn hoạt động) -> đã lưu {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
  
