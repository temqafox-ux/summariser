from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from tg_digest_bot.config import Settings
from tg_digest_bot.db import Database
from tg_digest_bot.llm.zai import ZaiDigestLLM


class InjectMiddleware(BaseMiddleware):
    def __init__(
        self,
        *,
        db: Database,
        settings: Settings,
        llm: ZaiDigestLLM,
        scheduler: AsyncIOScheduler | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.llm = llm
        self.scheduler = scheduler

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        data["db"] = self.db
        data["settings"] = self.settings
        data["llm"] = self.llm
        data["scheduler"] = self.scheduler
        return await handler(event, data)
