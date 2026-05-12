from __future__ import annotations

import logging
import time
from datetime import date

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from tg_digest_bot.config import Settings
from tg_digest_bot.db import Database
from tg_digest_bot.llm.zai import ZaiDigestLLM, build_day_transcript
from tg_digest_bot.telegram_chunks import split_telegram_chunks
from tg_digest_bot.timeutil import local_day_bounds_utc, parse_iso_date, today, yesterday

logger = logging.getLogger(__name__)

router = Router(name="digest")


def _user_can_digest(message: Message, settings: Settings) -> bool:
    """Only users listed in DIGEST_ALLOWED_USER_IDS (numeric Telegram user ids)."""
    user = message.from_user
    if user is None:
        return False
    allowed = settings.parsed_digest_allowed_user_ids()
    return bool(allowed) and user.id in allowed


_DIGEST_DENIED = (
    "Команда доступна только пользователям из списка DIGEST_ALLOWED_USER_IDS в .env бота.\n\n"
    "Указываются **числовые user id** Telegram (например `123456789`), через запятую. "
    "Это не «ник» в настройках профиля и не обязательно @username.\n"
    "Узнать свой id: напишите боту @userinfobot или @getidsbot в личку."
)


def _parse_digest_args(text: str) -> tuple[date | None, bool, str | None]:
    """
    /digest -> yesterday; /digest force -> yesterday + force;
    /digest 2026-05-12; /digest 2026-05-12 force.
    """
    parts = (text or "").split()
    args = parts[1:] if len(parts) > 1 else []
    force = False
    if args and args[-1].lower() == "force":
        force = True
        args = args[:-1]
    if not args:
        return None, force, None
    if len(args) != 1:
        return None, force, "Укажите дату как YYYY-MM-DD или без аргументов (вчера)."
    try:
        d = parse_iso_date(args[0])
        return d, force, None
    except ValueError:
        return None, force, "Неверная дата. Формат: YYYY-MM-DD"


async def _run_digest_for_day(
    message: Message,
    *,
    target: date,
    force: bool,
    db: Database,
    settings: Settings,
    llm: ZaiDigestLLM,
) -> None:
    chat_id = message.chat.id
    tz_name = settings.digest_tz
    local_date_str = target.isoformat()
    start_utc, end_utc = local_day_bounds_utc(target, tz_name)

    status_msg = await message.reply(
        f"Собираю сообщения за {local_date_str} ({tz_name})…",
    )

    limit = settings.digest_max_messages if settings.digest_max_messages > 0 else None
    total = await db.count_messages_for_day(chat_id=chat_id, start_utc=start_utc, end_utc=end_utc)
    rows = await db.fetch_messages_for_day(
        chat_id=chat_id,
        start_utc=start_utc,
        end_utc=end_utc,
        limit=limit,
    )
    truncated = limit is not None and total > limit
    if not rows:
        await status_msg.edit_text(
            f"За {local_date_str} нет сохранённых текстовых сообщений в этой группе.",
        )
        return

    max_mid = max(int(r["message_id"]) for r in rows)
    pv = settings.prompt_version

    if force:
        await db.delete_digests_for_day(chat_id=chat_id, local_date=local_date_str, tz=tz_name)
        logger.info("Force: cleared digest cache for chat=%s day=%s", chat_id, local_date_str)

    cached = await db.get_digest(
        chat_id=chat_id,
        local_date=local_date_str,
        tz=tz_name,
        max_message_id=max_mid,
        prompt_version=pv,
    )
    if cached is not None and not force:
        logger.info("Digest cache hit chat=%s day=%s max_mid=%s", chat_id, local_date_str, max_mid)
        body = f"(из кэша)\n\n{cached}"
        if truncated:
            body = f"[Обрезано: в дайджест вошли последние {limit} из {total} сообщений]\n\n{body}"
        await status_msg.delete()
        for chunk in split_telegram_chunks(body):
            await message.answer(chunk)
        return

    await status_msg.edit_text("Зову модель…")
    transcript = build_day_transcript(rows)
    digest_text = await llm.summarize_day(
        transcript=transcript,
        local_date=local_date_str,
        tz_name=tz_name,
    )
    now_ts = int(time.time())
    await db.upsert_digest(
        chat_id=chat_id,
        local_date=local_date_str,
        tz=tz_name,
        max_message_id=max_mid,
        model=settings.digest_model,
        prompt_version=pv,
        content=digest_text,
        created_at=now_ts,
    )
    body = digest_text
    if truncated:
        body = f"[Обрезано: в дайджест вошли последние {limit} из {total} сообщений]\n\n{body}"
    await status_msg.delete()
    for chunk in split_telegram_chunks(body):
        await message.answer(chunk)


@router.message(Command("digest"), lambda m: m.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP})
async def cmd_digest(message: Message, db: Database, settings: Settings, llm: ZaiDigestLLM) -> None:
    if not _user_can_digest(message, settings):
        await message.reply(_DIGEST_DENIED)
        return
    d, force, err = _parse_digest_args(message.text or "")
    if err:
        await message.reply(err)
        return
    target = yesterday(settings.digest_tz) if d is None else d
    await _run_digest_for_day(message, target=target, force=force, db=db, settings=settings, llm=llm)


@router.message(Command("digest_today"), lambda m: m.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP})
async def cmd_digest_today(message: Message, db: Database, settings: Settings, llm: ZaiDigestLLM) -> None:
    if not _user_can_digest(message, settings):
        await message.reply(_DIGEST_DENIED)
        return
    parts = (message.text or "").split()
    force = len(parts) > 1 and parts[-1].lower() == "force"
    target = today(settings.digest_tz)
    await _run_digest_for_day(message, target=target, force=force, db=db, settings=settings, llm=llm)
