"""Làm sạch gia_lich_su_rs.csv một lần: bỏ các dòng thuộc ngày KHÔNG phải phiên giao dịch (thứ Bảy/Chủ nhật, ngày lễ,
ngày chưa tới) do nguồn TradingView cũ trả thừa cho vài mã (ví dụ NAF). Các dòng này làm biểu đồ chỉ số dòng tiền bị
cách ngày và làm lệch giá trị chỉ số.

Không bắt buộc: workflow lấy giá (fetch_data.py) và app (engine.load_prices) đã tự bỏ các dòng này mỗi lần chạy.
Chạy tay (từ thư mục gốc repo):  python clean_price_csv.py            # chỉ báo cáo, không ghi file
                                  python clean_price_csv.py --write    # ghi đè file (tạo bản sao .bak trước)
"""
import shutil
import sys

import pandas as pd

from price_sources import drop_non_sessions

PATH = "gia_lich_su_rs.csv"


def main(write: bool) -> None:
    df = pd.read_csv(PATH, low_memory=False)
    clean = drop_non_sessions(df)
    dropped = df.loc[~df.index.isin(clean.index)]
    days = pd.to_datetime(dropped["date"]).dt.normalize()
    print(f"{len(df)} dòng -> {len(clean)} dòng; bỏ {len(dropped)} dòng thuộc {days.nunique()} ngày không phải phiên giao dịch.")
    if len(dropped):
        print("Mã bị ảnh hưởng:", dropped["ticker"].value_counts().head(10).to_dict())
        print("Ngày gần nhất bị bỏ:", sorted(days.dt.strftime("%Y-%m-%d").unique())[-5:])
    if not write:
        print("Chưa ghi gì. Thêm --write để ghi đè file.")
        return
    shutil.copyfile(PATH, PATH + ".bak")
    clean.to_csv(PATH, index=False)
    print(f"Đã ghi {PATH} (bản cũ lưu ở {PATH}.bak).")


if __name__ == "__main__":
    main("--write" in sys.argv[1:])
