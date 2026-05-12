from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from tg_digest_bot.config import Settings
from tg_digest_bot.db import Database
from tg_digest_bot.handlers.digest import router as digest_router
from tg_digest_bot.handlers.messages import router as messages_router
from tg_digest_bot.llm.zai import ZaiDigestLLM
from tg_digest_bot.middlewares import InjectMiddleware


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
    dp = Dispatcher()
    dp.update.outer_middleware(InjectMiddleware(db=db, settings=settings, llm=llm))
    dp.include_router(messages_router)
    dp.include_router(digest_router)

    try:
        await dp.start_polling(bot)
    finally:
        await db.close()


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
