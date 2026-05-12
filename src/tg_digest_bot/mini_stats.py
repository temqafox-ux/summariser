from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from typing import Any

from zoneinfo import ZoneInfo


def _preview_text(text: str, max_chars: int) -> str:
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= max_chars:
        return collapsed
    return collapsed[: max_chars - 1] + "…"


def _author_label(user_id: int, username: str | None) -> str:
    u = (username or "").strip()
    if u:
        return f"@{u}"
    return f"id{user_id}"


def build_mini_stats_text(
    *,
    local_day: dt.date,
    tz_name: str,
    rows: list[dict[str, Any]],
    top_n: int = 5,
    long_preview: int = 140,
) -> str:
    """
    Короткая сводка по сырым сообщениям за локальный день (границы дня уже отфильтрованы в выборке).
    """
    lines: list[str] = [
        f"Мини-стат за {local_day.isoformat()} ({tz_name})",
        "",
    ]
    if not rows:
        lines.append("За этот день в базе нет ни одного сообщения.")
        return "\n".join(lines)

    tz = ZoneInfo(tz_name)
    ordered = sorted(rows, key=lambda r: int(r["message_id"]))

    last_username: dict[int, str | None] = {}
    for r in ordered:
        last_username[int(r["user_id"])] = r.get("username")

    by_user = Counter(int(r["user_id"]) for r in ordered)
    n_msg = len(ordered)
    n_authors = len(by_user)
    n_replies = sum(1 for r in ordered if r.get("reply_to_message_id") is not None)

    lines.append(f"Сообщений: {n_msg} · Авторов: {n_authors} · С ответом (reply): {n_replies}")
    lines.append("")

    lines.append("Топ по числу реплик:")
    for i, (uid, cnt) in enumerate(by_user.most_common(top_n), start=1):
        label = _author_label(uid, last_username.get(uid))
        lines.append(f"{i}. {label} — {cnt}")
    lines.append("")

    longest = max(ordered, key=lambda r: len(str(r.get("text") or "")))
    long_text = str(longest.get("text") or "")
    long_uid = int(longest["user_id"])
    long_label = _author_label(long_uid, longest.get("username"))
    lines.append(f"Самая длинная реплика ({len(long_text)} симв., {long_label}):")
    lines.append(f"«{_preview_text(long_text, long_preview)}»")
    lines.append("")

    hour_counts: dict[int, int] = defaultdict(int)
    for r in ordered:
        local_ts = dt.datetime.fromtimestamp(int(r["date_utc"]), tz=dt.UTC).astimezone(tz)
        hour_counts[local_ts.hour] += 1

    quiet_h = min(range(24), key=lambda h: hour_counts[h])
    busy_h = max(range(24), key=lambda h: hour_counts[h])

    def _slot(h: int) -> str:
        end = (h + 1) % 24
        return f"{h:02d}:00–{end:02d}:00"

    lines.append(
        "По часам (локально): "
        f"тише {_slot(quiet_h)} ({hour_counts[quiet_h]}), "
        f"гуще {_slot(busy_h)} ({hour_counts[busy_h]})",
    )

    first = ordered[0]
    last = ordered[-1]
    t0 = dt.datetime.fromtimestamp(int(first["date_utc"]), tz=dt.UTC).astimezone(tz)
    t1 = dt.datetime.fromtimestamp(int(last["date_utc"]), tz=dt.UTC).astimezone(tz)
    lines.append(
        f"Первое сообщение дня: {t0.strftime('%H:%M')}, "
        f"последнее: {t1.strftime('%H:%M')}",
    )

    return "\n".join(lines)
