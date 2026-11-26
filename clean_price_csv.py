"""Dọn file gia_lich_su_rs.csv: bỏ các dòng ở ngày không phải phiên giao dịch thật.

  - thứ Bảy / Chủ nhật
  - ngày chỉ có vài mã trong khi phiên liền kề có rất nhiều mã (một vài mã bị gán lệch ngày, vd NAF)

Chạy từ thư mục gốc repo:
    python clean_price_csv.py --dry-run     # chỉ báo, không ghi
    python clean_price_csv.py               # ghi đè gia_lich_su_rs.csv (giữ nguyên định dạng cột/ngày)
Quy tắc trùng với rs_app/src/engine.py (drop_stray_days) nên app đã tự lọc khi đọc; dọn file chỉ để dữ liệu gốc sạch.
"""
import argparse
import sys

import pandas as pd

STRAY_RATIO = 0.2
STRAY_MIN_REF = 30


def stray_mask(day: pd.Series) -> pd.Series:
    d = pd.to_datetime(day).dt.tz_localize(None).dt.normalize()
    n = d.groupby(d).size()
    ref = pd.concat([n.shift(1), n.shift(-1)], axis=1).max(axis=1)
    stray_days = set(n.index[(n < STRAY_RATIO * ref) & (ref >= STRAY_MIN_REF)])
    return (d.dt.dayofweek >= 5) | d.isin(stray_days)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="gia_lich_su_rs.csv")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    df = pd.read_csv(args.csv, low_memory=False)
    bad = stray_mask(df["date"])
    removed = df[bad]
    print(f"{len(df):,} dòng; sẽ bỏ {len(removed):,} dòng ở {pd.to_datetime(removed['date']).dt.normalize().nunique()} ngày lẻ")
    if len(removed):
        print(removed.groupby("ticker").size().sort_values(ascending=False).head(5).to_string())
    if args.dry_run or not len(removed):
        return 0
    df[~bad].to_csv(args.csv, index=False)
    print("Đã ghi", args.csv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
