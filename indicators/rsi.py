"""
Chỉ báo RSI (Relative Strength Index)
======================================
Hiển thị trong panel riêng bên dưới biểu đồ nến.
Có 2 đường ngưỡng ngang: OVERBOUGHT (quá mua) và OVERSOLD (quá bán).

Cách tùy chỉnh:
- PERIOD     : số phiên tính RSI (mặc định 14)
- OVERBOUGHT : ngưỡng quá mua (mặc định 70)
- OVERSOLD   : ngưỡng quá bán (mặc định 30)
"""

NAME   = "RSI"
PANEL  = "separate"   # panel riêng bên dưới

PERIOD      = 14
OVERBOUGHT  = 70
OVERSOLD    = 30

COLOR_RSI        = "#a78bfa"
COLOR_OVERBOUGHT = "#f87171"
COLOR_OVERSOLD   = "#34d399"


def compute(df):
    """
    Trả về:
    - Đường RSI
    - Đường ngưỡng overbought (ngang 70)
    - Đường ngưỡng oversold  (ngang 30)
    """
    import pandas as pd
    import numpy as np

    closes = df["close"]
    delta  = closes.diff()
    gain   = delta.clip(lower=0)
    loss   = -delta.clip(upper=0)

    avg_gain = gain.ewm(com=PERIOD - 1, min_periods=PERIOD).mean()
    avg_loss = loss.ewm(com=PERIOD - 1, min_periods=PERIOD).mean()

    rs  = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    dates = [str(d)[:10] for d in df["date"]]

    rsi_values  = [[d, round(float(v), 2) if pd.notna(v) else None]
                   for d, v in zip(dates, rsi)]
    ob_values   = [[d, OVERBOUGHT] for d in dates]
    os_values   = [[d, OVERSOLD]   for d in dates]

    return [
        {
            "label"  : f"RSI({PERIOD})",
            "color"  : COLOR_RSI,
            "width"  : 2,
            "values" : rsi_values,
            "fill"   : False,
            # Giới hạn trục Y cho panel RSI
            "y_min"  : 0,
            "y_max"  : 100,
        },
        {
            "label"  : f"Overbought ({OVERBOUGHT})",
            "color"  : COLOR_OVERBOUGHT,
            "width"  : 1,
            "values" : ob_values,
            "fill"   : False,
            "dashed" : True,
        },
        {
            "label"  : f"Oversold ({OVERSOLD})",
            "color"  : COLOR_OVERSOLD,
            "width"  : 1,
            "values" : os_values,
            "fill"   : False,
            "dashed" : True,
        },
    ]
