from __future__ import annotations

import logging

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.types import Message

from tg_digest_bot.db import Database

logger = logging.getLogger(__name__)

router = Router(name="messages")


def _extract_text(message: Message) -> str | None:
    if message.text:
        return message.text
    if message.caption:
        return message.caption
    return None


@router.message(
    lambda m: m.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP},
)
async def store_group_message(message: Message, db: Database) -> None:
    text = _extract_text(message)
    if text is None or not text.strip():
        return
    user = message.from_user
    if user is None:
        return
    date_utc = int(message.date.timestamp())
    reply_id = message.reply_to_message.message_id if message.reply_to_message else None
    try:
        await db.insert_message(
            chat_id=message.chat.id,
            message_id=message.message_id,
            user_id=user.id,
            username=user.username,
            date_utc=date_utc,
            text=text.strip(),
            reply_to_message_id=reply_id,
        )
    except Exception:
        logger.exception("Failed to store message chat=%s mid=%s", message.chat.id, message.message_id)
