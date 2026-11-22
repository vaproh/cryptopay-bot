import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  telegram_id INTEGER PRIMARY KEY,
  role        TEXT NOT NULL DEFAULT 'member',
  added_by    INTEGER,
  added_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  token       TEXT NOT NULL UNIQUE,
  inv         TEXT UNIQUE,
  chat_id     INTEGER NOT NULL,
  chain       TEXT NOT NULL,
  asset       TEXT NOT NULL,
  provider    TEXT NOT NULL,
  usd         REAL NOT NULL,
  quote       REAL NOT NULL DEFAULT 0,
  received    REAL NOT NULL DEFAULT 0,
  status      TEXT NOT NULL DEFAULT 'pending',
  label       TEXT,
  address     TEXT,
  provider_ref TEXT,
  expires_at  TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS orders_chat ON orders(chat_id, id DESC);
CREATE TABLE IF NOT EXISTS payments (
  txid       TEXT PRIMARY KEY,
  order_id   INTEGER NOT NULL,
  coin       TEXT,
  amount     REAL NOT NULL,
  raw        TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS payments_order ON payments(order_id);
CREATE TABLE IF NOT EXISTS drafts (
  chat_id    INTEGER PRIMARY KEY,
  step       TEXT,
  data       TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL
);
"""


def now() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None = None) -> str:
    return (dt or now()).isoformat(timespec="seconds")


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def init(path: str) -> None:
    global _conn
    _conn = sqlite3.connect(path, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA foreign_keys=ON")
    _conn.executescript(SCHEMA)
    _conn.commit()


def conn() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("db not initialised")
    return _conn


def q(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        return conn().execute(sql, args).fetchall()


def q1(sql: str, args: tuple = ()) -> sqlite3.Row | None:
    with _lock:
        return conn().execute(sql, args).fetchone()


def x(sql: str, args: tuple = ()) -> int:
    with _lock:
        cur = conn().execute(sql, args)
        conn().commit()
        return cur.lastrowid or cur.rowcount


# ---- users -------------------------------------------------------------

def get_user(tid: int) -> sqlite3.Row | None:
    return q1("SELECT * FROM users WHERE telegram_id=?", (tid,))


def add_user(tid: int, role: str = "member", added_by: int | None = None) -> None:
    x("INSERT INTO users(telegram_id, role, added_by, added_at) VALUES(?,?,?,?) "
      "ON CONFLICT(telegram_id) DO UPDATE SET role=excluded.role",
      (tid, role, added_by, iso()))


def drop_user(tid: int) -> None:
    x("DELETE FROM users WHERE telegram_id=?", (tid,))


def users() -> list[sqlite3.Row]:
    return q("SELECT * FROM users ORDER BY added_at")


# ---- orders ------------------------------------------------------------

def create_order(token: str, chat_id: int, chain: str, asset: str, provider: str,
                 usd: float, quote: float, label: str | None, expires_min: int) -> sqlite3.Row:
    created = now()
    expires = created + timedelta(minutes=expires_min)
    with _lock:
        cur = conn().execute(
            "INSERT INTO orders(token, chat_id, chain, asset, provider, usd, quote, label,"
            " status, expires_at, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?, 'pending', ?,?,?)",
            (token, chat_id, chain, asset, provider, usd, quote, label,
             iso(expires), iso(created), iso(created)))
        conn().commit()
        oid = cur.lastrowid
        conn().execute("UPDATE orders SET inv=? WHERE id=?", (f"INV-{oid:04d}", oid))
        conn().commit()
    return order_by_id(oid)


def order_by_token(token: str) -> sqlite3.Row | None:
    return q1("SELECT * FROM orders WHERE token=?", (token,))


def order_by_id(oid: int) -> sqlite3.Row | None:
    return q1("SELECT * FROM orders WHERE id=?", (oid,))


def set_order(oid: int, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = iso()
    cols = ", ".join(f"{k}=?" for k in fields)
    x(f"UPDATE orders SET {cols} WHERE id=?", (*fields.values(), oid))


def orders_for(chat_id: int | None, status: str | None, limit: int, offset: int) -> list[sqlite3.Row]:
    where, args = [], []
    if chat_id is not None:
        where.append("chat_id=?")
        args.append(chat_id)
    if status and status != "all":
        if status == "open":
            where.append("status IN ('pending','partial')")
        else:
            where.append("status=?")
            args.append(status)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    return q(f"SELECT * FROM orders {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
             (*args, limit, offset))


def count_orders(chat_id: int | None, status: str | None) -> int:
    where, args = [], []
    if chat_id is not None:
        where.append("chat_id=?")
        args.append(chat_id)
    if status and status != "all":
        if status == "open":
            where.append("status IN ('pending','partial')")
        else:
            where.append("status=?")
            args.append(status)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    row = q1(f"SELECT COUNT(*) c FROM orders {clause}", tuple(args))
    return int(row["c"]) if row else 0


def due_for_expiry() -> list[sqlite3.Row]:
    return q("SELECT * FROM orders WHERE status IN ('pending','partial') AND expires_at<?",
             (iso(),))


def open_with_ref() -> list[sqlite3.Row]:
    return q("SELECT * FROM orders WHERE status IN ('pending','partial') "
             "AND provider_ref IS NOT NULL AND expires_at>?",
             (iso(now() - timedelta(days=2)),))


def recent_for_summary(since_iso: str) -> list[sqlite3.Row]:
    return q("SELECT * FROM orders WHERE created_at>=?", (since_iso,))


def totals(since_iso: str) -> dict:
    rows = q("SELECT status, COUNT(*) c, COALESCE(SUM(usd),0) s FROM orders "
             "WHERE created_at>=? GROUP BY status", (since_iso,))
    out = {"orders": 0, "paid": 0, "volume": 0.0, "pending": 0, "expired": 0}
    for r in rows:
        out["orders"] += r["c"]
        if r["status"] in ("paid", "overpaid", "late_paid", "partial"):
            out["paid"] += r["c"]
            out["volume"] += r["s"]
        elif r["status"] in ("pending", "confirming"):
            out["pending"] += r["c"]
        elif r["status"] in ("expired", "cancelled"):
            out["expired"] += r["c"]
    return out


# ---- payments ----------------------------------------------------------

def add_payment(txid: str, order_id: int, coin: str | None, amount: float, raw: str) -> bool:
    """True when this txid is new. False means a replay — never double-credit."""
    with _lock:
        cur = conn().execute(
            "INSERT OR IGNORE INTO payments(txid, order_id, coin, amount, raw, created_at)"
            " VALUES(?,?,?,?,?,?)", (txid, order_id, coin, amount, raw, iso()))
        conn().commit()
        return cur.rowcount == 1


def payment_amount(txid: str) -> float:
    row = q1("SELECT amount FROM payments WHERE txid=?", (txid,))
    return float(row["amount"]) if row else 0.0


def upsert_payment(txid: str, order_id: int, coin: str | None, amount: float, raw: str) -> None:
    """Absolute amount for a payment that can grow (gateway reports a running total)."""
    x("INSERT INTO payments(txid, order_id, coin, amount, raw, created_at) VALUES(?,?,?,?,?,?) "
      "ON CONFLICT(txid) DO UPDATE SET amount=excluded.amount, raw=excluded.raw",
      (txid, order_id, coin, amount, raw, iso()))


# ---- drafts ------------------------------------------------------------

def draft(chat_id: int) -> dict:
    row = q1("SELECT * FROM drafts WHERE chat_id=?", (chat_id,))
    if not row:
        return {"step": None, "data": {}}
    return {"step": row["step"], "data": json.loads(row["data"] or "{}")}


def save_draft(chat_id: int, step: str | None, data: dict) -> None:
    x("INSERT INTO drafts(chat_id, step, data, updated_at) VALUES(?,?,?,?) "
      "ON CONFLICT(chat_id) DO UPDATE SET step=excluded.step, data=excluded.data, "
      "updated_at=excluded.updated_at", (chat_id, step, json.dumps(data), iso()))


def clear_draft(chat_id: int) -> None:
    x("DELETE FROM drafts WHERE chat_id=?", (chat_id,))
