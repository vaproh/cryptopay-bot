import asyncio
import logging
import os

import uvicorn

from . import bot as botmod
from . import config, db, scheduler
from . import web as webmod

log = logging.getLogger("cryptopay")


async def connect_telegram(tg) -> None:
    """Keep retrying. A dead bot token must not take the page or the webhooks with it:
    money can still arrive on an order created before the outage."""
    while True:
        try:
            if not tg.running:
                await tg.initialize()
                await tg.start()
            assert tg.updater is not None
            await tg.updater.start_polling(drop_pending_updates=True)
            log.info("telegram polling started")
            return
        except Exception as exc:
            log.error("telegram unavailable (%s); retrying in 30s", exc)
            try:
                await tg.shutdown()
            except Exception:
                pass
            await asyncio.sleep(30)


async def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = config.load()
    db.init(cfg.db_path)
    db.add_user(cfg.owner_id, "owner")

    tg = botmod.build(cfg)
    api = webmod.build(cfg)

    telegram = asyncio.create_task(connect_telegram(tg))

    server = uvicorn.Server(uvicorn.Config(
        api, host="0.0.0.0", port=int(os.getenv("PORT", "8090")),
        log_level="info", access_log=False))

    try:
        await asyncio.gather(server.serve(), scheduler.run(tg, cfg))
    finally:
        telegram.cancel()
        for step in (tg.updater.stop if tg.updater else None, tg.stop, tg.shutdown):
            try:
                if step:
                    await step()
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
