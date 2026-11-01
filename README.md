# rs-dashboard
Dashboard xếp hạng RS chứng khoán (Streamlit, thư mục `rs_app/`), dữ liệu cập nhật tự động bằng GitHub Actions.

## Dữ liệu và workflow (`.github/workflows/`)
| Workflow | Việc làm | Lịch (giờ VN) |
|---|---|---|
| `update_data.yml` | giá vnstock, phần đuôi | T2-T6, 6 lần/ngày |
| `update_data_full.yml` | giá vnstock, toàn bộ lịch sử | 15 lần/ngày, cả cuối tuần |
| `update_data_tv.yml` | giá TradingView | Chủ nhật 08:00 (full), thứ Hai 16:00 |
| `update_macro.yml` | vĩ mô + lãi suất trái phiếu | T2-T6 6 lần/ngày + 05:15 hằng ngày |
| `update_financials.yml` | BCTC | T2-T6 08:00 |
| `update_calendar.yml` | lịch kinh tế | T2-T6, mỗi 3 giờ |
| `update_news.yml` | tin tức RSS | mỗi 2 giờ |

App đọc trực tiếp các file `gia_lich_su_rs.csv`, `macro_data.json`, `financials_data.json`, `news_data.json`, ... trong repo.
Xem `rs_app/README.md` để cấu hình và chạy app.
