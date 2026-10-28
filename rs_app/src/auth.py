"""
Đăng ký / đăng nhập cho Chứng khoán sung rụng (Streamlit).

Thiết kế dựa trên bản của Dupont nhưng đã sửa các điểm yếu bảo mật:
- Mật khẩu băm bằng bcrypt (salt riêng cho từng người, chậm có chủ đích) thay vì SHA-256 + salt cố định.
- Token phiên ngẫu nhiên (secrets.token_urlsafe), CHỈ lưu hash của token phía server, có hạn dùng.
- Giới hạn đăng nhập sai (khoá tạm theo tên đăng nhập) và giới hạn số lần đăng ký.
- Không có mật khẩu admin mặc định trong mã: admin được tạo từ secrets (ADMIN_USERNAME/ADMIN_PASSWORD).
- Lưu trữ: Upstash Redis (khuyên dùng, bền vững) hoặc file JSON cục bộ (chỉ để chạy thử trên máy).
  Mỗi người dùng là 1 field riêng của Redis hash -> 2 người đăng ký cùng lúc không ghi đè nhau;
  phiên dùng khoá riêng có TTL nên Redis tự xoá phiên hết hạn.
"""

import hashlib
import json
import os
import re
import secrets
import time
from datetime import datetime
from pathlib import Path

import bcrypt
import streamlit as st

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LOCAL_USERS_FILE = DATA_DIR / "users.json"
LOCAL_STATE_FILE = DATA_DIR / "auth_state.json"  # phiên + bộ đếm giới hạn khi chạy không có Redis

REDIS_USERS_KEY = "rs:users"          # hash: field = username (chữ thường), value = JSON người dùng
REDIS_SESSION_PREFIX = "rs:session:"  # khoá riêng cho mỗi phiên, có TTL
REDIS_RATE_PREFIX = "rs:rate:"

SESSION_TTL_SECONDS = 7 * 24 * 3600   # phiên sống 7 ngày
MAX_FAILED_LOGINS = 5                 # sai quá số lần này thì khoá tạm
LOCKOUT_SECONDS = 15 * 60
MAX_REGISTER_PER_HOUR = 20            # giới hạn đăng ký toàn hệ thống mỗi giờ (chống spam)
MIN_PASSWORD_LEN = 8
BCRYPT_ROUNDS = 12


# ----------------------------------------------------------------------------
# Cấu hình & lưu trữ (Redis hoặc file cục bộ)
# ----------------------------------------------------------------------------

def _secret(name: str, default: str | None = None) -> str | None:
    """Đọc từ st.secrets rồi tới biến môi trường."""
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.environ.get(name, default)


def _redis_config() -> tuple[str | None, str | None]:
    url = _secret("UPSTASH_REDIS_REST_URL")
    token = _secret("UPSTASH_REDIS_REST_TOKEN")
    if url:
        url = url.strip()
        if not url.startswith("http"):
            url = "https://" + url
    return url, (token.strip() if token else None)


def redis_enabled() -> bool:
    url, token = _redis_config()
    return bool(url and token)


def _redis(*command):
    """Gọi 1 lệnh Redis qua Upstash REST. Trả về result, hoặc ném lỗi nếu không gọi được."""
    import requests
    url, token = _redis_config()
    resp = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=list(command), timeout=5)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data.get("result")


def _read_local(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_local(path: Path, data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def storage_status() -> dict:
    """Trạng thái lưu trữ, hiển thị cho admin."""
    if not redis_enabled():
        return {"ok": False, "label": "📁 File cục bộ (mất khi máy chủ khởi động lại)",
                "detail": "Chưa cấu hình Upstash Redis — chỉ nên dùng khi chạy thử."}
    try:
        if _redis("PING") == "PONG":
            return {"ok": True, "label": "⚡ Upstash Redis (bền vững)", "detail": "Kết nối bình thường."}
    except Exception as e:
        return {"ok": False, "label": "⚠️ Lỗi kết nối Redis", "detail": f"{type(e).__name__}"}
    return {"ok": False, "label": "⚠️ Redis không phản hồi PING", "detail": ""}


# --- Người dùng ---

def _get_user(username: str) -> dict | None:
    key = username.strip().lower()
    if not key:
        return None
    if redis_enabled():
        raw = _redis("HGET", REDIS_USERS_KEY, key)
        return json.loads(raw) if raw else None
    return _read_local(LOCAL_USERS_FILE).get(key)


def _put_user(user: dict) -> None:
    key = user["username"].lower()
    if redis_enabled():
        _redis("HSET", REDIS_USERS_KEY, key, json.dumps(user, ensure_ascii=False))
    else:
        users = _read_local(LOCAL_USERS_FILE)
        users[key] = user
        _write_local(LOCAL_USERS_FILE, users)


def _all_users() -> dict:
    if redis_enabled():
        flat = _redis("HGETALL", REDIS_USERS_KEY) or []
        # Upstash trả về mảng phẳng [field, value, field, value...]
        return {flat[i]: json.loads(flat[i + 1]) for i in range(0, len(flat), 2)}
    return _read_local(LOCAL_USERS_FILE)


def _delete_user(username: str) -> None:
    key = username.strip().lower()
    if redis_enabled():
        _redis("HDEL", REDIS_USERS_KEY, key)
    else:
        users = _read_local(LOCAL_USERS_FILE)
        users.pop(key, None)
        _write_local(LOCAL_USERS_FILE, users)


# --- Khoá TTL (phiên, bộ đếm) ---

def _kv_set(key: str, value: str, ttl: int) -> None:
    if redis_enabled():
        _redis("SET", key, value, "EX", str(ttl))
        return
    state = _read_local(LOCAL_STATE_FILE)
    state[key] = {"v": value, "exp": time.time() + ttl}
    _write_local(LOCAL_STATE_FILE, state)


def _kv_get(key: str) -> str | None:
    if redis_enabled():
        return _redis("GET", key)
    state = _read_local(LOCAL_STATE_FILE)
    item = state.get(key)
    if not item:
        return None
    if item["exp"] < time.time():
        state.pop(key, None)
        _write_local(LOCAL_STATE_FILE, state)
        return None
    return item["v"]


def _kv_del(key: str) -> None:
    if redis_enabled():
        _redis("DEL", key)
        return
    state = _read_local(LOCAL_STATE_FILE)
    if state.pop(key, None) is not None:
        _write_local(LOCAL_STATE_FILE, state)


def _kv_incr(key: str, ttl: int) -> int:
    """Tăng bộ đếm; lần đầu tạo bộ đếm có TTL."""
    if redis_enabled():
        n = int(_redis("INCR", key))
        if n == 1:
            _redis("EXPIRE", key, str(ttl))
        return n
    state = _read_local(LOCAL_STATE_FILE)
    item = state.get(key)
    if not item or item["exp"] < time.time():
        item = {"v": "0", "exp": time.time() + ttl}
    item["v"] = str(int(item["v"]) + 1)
    state[key] = item
    _write_local(LOCAL_STATE_FILE, state)
    return int(item["v"])


# ----------------------------------------------------------------------------
# Mật khẩu
# ----------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


_DUMMY_HASH = None


def _dummy_hash() -> str:
    """Hash giả hợp lệ, dùng để mất cùng thời gian khi tên đăng nhập không tồn tại."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("dummy-password-for-timing")
    return _DUMMY_HASH


def validate_password(password: str) -> str | None:
    """Trả về thông báo lỗi nếu mật khẩu yếu, None nếu hợp lệ."""
    if len(password) < MIN_PASSWORD_LEN:
        return f"Mật khẩu cần ít nhất {MIN_PASSWORD_LEN} ký tự."
    if len(password.encode("utf-8")) > 72:
        return "Mật khẩu tối đa 72 byte (giới hạn của bcrypt)."
    if password.isdigit() or password.isalpha():
        return "Mật khẩu cần kết hợp cả chữ và số."
    return None


# ----------------------------------------------------------------------------
# Đăng ký / đăng nhập
# ----------------------------------------------------------------------------

EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,20}$")


def public_user(user: dict) -> dict:
    """Bản người dùng KHÔNG có hash mật khẩu, an toàn để đưa vào session_state/giao diện."""
    return {k: v for k, v in user.items() if k != "password_hash"}


def ensure_admin() -> None:
    """Tạo admin ban đầu từ secrets (ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_EMAIL) nếu chưa có.
    Không có mật khẩu mặc định trong mã nguồn."""
    username = _secret("ADMIN_USERNAME")
    password = _secret("ADMIN_PASSWORD")
    if not username or not password:
        return
    try:
        if _get_user(username):
            return
        _put_user({
            "username": username.strip(),
            "fullname": _secret("ADMIN_FULLNAME", username),
            "email": _secret("ADMIN_EMAIL", f"{username}@example.com"),
            "password_hash": hash_password(password),
            "role": "admin",
            "status": "active",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    except Exception:
        pass


def register_user(username, fullname, email, password, confirm) -> tuple[bool, str]:
    username, fullname, email = (username or "").strip(), (fullname or "").strip(), (email or "").strip()
    if not (username and fullname and email and password):
        return False, "Vui lòng điền đầy đủ các trường."
    if not USERNAME_RE.match(username):
        return False, "Tên đăng nhập 3–20 ký tự, chỉ gồm chữ không dấu, số và gạch dưới."
    if len(fullname) < 2:
        return False, "Họ và tên cần ít nhất 2 ký tự."
    if not EMAIL_RE.match(email):
        return False, "Email không hợp lệ."
    err = validate_password(password)
    if err:
        return False, err
    if password != confirm:
        return False, "Mật khẩu xác nhận không khớp."

    try:
        if _kv_incr(REDIS_RATE_PREFIX + "register", 3600) > MAX_REGISTER_PER_HOUR:
            return False, "Có quá nhiều lượt đăng ký trong thời gian ngắn. Vui lòng thử lại sau."
        if _get_user(username):
            return False, f"Tên đăng nhập '{username}' đã được sử dụng."
        for u in _all_users().values():
            if u.get("email", "").lower() == email.lower():
                return False, "Email này đã được đăng ký."
        _put_user({
            "username": username, "fullname": fullname, "email": email,
            "password_hash": hash_password(password), "role": "member", "status": "active",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    except Exception:
        return False, "Không lưu được dữ liệu (lỗi lưu trữ). Vui lòng thử lại sau."
    return True, f"Đăng ký thành công! Chào mừng **{fullname}**, hãy chuyển sang tab Đăng nhập."


def authenticate(username: str, password: str) -> tuple[bool, str, dict | None]:
    username = (username or "").strip()
    if not username or not password:
        return False, "Vui lòng nhập cả tên đăng nhập và mật khẩu.", None
    key = username.lower()
    fail_key = REDIS_RATE_PREFIX + "fail:" + key
    try:
        fails = int(_kv_get(fail_key) or 0)
        if fails >= MAX_FAILED_LOGINS:
            return False, "Đăng nhập sai quá nhiều lần. Tài khoản bị khoá tạm 15 phút.", None

        user = _get_user(username)
        # Luôn băm 1 lần dù tài khoản không tồn tại để thời gian phản hồi không lộ tên đăng nhập có thật
        ok = verify_password(password, user["password_hash"] if user else _dummy_hash())
        if not user or not ok:
            _kv_incr(fail_key, LOCKOUT_SECONDS)
            return False, "Tên đăng nhập hoặc mật khẩu không đúng.", None
        if user.get("status") == "blocked":
            return False, "Tài khoản đã bị khoá. Vui lòng liên hệ quản trị viên.", None
        _kv_del(fail_key)
        return True, "Đăng nhập thành công!", public_user(user)
    except Exception:
        return False, "Lỗi hệ thống lưu trữ, vui lòng thử lại sau.", None


# ----------------------------------------------------------------------------
# Phiên đăng nhập (token trên URL ?session=..., để giữ phiên khi F5)
# ----------------------------------------------------------------------------

def _token_key(token: str) -> str:
    return REDIS_SESSION_PREFIX + hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    _kv_set(_token_key(token), username.lower(), SESSION_TTL_SECONDS)
    return token


def restore_session() -> bool:
    token = st.query_params.get("session")
    if not token:
        return False
    try:
        username = _kv_get(_token_key(token))
        user = _get_user(username) if username else None
    except Exception:
        return False
    if not user or user.get("status") == "blocked":
        return False
    st.session_state["authenticated"] = True
    st.session_state["user"] = public_user(user)
    return True


def init_session() -> None:
    st.session_state.setdefault("authenticated", False)
    st.session_state.setdefault("user", None)
    if not st.session_state["authenticated"]:
        restore_session()


def login(user: dict) -> None:
    token = create_session(user["username"])
    st.query_params["session"] = token
    st.session_state["authenticated"] = True
    st.session_state["user"] = user
    st.rerun()


def logout() -> None:
    token = st.query_params.get("session")
    if token:
        try:
            _kv_del(_token_key(token))
        except Exception:
            pass
        try:
            del st.query_params["session"]
        except Exception:
            st.query_params.clear()
    st.session_state["authenticated"] = False
    st.session_state["user"] = None
    st.rerun()


# ----------------------------------------------------------------------------
# Quản trị (chỉ admin)
# ----------------------------------------------------------------------------

def list_users() -> list[dict]:
    users = [public_user(u) for u in _all_users().values()]
    users.sort(key=lambda u: (0 if u.get("role") == "admin" else 1, u.get("created_at", "")))
    return users


def _admin_target(username: str):
    user = _get_user(username)
    if not user:
        return None, "Không tìm thấy người dùng."
    if user.get("role") == "admin":
        return None, "Không thao tác khoá/xoá trên tài khoản quản trị viên."
    return user, None


def set_user_status(username: str, status: str) -> tuple[bool, str]:
    user, err = _admin_target(username)
    if err:
        return False, err
    user["status"] = status
    _put_user(user)
    return True, f"Đã {'khoá' if status == 'blocked' else 'mở khoá'} '{username}'."


def reset_password(username: str, new_password: str) -> tuple[bool, str]:
    err = validate_password(new_password)
    if err:
        return False, err
    user = _get_user(username)
    if not user:
        return False, "Không tìm thấy người dùng."
    user["password_hash"] = hash_password(new_password)
    _put_user(user)
    return True, f"Đã đặt lại mật khẩu cho '{username}'."


def delete_user(username: str) -> tuple[bool, str]:
    user, err = _admin_target(username)
    if err:
        return False, err
    _delete_user(username)
    return True, f"Đã xoá '{username}'."


# ---------------------------------------------------------------- Danh sách theo dõi (riêng từng người dùng)
REDIS_WATCH_KEY = "rs:watch"             # hash: field = username (chữ thường), value = JSON danh sách
WATCH_FILE = DATA_DIR / "watchlists.json"
MAX_WATCH = 100


def get_watchlist(username: str) -> list[dict]:
    """[{"ticker": "MSR", "note": "...", "added": "2026-10-28"}, ...]"""
    key = username.strip().lower()
    if redis_enabled():
        raw = _redis("HGET", REDIS_WATCH_KEY, key)
        try:
            return json.loads(raw) if raw else []
        except ValueError:
            return []
    return _read_local(WATCH_FILE).get(key, [])


def set_watchlist(username: str, items: list[dict]) -> None:
    key = username.strip().lower()
    items = [{"ticker": str(i["ticker"]).upper(), "note": str(i.get("note", ""))[:300], "added": i.get("added", "")}
             for i in items][:MAX_WATCH]
    if redis_enabled():
        _redis("HSET", REDIS_WATCH_KEY, key, json.dumps(items, ensure_ascii=False))
    else:
        data = _read_local(WATCH_FILE)
        data[key] = items
        _write_local(WATCH_FILE, data)
