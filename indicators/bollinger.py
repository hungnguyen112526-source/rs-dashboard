"""
Chỉ báo Bollinger Bands
=======================
Vẽ chồng lên biểu đồ nến (overlay): 3 đường Upper / Middle / Lower
kèm vùng tô mờ giữa Upper và Lower.

Cách tùy chỉnh:
- PERIOD : số phiên tính MA (mặc định 20)
- STD    : số lần độ lệch chuẩn (mặc định 2)
- Đổi màu trong COLOR_*
"""

NAME   = "BB"
PANEL  = "overlay"

PERIOD = 20    # số phiên
STD    = 2     # độ lệch chuẩn

COLOR_UPPER  = "#94a3b8"
COLOR_MIDDLE = "#64748b"
COLOR_LOWER  = "#94a3b8"


def compute(df):
    """
    Trả về 3 đường: Upper, Middle (MA), Lower.
    Mỗi đường là dict {label, color, width, values, fill}.
    fill=True ở Upper → JS sẽ tô vùng giữa Upper-Lower.
    """
    import pandas as pd

    closes = df["close"]
    middle = closes.rolling(window=PERIOD).mean()
    std    = closes.rolling(window=PERIOD).std()
    upper  = middle + STD * std
    lower  = middle - STD * std

    def to_values(series):
        out = []
        for idx, val in series.items():
            date_str = str(df.loc[idx, "date"])[:10]
            out.append([date_str, round(float(val), 2) if pd.notna(val) else None])
        return out

    return [
        {"label": f"BB Upper({PERIOD},{STD})", "color": COLOR_UPPER,  "width": 1, "values": to_values(upper),  "fill": True},
        {"label": f"BB Mid({PERIOD})",         "color": COLOR_MIDDLE, "width": 1, "values": to_values(middle), "fill": False},
        {"label": f"BB Lower({PERIOD},{STD})", "color": COLOR_LOWER,  "width": 1, "values": to_values(lower),  "fill": False},
    ]
