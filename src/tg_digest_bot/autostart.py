from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from tg_digest_bot.config import Settings
from tg_digest_bot.db import Database
from tg_digest_bot.handlers.digest import execute_scheduled_daily_digest
from tg_digest_bot.llm.zai import ZaiDigestLLM

logger = logging.getLogger(__name__)

AUTOSTART_JOB_PREFIX = "digest_autostart_"


def autostart_job_id(chat_id: int) -> str:
    return f"{AUTOSTART_JOB_PREFIX}{chat_id}"


async def refresh_digest_autostart_jobs(
    scheduler: AsyncIOScheduler,
    bot: Bot,
    db: Database,
    settings: Settings,
    llm: ZaiDigestLLM,
) -> None:
    """Синхронизировать cron-задания с таблицей digest_autostart."""
    try:
        tz = ZoneInfo(settings.digest_tz)
    except Exception:
        logger.exception("refresh_digest_autostart_jobs: неверный DIGEST_TZ=%s", settings.digest_tz)
        return

    for job in list(scheduler.get_jobs()):
        jid = job.id
        if jid is not None and jid.startswith(AUTOSTART_JOB_PREFIX):
            scheduler.remove_job(jid)

    rows = await db.list_digest_autostarts()
    for row in rows:
        cid = int(row["chat_id"])
        raw_tid = row["message_thread_id"]
        tid: int | None = int(raw_tid) if raw_tid is not None else None
        hour = int(row["hour"])
        minute = int(row["minute"])

        async def _job(
            *,
            chat_id: int = cid,
            thread_id: int | None = tid,
        ) -> None:
            await execute_scheduled_daily_digest(
                bot,
                db,
                settings,
                llm,
                chat_id=chat_id,
                message_thread_id=thread_id,
            )

        scheduler.add_job(
            _job,
            CronTrigger(hour=hour, minute=minute, timezone=tz),
            id=autostart_job_id(cid),
            replace_existing=True,
        )
        logger.info(
            "autostart: chat=%s thread=%s time=%02d:%02d tz=%s",
            cid,
            tid,
            hour,
            minute,
            settings.digest_tz,
        )
