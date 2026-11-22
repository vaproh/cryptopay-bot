import html
import secrets
from dataclasses import dataclass
from datetime import timedelta

from . import db, pricing
from .config import Config
from .providers import CryptAPI, NowPayments, ProviderError, callback_url

_notify = None
_alert = None


def set_notifier(notify, alert):
    global _notify, _alert
    _notify, _alert = notify, alert


def money(n: float) -> str:
    return f"{n:,.2f}"


def crypto(n: float) -> str:
    if 0 < abs(n) < 1:
        return f"{n:.4f}"
    return f"{n:,.2f}"


@dataclass
class Result:
    order: object
    status: str
    changed: bool
    amount: float


async def create(cfg: Config, *, chain_key: str, usd: float, label: str | None,
                 expires_min: int, chat_id: int) -> object:
    chain = pricing.CHAINS[chain_key]
    floor = pricing.floor_for(chain, cfg.min_usd)
    if usd < floor:
        raise ValueError(f"minimum on {chain.name} is ${floor:.2f}")
    token = secrets.token_urlsafe(16)
    order = db.create_order(token, chat_id, chain.key, chain.asset, chain.provider,
                            usd, 0.0, label, expires_min)
    cb = callback_url(cfg.public_base, chain.provider, token)

    try:
        if chain.provider == "cryptapi":
            api = CryptAPI(cfg.cryptapi_base)
            quote = await api.convert(chain.ticker, usd)
            made = await api.create(chain.ticker, cb)
        else:
            api = NowPayments(cfg.nowpayments_api, cfg.nowpayments_key)
            made = await api.create(
                usd=usd, pay_currency=chain.pay_currency, order_id=token, ipn_url=cb,
                description=f"{order['inv']} {chain.name}")
            quote = made.quote
    except Exception:
        db.set_order(order["id"], status="failed")
        raise

    db.set_order(order["id"], address=made.address, provider_ref=made.ref, quote=quote)
    return db.order_by_id(order["id"])


def _tolerance_ok(cfg: Config, received: float, quote: float) -> bool:
    if quote <= 0:
        return received > 0
    return received >= quote * cfg.tolerance_pct and received >= quote - cfg.tolerance_abs


def classify(cfg: Config, order, received: float, late: bool) -> str:
    quote = float(order["quote"] or order["usd"])
    if received <= 0:
        return order["status"]
    if late:
        return "late_paid"
    if _tolerance_ok(cfg, received, quote):
        return "overpaid" if received > quote * 1.02 else "paid"
    return "partial"


async def apply(cfg: Config, order, *, amount: float, txid: str,
                coin: str | None, raw: str) -> Result:
    """Idempotent on txid. Amount is in asset units and accumulates."""
    if not db.add_payment(txid, order["id"], coin, amount, raw):
        return Result(order, order["status"], False, amount)
    return await _credit(cfg, order, amount)


async def _credit(cfg: Config, order, amount: float) -> Result:
    fresh = db.order_by_id(order["id"])
    total = float(fresh["received"]) + amount
    expires = db.parse(fresh["expires_at"])
    grace = expires + timedelta(minutes=cfg.grace_minutes)
    late = db.now() > grace
    status = classify(cfg, fresh, total, late)
    if status == "partial" and total < pricing.CHAINS[fresh["chain"]].minimum:
        status = "underpaid"

    db.set_order(fresh["id"], received=total, status=status)
    updated = db.order_by_id(fresh["id"])
    await announce(cfg, updated, amount)
    return Result(updated, status, True, amount)


async def announce(cfg: Config, order, amount: float) -> None:
    if not _notify:
        return
    st = order["status"]
    quote = float(order["quote"] or order["usd"])
    head = {
        "paid": "PAID", "overpaid": "OVERPAID", "partial": "PART PAID",
        "late_paid": "PAID LATE", "underpaid": "TOO SMALL",
    }.get(st, st.upper())
    label = f" · {html.escape(order['label'])}" if order["label"] else ""
    body = (f"<b>{head}</b> {order['inv']}{label}\n"
            f"{pricing.CHAINS[order['chain']].name} · {order['asset']}\n"
            f"received {crypto(float(order['received']))} of {crypto(quote)} {order['asset']}")
    if st == "partial":
        body += f"\nshort {crypto(max(quote - float(order['received']), 0))}"
    if st == "overpaid":
        body += f"\nover {crypto(float(order['received']) - quote)}"
    try:
        await _notify(order["chat_id"], body)
    except Exception:
        db.set_order(order["id"], status=order["status"])
        if cfg.alert_chat_id and _notify:
            await _notify(cfg.alert_chat_id,
                          f"undelivered: {order['inv']} {head} ({order['chat_id']})")


async def expire_due(cfg: Config) -> int:
    n = 0
    for order in db.due_for_expiry():
        db.set_order(order["id"], status="expired")
        n += 1
        if _notify:
            label = f" · {html.escape(order['label'])}" if order["label"] else ""
            await _notify(order["chat_id"],
                          f"<b>EXPIRED</b> {order['inv']}{label}\n"
                          f"{pricing.CHAINS[order['chain']].name} · "
                          f"{money(order['usd'])} USD · no payment")
    return n


async def reconcile(cfg: Config, order) -> Result | None:
    """Webhooks get lost. Ask the provider what actually happened."""
    chain = pricing.CHAINS[order["chain"]]
    try:
        if chain.provider == "cryptapi":
            api = CryptAPI(cfg.cryptapi_base)
            entries = await api.logs(chain.ticker, order["provider_ref"])
            last = None
            for e in entries:
                txid = e.get("txid_in") or ""
                if not txid:
                    continue
                last = await apply(cfg, order, amount=float(e.get("value_coin") or 0),
                                   txid=txid, coin=e.get("coin"), raw=str(e))
            return last
        api = NowPayments(cfg.nowpayments_api, cfg.nowpayments_key)
        body = await api.get(order["provider_ref"])
        return await apply_provider_status(cfg, order, body)
    except ProviderError:
        return None


STATUS_MAP = {
    "waiting": "pending",
    "confirming": "confirming",
    "confirmed": "paid",
    "sending": "paid",
    "finished": "paid",
    "partially_paid": "partial",
    "failed": "failed",
    "expired": "expired",
    "cancelled": "cancelled",
    "wrong asset confirmed": "wrongasset",
}


async def apply_provider_status(cfg: Config, order, body: dict) -> Result | None:
    raw_status = str(body.get("payment_status", "")).lower()
    mapped = STATUS_MAP.get(raw_status)
    if not mapped:
        return None
    if mapped in ("paid", "partial", "confirming"):
        # the gateway reports a running total, so credit only the difference
        total = float(body.get("actually_paid") or body.get("pay_amount") or 0)
        key = f"np:{order['provider_ref']}"
        prev = db.payment_amount(key)
        delta = round(total - prev, 8)
        if delta > 0:
            db.upsert_payment(key, order["id"], body.get("pay_currency"), total, str(body))
            return await _credit(cfg, order, delta)
    if mapped != order["status"]:
        db.set_order(order["id"], status=mapped)
        return Result(db.order_by_id(order["id"]), mapped, True, 0.0)
    return None


def page_state(cfg: Config, order) -> tuple[str, int, int]:
    """(state, seconds_left, window_seconds) for the payment page."""
    created = db.parse(order["created_at"])
    expires = db.parse(order["expires_at"])
    window = max(int((expires - created).total_seconds()), 0)
    left = max(int((expires - db.now()).total_seconds()), 0)
    st = order["status"]
    if st == "pending" and left == 0:
        st = "expired"
    if st == "partial" and left == 0:
        st = "expired"
    if st == "partial":
        return "partial", left, window
    if st == "late_paid":
        return "late", 0, window
    if st in ("paid", "overpaid", "confirming", "expired", "cancelled",
              "underpaid", "wrongasset", "failed"):
        return ("expired" if st == "failed" else st), left, window
    return "live", left, window
