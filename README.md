# rs-dashboard
Dashboard xếp hạng RS chứng khoán (Streamlit, thư mục `rs_app/`), dữ liệu cập nhật tự động bằng GitHub Actions.

## Dữ liệu và workflow (`.github/workflows/`)
| Workflow | Việc làm | Lịch (giờ VN) |
|---|---|---|
| `update_data.yml` | giá TradingView (tạm thời, thay vnstock), phần đuôi | T2-T6, 6 lần/ngày |
| `update_data_full.yml` | giá TradingView (tạm thời, thay vnstock), toàn bộ lịch sử | 15 lần/ngày, cả cuối tuần |
| `update_data_tv.yml` | giá TradingView | Chủ nhật 08:00 (full), thứ Hai 16:00 |
| `update_macro.yml` | vĩ mô + lãi suất trái phiếu + chỉ số chứng khoán thế giới (TradingView) | T2-T6 6 lần/ngày + 05:15 hằng ngày |
| `update_financials.yml` | BCTC (TẠM TẮT lịch, chỉ chạy tay; chờ nguồn dữ liệu mới) | — |
| `update_calendar.yml` | lịch kinh tế | T2-T6, mỗi 3 giờ |
| `update_news.yml` | tin tức RSS | mỗi 2 giờ |

App đọc trực tiếp các file `gia_lich_su_rs.csv`, `macro_data.json`, `financials_data.json`, `news_data.json`, ... trong repo.
Xem `rs_app/README.md` để cấu hình và chạy app.

## Dùng vnstock thế hệ 6 (Open API) - chạy thủ công
Các workflow hiện chạy bằng TradingView. Phần vnstock 6 (`fetch_data.py` với `PRICE_SOURCE=vnstock|auto`, `fetch_financials.py`) chạy trên máy bạn:
1. `python -m pip install -r requirements-vnstock6.txt` (nên dùng môi trường ảo riêng).
2. Tự đăng ký khoá ở nguồn rồi `vnstock keys set <nguồn>`; nếu có gói quyền sử dụng thì `vnstock login`. Không dán khoá vào code hay chat.
3. Khai báo nguồn **một chỗ** bằng biến môi trường, không có mặc định: PowerShell `$env:VNSTOCK_SOURCE="<nguồn>"` (đổi nguồn sau này chỉ cần đổi biến này; BCTC có thể dùng `FIN_SOURCE` riêng).
4. Kiểm tra nguồn có hỗ trợ chức năng cần dùng: `vnstock doctor`, `vnstock tools --source <nguồn>`.
5. Chạy: `python fetch_data.py` (giá) và `python fetch_financials.py` (BCTC). Lưu ý: theo tài liệu 6.0.1, nến giá có ở `dnse`, `fhsc`, `ssi`, `tcbs`; báo cáo tài chính hiện chỉ có ở `fhsc`. Nguồn có Smart OTP (như tcbs) không chạy tự động được trên GitHub Actions.
Bảng `ratio` không còn lấy từ vnstock ở đây (xem phần đầu `fetch_financials.py`).

### Cấu hình nguồn fhsc (Finhay Securities)
- **Local (PowerShell):** `vnstock keys set fhsc` (nhập khoá tại đó, không gõ trong lệnh/chat) rồi `$env:VNSTOCK_SOURCE="fhsc"`.
  Thử nhanh một mã: `python -c "from vnstock import Market; print(Market('fhsc').equity('FPT').ohlcv(start='2026-11-01').tail())"`.
  Thử BCTC an toàn (ghi `financials_data.sample.json`, không đụng file chính): `$env:FIN_LIMIT="3"; python fetch_financials.py`.
- **GitHub Actions:** Settings → Secrets and variables → Actions → New repository secret, tên `FHSC_API_KEY` (chỉ cần API Key; theo tài liệu vnstock-oapi, fhsc không dùng Secret Key).
  Khoá FHSC **hết hạn sau 30 ngày kể từ ngày tạo**: nhớ tạo lại và cập nhật Secret trước hạn.
- `update_data.yml` / `update_data_full.yml`: TradingView là chính, mã lỗi hoặc mã mới chuyển sang fhsc (`PRICE_SOURCE=auto`).
- `update_financials.yml`: lịch đang tắt; bấm chạy tay lần đầu và so sánh `financials_data.json` trước khi bật lịch.
