"""
Sinh báo cáo HTML tĩnh (bảng xếp hạng RS) từ gia_lich_su_rs.csv
Dùng để publish lên GitHub Pages — không cần Streamlit, không cần server chạy liên tục.
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime

INPUT_FILE = "gia_lich_su_rs.csv"
OUTPUT_FILE = "docs/index.html"


def pct_change_over(df, weeks):
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


def raw_score_to_rs(raw_scores):
    n = len(raw_scores)
    rank = raw_scores.rank(method="min", ascending=False)
    rs = ((n - rank) / n) * 99 + 1
    return rs.round(0).astype(int)


def main():
    df = pd.read_csv(INPUT_FILE, parse_dates=["date"])

    pct_4w = pct_change_over(df, 4)
    pct_8w = pct_change_over(df, 8)
    pct_12w = pct_change_over(df, 12)

    scores = pd.DataFrame({"pct_4w": pct_4w, "pct_8w": pct_8w, "pct_12w": pct_12w})
    scores["raw_score"] = 2 * scores["pct_4w"] + scores["pct_8w"] + scores["pct_12w"]
    industry_map = df.drop_duplicates("ticker").set_index("ticker")["industry"]
    scores["industry"] = industry_map
    scores = scores.dropna(subset=["raw_score"])
    scores.index.name = "ticker"
    scores = scores.reset_index()
    scores["RS"] = raw_score_to_rs(scores["raw_score"])
    scores = scores.sort_values("RS", ascending=False)

    industry_raw = scores.groupby("industry")["raw_score"].mean().rename("industry_raw_score")
    industry_df = industry_raw.reset_index()
    industry_df["RS_nganh"] = raw_score_to_rs(industry_df["industry_raw_score"])
    industry_df = industry_df.sort_values("RS_nganh", ascending=False)

    def rs_color(rs):
        if rs >= 80:
            return "#16a34a"
        if rs >= 50:
            return "#ca8a04"
        return "#dc2626"

    def stock_rows(df_):
        rows = ""
        for _, r in df_.iterrows():
            rows += f"""<tr>
                <td>{r['ticker']}</td>
                <td>{r['industry']}</td>
                <td>{r['pct_4w']:.1f}%</td>
                <td>{r['pct_8w']:.1f}%</td>
                <td>{r['pct_12w']:.1f}%</td>
                <td>{r['raw_score']:.1f}</td>
                <td style="font-weight:bold;color:{rs_color(r['RS'])}">{r['RS']}</td>
            </tr>"""
        return rows

    def industry_rows(df_):
        rows = ""
        for _, r in df_.iterrows():
            rows += f"""<tr>
                <td>{r['industry']}</td>
                <td>{r['industry_raw_score']:.1f}</td>
                <td style="font-weight:bold;color:{rs_color(r['RS_nganh'])}">{r['RS_nganh']}</td>
            </tr>"""
        return rows

    updated_at = datetime.now().strftime("%d/%m/%Y %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<title>Bảng xếp hạng RS chứng khoán</title>
<style>
  body {{ font-family: -apple-system, Arial, sans-serif; background:#0f172a; color:#e2e8f0; margin:0; padding:24px; }}
  h1 {{ font-size: 22px; }}
  .updated {{ color:#94a3b8; font-size: 13px; margin-bottom: 24px; }}
  table {{ width:100%; border-collapse: collapse; margin-bottom: 40px; background:#1e293b; border-radius:8px; overflow:hidden; }}
  th, td {{ padding: 8px 12px; text-align:left; border-bottom:1px solid #334155; font-size: 14px; }}
  th {{ background:#334155; position: sticky; top:0; }}
  tr:hover {{ background:#334155; }}
  .section-title {{ font-size: 18px; margin: 24px 0 12px; }}
</style>
</head>
<body>
  <h1>📈 Bảng xếp hạng RS chứng khoán</h1>
  <div class="updated">Cập nhật lần cuối: {updated_at}</div>

  <div class="section-title">🏆 Xếp hạng cổ phiếu</div>
  <table>
    <tr><th>Mã</th><th>Ngành</th><th>%Δ 4w</th><th>%Δ 8w</th><th>%Δ 12w</th><th>Điểm thô</th><th>RS</th></tr>
    {stock_rows(scores)}
  </table>

  <div class="section-title">🏭 Xếp hạng ngành</div>
  <table>
    <tr><th>Ngành</th><th>Điểm thô Ngành</th><th>RS Ngành</th></tr>
    {industry_rows(industry_df)}
  </table>
</body>
</html>"""

    os.makedirs("docs", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Đã tạo {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
