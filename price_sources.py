"""
Lớp nguồn dữ liệu giá: TradingView (tvdatafeed) là nguồn chính, vnstock là nguồn dự phòng.

Web/RS/AI chỉ đọc gia_lich_su_rs.csv; file này do fetch_data.py tạo bằng các lớp ở đây (chạy trong GitHub Actions).

Nguyên tắc an toàn:
- Dữ liệu TradingView chỉ được nhận khi KHỚP với dữ liệu đang có trong CSV ở các phiên chồng lấn (giá đóng cửa lệch
  <= 0,5% ở >= 90% số phiên, khối lượng cùng thang). Quá trình đối chiếu cũng TỰ TÌM ra đơn vị giá (đồng hay nghìn đồng)
  và độ lệch ngày (múi giờ của nến) của TradingView, nên không cần đoán trước.
- Không khớp / lỗi / rỗng / cũ hơn dữ liệu hiện có  ->  dùng vnstock cho đúng mã đó.
- Ngắt mạch: TradingView lỗi liên tiếp BREAKER lần  ->  phần còn lại của lần chạy dùng vnstock.
- Mã chưa có lịch sử trong CSV (không có gì để đối chiếu)  ->  vnstock lấy toàn bộ lịch sử.
- FULL_REFRESH: TradingView lấy tối đa FULL_REFRESH_BARS nến ngày (toàn bộ lịch sử có thể lấy) và GHI TOÀN BỘ số nến đó
  (không giới hạn ở phần đuôi). Vẫn phải qua bước đối chiếu 20 phiên gần nhất như thường; mã bị loại / lỗi -> vnstock lấy
  toàn bộ lịch sử từ history_start. Muốn lấy toàn bộ bằng vnstock như trước: PRICE_SOURCE=vnstock + FULL_REFRESH=1.

Biến môi trường (đọc ở fetch_data.py): PRICE_SOURCE=auto|tv|vnstock, FULL_REFRESH=1, TV_BARS, TV_USERNAME/TV_PASSWORD.
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd

STD_COLS = ["date", "open", "high", "low", "close", "volume", "ticker"]
TV_EXCHANGES = ["HOSE", "HNX", "UPCOM"]
INDEX_SYMBOLS = {"VNINDEX": "HOSE", "VN30": "HOSE", "HNXINDEX": "HNX"}

PRICE_TOL = 0.005        # giá lệch tối đa 0,5% được coi là "khớp"
MIN_MATCH = 0.90         # tỷ lệ phiên chồng lấn phải khớp
MIN_OVERLAP = 10         # số phiên chồng lấn tối thiểu để đối chiếu
RECENT_WINDOW = 20       # chỉ đối chiếu giá/khối lượng ở ngần này phiên chồng lấn gần nhất (điều chỉnh giá cũ không làm hỏng việc nhận dữ liệu)
MERGE_BACK_DAYS = 5      # chỉ ghi các nến từ (ngày cuối trong CSV - 5 ngày) trở đi; lịch sử cũ giữ nguyên, không bị TradingView ghi đè
                         # (bỏ giới hạn này khi FULL_REFRESH: ghi toàn bộ số nến TradingView trả về)
FULL_REFRESH_BARS = 5000 # số nến ngày tối đa xin TradingView khi FULL_REFRESH (giới hạn của tvdatafeed ~5000 nến/lần gọi)
VOL_RATIO_RANGE = (0.9, 1.1)   # trung vị KL mới / KL cũ phải nằm trong khoảng này
SESSION_OFFSET = pd.Timedelta(hours=7)   # CSV cũ lưu ngày dạng "YYYY-MM-DD 07:00:00"


# Ghi chú của Result khi TradingView có phản hồi nhưng dữ liệu mã đó bị loại (không phải sự cố của TradingView)
REJECTED_PREFIXES = ("chưa có lịch sử", "dữ liệu TradingView không khớp", "dữ liệu TradingView cũ hơn",
                     "dữ liệu TradingView không hợp lệ")


class SourceError(Exception):
    """Nguồn không dùng được (thiếu khoá, thư viện, mạng...)."""


# ----------------------------------------------------------------------------
# Lịch sử hiện có (để đối chiếu)
# ----------------------------------------------------------------------------

def load_history(path: str) -> dict[str, pd.DataFrame]:
    """CSV hiện có -> {mã: DataFrame(index=ngày đã chuẩn hoá, cột close, volume)}; rỗng nếu chưa có file."""
    if not os.path.exists(path):
        return {}
    try:
        df = pd.read_csv(path, usecols=["date", "ticker", "close", "volume"], low_memory=False)
    except Exception as e:  # noqa: BLE001
        print(f"CẢNH BÁO: không đọc được {path} để đối chiếu ({type(e).__name__}) - sẽ dùng vnstock toàn bộ.")
        return {}
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.tz_localize(None).dt.normalize()
    df = df.dropna(subset=["date"]).drop_duplicates(["ticker", "date"], keep="last")
    return {t: g.set_index("date").sort_index()[["close", "volume"]] for t, g in df.groupby("ticker")}


# ----------------------------------------------------------------------------
# Chuẩn hoá + đối chiếu dữ liệu TradingView
# ----------------------------------------------------------------------------

def tv_raw_to_frame(raw: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Kết quả get_hist của tvdatafeed (index = thời gian) -> cột date/open/high/low/close/volume (chưa hiệu chỉnh)."""
    if raw is None or len(raw) == 0:
        return None
    df = raw.copy()
    df.columns = [str(c).lower() for c in df.columns]
    if "date" not in df.columns and "datetime" not in df.columns:
        df = df.reset_index()
        df.columns = [str(c).lower() for c in df.columns]
    date_col = next((c for c in ("datetime", "date", "time", "index") if c in df.columns), df.columns[0])
    need = ["open", "high", "low", "close"]
    if any(c not in df.columns for c in need):
        return None
    if "volume" not in df.columns:
        df["volume"] = np.nan
    out = df[[date_col] + need + ["volume"]].rename(columns={date_col: "date"})
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    try:
        out["date"] = out["date"].dt.tz_localize(None)
    except (TypeError, AttributeError):
        pass
    out = out.dropna(subset=["date", "close"])
    return out if len(out) else None


@dataclass
class Calibration:
    shift_days: int
    scale: float
    match: float                 # tỷ lệ khớp giá ở RECENT_WINDOW phiên gần nhất (dùng để quyết định nhận/loại)
    overlap: int
    vol_ratio: Optional[float]
    match_all: float = 0.0       # tỷ lệ khớp trên toàn bộ phần chồng lấn (chỉ để tham khảo/chẩn đoán)


def _compare(new: pd.DataFrame, old: pd.DataFrame, shift: int, scale: float) -> Optional[dict]:
    old_close = old["close"].astype(float)
    days = pd.DatetimeIndex((new["date"].dt.normalize() + pd.Timedelta(days=shift)).values)
    s = pd.Series((new["close"].astype(float) * scale).values, index=days)
    s = s[~s.index.duplicated(keep="last")]
    common = s.index.intersection(old_close.index).sort_values()
    if len(common) < MIN_OVERLAP:
        return None
    a, b = s.loc[common], old_close.loc[common]
    rel = (a - b).abs() / b.abs().clip(lower=1e-9)
    vr = None
    if "volume" in new.columns and "volume" in old.columns:
        nv = pd.Series(new["volume"].astype(float).values, index=days)
        nv = nv[~nv.index.duplicated(keep="last")].reindex(common)
        ov = old["volume"].astype(float).reindex(common)
        m = ((ov > 0) & (nv > 0)).iloc[-RECENT_WINDOW:]
        if m.sum() >= 5:
            vr = float((nv.iloc[-RECENT_WINDOW:][m] / ov.iloc[-RECENT_WINDOW:][m]).median())
    return {"shift": shift, "scale": scale, "a": a, "b": b, "rel": rel, "overlap": int(len(common)), "vol_ratio": vr,
            "match": float((rel.iloc[-RECENT_WINDOW:] <= PRICE_TOL).mean()), "match_all": float((rel <= PRICE_TOL).mean())}


def diagnose(new: pd.DataFrame, old: pd.DataFrame, is_index: bool = False):
    """Tìm (độ lệch ngày, hệ số đơn vị) khớp nhất rồi quyết định nhận/loại.
    Trả về (Calibration hoặc None, thông tin chẩn đoán gồm 'best' và 'reason')."""
    if old is None or old.empty:
        return None, {"best": None, "reason": "chưa có lịch sử để đối chiếu"}
    best = None
    for shift in (0, 1, -1):
        for scale in ((1.0,) if is_index else (1.0, 0.001)):
            c = _compare(new, old, shift, scale)
            if c and (best is None or (c["match"], c["match_all"]) > (best["match"], best["match_all"])):
                best = c
    if best is None:
        return None, {"best": None, "reason": f"không đủ phiên chồng lấn (< {MIN_OVERLAP})"}
    reason = ""
    if best["match"] < MIN_MATCH:
        reason = f"giá {RECENT_WINDOW} phiên gần nhất chỉ khớp {best['match']:.0%} (toàn bộ {best['match_all']:.0%})"
    elif best["vol_ratio"] is not None and not (VOL_RATIO_RANGE[0] <= best["vol_ratio"] <= VOL_RATIO_RANGE[1]):
        reason = f"khối lượng lệch thang (TV/CSV = {best['vol_ratio']:.2f})"
    cal = None if reason else Calibration(best["shift"], best["scale"], best["match"], best["overlap"], best["vol_ratio"], best["match_all"])
    return cal, {"best": best, "reason": reason}


def calibrate(new: pd.DataFrame, old: pd.DataFrame, is_index: bool = False) -> Optional[Calibration]:
    return diagnose(new, old, is_index)[0]


def apply_calibration(new: pd.DataFrame, cal: Calibration, ticker: str) -> Optional[pd.DataFrame]:
    out = new.copy()
    out["date"] = out["date"].dt.normalize() + pd.Timedelta(days=cal.shift_days) + SESSION_OFFSET
    for c in ("open", "high", "low", "close"):
        out[c] = (out[c].astype(float) * cal.scale).round(4)
    out["volume"] = out["volume"].astype(float)
    out["ticker"] = ticker
    out = out.dropna(subset=["close"])
    out = out[(out["close"] > 0) & (out["high"] >= out["low"])]
    out = out.sort_values("date").drop_duplicates("date", keep="last")
    return out[STD_COLS] if len(out) else None


# ----------------------------------------------------------------------------
# Nguồn vnstock
# ----------------------------------------------------------------------------

def vnstock_frame(df: pd.DataFrame, ticker: str) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None
    df = df.rename(columns={c: str(c).lower() for c in df.columns})
    date_col = "time" if "time" in df.columns else "date"
    keep = [c for c in (date_col, "open", "high", "low", "close", "volume") if c in df.columns]
    out = df[keep].rename(columns={date_col: "date"})
    out["ticker"] = ticker
    return out


def vnstock_ohlcv(obj, start: str, count_fallback: int = 1300):
    end = pd.Timestamp.today().strftime("%Y-%m-%d")
    try:
        return obj.ohlcv(start=start, end=end, interval="1D")
    except TypeError:
        return obj.ohlcv(count=count_fallback, interval="1D")


# ----------------------------------------------------------------------------
# Bộ điều phối
# ----------------------------------------------------------------------------

@dataclass
class Result:
    df: Optional[pd.DataFrame]
    source: str                 # "tv" | "vnstock" | "none"
    note: str = ""
    exchange: Optional[str] = None


@dataclass
class PriceFetcher:
    mode: str                                   # auto | tv | vnstock
    history: dict
    history_start: str = "2015-01-01"
    tv_factory: Optional[Callable[[], object]] = None       # -> đối tượng có get_hist (tvdatafeed)
    vn_factory: Optional[Callable[[], object]] = None       # -> vnstock Market
    exchange_map: dict = field(default_factory=dict)
    tv_bars: int = 150
    full_refresh: bool = False
    breaker: int = 5
    tv_sleep: float = 1.0
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], pd.Timestamp] = pd.Timestamp.today

    def __post_init__(self):
        self._tv = None
        self._vn = None
        self.tv_disabled = self.mode == "vnstock"
        self.tv_fail_streak = 0
        self.tv_disabled_reason = "PRICE_SOURCE=vnstock" if self.mode == "vnstock" else ""
        self.calib_votes: Counter = Counter()
        self.log: dict = {}

    # ---- TradingView ----
    def _get_tv(self):
        if self._tv is None:
            if self.tv_factory is None:
                raise SourceError("Chưa cấu hình tvdatafeed")
            self._tv = self.tv_factory()
        return self._tv

    def _tv_download(self, ticker: str, is_index: bool):
        """Trả (sàn, DataFrame thô) hoặc (None, None) nếu không có; ném ngoại lệ nếu lỗi mạng/thư viện."""
        tv = self._get_tv()
        cached = self.exchange_map.get(ticker) or (INDEX_SYMBOLS.get(ticker) if is_index else None)
        order = ([cached] if cached else []) + [e for e in TV_EXCHANGES if e != cached]
        if is_index:
            order = order[:1] if cached else ["HOSE"]
        from tvDatafeed import Interval  # nhập muộn: kiểm thử không cần cài thư viện
        n_bars = max(self.tv_bars, FULL_REFRESH_BARS) if self.full_refresh else self.tv_bars
        for ex in order:
            raw = None
            for attempt in range(2):
                try:
                    raw = tv.get_hist(symbol=ticker, exchange=ex, interval=Interval.in_daily, n_bars=n_bars)
                    break
                except Exception:  # noqa: BLE001
                    if attempt == 1:
                        raise
                    self.sleep(2)
            if raw is not None and len(raw):
                return ex, raw
            self.sleep(self.tv_sleep)
        return None, None

    def _try_tv(self, ticker: str, is_index: bool) -> Result:
        old = self.history.get(ticker)
        if old is None or len(old) < MIN_OVERLAP:
            return Result(None, "none", "chưa có lịch sử để đối chiếu")
        ex, raw = self._tv_download(ticker, is_index)
        if raw is None:
            return Result(None, "none", "TradingView không có dữ liệu mã này")
        frame = tv_raw_to_frame(raw)
        if frame is None:
            return Result(None, "none", "dữ liệu TradingView sai định dạng")
        cal, info = diagnose(frame, old, is_index)
        if cal is None:
            return Result(None, "none", "dữ liệu TradingView không khớp lịch sử: " + info["reason"])
        out = apply_calibration(frame, cal, ticker)
        if out is None:
            return Result(None, "none", "dữ liệu TradingView không hợp lệ sau chuẩn hoá")
        if out["date"].max().normalize() < old.index.max():
            return Result(None, "none", "dữ liệu TradingView cũ hơn dữ liệu hiện có")
        if not self.full_refresh:   # chạy thường: chỉ nối phần đuôi; FULL_REFRESH: ghi toàn bộ lịch sử TradingView trả về
            out = out[out["date"].dt.normalize() >= old.index.max() - pd.Timedelta(days=MERGE_BACK_DAYS)]
        self.calib_votes[(cal.shift_days, cal.scale)] += 1
        return Result(out, "tv", f"khớp {cal.match:.0%} ({RECENT_WINDOW} phiên gần nhất, toàn bộ {cal.match_all:.0%}/{cal.overlap}), lệch ngày {cal.shift_days:+d}, hệ số giá {cal.scale:g}", ex)

    # ---- vnstock ----
    def _get_vn(self):
        if self._vn is None:
            if self.vn_factory is None:
                raise SourceError("Chưa cấu hình vnstock")
            self._vn = self.vn_factory()
        return self._vn

    def _vn_start(self, ticker: str) -> str:
        old = self.history.get(ticker)
        if self.full_refresh or old is None or len(old) < MIN_OVERLAP:
            return self.history_start
        return str(max(pd.Timestamp(self.history_start), old.index.max() - pd.Timedelta(days=45)).date())

    def _try_vn(self, ticker: str, is_index: bool) -> Result:
        market = self._get_vn()
        obj = market.index(symbol=ticker) if is_index else market.equity(symbol=ticker)
        df = vnstock_frame(vnstock_ohlcv(obj, self._vn_start(ticker)), ticker)
        if df is None:
            return Result(None, "none", "vnstock không có dữ liệu")
        return Result(df, "vnstock", f"từ {self._vn_start(ticker)}")

    # ---- điều phối ----
    def fetch(self, ticker: str, is_index: bool = False) -> Result:
        notes = []
        if self.mode in ("auto", "tv") and not self.tv_disabled:
            try:
                res = self._try_tv(ticker, is_index)
                if res.df is not None:
                    self.tv_fail_streak = 0
                    self._record(ticker, res)
                    return res
                notes.append("TV: " + res.note)
                # TradingView vẫn phản hồi bình thường, chỉ là dữ liệu của RIÊNG mã này bị loại (chưa có lịch sử để đối chiếu,
                # không khớp, cũ hơn...) -> chuyển riêng mã đó sang vnstock, KHÔNG tính vào ngắt mạch (nếu không, vài mã
                # lệch khối lượng liên tiếp sẽ tắt TradingView cho cả những mã dữ liệu tốt).
                if not res.note.startswith(REJECTED_PREFIXES):
                    self._tv_failed()
            except Exception as e:  # noqa: BLE001
                notes.append(f"TV lỗi: {type(e).__name__}")
                self._tv_failed()
        elif self.mode in ("auto", "tv") and self.tv_disabled:
            notes.append(f"TV tắt: {self.tv_disabled_reason}")
        if self.mode == "tv":
            res = Result(None, "none", "; ".join(notes) or "PRICE_SOURCE=tv")
            self._record(ticker, res)
            return res
        try:
            res = self._try_vn(ticker, is_index)
        except Exception as e:  # noqa: BLE001
            res = Result(None, "none", f"vnstock lỗi: {type(e).__name__}")
        res.note = "; ".join(notes + [res.note]) if notes else res.note
        self._record(ticker, res)
        return res

    def _tv_failed(self):
        self.tv_fail_streak += 1
        if self.tv_fail_streak >= self.breaker and not self.tv_disabled:
            self.tv_disabled = True
            self.tv_disabled_reason = f"ngắt mạch sau {self.breaker} lần lỗi liên tiếp"
            print(f"   >> TradingView lỗi {self.breaker} lần liên tiếp - chuyển toàn bộ phần còn lại sang vnstock.")

    def _record(self, ticker: str, res: Result):
        if res.exchange:
            self.exchange_map[ticker] = res.exchange
        rows = int(len(res.df)) if res.df is not None else 0
        last = str(pd.Timestamp(res.df["date"].max()).date()) if rows else None
        self.log[ticker] = {"source": res.source, "rows": rows, "last": last, "note": res.note}

    # ---- báo cáo ----
    def summary(self) -> dict:
        counts = Counter(v["source"] for v in self.log.values())
        return {
            "updated_at": pd.Timestamp.now(tz="Asia/Ho_Chi_Minh").strftime("%d/%m/%Y %H:%M"),
            "mode": self.mode, "full_refresh": self.full_refresh,
            "tv_disabled": bool(self.tv_disabled), "tv_disabled_reason": self.tv_disabled_reason,
            "counts": {"tv": counts.get("tv", 0), "vnstock": counts.get("vnstock", 0), "none": counts.get("none", 0)},
            "tickers": self.log,
        }


def save_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


def load_json(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default
