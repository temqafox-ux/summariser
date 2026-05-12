from __future__ import annotations

import html
import json
import logging
import time
from datetime import date

from aiogram import Router
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, Message

import httpx

from tg_digest_bot.config import Settings
from tg_digest_bot.db import Database
from tg_digest_bot.filtered_day import (
    build_filtered_export_dict,
    build_filtered_text_for_llm,
    build_user_message_groups,
)
from tg_digest_bot.llm.zai import ZaiDigestLLM, format_openai_api_error
from tg_digest_bot.mini_stats import build_mini_stats_text
from tg_digest_bot.poe2scout_client import (
    build_leagues_catalog_text,
    fetch_leagues,
    pick_league_row,
    snapshot_for_llm,
)
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
    "Указываются числовые user id Telegram (например 123456789), через запятую. "
    "Это не «ник» в настройках профиля и не обязательно @username.\n"
    "Узнать свой id: напишите боту @userinfobot или @getidsbot в личку."
)


def _parse_digest_args_tail(tail: str | None) -> tuple[date | None, bool, str | None]:
    """
    Хвост команды после /digest[@bot] — аргументы.
    Пусто -> вчера; «force» -> вчера+force; «2026-05-12»; «2026-05-12 force».
    """
    raw = (tail or "").strip()
    if not raw:
        return None, False, None
    parts = raw.split()
    force = False
    if parts and parts[-1].lower() == "force":
        force = True
        parts = parts[:-1]
    if not parts:
        return None, force, None
    if len(parts) != 1:
        return None, force, "Укажите дату как YYYY-MM-DD или без аргументов (вчера)."
    try:
        d = parse_iso_date(parts[0])
        return d, force, None
    except ValueError:
        return None, force, "Неверная дата. Формат: YYYY-MM-DD"


def _parse_digest_mini_args(tail: str | None, tz: str) -> tuple[date | None, str | None]:
    """Пусто -> вчера; одна дата YYYY-MM-DD; «сегодня» / «today»."""
    raw = (tail or "").strip()
    if not raw:
        return yesterday(tz), None
    parts = raw.split()
    if len(parts) != 1:
        return None, "Одна дата: YYYY-MM-DD или «сегодня» / «today»; без аргумента = вчера."
    token = parts[0].lower()
    if token in {"today", "сегодня"}:
        return today(tz), None
    try:
        return parse_iso_date(parts[0]), None
    except ValueError:
        return None, "Неверная дата. Формат: YYYY-MM-DD (как в /digest)."


# Telegram message hard limit; запас под HTML <pre></pre>
_RAW_JSON_MAX_MESSAGE_HTML = 4000


async def _send_raw_export_for_local_day(
    message: Message,
    *,
    target: date,
    db: Database,
    settings: Settings,
) -> None:
    chat_id = message.chat.id
    tz_name = settings.digest_tz
    local_date_str = target.isoformat()
    start_utc, end_utc = local_day_bounds_utc(target, tz_name)
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
        await message.reply(
            f"За {local_date_str} ({tz_name}) нет сохранённых текстовых сообщений в этой группе.",
        )
        return

    payload: dict[str, object] = {
        "schema": "tg_digest_bot.raw_export_v1",
        "chat_id": chat_id,
        "local_date": local_date_str,
        "tz": tz_name,
        "truncated": truncated,
        "total_messages_in_day": total,
        "exported_message_count": len(rows),
        "messages": [
            {
                "message_id": r["message_id"],
                "user_id": r["user_id"],
                "username": r["username"],
                "date_utc": r["date_utc"],
                "text": r["text"],
                "reply_to_message_id": r["reply_to_message_id"],
            }
            for r in rows
        ],
    }
    json_str = json.dumps(payload, ensure_ascii=False, indent=2)
    wrapped = f"<pre>{html.escape(json_str)}</pre>"
    if len(wrapped) <= _RAW_JSON_MAX_MESSAGE_HTML:
        await message.reply(wrapped, parse_mode=ParseMode.HTML)
        return

    raw_bytes = json_str.encode("utf-8")
    fname = f"digest_raw_{local_date_str}.json"
    await message.reply_document(
        document=BufferedInputFile(raw_bytes, filename=fname),
        caption=(
            f"Сырой экспорт за {local_date_str} ({tz_name}). "
            "JSON слишком длинный для одного сообщения — отправлен файлом."
            + (" Учтён лимит DIGEST_MAX_MESSAGES (см. поле truncated в JSON)." if truncated else "")
        ),
    )


async def _send_filtered_raw_export_for_local_day(
    message: Message,
    *,
    target: date,
    db: Database,
    settings: Settings,
) -> None:
    chat_id = message.chat.id
    tz_name = settings.digest_tz
    local_date_str = target.isoformat()
    start_utc, end_utc = local_day_bounds_utc(target, tz_name)
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
        await message.reply(
            f"За {local_date_str} ({tz_name}) нет сохранённых текстовых сообщений в этой группе.",
        )
        return
    flt = settings.day_view_filter()
    groups = build_user_message_groups(rows, flt)
    if not groups:
        await message.reply(
            "После фильтрации не осталось сообщений (см. DIGEST_FILTER_* в .env).",
        )
        return
    payload = build_filtered_export_dict(
        chat_id=chat_id,
        local_date=local_date_str,
        tz=tz_name,
        truncated_day_slice=truncated,
        total_messages_in_day=total,
        messages_in_export_slice=len(rows),
        flt=flt,
        groups=groups,
    )
    json_str = json.dumps(payload, ensure_ascii=False, indent=2)
    wrapped = f"<pre>{html.escape(json_str)}</pre>"
    if len(wrapped) <= _RAW_JSON_MAX_MESSAGE_HTML:
        await message.reply(wrapped, parse_mode=ParseMode.HTML)
        return
    raw_bytes = json_str.encode("utf-8")
    fname = f"digest_filtered_{local_date_str}.json"
    await message.reply_document(
        document=BufferedInputFile(raw_bytes, filename=fname),
        caption=(
            f"Отфильтрованный экспорт за {local_date_str} ({tz_name}). "
            "JSON слишком длинный — файл."
        ),
    )


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
    cache_key = settings.digest_cache_key()

    if force:
        await db.delete_digests_for_day(chat_id=chat_id, local_date=local_date_str, tz=tz_name)
        logger.info("Force: cleared digest cache for chat=%s day=%s", chat_id, local_date_str)

    cached = await db.get_digest(
        chat_id=chat_id,
        local_date=local_date_str,
        tz=tz_name,
        max_message_id=max_mid,
        prompt_version=cache_key,
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
    flt = settings.day_view_filter()
    transcript = build_filtered_text_for_llm(rows, flt)
    if not transcript.strip():
        await status_msg.edit_text(
            "После фильтрации не осталось текста для дайджеста. "
            "Ослабьте DIGEST_FILTER_MIN_MESSAGE_CHARS или увеличьте лимиты в .env.",
        )
        return
    try:
        digest_text = await llm.summarize_day(
            transcript=transcript,
            local_date=local_date_str,
            tz_name=tz_name,
        )
    except Exception as e:
        detail = format_openai_api_error(e)
        logger.exception("LLM failed chat=%s day=%s: %s", chat_id, local_date_str, detail)
        await status_msg.edit_text(
            f"Не удалось вызвать Z.AI.\n{detail}\n\nПолный traceback в консоли бота.",
        )
        return
    now_ts = int(time.time())
    await db.upsert_digest(
        chat_id=chat_id,
        local_date=local_date_str,
        tz=tz_name,
        max_message_id=max_mid,
        model=settings.digest_model,
        prompt_version=cache_key,
        content=digest_text,
        created_at=now_ts,
    )
    body = digest_text
    if truncated:
        body = f"[Обрезано: в дайджест вошли последние {limit} из {total} сообщений]\n\n{body}"
    await status_msg.delete()
    for chunk in split_telegram_chunks(body):
        await message.answer(chunk)


@router.message(
    Command("digest", ignore_mention=True),
    lambda m: m.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP},
)
async def cmd_digest(
    message: Message,
    command: CommandObject,
    db: Database,
    settings: Settings,
    llm: ZaiDigestLLM,
) -> None:
    if not _user_can_digest(message, settings):
        await message.reply(_DIGEST_DENIED)
        return
    logger.info("/digest user_id=%s chat_id=%s", message.from_user.id, message.chat.id)
    d, force, err = _parse_digest_args_tail(command.args)
    if err:
        await message.reply(err)
        return
    target = yesterday(settings.digest_tz) if d is None else d
    try:
        await _run_digest_for_day(
            message, target=target, force=force, db=db, settings=settings, llm=llm
        )
    except Exception:
        logger.exception("digest failed chat=%s", message.chat.id)
        await message.reply("Ошибка при выполнении /digest. Смотрите лог в консоли бота.")


@router.message(
    Command("digest_today", ignore_mention=True),
    lambda m: m.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP},
)
async def cmd_digest_today(
    message: Message,
    command: CommandObject,
    db: Database,
    settings: Settings,
    llm: ZaiDigestLLM,
) -> None:
    if not _user_can_digest(message, settings):
        await message.reply(_DIGEST_DENIED)
        return
    tail = (command.args or "").strip().lower()
    force = tail == "force"
    target = today(settings.digest_tz)
    try:
        await _run_digest_for_day(
            message, target=target, force=force, db=db, settings=settings, llm=llm
        )
    except Exception:
        logger.exception("digest_today failed chat=%s", message.chat.id)
        await message.reply("Ошибка при выполнении /digest_today. Смотрите лог в консоли бота.")


@router.message(
    Command("digest_mini", ignore_mention=True),
    lambda m: m.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP},
)
async def cmd_digest_mini(
    message: Message,
    command: CommandObject,
    db: Database,
    settings: Settings,
) -> None:
    if not _user_can_digest(message, settings):
        await message.reply(_DIGEST_DENIED)
        return
    target, err = _parse_digest_mini_args(command.args, settings.digest_tz)
    if err:
        await message.reply(err)
        return
    logger.info(
        "/digest_mini user_id=%s chat_id=%s day=%s",
        message.from_user.id,
        message.chat.id,
        target.isoformat(),
    )
    chat_id = message.chat.id
    start_utc, end_utc = local_day_bounds_utc(target, settings.digest_tz)
    try:
        rows = await db.fetch_messages_for_day(
            chat_id=chat_id,
            start_utc=start_utc,
            end_utc=end_utc,
            limit=None,
        )
        text = build_mini_stats_text(
            local_day=target,
            tz_name=settings.digest_tz,
            rows=rows,
        )
        await message.reply(text)
    except Exception:
        logger.exception("digest_mini failed chat=%s", message.chat.id)
        await message.reply("Ошибка при выполнении /digest_mini. Смотрите лог в консоли бота.")


@router.message(
    Command("digest_today_raw", ignore_mention=True),
    lambda m: m.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP},
)
async def cmd_digest_today_raw(
    message: Message,
    db: Database,
    settings: Settings,
) -> None:
    if not _user_can_digest(message, settings):
        await message.reply(_DIGEST_DENIED)
        return
    logger.info("/digest_today_raw user_id=%s chat_id=%s", message.from_user.id, message.chat.id)
    target = today(settings.digest_tz)
    try:
        await _send_raw_export_for_local_day(message, target=target, db=db, settings=settings)
    except Exception:
        logger.exception("digest_today_raw failed chat=%s", message.chat.id)
        await message.reply(
            "Ошибка при выполнении /digest_today_raw. Смотрите лог в консоли бота.",
        )


@router.message(
    Command("digest_today_raw_filtered", ignore_mention=True),
    lambda m: m.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP},
)
async def cmd_digest_today_raw_filtered(
    message: Message,
    db: Database,
    settings: Settings,
) -> None:
    if not _user_can_digest(message, settings):
        await message.reply(_DIGEST_DENIED)
        return
    logger.info(
        "/digest_today_raw_filtered user_id=%s chat_id=%s",
        message.from_user.id,
        message.chat.id,
    )
    target = today(settings.digest_tz)
    try:
        await _send_filtered_raw_export_for_local_day(
            message, target=target, db=db, settings=settings
        )
    except Exception:
        logger.exception("digest_today_raw_filtered failed chat=%s", message.chat.id)
        await message.reply(
            "Ошибка при выполнении /digest_today_raw_filtered. Смотрите лог в консоли бота.",
        )


@router.message(
    Command("poe2market", ignore_mention=True),
    lambda m: m.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP},
)
async def cmd_poe2market(
    message: Message,
    command: CommandObject,
    settings: Settings,
    llm: ZaiDigestLLM,
) -> None:
    if not _user_can_digest(message, settings):
        await message.reply(_DIGEST_DENIED)
        return
    league_override = (command.args or "").strip() or settings.poe2_market_league
    logger.info(
        "/poe2market user_id=%s chat_id=%s league=%r",
        message.from_user.id,
        message.chat.id,
        league_override or "(auto)",
    )
    status_msg = await message.reply("Собираю рынок…")
    try:
        rows = await fetch_leagues(settings)
        row = pick_league_row(rows, league_override=league_override)
        snap = snapshot_for_llm(row)
        text = await llm.market_quip(snapshot=snap)
    except httpx.HTTPStatusError as e:
        logger.exception("market fetch HTTP error")
        await status_msg.edit_text(
            f"Не вышло стянуть котировки: HTTP {e.response.status_code}. Попробуй позже.",
        )
        return
    except ValueError as e:
        err = str(e)
        if err.startswith("league_not_found:"):
            bad = err.split(":", 1)[1] if ":" in err else league_override
            await status_msg.edit_text(
                f"Лига «{bad}» не найдена в фиде. Проверь написание или посмотри список: /poe2leagues",
            )
            return
        if err == "empty_leagues":
            await status_msg.edit_text("Список лиг пустой — попробуй позже.")
            return
        logger.exception("poe2market pick failed")
        await status_msg.edit_text("Не удалось разобрать ответ сервера. Смотри лог бота.")
        return
    except Exception as e:
        detail = format_openai_api_error(e)
        logger.exception("poe2market failed: %s", detail)
        await status_msg.edit_text(
            f"Ошибка при сборке сводки.\n{detail}",
        )
        return
    try:
        await status_msg.delete()
    except Exception:
        logger.debug("could not delete status message", exc_info=True)
    header = "Мемная сводка по рынку лиги PoE2:\n\n"
    for chunk in split_telegram_chunks(header + text):
        await message.answer(chunk)


@router.message(
    Command("poe2leagues", ignore_mention=True),
    lambda m: m.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP},
)
async def cmd_poe2leagues(message: Message, settings: Settings) -> None:
    if not _user_can_digest(message, settings):
        await message.reply(_DIGEST_DENIED)
        return
    logger.info("/poe2leagues user_id=%s chat_id=%s", message.from_user.id, message.chat.id)
    try:
        rows = await fetch_leagues(settings)
    except httpx.HTTPStatusError as e:
        logger.exception("poe2leagues fetch HTTP error")
        await message.reply(f"Не вышло стянуть список лиг: HTTP {e.response.status_code}.")
        return
    except ValueError:
        logger.exception("poe2leagues unexpected response")
        await message.reply("Не удалось разобрать ответ сервера. Смотри лог бота.")
        return
    except Exception:
        logger.exception("poe2leagues failed")
        await message.reply("Ошибка при запросе списка лиг. Смотри лог бота.")
        return
    catalog = build_leagues_catalog_text(rows)
    for chunk in split_telegram_chunks(catalog):
        await message.reply(chunk)
