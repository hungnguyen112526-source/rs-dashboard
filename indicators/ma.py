"""
Chỉ báo MA / EMA (Moving Average / Exponential Moving Average)
=============================================================
Vẽ chồng lên biểu đồ nến (overlay).

Cách tùy chỉnh:
- Thêm/bớt đường trong LINES (mỗi dict là 1 đường)
- Đổi period, color, width tùy ý
- type: "sma" = đường trung bình đơn giản, "ema" = trung bình hàm mũ
"""

# Tên hiển thị trên nút toggle
NAME = "MA"

# "overlay"  = vẽ chồng lên biểu đồ nến (dùng cho MA, BB...)
# "separate" = panel riêng bên dưới (dùng cho RSI, MACD...)
PANEL = "overlay"

# Danh sách các đường muốn vẽ
LINES = [
    {"period": 20,  "type": "sma", "color": "#f59e0b", "width": 1, "label": "MA20"},
    {"period": 50,  "type": "sma", "color": "#60a5fa", "width": 1, "label": "MA50"},
    {"period": 200, "type": "sma", "color": "#f87171", "width": 1, "label": "MA200"},
    {"period": 20,  "type": "ema", "color": "#a78bfa", "width": 1, "label": "EMA20"},
]


def compute(df):
    """
    Tính toán giá trị cho tất cả các đường MA/EMA.

    Tham số:
        df (pd.DataFrame): Dữ liệu giá, có cột: date, open, high, low, close, volume
                           Đã được sort theo date tăng dần.

    Trả về:
        list[dict]: Mỗi phần tử là 1 đường, gồm:
            - label  : tên hiện trên biểu đồ
            - color  : màu hex
            - width  : độ dày nét vẽ
            - values : list [[date_str, value], ...]  (value=None nếu chưa đủ dữ liệu)
    """
    import pandas as pd

    results = []
    closes = df["close"]

    for line in LINES:
        period = line["period"]
        if line["type"] == "sma":
            series = closes.rolling(window=period).mean()
        else:  # ema
            series = closes.ewm(span=period, adjust=False).mean()

        values = []
        for i, (idx, val) in enumerate(series.items()):
            date_str = df.loc[idx, "date"].strftime("%Y-%m-%d") if hasattr(df.loc[idx, "date"], "strftime") else str(df.loc[idx, "date"])[:10]
            values.append([date_str, round(float(val), 2) if pd.notna(val) else None])

        results.append({
            "label": line["label"],
            "color": line["color"],
            "width": line["width"],
            "values": values,
        })

    return results
