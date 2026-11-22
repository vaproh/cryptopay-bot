import asyncio
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram.error import TelegramError

from . import db, orders
from .config import Config


def _next_at(cfg: Config, hour: int) -> float:
    now = datetime.now(tz=ZoneInfo(cfg.tz))
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return max((target - now).total_seconds(), 60)


async def run(app, cfg: Config) -> None:
    bot = app.bot

    async def notify(chat_id: int, text: str) -> None:
        try:
            await bot.send_message(chat_id, text, parse_mode="HTML",
                                   disable_web_page_preview=True)
        except TelegramError as e:
            raise RuntimeError(f"send failed: {e}") from e

    async def alert(text: str) -> None:
        if cfg.alert_chat_id:
            try:
                await bot.send_message(cfg.alert_chat_id, text, parse_mode="HTML")
            except TelegramError:
                pass

    orders.set_notifier(notify, alert)
    await asyncio.gather(
        _expiry(cfg),
        _reconcile(cfg),
        _daily(cfg, bot),
        _backup(cfg),
    )


async def _expiry(cfg: Config) -> None:
    while True:
        try:
            await orders.expire_due(cfg)
        except Exception:
            pass
        await asyncio.sleep(30)


async def _reconcile(cfg: Config) -> None:
    while True:
        await asyncio.sleep(300)
        try:
            for order in db.open_with_ref():
                await orders.reconcile(cfg, order)
        except Exception:
            pass


async def _daily(cfg: Config, bot) -> None:
    while True:
        await asyncio.sleep(_next_at(cfg, 9))
        try:
            from .bot import day_start, stat_block
            yesterday = db.totals(day_start(cfg, 1))
            text = (f"<b>DAILY</b>\n{stat_block(cfg)}\n\n"
                    f"yesterday: {yesterday['orders']} · {yesterday['paid']} paid · "
                    f"${orders.money(yesterday['volume'])}\n"
                    f"open now: {db.count_orders(None, 'open')}")
            await bot.send_message(cfg.owner_id, text, parse_mode="HTML")
        except Exception:
            pass


async def _backup(cfg: Config) -> None:
    folder = os.path.dirname(cfg.db_path) or "."
    while True:
        await asyncio.sleep(_next_at(cfg, 3))
        try:
            stamp = datetime.now(tz=ZoneInfo(cfg.tz)).strftime("%Y%m%d")
            path = os.path.join(folder, f"payram-{stamp}.db")
            db.conn().execute("VACUUM INTO ?", (path,))
            keep = sorted(f for f in os.listdir(folder)
                          if f.startswith("payram-") and f.endswith(".db"))
            for old in keep[:-7]:
                os.remove(os.path.join(folder, old))
        except Exception:
            pass
