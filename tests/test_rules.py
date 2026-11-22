"""Business rules that lose money when wrong. Runs under pytest or plain python."""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, orders, pricing  # noqa: E402
from app.config import Config  # noqa: E402

CFG = Config(
    bot_token="x", owner_id=1, public_base="https://bot.test", db_path=":memory:",
    nowpayments_key="", nowpayments_ipn_secret="s", alert_chat_id=None,
    tz="Asia/Kolkata", min_usd=4.0, max_usd=10000.0, grace_minutes=10,
    tolerance_pct=0.99, tolerance_abs=0.50,
    cryptapi_base="https://api.cryptapi.io", nowpayments_api="https://api.nowpayments.io/v1",
)


def fresh():
    db.init(":memory:")
    db.add_user(1, "owner")


def make(chain="bsc", usd=10.0, quote=10.0, minutes=30):
    row = db.create_order("tok123", 1, chain, "USDT", "cryptapi", usd, quote, None, minutes)
    return row


def test_tolerance_needs_both_percent_and_cap():
    assert orders._tolerance_ok(CFG, 9.90, 10.0)            # 0.10 short, both pass
    assert not orders._tolerance_ok(CFG, 9.40, 10.0)         # 6% short
    assert not orders._tolerance_ok(CFG, 999.40, 1000.0)     # 0.06% but 0.60 over the cap
    assert orders._tolerance_ok(CFG, 999.60, 1000.0)


def test_floors():
    assert pricing.floor_for(pricing.CHAINS["polygon"], 4.0) == 4.0
    assert pricing.floor_for(pricing.CHAINS["ethereum"], 4.0) == 5.0
    assert pricing.floor_for(pricing.CHAINS["bsc"], 4.0) == 4.0


def test_expiry_options_follow_provider():
    assert 10080 in dict(pricing.expiry_options(pricing.CHAINS["bsc"]))
    assert 10080 not in dict(pricing.expiry_options(pricing.CHAINS["ethereum"]))


def test_payment_uri_units():
    uri = pricing.pay_uri(pricing.CHAINS["bsc"], "0xabc", 40, "INV-0001")
    assert uri.startswith("ethereum:0x55d3")
    assert "@56/transfer" in uri
    assert uri.endswith(str(40 * 10 ** 18))
    sol = pricing.pay_uri(pricing.CHAINS["solana"], "So1addr", 25, "INV-0002")
    assert sol.startswith("solana:So1addr?amount=25.00")
    assert "spl-token=Es9v" in sol and "message=INV-0002" in sol


def test_txid_is_idempotent():
    fresh()
    o = make()
    assert db.add_payment("tx1", o["id"], "usdt", 5.0, "{}") is True
    assert db.add_payment("tx1", o["id"], "usdt", 5.0, "{}") is False


def test_partials_accumulate_to_paid():
    fresh()
    o = make(usd=10, quote=10)
    r1 = _apply(o, 5.0, "a")
    assert r1.status == "partial"
    r2 = _apply(db.order_by_id(o["id"]), 6.0, "b")
    assert r2.status == "overpaid"          # 11 of 10
    assert db.order_by_id(o["id"])["received"] == 11.0


def test_under_minimum_is_flagged():
    fresh()
    o = make(usd=10, quote=10)
    r = _apply(o, 0.4, "small")
    assert r.status == "underpaid"


def test_late_payment_is_not_paid():
    fresh()
    o = make(usd=10, quote=10, minutes=30)
    db.set_order(o["id"], expires_at=db.iso(db.now() - timedelta(hours=2)))
    r = _apply(db.order_by_id(o["id"]), 10.0, "late")
    assert r.status == "late_paid"


def test_grace_window_still_pays():
    fresh()
    o = make(usd=10, quote=10, minutes=30)
    db.set_order(o["id"], expires_at=db.iso(db.now() - timedelta(minutes=2)))
    r = _apply(db.order_by_id(o["id"]), 10.0, "in-grace")
    assert r.status == "paid"


def test_page_state_expires():
    fresh()
    o = make(minutes=30)
    db.set_order(o["id"], expires_at=db.iso(db.now() - timedelta(minutes=1)))
    state, left, _ = orders.page_state(CFG, db.order_by_id(o["id"]))
    assert state == "expired" and left == 0


def _apply(order, amount, txid):
    import asyncio
    return asyncio.run(
        orders.apply(CFG, order, amount=amount, txid=txid, coin="usdt", raw="{}"))


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all rules pass")
