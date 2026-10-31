"""
Lưu tài khoản và lệnh giao dịch giả lập, riêng từng người dùng.
Dùng lại hạ tầng của auth.py: Upstash Redis (bền vững) hoặc file JSON cục bộ (chỉ để chạy thử).

Redis: 2 hash, field = username (chữ thường)
  rs:paper:acct   -> JSON {"start_cash": ..., "created": "YYYY-MM-DD"}
  rs:paper:trades -> JSON danh sách lệnh đã khớp (xem paper_engine.make_trade)
"""
from __future__ import annotations

import json

from src import auth

REDIS_ACCT_KEY = "rs:paper:acct"
REDIS_TRADES_KEY = "rs:paper:trades"
PAPER_FILE = auth.DATA_DIR / "paper.json"


def _key(username: str) -> str:
    return username.strip().lower()


def _loads(raw, default):
    try:
        return json.loads(raw) if raw else default
    except ValueError:
        return default


def get_account(username: str) -> dict | None:
    k = _key(username)
    if auth.redis_enabled():
        return _loads(auth._redis("HGET", REDIS_ACCT_KEY, k), None)
    return auth._read_local(PAPER_FILE).get(k, {}).get("acct")


def get_trades(username: str) -> list[dict]:
    k = _key(username)
    if auth.redis_enabled():
        return _loads(auth._redis("HGET", REDIS_TRADES_KEY, k), [])
    return auth._read_local(PAPER_FILE).get(k, {}).get("trades", [])


def _save(username: str, acct: dict | None = None, trades: list[dict] | None = None) -> None:
    k = _key(username)
    if auth.redis_enabled():
        if acct is not None:
            auth._redis("HSET", REDIS_ACCT_KEY, k, json.dumps(acct, ensure_ascii=False))
        if trades is not None:
            auth._redis("HSET", REDIS_TRADES_KEY, k, json.dumps(trades, ensure_ascii=False))
        return
    data = auth._read_local(PAPER_FILE)
    rec = data.setdefault(k, {})
    if acct is not None:
        rec["acct"] = acct
    if trades is not None:
        rec["trades"] = trades
    auth._write_local(PAPER_FILE, data)


def create_account(username: str, start_cash: int, today: str) -> dict:
    acct = {"start_cash": int(start_cash), "created": today}
    _save(username, acct=acct, trades=[])
    return acct


def add_trade(username: str, trade: dict, expected_len: int) -> tuple[bool, str]:
    """Ghi thêm 1 lệnh. Đọc lại ngay trước khi ghi: nếu số lệnh đã khác `expected_len`
    (vd. mở 2 tab cùng đặt lệnh) thì từ chối để người dùng tải lại, tránh ghi đè nhau."""
    trades = get_trades(username)
    if len(trades) != expected_len:
        return False, "Dữ liệu vừa thay đổi ở nơi khác (tab khác?). Hãy tải lại trang rồi đặt lại lệnh."
    trades.append(trade)
    _save(username, trades=trades)
    return True, ""
