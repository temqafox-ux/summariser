from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DayViewFilter:
    """Сжатие дня для LLM и для filtered JSON."""

    max_message_chars: int
    min_message_chars: int
    max_messages_per_user: int  # 0 = без лимита на пользователя


def user_display(user_id: int, username: str | None) -> str:
    u = (username or "").strip()
    return f"@{u}" if u else f"user:{user_id}"


def _normalize_line(text: str) -> str:
    return (text or "").replace("\n", " ").strip()


def _trim(s: str, max_len: int) -> str:
    if max_len <= 0 or len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def build_user_message_groups(
    rows: list[dict[str, Any]],
    flt: DayViewFilter,
) -> list[dict[str, Any]]:
    """
    rows — по возрастанию message_id (как из БД).
    Возвращает блоки по первому появлению пользователя в этот день (порядок как в чате).
    """
    by_uid: dict[int, list[str]] = defaultdict(list)
    username_by_uid: dict[int, str | None] = {}
    order: list[int] = []

    for r in rows:
        uid = int(r["user_id"])
        if uid not in username_by_uid:
            username_by_uid[uid] = r.get("username")
            order.append(uid)
        norm = _normalize_line(str(r.get("text") or ""))
        if len(norm) < flt.min_message_chars:
            continue
        norm = _trim(norm, flt.max_message_chars)
        if not norm:
            continue
        by_uid[uid].append(norm)

    out: list[dict[str, Any]] = []
    for uid in order:
        msgs = by_uid[uid]
        if not msgs:
            continue
        if flt.max_messages_per_user > 0 and len(msgs) > flt.max_messages_per_user:
            msgs = msgs[-flt.max_messages_per_user :]
        un = username_by_uid.get(uid)
        out.append(
            {
                "user_id": uid,
                "username": un,
                "display": user_display(uid, un),
                "messages": msgs,
            }
        )
    return out


def build_filtered_text_for_llm(rows: list[dict[str, Any]], flt: DayViewFilter) -> str:
    groups = build_user_message_groups(rows, flt)
    parts: list[str] = []
    for g in groups:
        body = "\n".join(g["messages"])
        parts.append(f"=== {g['display']} ===\n{body}")
    return "\n\n".join(parts)


def build_filtered_export_dict(
    *,
    chat_id: int,
    local_date: str,
    tz: str,
    truncated_day_slice: bool,
    total_messages_in_day: int,
    messages_in_export_slice: int,
    flt: DayViewFilter,
    groups: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": "tg_digest_bot.filtered_export_v1",
        "chat_id": chat_id,
        "local_date": local_date,
        "tz": tz,
        "truncated_day_slice": truncated_day_slice,
        "total_messages_in_day": total_messages_in_day,
        "messages_in_export_slice": messages_in_export_slice,
        "filter": {
            "max_message_chars": flt.max_message_chars,
            "min_message_chars": flt.min_message_chars,
            "max_messages_per_user": flt.max_messages_per_user,
        },
        "users": [
            {
                "user_id": g["user_id"],
                "username": g.get("username"),
                "display": g["display"],
                "message_count": len(g["messages"]),
                "messages": g["messages"],
            }
            for g in groups
        ],
    }
