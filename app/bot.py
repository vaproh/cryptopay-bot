import csv
import html
import io
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    Defaults,
    MessageHandler,
    filters,
)

from . import db, orders, pricing
from .config import Config
from .providers import CryptAPI, NowPayments, ProviderError

E = html.escape

COIN = {"bsc": "🟡", "polygon": "🟣", "solana": "🟢", "ethereum": "🔵",
        "arbitrum": "🔷", "base": "🔵"}


def rows(*items):
    return [list(i) if isinstance(i, (list, tuple)) else [i] for i in items]


def kb(rows_):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d) for t, d in row]
                                 for row in rows_])


def is_owner(cfg: Config, uid: int) -> bool:
    return uid == cfg.owner_id


def allowed(cfg: Config, uid: int) -> bool:
    return is_owner(cfg, uid) or db.get_user(uid) is not None


def tz(cfg: Config) -> ZoneInfo:
    return ZoneInfo(cfg.tz)


def day_start(cfg: Config, days: int = 0) -> str:
    local = datetime.now(tz(cfg)) - timedelta(days=days)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(UTC).isoformat(timespec="seconds")


def stat_block(cfg: Config) -> str:
    t = db.totals(day_start(cfg))
    w = db.totals(day_start(cfg, 6))
    a = db.totals("1970-01-01T00:00:00+00:00")
    return (f"<b>TODAY</b>   {t['orders']} · {t['paid']} paid · ${orders.money(t['volume'])}\n"
            f"<b>7 DAYS</b>  {w['orders']} · {w['paid']} paid · ${orders.money(w['volume'])}\n"
            f"<b>ALL</b>     {a['orders']} · {a['paid']} paid · ${orders.money(a['volume'])}")


def home_text(cfg: Config, uid: int) -> str:
    role = "owner" if is_owner(cfg, uid) else "member"
    return (f"<b>{E(cfg.brand_name)} PAY</b>\n\n{stat_block(cfg)}\n\n"
            f"{len(db.users())} on the team · you are {role}")


def home_kb(cfg: Config, uid: int):
    r = [[("NEW PAYMENT", "m:new")], [("ORDERS", "f:open:1"), ("STATS", "m:stats")]]
    if is_owner(cfg, uid):
        r.append([("TEAM", "m:team")])
    return kb(r)


async def guard(update: Update, cfg: Config) -> bool:
    uid = update.effective_user.id
    if allowed(cfg, uid):
        return True
    msg = update.effective_message
    if msg:
        await msg.reply_text("Not on the team.")
    return False


# ---------------------------------------------------------------- menu

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    uid = update.effective_user.id
    if not allowed(cfg, uid):
        await update.message.reply_text(
            f"Not on the team.\nYour ID: <code>{uid}</code>\nAsk the owner to add you.")
        return
    await update.message.reply_text(home_text(cfg, uid), reply_markup=home_kb(cfg, uid))


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    if not await guard(update, cfg):
        return
    await update.message.reply_text(
        f"<b>{E(cfg.brand_name)} · COMMANDS</b>\n"
        "/new — build a payment link\n"
        "/orders — list, filter, open\n"
        "/find &lt;text&gt; — label, invoice, txid, amount\n"
        "/export [today|7d|all] — CSV\n"
        "/quote &lt;chain&gt; &lt;usd&gt; — rate and minimum\n"
        "/label &lt;invoice&gt; &lt;text&gt; — fix a label\n"
        "/cancel &lt;invoice&gt; — kill an open order\n"
        "/ping — bot, db, both gateways\n"
        "/add &lt;id&gt; · /remove &lt;id&gt; · /team — owner only\n"
        "/help — this")


# ---------------------------------------------------------------- new order

CHAIN_BTN = [(f"{COIN[k]} {pricing.CHAINS[k].name.upper()}", f"c:{k}") for k in pricing.ORDER]


async def cmd_new(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    if not await guard(update, cfg):
        return
    db.save_draft(update.effective_chat.id, "chain", {})
    await update.message.reply_text(
        "<b>NEW PAYMENT</b>\nPick the chain.",
        reply_markup=kb([[CHAIN_BTN[0], CHAIN_BTN[1]], [CHAIN_BTN[2], CHAIN_BTN[3]],
                         [CHAIN_BTN[4], CHAIN_BTN[5]], [("BACK", "m:home")]]))


def amount_row(chain: pricing.Chain, cfg: Config) -> list:
    floor = pricing.floor_for(chain, cfg.min_usd)
    presets = [p for p in (4, 5, 10, 25, 50, 100) if p >= floor][:5]
    row1 = [(f"${p}", f"a:{p}") for p in presets[:3]]
    row2 = [(f"${p}", f"a:{p}") for p in presets[3:]]
    out = [row1]
    if row2:
        out.append(row2)
    out.append([("CUSTOM", "a:x")])
    out.append([("BACK", "b:chain")])
    return out


async def on_chain(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    q = update.callback_query
    if not await guard(update, cfg):
        return
    key = q.data.split(":", 1)[1]
    chain = pricing.CHAINS.get(key)
    if not chain:
        await q.answer("unknown chain")
        return
    d = db.draft(q.message.chat_id)
    d["data"]["chain"] = key
    db.save_draft(q.message.chat_id, "amount", d["data"])
    floor = pricing.floor_for(chain, cfg.min_usd)
    await q.edit_message_text(
        f"<b>{chain.name.upper()}</b> · {chain.asset}\n"
        f"Minimum ${orders.money(floor)}\n\nHow much, in USD?",
        reply_markup=kb(amount_row(chain, cfg)))


async def on_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    q = update.callback_query
    if not await guard(update, cfg):
        return
    val = q.data.split(":", 1)[1]
    d = db.draft(q.message.chat_id)
    if val == "x":
        db.save_draft(q.message.chat_id, "amount", d["data"])
        await q.edit_message_text("Send the amount in USD. Example: <code>40</code>",
                                  reply_markup=kb([[("BACK", "b:chain")]]))
        return
    d["data"]["usd"] = float(val)
    db.save_draft(q.message.chat_id, "expiry", d["data"])
    await show_expiry(q, cfg, d["data"])


async def show_expiry(q, cfg: Config, data: dict) -> None:
    chain = pricing.CHAINS[data["chain"]]
    opts = pricing.expiry_options(chain)
    r = [[(label, f"e:{mins}")] for mins, label in opts]
    r.append([("BACK", "b:amt")])
    await q.edit_message_text(
        f"<b>{orders.money(data['usd'])} USD</b> on {chain.name}\n"
        f"How long should the link stay open?",
        reply_markup=kb(r))


async def on_expiry(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    q = update.callback_query
    if not await guard(update, cfg):
        return
    mins = int(q.data.split(":", 1)[1])
    d = db.draft(q.message.chat_id)
    d["data"]["exp"] = mins
    db.save_draft(q.message.chat_id, "label", d["data"])
    await q.edit_message_text(
        "Client name or reference?\nType it, or skip.",
        reply_markup=kb([[("SKIP", "l:skip")], [("BACK", "b:exp")]]))


async def on_label_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    q = update.callback_query
    if not await guard(update, cfg):
        return
    d = db.draft(q.message.chat_id)
    d["data"]["label"] = None
    db.save_draft(q.message.chat_id, "confirm", d["data"])
    await show_confirm(q, cfg, d["data"])


async def show_confirm(q, cfg: Config, data: dict) -> None:
    chain = pricing.CHAINS[data["chain"]]
    label = f"\nClient: {E(data['label'])}" if data.get("label") else ""
    mins = data.get("exp", 30)
    human = dict(pricing.EXPIRY + [(10080, "7 DAYS")]).get(mins, f"{mins} MIN")
    await q.edit_message_text(
        f"<b>CHECK</b>\n{chain.name} · {chain.asset}\n"
        f"{orders.money(data['usd'])} USD\nLink open {human}{label}",
        reply_markup=kb([[("CREATE LINK", "go")], [("BACK", "b:exp")]]))


async def on_create(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    q = update.callback_query
    if not await guard(update, cfg):
        return
    d = db.draft(q.message.chat_id)
    data = d["data"]
    if not data.get("chain") or not data.get("usd"):
        await q.answer("start again")
        return
    await q.answer("creating")
    await q.edit_message_text("Creating the link…")
    chain = pricing.CHAINS[data["chain"]]
    try:
        order = await orders.create(cfg, chain_key=chain.key, usd=float(data["usd"]),
                                    label=data.get("label"), expires_min=int(data.get("exp", 30)),
                                    chat_id=q.message.chat_id)
    except ProviderError as e:
        await q.edit_message_text(f"Gateway refused it.\n<code>{E(str(e))[:200]}</code>\n\nTry again.",
                                  reply_markup=kb([[("BACK", "b:chain")]]))
        return
    db.clear_draft(q.message.chat_id)
    link = f"{cfg.public_base}/p/{order['token']}"
    await q.edit_message_text(link_text(order, link), reply_markup=kb([
        [("OPEN PAGE", link)],
        [("NEW PAYMENT", "m:new"), ("ORDERS", "f:open:1")],
    ]))


def link_text(order, link: str) -> str:
    chain = pricing.CHAINS[order["chain"]]
    label = f"\n{E(order['label'])}" if order["label"] else ""
    return (f"<b>{order['inv']}</b>{label}\n"
            f"{chain.name} · {chain.asset}\n"
            f"{orders.money(order['usd'])} USD\n\n"
            f"<code>{link}</code>\n\n"
            f"Send this link to the client.")


# ---------------------------------------------------------------- text input

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    if not await guard(update, cfg):
        return
    msg = update.message
    d = db.draft(msg.chat_id)
    step, data = d["step"], d["data"]

    if step == "amount":
        raw = (msg.text or "").replace("$", "").replace(",", "").strip()
        try:
            usd = float(raw)
        except ValueError:
            await msg.reply_text("That isn't a number. Send it like <code>40</code>.")
            return
        chain = pricing.CHAINS[data["chain"]]
        floor = pricing.floor_for(chain, cfg.min_usd)
        if usd < floor:
            await msg.reply_text(f"Minimum on {chain.name} is ${orders.money(floor)}.")
            return
        if usd > cfg.max_usd:
            await msg.reply_text(f"Cap is ${orders.money(cfg.max_usd)}. Split it or lower it.")
            return
        data["usd"] = usd
        db.save_draft(msg.chat_id, "expiry", data)
        opts = pricing.expiry_options(chain)
        await msg.reply_text(
            f"<b>{orders.money(usd)} USD</b> on {chain.name}\nHow long should the link stay open?",
            reply_markup=kb([[(label, f"e:{mins}")] for mins, label in opts] +
                            [[("BACK", "b:chain")]]))
        return

    if step == "label":
        text = (msg.text or "").strip()[:64]
        data["label"] = text or None
        db.save_draft(msg.chat_id, "confirm", data)
        chain = pricing.CHAINS[data["chain"]]
        human = dict(pricing.EXPIRY + [(10080, "7 DAYS")]).get(data.get("exp", 30), "30 MIN")
        await msg.reply_text(
            f"<b>CHECK</b>\n{chain.name} · {chain.asset}\n"
            f"{orders.money(data['usd'])} USD\nLink open {human}"
            + (f"\nClient: {E(text)}" if text else ""),
            reply_markup=kb([[("CREATE LINK", "go")], [("BACK", "b:exp")]]))
        return

    await msg.reply_text("Use /new to start a payment.", reply_markup=home_kb(cfg, msg.chat_id))


# ---------------------------------------------------------------- orders

def order_row(o) -> str:
    chain = pricing.CHAINS[o["chain"]]
    mark = COIN.get(o["chain"], "")
    label = f" · {E(o['label'][:18])}" if o["label"] else ""
    return (f"{o['inv']} · {mark} {chain.asset} · ${orders.money(o['usd'])}"
            f" · {o['status'].upper()}{label}")


async def list_orders(update_or_q, cfg: Config, uid: int, status: str, page: int, mine: int):
    chat = None if (mine == 0 and is_owner(cfg, uid)) else (
        update_or_q.message.chat_id if hasattr(update_or_q, "message") and update_or_q.message
        else update_or_q.effective_chat.id)
    total = db.count_orders(chat, status)
    rows_ = db.orders_for(chat, status, 5, page * 5)
    btns = [[(order_row(o)[:60], f"o:{o['id']}")] for o in rows_]
    nav = []
    if page > 0:
        nav.append(("PREV", f"f:{status}:{mine}:{page-1}"))
    if (page + 1) * 5 < total:
        nav.append(("NEXT", f"f:{status}:{mine}:{page+1}"))
    if nav:
        btns.append(nav)
    filters = [("OPEN", f"f:open:{mine}:0"), ("PAID", f"f:paid:{mine}:0"),
               ("ALL", f"f:all:{mine}:0")]
    btns.append(filters)
    if is_owner(cfg, uid):
        btns.append([("MINE", f"f:{status}:1:0"), ("EVERYONE", f"f:{status}:0:0")])
    btns.append([("NEW PAYMENT", "m:new"), ("HOME", "m:home")])
    head = f"<b>ORDERS</b> · {status.upper()} · {total}\n" + \
           ("yours" if (mine == 1 or not is_owner(cfg, uid)) else "everyone")
    return head, kb(btns)


async def cmd_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    if not await guard(update, cfg):
        return
    text, markup = await list_orders(update, cfg, update.effective_user.id, "open", 0,
                                     1 if not is_owner(cfg, update.effective_user.id) else 1)
    await update.message.reply_text(text, reply_markup=markup)


async def on_filter(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    q = update.callback_query
    if not await guard(update, cfg):
        return
    parts = q.data.split(":")
    status = parts[1]
    mine = int(parts[2]) if len(parts) > 2 else 1
    page = int(parts[3]) if len(parts) > 3 else 0
    text, markup = await list_orders(q, cfg, update.effective_user.id, status, page, mine)
    await q.edit_message_text(text, reply_markup=markup)


async def on_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    q = update.callback_query
    if not await guard(update, cfg):
        return
    oid = int(q.data.split(":", 1)[1])
    o = db.order_by_id(oid)
    if not o:
        await q.answer("gone")
        return
    await q.edit_message_text(detail(o), reply_markup=kb([
        [("REFRESH", f"r:{oid}")],
        [("OPEN PAGE", f"{cfg.public_base}/p/{o['token']}")],
        [("CANCEL ORDER", f"x:{oid}")],
        [("BACK", "f:open:1:0")],
    ]))


def detail(o) -> str:
    chain = pricing.CHAINS[o["chain"]]
    pct = (float(o["received"]) / float(o["quote"])) * 100 if o["quote"] else 0
    label = f"\n{E(o['label'])}" if o["label"] else ""
    return (f"<b>{o['inv']}</b>{label}\n"
            f"{chain.name} · {chain.asset} · {o['provider']}\n"
            f"asked {orders.crypto(float(o['quote']))} · got {orders.crypto(float(o['received']))}"
            f" ({pct:.0f}%)\n"
            f"status {o['status'].upper()}\n"
            f"expires {o['expires_at'][:16].replace('T', ' ')} UTC\n"
            f"<code>{o['address'] or '—'}</code>")


async def on_refresh(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    q = update.callback_query
    if not await guard(update, cfg):
        return
    oid = int(q.data.split(":", 1)[1])
    o = db.order_by_id(oid)
    if not o:
        await q.answer("gone")
        return
    await q.answer("checking")
    if o["provider_ref"]:
        await orders.reconcile(cfg, o)
    o = db.order_by_id(oid)
    await q.edit_message_text(detail(o), reply_markup=kb([
        [("REFRESH", f"r:{oid}")],
        [("OPEN PAGE", f"{cfg.public_base}/p/{o['token']}")],
        [("CANCEL ORDER", f"x:{oid}")],
        [("BACK", "f:open:1:0")],
    ]))


async def on_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    q = update.callback_query
    if not await guard(update, cfg):
        return
    oid = int(q.data.split(":", 1)[1])
    o = db.order_by_id(oid)
    if not o:
        await q.answer("gone")
        return
    db.set_order(oid, status="cancelled")
    note = ""
    if pricing.CHAINS[o["chain"]].provider == "cryptapi":
        note = "\nThe address still accepts crypto. Late money will be flagged."
    await q.edit_message_text(f"<b>{o['inv']}</b> cancelled.{note}",
                              reply_markup=kb([[("BACK", "f:all:1:0")]]))


# ---------------------------------------------------------------- search, export

async def cmd_find(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    if not await guard(update, cfg):
        return
    term = " ".join(ctx.args).strip()
    if not term:
        await update.message.reply_text("Usage: /find acme")
        return
    like = f"%{term}%"
    rows_ = db.q("SELECT * FROM orders WHERE label LIKE ? OR inv LIKE ? OR token LIKE ? "
                 "OR provider_ref LIKE ? OR CAST(usd AS TEXT) LIKE ? ORDER BY id DESC LIMIT 10",
                 (like, like, like, like, like))
    if not rows_:
        await update.message.reply_text("Nothing matches.")
        return
    await update.message.reply_text(
        f"<b>{len(rows_)} MATCHES</b>",
        reply_markup=kb([[(order_row(o)[:60], f"o:{o['id']}")] for o in rows_] +
                        [[("HOME", "m:home")]]))


async def cmd_export(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    if not await guard(update, cfg):
        return
    scope = (ctx.args[0] if ctx.args else "all").lower()
    since = {"today": day_start(cfg), "7d": day_start(cfg, 6)}.get(scope, "1970-01-01T00:00:00+00:00")
    rows_ = db.q("SELECT * FROM orders WHERE created_at>=? ORDER BY id", (since,))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["invoice", "created", "label", "chain", "asset", "usd",
                "quote", "received", "status", "txid_ref", "address"])
    for o in rows_:
        w.writerow([o["inv"], o["created_at"], o["label"] or "", o["chain"], o["asset"],
                    f"{o['usd']:.2f}", o["quote"], o["received"], o["status"],
                    o["provider_ref"] or "", o["address"] or ""])
    data = buf.getvalue().encode()
    await update.message.reply_document(
        InputFile(io.BytesIO(data), filename=f"orders-{scope}.csv"),
        caption=f"{len(rows_)} rows · {scope}")


async def cmd_quote(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    if not await guard(update, cfg):
        return
    if len(ctx.args) < 2:
        await update.message.reply_text("Usage: /quote bsc 40")
        return
    key = ctx.args[0].lower()
    chain = pricing.CHAINS.get(key)
    if not chain:
        await update.message.reply_text("Chains: " + ", ".join(pricing.ORDER))
        return
    try:
        usd = float(ctx.args[1].replace("$", ""))
    except ValueError:
        await update.message.reply_text("Second argument must be a number.")
        return
    floor = pricing.floor_for(chain, cfg.min_usd)
    lines = [f"<b>{chain.name}</b> · {chain.asset}",
             f"minimum ${orders.money(floor)}"]
    if usd < floor:
        lines.append("<b>below minimum</b>")
    if chain.provider == "cryptapi":
        try:
            amt = await CryptAPI(cfg.cryptapi_base).convert(chain.ticker, usd)
            lines.append(f"${orders.money(usd)} → {orders.crypto(amt)} {chain.asset}")
        except ProviderError as e:
            lines.append(f"rate unavailable: {E(str(e))[:80]}")
    else:
        lines.append(f"${orders.money(usd)} → about {orders.crypto(usd)} {chain.asset}")
    lines.append("fee 1% is taken from the transfer")
    await update.message.reply_text("\n".join(lines))


async def cmd_ping(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    if not await guard(update, cfg):
        return
    out = []
    t0 = time.perf_counter()
    try:
        db.q1("SELECT 1")
        out.append(f"🟢 db {int((time.perf_counter()-t0)*1000)} ms")
    except Exception as e:
        out.append(f"🔴 db {E(str(e))[:40]}")

    t0 = time.perf_counter()
    try:
        await CryptAPI(cfg.cryptapi_base).convert("bep20/usdt", 10)
        out.append(f"🟢 cryptapi {int((time.perf_counter()-t0)*1000)} ms")
    except Exception as e:
        out.append(f"🔴 cryptapi {E(str(e))[:40]}")

    t0 = time.perf_counter()
    try:
        await NowPayments(cfg.nowpayments_api, cfg.nowpayments_key).status()
        out.append(f"🟢 nowpayments {int((time.perf_counter()-t0)*1000)} ms")
    except Exception as e:
        out.append(f"🔴 nowpayments {E(str(e))[:40]}")

    await update.message.reply_text("<b>PING</b>\n" + "\n".join(out))


async def cmd_label(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    if not await guard(update, cfg):
        return
    if len(ctx.args) < 2:
        await update.message.reply_text("Usage: /label INV-0007 acme invoice 22")
        return
    inv = ctx.args[0].upper()
    o = db.q1("SELECT * FROM orders WHERE inv=?", (inv,))
    if not o:
        await update.message.reply_text("No such invoice.")
        return
    db.set_order(o["id"], label=" ".join(ctx.args[1:])[:64])
    await update.message.reply_text(f"{inv} label updated.")


async def cmd_cancel_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    if not await guard(update, cfg):
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /cancel INV-0007")
        return
    o = db.q1("SELECT * FROM orders WHERE inv=?", (ctx.args[0].upper(),))
    if not o:
        await update.message.reply_text("No such invoice.")
        return
    db.set_order(o["id"], status="cancelled")
    await update.message.reply_text(f"{o['inv']} cancelled.")


# ---------------------------------------------------------------- team

async def cmd_team(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    if not await guard(update, cfg):
        return
    await show_team(update.message, cfg)


async def show_team(msg, cfg: Config) -> None:
    rows_ = db.users()
    lines = ["<b>TEAM</b>"]
    btns = []
    for u in rows_:
        tag = "owner" if u["telegram_id"] == cfg.owner_id else "member"
        lines.append(f"<code>{u['telegram_id']}</code> · {tag}")
        if u["telegram_id"] != cfg.owner_id:
            btns.append([(f"REMOVE {u['telegram_id']}", f"t:del:{u['telegram_id']}")])
    btns.append([("ADD MEMBER", "t:add")])
    btns.append([("HOME", "m:home")])
    await msg.reply_text("\n".join(lines), reply_markup=kb(btns))


async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    if not is_owner(cfg, update.effective_user.id):
        await update.message.reply_text("Owner only.")
        return
    target = None
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target = update.message.reply_to_message.from_user.id
    elif ctx.args and ctx.args[0].lstrip("-").isdigit():
        target = int(ctx.args[0])
    if not target:
        await update.message.reply_text("Usage: /add <telegram_id> or reply to a message.")
        return
    db.add_user(target, "member", update.effective_user.id)
    await update.message.reply_text(f"{target} added.")


async def cmd_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    if not is_owner(cfg, update.effective_user.id):
        await update.message.reply_text("Owner only.")
        return
    if not ctx.args or not ctx.args[0].lstrip("-").isdigit():
        await update.message.reply_text("Usage: /remove <telegram_id>")
        return
    db.drop_user(int(ctx.args[0]))
    await update.message.reply_text("Removed.")


async def on_callbacks(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    q = update.callback_query
    if not await guard(update, cfg):
        return
    data = q.data
    uid = update.effective_user.id

    if data.startswith("t:"):
        if not is_owner(cfg, uid):
            await q.answer("owner only")
            return
        if data == "t:add":
            await q.edit_message_text("Send /add <id>, or reply to a message with /add.",
                                      reply_markup=kb([[("BACK", "m:team")]]))
            return
        if data.startswith("t:del:"):
            db.drop_user(int(data.split(":")[2]))
            await q.answer("removed")
            await show_team(q.message, cfg)
            return

    if data.startswith("f:"):
        await on_filter(update, ctx)
        return
    if data.startswith("o:"):
        await on_order(update, ctx)
        return
    if data.startswith("r:"):
        await on_refresh(update, ctx)
        return
    if data.startswith("x:"):
        await on_cancel(update, ctx)
        return
    if data.startswith("c:"):
        await q.answer()
        await on_chain(update, ctx)
        return
    if data.startswith("a:"):
        await q.answer()
        await on_amount(update, ctx)
        return
    if data.startswith("e:"):
        await q.answer()
        await on_expiry(update, ctx)
        return
    if data == "l:skip":
        await q.answer()
        await on_label_skip(update, ctx)
        return
    if data == "go":
        await on_create(update, ctx)
        return
    if data == "b:chain":
        await q.answer()
        db.save_draft(q.message.chat_id, "chain", {})
        await q.edit_message_text(
            "<b>NEW PAYMENT</b>\nPick the chain.",
            reply_markup=kb([[CHAIN_BTN[0], CHAIN_BTN[1]], [CHAIN_BTN[2], CHAIN_BTN[3]],
                             [CHAIN_BTN[4], CHAIN_BTN[5]], [("BACK", "m:home")]]))
        return
    if data == "b:amt":
        d = db.draft(q.message.chat_id)
        db.save_draft(q.message.chat_id, "amount", d["data"])
        chain = pricing.CHAINS[d["data"]["chain"]]
        await q.answer()
        await q.edit_message_text(f"<b>{chain.name.upper()}</b> · {chain.asset}\nHow much, in USD?",
                                  reply_markup=kb(amount_row(chain, cfg)))
        return
    if data == "b:exp":
        d = db.draft(q.message.chat_id)
        await q.answer()
        await show_expiry(q, cfg, d["data"])
        return
    if data == "m:new":
        await q.answer()
        db.save_draft(q.message.chat_id, "chain", {})
        await q.edit_message_text(
            "<b>NEW PAYMENT</b>\nPick the chain.",
            reply_markup=kb([[CHAIN_BTN[0], CHAIN_BTN[1]], [CHAIN_BTN[2], CHAIN_BTN[3]],
                             [CHAIN_BTN[4], CHAIN_BTN[5]], [("BACK", "m:home")]]))
        return
    if data == "m:stats":
        await q.answer()
        a = db.totals("1970-01-01T00:00:00+00:00")
        per = db.q("SELECT chain, COUNT(*) c, SUM(usd) s FROM orders "
                   "WHERE status IN ('paid','overpaid','late_paid') GROUP BY chain")
        lines = ["<b>STATS</b>", stat_block(cfg), ""]
        for r in per:
            lines.append(f"{COIN.get(r['chain'], '')} {r['chain'].upper()} · "
                         f"{r['c']} · ${orders.money(r['s'] or 0)}")
        if a["paid"]:
            lines.append(f"\navg ${orders.money(a['volume'] / a['paid'])}")
        await q.edit_message_text("\n".join(lines),
                                  reply_markup=kb([[("HOME", "m:home")]]))
        return
    if data == "m:team":
        await q.answer()
        await show_team(q.message, cfg)
        return
    if data == "m:home":
        await q.answer()
        await q.edit_message_text(home_text(cfg, uid), reply_markup=home_kb(cfg, uid))
        return
    await q.answer()


def build(cfg: Config) -> Application:
    app = (Application.builder()
           .token(cfg.bot_token)
           .defaults(Defaults(parse_mode=ParseMode.HTML))
           .build())
    app.bot_data["cfg"] = cfg

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("orders", cmd_orders))
    app.add_handler(CommandHandler("find", cmd_find))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("quote", cmd_quote))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("label", cmd_label))
    app.add_handler(CommandHandler("cancel", cmd_cancel_cmd))
    app.add_handler(CommandHandler("team", cmd_team))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CallbackQueryHandler(on_callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app
