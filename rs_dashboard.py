"""
RS Ranking Dashboard (kiểu IBD RS Rating)
------------------------------------------
Công thức:
1) Điểm số thô cổ phiếu = 2*%ΔP(4w) + %ΔP(8w) + %ΔP(12w)
2) RS cổ phiếu (1-99) = ((N - rank)/N) * 99 + 1   (rank 1 = điểm thô cao nhất)
3) Điểm số thô Ngành = trung bình cộng Điểm số thô của các mã trong ngành
4) RS Ngành (1-99) = áp dụng công thức bách phân giống bước 2, trên các ngành

Chạy: streamlit run rs_dashboard.py
"""

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="RS Ranking Dashboard", layout="wide")

# ----------------------------------------------------------------------------
# 1. TẢI / TẠO DỮ LIỆU
# ----------------------------------------------------------------------------

@st.cache_data
def generate_sample_data(n_tickers: int = 60, n_weeks: int = 20, seed: int = 42) -> pd.DataFrame:
    """Sinh dữ liệu giá tuần giả lập cho demo (thay bằng dữ liệu thật khi có)."""
    rng = np.random.default_rng(seed)
    industries = ["Ngân hàng", "BĐS", "Thép", "Chứng khoán", "Bán lẻ", "Dầu khí"]
    tickers = [f"CK{str(i).zfill(2)}" for i in range(1, n_tickers + 1)]
    ticker_industry = {t: industries[i % len(industries)] for i, t in enumerate(tickers)}

    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=n_weeks, freq="W-FRI")

    rows = []
    for t in tickers:
        base_price = rng.uniform(10, 100)
        drift = rng.normal(0.002, 0.01)  # xu hướng khác nhau giữa các mã
        prices = [base_price]
        for _ in range(n_weeks - 1):
            shock = rng.normal(drift, 0.03)
            prices.append(max(prices[-1] * (1 + shock), 0.5))
        for d, p in zip(dates, prices):
            rows.append({"date": d, "ticker": t, "industry": ticker_industry[t], "close": p})

    return pd.DataFrame(rows)


def load_uploaded_data(file) -> pd.DataFrame:
    """Kỳ vọng CSV có cột: date, ticker, industry, close"""
    df = pd.read_csv(file, parse_dates=["date"])
    required = {"date", "ticker", "industry", "close"}
    missing = required - set(df.columns)
    if missing:
        st.error(f"File thiếu cột: {missing}. Cần đủ 4 cột: date, ticker, industry, close")
        st.stop()
    return df


@st.cache_data(ttl=3600)
def load_uploaded_data_from_path(path: str) -> pd.DataFrame:
    """Giống load_uploaded_data nhưng đọc trực tiếp từ đường dẫn file trên đĩa
    (dùng cho file gia_lich_su_rs.csv được GitHub Actions cập nhật tự động)."""
    df = pd.read_csv(path, parse_dates=["date"])
    required = {"date", "ticker", "industry", "close"}
    missing = required - set(df.columns)
    if missing:
        st.error(f"File {path} thiếu cột: {missing}")
        st.stop()
    return df


def load_industry_map_csv(file) -> pd.DataFrame:
    """
    Đọc file danh sách mã theo ngành kiểu: mã, ngành (giống danh_sach_ma_theo_nganh.csv).
    Tự dò cột tên mã và tên ngành cho linh hoạt vì tên cột tiếng Việt hay khác nhau.
    """
    raw = pd.read_csv(file)
    cols_lower = {c.lower().strip(): c for c in raw.columns}

    ticker_col = next((cols_lower[c] for c in cols_lower if c in ("mã", "ma", "ticker", "symbol", "code")), None)
    industry_col = next((cols_lower[c] for c in cols_lower if c in ("ngành", "nganh", "industry", "sector")), None)

    if ticker_col is None or industry_col is None:
        st.error(
            "Không tìm thấy cột Mã / Ngành trong file. "
            f"Các cột hiện có: {list(raw.columns)}. Đổi tên cột thành 'Mã' và 'Ngành' rồi thử lại."
        )
        st.stop()

    out = raw[[ticker_col, industry_col]].dropna()
    out.columns = ["ticker", "industry"]
    out["ticker"] = out["ticker"].astype(str).str.strip().str.upper()
    out["industry"] = out["industry"].astype(str).str.strip()
    return out.drop_duplicates("ticker")


@st.cache_data(show_spinner=False)
def fetch_vnstock_weekly(tickers: tuple, weeks_back: int = 20) -> pd.DataFrame:
    """
    Lấy dữ liệu giá tuần (OHLCV) thật từ vnstock cho danh sách mã.
    Yêu cầu: đã `pip install -U vnstock` và cấu hình API key theo hướng dẫn
    tại vnstocks.com (đăng nhập Google để lấy key, vnstock sẽ tự lưu).
    """
    from vnstock import Market

    market = Market()
    end = pd.Timestamp.today().normalize()
    start = end - pd.Timedelta(weeks=weeks_back + 4)  # dư ra để chắc đủ dữ liệu

    frames = []
    errors = []
    progress = st.progress(0.0, text="Đang tải dữ liệu từ vnstock...")

    for i, t in enumerate(tickers):
        try:
            df_t = market.equity(symbol=t).ohlcv(
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval="1W",
            )
            if df_t is None or df_t.empty:
                errors.append(t)
                continue
            df_t = df_t.rename(columns={c: c.lower() for c in df_t.columns})
            date_col = "time" if "time" in df_t.columns else "date"
            df_t = df_t[[date_col, "close"]].rename(columns={date_col: "date"})
            df_t["date"] = pd.to_datetime(df_t["date"])
            df_t["ticker"] = t
            frames.append(df_t)
        except Exception:
            errors.append(t)
        progress.progress((i + 1) / len(tickers), text=f"Đang tải {t} ({i + 1}/{len(tickers)})")

    progress.empty()
    if errors:
        st.warning(f"Không lấy được dữ liệu cho {len(errors)} mã: {', '.join(errors[:15])}"
                    + (" ..." if len(errors) > 15 else ""))

    if not frames:
        st.error("Không tải được dữ liệu nào từ vnstock. Kiểm tra lại API key / kết nối mạng.")
        st.stop()

    return pd.concat(frames, ignore_index=True)


# ----------------------------------------------------------------------------
# 2. CÔNG THỨC TÍNH TOÁN
# ----------------------------------------------------------------------------

def pct_change_over(df: pd.DataFrame, weeks: int) -> pd.Series:
    """% thay đổi giá trong N tuần gần nhất, tính trên giá đóng cửa mới nhất mỗi mã."""
    result = {}
    for ticker, g in df.groupby("ticker"):
        g = g.sort_values("date")
        if len(g) <= weeks:
            result[ticker] = np.nan
            continue
        end_price = g["close"].iloc[-1]
        start_price = g["close"].iloc[-1 - weeks]
        result[ticker] = (end_price - start_price) / start_price * 100
    return pd.Series(result, name=f"pct_{weeks}w")


def compute_raw_scores(df: pd.DataFrame) -> pd.DataFrame:
    p4 = pct_change_over(df, 4)
    p8 = pct_change_over(df, 8)
    p12 = pct_change_over(df, 12)

    out = pd.DataFrame({"pct_4w": p4, "pct_8w": p8, "pct_12w": p12})
    out["raw_score"] = 2 * out["pct_4w"] + out["pct_8w"] + out["pct_12w"]

    industry_map = df.drop_duplicates("ticker").set_index("ticker")["industry"]
    out["industry"] = industry_map
    out = out.dropna(subset=["raw_score"])
    out.index.name = "ticker"
    return out.reset_index()


def raw_score_to_rs(raw_scores: pd.Series) -> pd.Series:
    """Áp công thức bách phân: RS = ((N - rank)/N)*99 + 1, rank 1 = điểm thô cao nhất."""
    n = len(raw_scores)
    # rank 1 = cao nhất -> dùng ascending=False
    rank = raw_scores.rank(method="min", ascending=False)
    rs = ((n - rank) / n) * 99 + 1
    return rs.round(0).astype(int)


def compute_industry_rs(stock_table: pd.DataFrame) -> pd.DataFrame:
    industry_raw = stock_table.groupby("industry")["raw_score"].mean().rename("industry_raw_score")
    industry_df = industry_raw.reset_index()
    industry_df["RS_nganh"] = raw_score_to_rs(industry_df["industry_raw_score"])
    return industry_df.sort_values("RS_nganh", ascending=False)


# ----------------------------------------------------------------------------
# 3. GIAO DIỆN
# ----------------------------------------------------------------------------

st.title("📈 Bảng xếp hạng RS chứng khoán")
st.caption("Xếp hạng sức mạnh giá (Relative Strength) theo phương pháp trọng số 4/8/12 tuần, thang điểm 1-99")

import os

with st.sidebar:
    st.header("Nguồn dữ liệu")

    AUTO_FILE = "gia_lich_su_rs.csv"
    has_auto_file = os.path.exists(AUTO_FILE)

    source_options = ["Dữ liệu mẫu (demo)", "Tải file CSV giá có sẵn", "Lấy dữ liệu thật qua vnstock"]
    default_index = 0
    if has_auto_file:
        source_options.insert(0, "Dữ liệu tự động cập nhật hàng ngày")
        default_index = 0

    source = st.radio("Chọn nguồn dữ liệu", source_options, index=default_index)

    if source == "Dữ liệu tự động cập nhật hàng ngày":
        price_df = load_uploaded_data_from_path(AUTO_FILE)
        mtime = pd.Timestamp.fromtimestamp(os.path.getmtime(AUTO_FILE))
        st.success(f"Dữ liệu cập nhật lần cuối: {mtime:%d/%m/%Y %H:%M}")

    elif source == "Tải file CSV giá có sẵn":
        uploaded = st.file_uploader(
            "CSV với 4 cột: date, ticker, industry, close", type=["csv"]
        )
        if uploaded is None:
            st.info("Chưa có file, dùng tạm dữ liệu mẫu để xem giao diện.")
            price_df = generate_sample_data()
        else:
            price_df = load_uploaded_data(uploaded)

    elif source == "Lấy dữ liệu thật qua vnstock":
        st.caption(
            "Cần: `pip install -U vnstock` và đã cấu hình API key "
            "(xem hướng dẫn tại vnstocks.com/onboard/agent-guide)."
        )
        ind_file = st.file_uploader(
            "File danh sách mã theo ngành (2 cột: Mã, Ngành)", type=["csv"], key="ind_map"
        )
        weeks_back = st.slider("Số tuần dữ liệu cần lấy", 13, 52, 20)

        if ind_file is None:
            st.info("Chưa có file danh sách mã, dùng tạm dữ liệu mẫu để xem giao diện.")
            price_df = generate_sample_data()
        else:
            industry_map_df = load_industry_map_csv(ind_file)
            run = st.button("🔄 Tải dữ liệu từ vnstock", use_container_width=True)
            if run:
                tickers_tuple = tuple(industry_map_df["ticker"].tolist())
                raw_price_df = fetch_vnstock_weekly(tickers_tuple, weeks_back=weeks_back)
                price_df = raw_price_df.merge(industry_map_df, on="ticker", how="left")
                price_df["industry"] = price_df["industry"].fillna("Chưa phân loại")
                st.session_state["price_df_vnstock"] = price_df
            price_df = st.session_state.get("price_df_vnstock", generate_sample_data())

    else:
        n_tickers = st.slider("Số mã cổ phiếu (demo)", 10, 200, 60)
        price_df = generate_sample_data(n_tickers=n_tickers)

    st.divider()
    st.header("Bộ lọc")
    min_rs = st.slider("RS tối thiểu", 1, 99, 1)

# --- Tính toán ---
stock_scores = compute_raw_scores(price_df)
stock_scores["RS"] = raw_score_to_rs(stock_scores["raw_score"])
stock_scores = stock_scores.sort_values("RS", ascending=False)

industry_scores = compute_industry_rs(stock_scores)

with st.sidebar:
    industries_available = sorted(stock_scores["industry"].unique())
    chosen_industries = st.multiselect("Ngành", industries_available, default=industries_available)

filtered = stock_scores[
    (stock_scores["RS"] >= min_rs) & (stock_scores["industry"].isin(chosen_industries))
]

# --- Tổng quan ---
col1, col2, col3 = st.columns(3)
col1.metric("Số mã đang theo dõi", len(stock_scores))
col2.metric("Số mã hiển thị (sau lọc)", len(filtered))
col3.metric("Số ngành", stock_scores["industry"].nunique())

tab1, tab2 = st.tabs(["🏆 Xếp hạng cổ phiếu", "🏭 Xếp hạng ngành"])

with tab1:
    st.subheader("Bảng xếp hạng RS cổ phiếu")
    display_df = filtered[["ticker", "industry", "pct_4w", "pct_8w", "pct_12w", "raw_score", "RS"]].copy()
    display_df.columns = ["Mã", "Ngành", "%Δ 4w", "%Δ 8w", "%Δ 12w", "Điểm thô", "RS"]
    for c in ["%Δ 4w", "%Δ 8w", "%Δ 12w", "Điểm thô"]:
        display_df[c] = display_df[c].round(2)
    st.dataframe(
        display_df.sort_values("RS", ascending=False).reset_index(drop=True),
        use_container_width=True,
        height=500,
    )

    st.subheader("Top 20 mã theo RS")
    top20 = display_df.sort_values("RS", ascending=False).head(20)
    fig = px.bar(top20, x="Mã", y="RS", color="Ngành", title=None)
    st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("Bảng xếp hạng RS ngành")
    ind_display = industry_scores.copy()
    ind_display.columns = ["Ngành", "Điểm thô Ngành", "RS Ngành"]
    ind_display["Điểm thô Ngành"] = ind_display["Điểm thô Ngành"].round(2)
    st.dataframe(ind_display.reset_index(drop=True), use_container_width=True)

    fig2 = px.bar(
        ind_display.sort_values("RS Ngành", ascending=False),
        x="Ngành", y="RS Ngành", color="RS Ngành",
        color_continuous_scale="RdYlGn",
    )
    st.plotly_chart(fig2, use_container_width=True)

st.divider()
with st.expander("ℹ️ Dùng file danh_sach_ma_theo_nganh.csv (mã, ngành) với vnstock"):
    st.markdown(
        "- Chọn nguồn **'Lấy dữ liệu thật qua vnstock'** ở sidebar, tải lên file có 2 cột "
        "**Mã** và **Ngành** (giống file bạn đang dùng trong Jupyter).\n"
        "- App sẽ tự gọi `Market().equity(ticker).ohlcv(interval='1W')` cho từng mã để lấy giá tuần.\n"
        "- Cần cài `pip install -U vnstock` và cấu hình API key theo Vnstock Agent Guide "
        "(đăng nhập Google trên vnstocks.com để lấy key, thư viện sẽ tự lưu và dùng lại).\n"
        "- Nếu số lượng mã lớn, lần tải đầu sẽ hơi lâu vì gọi API tuần tự cho từng mã — "
        "kết quả được cache lại nên các lần sau (không đổi tham số) sẽ nhanh hơn."
    )

with st.expander("ℹ️ Định dạng CSV để dùng dữ liệu thật (nhập tay / nguồn khác)"):
    st.code(
        "date,ticker,industry,close\n"
        "2026-01-02,ABC,Ngân hàng,25.4\n"
        "2026-01-09,ABC,Ngân hàng,26.1\n"
        "...",
        language="csv",
    )
    st.markdown(
        "- Cần tối thiểu **13 tuần** dữ liệu giá (mỗi mã) để tính đủ 3 khung 4w/8w/12w.\n"
        "- `date` nên là giá đóng cửa cuối tuần (hoặc cuối ngày, tuỳ bạn định nghĩa 'tuần').\n"
        "- Mỗi mã cần có cột `industry` giống nhau qua các dòng để gộp nhóm ngành."
    )
