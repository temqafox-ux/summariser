from __future__ import annotations

import asyncio
import logging
import sys
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from tg_digest_bot.autostart import refresh_digest_autostart_jobs
from tg_digest_bot.config import Settings
from tg_digest_bot.db import Database
from tg_digest_bot.handlers.digest import router as digest_router
from tg_digest_bot.handlers.messages import router as messages_router
from tg_digest_bot.llm.zai import ZaiDigestLLM
from tg_digest_bot.middlewares import InjectMiddleware

logger = logging.getLogger(__name__)


async def _async_main() -> None:
    settings = Settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    db = Database(settings.database_path)
    await db.connect()

    llm = ZaiDigestLLM(
        api_key=settings.z_ai_api_key,
        base_url=settings.z_ai_base_url,
        model=settings.digest_model,
        chunk_chars=settings.digest_chunk_chars,
    )

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(),
    )

    scheduler: AsyncIOScheduler | None = None
    try:
        sched_tz = ZoneInfo(settings.digest_tz)
    except Exception:
        logger.exception(
            "Неверный DIGEST_TZ=%s — планировщик /autostart недоступен",
            settings.digest_tz,
        )
    else:
        scheduler = AsyncIOScheduler(timezone=sched_tz)
        await refresh_digest_autostart_jobs(scheduler, bot, db, settings, llm)
        scheduler.start()
        n = len([j for j in scheduler.get_jobs() if j.id and j.id.startswith("digest_autostart_")])
        logger.info("Планировщик autostart: DIGEST_TZ=%s, заданий=%s", settings.digest_tz, n)

    dp = Dispatcher()
    dp.update.outer_middleware(
        InjectMiddleware(db=db, settings=settings, llm=llm, scheduler=scheduler),
    )
    # Digest first so commands are not lost if handler ordering ever changes
    dp.include_router(digest_router)
    dp.include_router(messages_router)

    try:
        await dp.start_polling(bot)
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        await db.close()


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
