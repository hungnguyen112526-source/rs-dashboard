"""
Thăm dò TradingView (tvdatafeed) TRƯỚC khi dùng làm nguồn giá chính. Chạy bằng workflow "Thăm dò TradingView"
(tab Actions -> Run workflow) hoặc `python probe_tv.py` trên máy có mạng. Không ghi đè dữ liệu nào.

In ra: mỗi mã nằm ở sàn nào (HOSE/HNX/UPCOM), đơn vị giá, múi giờ/độ lệch ngày của nến, mức khớp với gia_lich_su_rs.csv,
số nến tối đa lấy được, tốc độ. Kết quả cũng ghi vào $GITHUB_STEP_SUMMARY để đọc ngay trên trang chạy workflow.
"""
import os
import sys
import time

import pandas as pd

from price_sources import calibrate, load_history, tv_raw_to_frame, TV_EXCHANGES

CSV = "gia_lich_su_rs.csv"
SYMBOLS = "danh_sach_ma_theo_nganh.csv"
SAMPLE_EXTRA = ["VNINDEX"]
N_SAMPLE = int(os.environ.get("PROBE_N", "12"))
lines = []


def out(s=""):
    print(s)
    lines.append(s)


def main():
    from tvDatafeed import TvDatafeed, Interval
    user, pwd = os.environ.get("TV_USERNAME"), os.environ.get("TV_PASSWORD")
    tv = TvDatafeed(user, pwd) if user and pwd else TvDatafeed()
    out(f"## Thăm dò TradingView ({'đã đăng nhập' if user and pwd else 'ẩn danh'})\n")

    history = load_history(CSV)
    syms = pd.read_csv(SYMBOLS)["symbol"].dropna().unique().tolist()
    # lấy rải đều trong danh sách để có cả mã nhiều sàn khác nhau
    step = max(1, len(syms) // N_SAMPLE)
    sample = syms[::step][:N_SAMPLE] + SAMPLE_EXTRA
    out("| Mã | Sàn tìm thấy | Số nến | Nến cuối (thô) | Giá đóng thô | Giá đóng CSV | Khớp | Lệch ngày | Hệ số giá | Tỷ lệ KL | Thời gian |")
    out("|---|---|---|---|---|---|---|---|---|---|---|")
    verdicts = []
    for t in sample:
        is_idx = t == "VNINDEX"
        found = None
        t0 = time.time()
        for ex in (["HOSE"] if is_idx else TV_EXCHANGES):
            try:
                raw = tv.get_hist(symbol=t, exchange=ex, interval=Interval.in_daily, n_bars=150)
            except Exception as e:  # noqa: BLE001
                out(f"| {t} | {ex} | lỗi {type(e).__name__} | | | | | | | | |")
                continue
            if raw is not None and len(raw):
                found = (ex, raw)
                break
        dt = time.time() - t0
        if not found:
            out(f"| {t} | KHÔNG THẤY | | | | | | | | | {dt:.1f}s |")
            verdicts.append((t, None))
            continue
        ex, raw = found
        frame = tv_raw_to_frame(raw)
        old = history.get(t)
        cal = calibrate(frame, old, is_idx) if (frame is not None and old is not None) else None
        last = raw.index[-1]
        old_last = f"{old['close'].iloc[-1]:g} ({old.index[-1]:%Y-%m-%d})" if old is not None and len(old) else "-"
        if cal:
            out(f"| {t} | {ex} | {len(raw)} | {last} | {raw['close'].iloc[-1]:g} | {old_last} | {cal.match:.0%}/{cal.overlap} | "
                f"{cal.shift_days:+d} | {cal.scale:g} | {cal.vol_ratio if cal.vol_ratio is None else round(cal.vol_ratio, 3)} | {dt:.1f}s |")
        else:
            out(f"| {t} | {ex} | {len(raw)} | {last} | {raw['close'].iloc[-1]:g} | {old_last} | KHÔNG KHỚP | | | | {dt:.1f}s |")
        verdicts.append((t, cal))
        time.sleep(1)

    # thử lấy nhiều nến nhất có thể (bản ẩn danh có thể bị giới hạn)
    out("\n### Số nến tối đa (MWG, HOSE)")
    for n in (150, 1000, 5000):
        try:
            t0 = time.time()
            raw = tv.get_hist(symbol="MWG", exchange="HOSE", interval=Interval.in_daily, n_bars=n)
            out(f"- yêu cầu {n} nến -> nhận {0 if raw is None else len(raw)} nến, {time.time() - t0:.1f}s")
        except Exception as e:  # noqa: BLE001
            out(f"- yêu cầu {n} nến -> lỗi {type(e).__name__}")

    ok = sum(1 for _, c in verdicts if c)
    out(f"\n### Kết luận nhanh\n- Khớp lịch sử CSV: **{ok}/{len(verdicts)}** mã mẫu.")
    shifts = sorted({c.shift_days for _, c in verdicts if c})
    scales = sorted({c.scale for _, c in verdicts if c})
    out(f"- Độ lệch ngày gặp: {shifts or 'không có'} · Hệ số giá gặp: {scales or 'không có'} (0.001 nghĩa là TradingView trả giá theo đồng, đã tự chia 1000).")
    out("- Nếu 'Khớp' đa số và ổn định -> bật PRICE_SOURCE=auto. Nếu nhiều 'KHÔNG KHỚP' -> gửi bảng này cho người phát triển.")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
