"""
Chỉ báo MACD (Moving Average Convergence Divergence)
=====================================================
Hiển thị trong panel riêng bên dưới biểu đồ nến, gồm:
- Đường MACD (EMA nhanh - EMA chậm)
- Đường Signal (EMA của MACD)
- Histogram (MACD - Signal), tô xanh khi dương, đỏ khi âm

Cách tùy chỉnh:
- FAST   : EMA nhanh (mặc định 12)
- SLOW   : EMA chậm (mặc định 26)
- SIGNAL : EMA signal (mặc định 9)
"""

NAME   = "MACD"
PANEL  = "separate"

FAST   = 12
SLOW   = 26
SIGNAL = 9

COLOR_MACD      = "#60a5fa"
COLOR_SIGNAL    = "#f59e0b"
COLOR_HIST_POS  = "#34d399"   # histogram dương (xanh)
COLOR_HIST_NEG  = "#f87171"   # histogram âm (đỏ)


def compute(df):
    """
    Trả về:
    - Đường MACD
    - Đường Signal
    - Histogram (dạng bar — JS nhận biết qua type='histogram')
    """
    import pandas as pd

    closes  = df["close"]
    ema_fast = closes.ewm(span=FAST,   adjust=False).mean()
    ema_slow = closes.ewm(span=SLOW,   adjust=False).mean()
    macd     = ema_fast - ema_slow
    signal   = macd.ewm(span=SIGNAL, adjust=False).mean()
    hist     = macd - signal

    dates = [str(d)[:10] for d in df["date"]]

    macd_vals   = [[d, round(float(v), 4) if pd.notna(v) else None] for d, v in zip(dates, macd)]
    signal_vals = [[d, round(float(v), 4) if pd.notna(v) else None] for d, v in zip(dates, signal)]
    # Histogram: mỗi điểm kèm color để JS tô màu đúng
    hist_vals   = [
        [d, round(float(v), 4) if pd.notna(v) else None,
         COLOR_HIST_POS if (pd.notna(v) and v >= 0) else COLOR_HIST_NEG]
        for d, v in zip(dates, hist)
    ]

    return [
        {
            "label"  : f"MACD({FAST},{SLOW})",
            "color"  : COLOR_MACD,
            "width"  : 2,
            "values" : macd_vals,
            "fill"   : False,
            "type"   : "line",
        },
        {
            "label"  : f"Signal({SIGNAL})",
            "color"  : COLOR_SIGNAL,
            "width"  : 1,
            "values" : signal_vals,
            "fill"   : False,
            "type"   : "line",
        },
        {
            "label"  : "Histogram",
            "color"  : COLOR_HIST_POS,
            "width"  : 1,
            "values" : hist_vals,
            "fill"   : False,
            "type"   : "histogram",   # JS dùng addHistogramSeries()
        },
    ]
