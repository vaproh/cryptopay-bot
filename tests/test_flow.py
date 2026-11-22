"""Bot flow without Telegram: drafts, keyboards, guards."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import bot, db, orders  # noqa: E402
from app.config import Config  # noqa: E402

CFG = Config(
    bot_token="x", owner_id=1, public_base="https://bot.test", db_path=":memory:",
    nowpayments_key="", nowpayments_ipn_secret="s", alert_chat_id=None,
    tz="Asia/Kolkata", min_usd=4.0, max_usd=10000.0, grace_minutes=10,
    tolerance_pct=0.99, tolerance_abs=0.50,
    cryptapi_base="https://api.cryptapi.io", nowpayments_api="https://api.nowpayments.io/v1",
)


class Msg:
    def __init__(self, chat_id=1, text=""):
        self.chat_id = chat_id
        self.text = text
        self.sent = []

    async def reply_text(self, text, **kw):
        self.sent.append((text, kw))

    async def edit_message_text(self, text, **kw):
        self.sent.append((text, kw))

    async def reply_document(self, *a, **k):
        self.sent.append(("doc", k))


class User:
    def __init__(self, uid):
        self.id = uid


class Update:
    def __init__(self, uid=1, text="", data=None):
        self.effective_user = User(uid)
        self.effective_chat = Msg(uid)
        self.message = Msg(uid, text)
        self.callback_query = Q(data, uid) if data is not None else None


class Q:
    def __init__(self, data, uid=1):
        self.data = data
        self.message = Msg(uid)
        self.answered = []

    async def answer(self, *a, **k):
        self.answered.append((a, k))

    async def edit_message_text(self, text, **kw):
        self.message.sent.append((text, kw))


class Ctx:
    def __init__(self, args=None):
        self.bot_data = {"cfg": CFG}
        self.args = args or []


def setup():
    db.init(":memory:")
    db.add_user(1, "owner")


async def flow():
    setup()
    db.save_draft(1, "chain", {})
    ctx = Ctx()

    await bot.on_chain(Update(data="c:bsc"), ctx)
    d = db.draft(1)
    assert d["data"]["chain"] == "bsc" and d["step"] == "amount"

    await bot.on_amount(Update(data="a:10"), ctx)
    assert db.draft(1)["step"] == "expiry"

    await bot.on_expiry(Update(data="e:30"), ctx)
    assert db.draft(1)["step"] == "label"

    await bot.on_label_skip(Update(data="l:skip"), ctx)
    assert db.draft(1)["step"] == "confirm"

    # custom amount path, including rejection below the floor
    db.save_draft(1, "amount", {"chain": "ethereum"})
    low = Update(text="4")
    await bot.on_text(low, ctx)
    assert "Minimum" in low.message.sent[-1][0]
    assert db.draft(1)["step"] == "amount"
    await bot.on_text(Update(text="40"), ctx)
    assert db.draft(1)["data"]["usd"] == 40.0
    assert db.draft(1)["step"] == "expiry"

    # label typed by hand
    db.save_draft(1, "label", {"chain": "bsc", "usd": 40.0, "exp": 30})
    await bot.on_text(Update(text="Acme 2291"), ctx)
    assert db.draft(1)["data"]["label"] == "Acme 2291"
    assert db.draft(1)["step"] == "confirm"

    # create with a stubbed provider
    async def fake_create(cfg, **kw):
        row = db.create_order("tok-flow", 1, kw["chain_key"], "USDT", "cryptapi",
                              kw["usd"], kw["usd"], kw["label"], kw["expires_min"])
        db.set_order(row["id"], address="0xabc", provider_ref="cb", quote=kw["usd"])
        return db.order_by_id(row["id"])

    orders.create = fake_create
    upd = Update(data="go")
    await bot.on_create(upd, ctx)
    text = upd.callback_query.message.sent[-1][0]
    assert "INV-0" in text and "https://bot.test/p/tok-flow" in text
    assert db.draft(1)["step"] is None

    # unknown user is refused
    db.drop_user(2)
    m = Msg(2)
    u = Update(uid=2, text="/start")
    u.message = m
    await bot.cmd_start(u, ctx)
    assert "Not on the team" in m.sent[-1][0]

    print("flow ok")


if __name__ == "__main__":
    asyncio.run(flow())
