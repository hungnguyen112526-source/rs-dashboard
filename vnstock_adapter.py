"""Lớp mỏng nối vnstock THẾ HỆ 6 (Open API): mọi chỗ phụ thuộc vào "nguồn dữ liệu" nằm ở đây.

Mục tiêu: sau này đổi nguồn (tcbs, ssi, dnse, fhsc...) chỉ cần đổi biến môi trường, KHÔNG sửa code.

  VNSTOCK_SOURCE   tên nguồn Open API bạn đã đăng ký khoá (vd tcbs | ssi | dnse | fhsc). KHÔNG có giá trị mặc định:
                   thế hệ 6 không tự chọn nguồn thay bạn, code này cũng vậy.
  FIN_SOURCE       (tuỳ chọn) nguồn riêng cho báo cáo tài chính; để trống = dùng VNSTOCK_SOURCE.
                   Lưu ý: theo tài liệu thế hệ 6.0.1, báo cáo tài chính hiện chỉ có ở nguồn `fhsc`.

Khoá API của nguồn và khoá tài khoản Vnstock KHÔNG nằm trong code: đặt bằng `vnstock keys set <nguồn>` /
`vnstock login` trên máy, hoặc biến môi trường (<NGUỒN>_API_KEY, VNSTOCK_API_KEY) trong GitHub Secrets.
"""
import os
import re

SOURCE_ENV = "VNSTOCK_SOURCE"
FIN_SOURCE_ENV = "FIN_SOURCE"

# Mã lỗi ổn định của vnstock 6 (xem vnstocks.com/docs/vnstock/v6/xu-ly-loi). Chỉ dùng mã khi chắc chắn,
# còn lại so khớp theo từ khoá để không phụ thuộc vào tên mã cụ thể.
_CODE_RE = re.compile(r"VNSTOCK_[A-Z0-9_]+")
RATE_LIMIT_HINTS = ("rate limit", "hạn mức", "ha n muc", "429", "too many requests")
UNSUPPORTED_CODES = ("VNSTOCK_ROUTE_UNSUPPORTED", "VNSTOCK_INPUT_SOURCE", "VNSTOCK_VAS_TEMPLATE_UNSUPPORTED")


class SourceNotConfigured(RuntimeError):
    """Chưa khai báo nguồn dữ liệu (VNSTOCK_SOURCE)."""


def get_source(env_name: str = SOURCE_ENV, fallback_env: str = "") -> str:
    """Đọc tên nguồn từ biến môi trường. Không có -> báo lỗi rõ ràng, không đoán."""
    value = (os.environ.get(env_name) or (os.environ.get(fallback_env) if fallback_env else "") or "").strip().lower()
    if not value:
        raise SourceNotConfigured(
            f"chưa khai báo nguồn dữ liệu: đặt biến môi trường {env_name}=<nguồn> (vd tcbs, ssi, dnse, fhsc)"
        )
    return value


def error_code(exc: BaseException) -> str:
    """Mã lỗi VNSTOCK_* của một ngoại lệ (thuộc tính .code, hoặc tìm trong nội dung), '' nếu không có."""
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        return code
    m = _CODE_RE.search(str(exc))
    return m.group(0) if m else ""


def is_rate_limited(exc: BaseException) -> bool:
    code = error_code(exc).upper()
    if "RATE" in code or "LIMIT" in code or "THROTTLE" in code:
        return True
    return any(h in str(exc).lower() for h in RATE_LIMIT_HINTS)


def is_unsupported(exc: BaseException) -> bool:
    """Nguồn đã chọn không có chức năng này (hoặc chưa chọn nguồn): thử lại cũng vô ích."""
    code = error_code(exc).upper()
    return code in UNSUPPORTED_CODES or "UNSUPPORTED" in code


def make_market(source: str = ""):
    """Market(<nguồn>) của vnstock 6. Import muộn để các workflow không dùng vnstock không cần cài thư viện."""
    source = source or get_source()          # kiểm tra nguồn TRƯỚC khi import để báo lỗi đúng chỗ
    from vnstock import Market  # noqa: PLC0415
    return Market(source)


def make_fundamental():
    from vnstock import Fundamental  # noqa: PLC0415
    return Fundamental()
