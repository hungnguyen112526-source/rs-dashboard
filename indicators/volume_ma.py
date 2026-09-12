"""
Chỉ báo Volume MA (đường trung bình khối lượng)
================================================
Vẽ đường MA trên panel volume (không phải panel giá, không phải panel riêng).
Giúp nhận ra phiên có khối lượng bất thường cao/thấp so với trung bình.

Cách tùy chỉnh:
- PERIOD : số phiên tính MA (mặc định 20)
- COLOR  : màu đường
"""

NAME   = "VolMA"
PANEL  = "volume"    # panel đặc biệt: vẽ chồng lên cột volume

PERIOD = 20
COLOR  = "#f59e0b"


def compute(df):
    """
    Trả về đường MA của volume.
    """
    import pandas as pd

    volumes  = df["volume"]
    vol_ma   = volumes.rolling(window=PERIOD).mean()
    dates    = [str(d)[:10] for d in df["date"]]

    values = [
        [d, round(float(v), 0) if pd.notna(v) else None]
        for d, v in zip(dates, vol_ma)
    ]

    return [
        {
            "label"  : f"Vol MA({PERIOD})",
            "color"  : COLOR,
            "width"  : 2,
            "values" : values,
            "fill"   : False,
        }
    ]
