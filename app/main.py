import asyncio
import os

import uvicorn

from . import bot as botmod
from . import config, db, scheduler
from . import web as webmod


async def main() -> None:
    cfg = config.load()
    db.init(cfg.db_path)
    db.add_user(cfg.owner_id, "owner")

    tg = botmod.build(cfg)
    api = webmod.build(cfg)

    await tg.initialize()
    await tg.start()
    assert tg.updater is not None
    await tg.updater.start_polling(drop_pending_updates=True)

    server = uvicorn.Server(uvicorn.Config(
        api, host="0.0.0.0", port=int(os.getenv("PORT", "8090")),
        log_level="info", access_log=False))

    try:
        await asyncio.gather(server.serve(), scheduler.run(tg, cfg))
    finally:
        await tg.updater.stop()
        await tg.stop()
        await tg.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
