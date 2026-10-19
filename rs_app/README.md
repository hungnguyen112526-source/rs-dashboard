# RS Dashboard (Streamlit) — có đăng ký / đăng nhập

Bản Streamlit của RS Dashboard. Đợt 1 gồm: cổng đăng ký/đăng nhập, trang **Xếp hạng RS** (ngày/tuần),
trang **Lọc KLGD giảm dần**, và trang **Quản trị người dùng** (chỉ admin).
Bản trang tĩnh cũ (GitHub Pages) vẫn giữ nguyên làm dự phòng.

## Đặt vào repo
Chép thư mục `rs_app/` vào repo `rs-dashboard` (cạnh `gia_lich_su_rs.csv`). App tự tìm file dữ liệu trong
`rs_app/` hoặc thư mục cha, và GitHub Actions hiện có vẫn cập nhật file đó như cũ.
Trên Streamlit Cloud chọn **Main file path = `rs_app/app.py`**.

## Cấu hình bí mật (Secrets)
Xem `.streamlit/secrets.toml.example`. Bắt buộc:
- `ADMIN_USERNAME`, `ADMIN_PASSWORD` — tài khoản quản trị tạo tự động ở lần chạy đầu (đặt mật khẩu mạnh).
- `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` — lưu tài khoản/phiên bền vững
  (tạo Redis miễn phí tại upstash.com, lấy mục REST API). Không có Redis thì app lưu file cục bộ và
  **mất tài khoản mỗi lần máy chủ khởi động lại**.

## Chạy thử trên máy
```
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # sửa lại giá trị
streamlit run app.py
```

## Bảo mật đã áp dụng (so với bản Dupont)
- bcrypt cho mật khẩu (salt riêng từng người); mật khẩu ≥ 8 ký tự, có cả chữ và số.
- Token phiên ngẫu nhiên, chỉ lưu hash phía server, hết hạn sau 7 ngày, huỷ khi đăng xuất.
- Sai mật khẩu 5 lần → khoá 15 phút; giới hạn 20 lượt đăng ký/giờ.
- Không có mật khẩu mặc định trong mã; không đưa hash mật khẩu vào session.
- Người dùng lưu theo từng field Redis (không ghi đè nhau khi đăng ký đồng thời).
- Giới hạn còn lại: token nằm trên URL (`?session=`) nên đừng chia sẻ link khi đã đăng nhập; chưa có xác thực email và quên mật khẩu (admin đặt lại).

## Lưu ý quan trọng về quyền riêng tư dữ liệu
Đăng nhập chỉ chặn việc vào ứng dụng. Nếu repo GitHub để **public**, ai cũng đọc được `gia_lich_su_rs.csv`.
Muốn dữ liệu thật sự riêng tư phải để repo **private** — nhưng GitHub Pages (bản dự phòng) cần gói trả phí cho repo private.
