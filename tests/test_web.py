"""Web surface: page render, signature checks, static assets."""
import hashlib
import hmac
import json
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, web  # noqa: E402
from app.config import Config  # noqa: E402

CFG = Config(
    bot_token="x", owner_id=1, public_base="https://bot.test", db_path=":memory:",
    nowpayments_key="k", nowpayments_ipn_secret="secret", alert_chat_id=None,
    tz="Asia/Kolkata", min_usd=4.0, max_usd=10000.0, grace_minutes=10,
    tolerance_pct=0.99, tolerance_abs=0.50,
    cryptapi_base="https://api.cryptapi.io", nowpayments_api="https://api.nowpayments.io/v1",
)


def client():
    db.init(":memory:")
    order = db.create_order("tok-abc", 1, "bsc", "USDT", "cryptapi", 40.0, 40.0,
                            "Acme 2291", 30)
    db.set_order(order["id"], address="0x9F2C4a7E1bD3c05A8f6E2d1B4c7A0e3D5b8F1c62")
    app = web.build(CFG)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://t"), order


def sign(payload: dict, secret: str) -> str:
    body = json.dumps(dict(sorted(payload.items())), separators=(",", ":"))
    return hmac.new(secret.encode(), body.encode(), hashlib.sha512).hexdigest()


async def run():
    c, order = client()

    r = await c.get("/healthz")
    assert r.status_code == 200 and r.text == "ok"

    r = await c.get(f"/p/{order['token']}")
    assert r.status_code == 200
    assert "history.replaceState" in r.text
    assert "chain=bsc" in r.text and "addr=0x9F2C" in r.text and "live=1" in r.text
    assert '<base href="/">' in r.text
    assert r.headers["cache-control"].startswith("no-store")

    r = await c.get("/p/does-not-exist")
    assert r.status_code == 200 and "state=notfound" in r.text

    r = await c.get("/icons/logo.svg")
    assert r.status_code == 200 and len(r.content) > 1000

    payload = {"order_id": order["token"], "payment_id": "55", "payment_status": "finished",
               "actually_paid": 40.0, "pay_currency": "usdttrc20"}
    r = await c.post("/cb/nowpayments", content=json.dumps(payload),
                     headers={"x-nowpayments-sig": "nope"})
    assert r.status_code == 401

    r = await c.post("/cb/nowpayments", content=json.dumps(payload),
                     headers={"x-nowpayments-sig": sign(payload, "secret")})
    assert r.status_code == 200
    assert db.order_by_token(order["token"])["status"] == "paid"

    r = await c.get("/cb/cryptapi?o=unknown")
    assert r.status_code == 404

    await c.aclose()
    print("web surface ok")


if __name__ == "__main__":
    import asyncio
    asyncio.run(run())
