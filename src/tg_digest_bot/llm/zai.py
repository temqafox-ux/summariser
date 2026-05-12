from __future__ import annotations

import logging
import time
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

MAP_SYSTEM = (
    "Ты сжимаешь фрагмент переписки Telegram-группы за один календарный день. "
    "Пиши по-русски, нейтрально и кратко: маркированный список фактов, тем, шуток. "
    "Не добавляй информацию, которой нет во фрагменте."
)

FINAL_SYSTEM = (
    "Ты составляешь дайджест дня в Telegram-группе строго на основе предоставленных сводок и переписки. "
    "Не выдумывай биографические факты и события вне текста. "
    "Если чего-то нет в материалах — не заполняй пустыми домыслами.\n"
    "Структура ответа на русском:\n"
    "1) Общий конспект дня (кратко).\n"
    "2) По участникам (по @username или user:id): заметные темы, тон, шутки — только из текста.\n"
    "Пиши связным текстом или маркированными списками, без вымышленных деталей."
)


def _chunk_text(s: str, max_chars: int) -> list[str]:
    if len(s) <= max_chars:
        return [s]
    parts: list[str] = []
    i = 0
    while i < len(s):
        parts.append(s[i : i + max_chars])
        i += max_chars
    return parts


def build_day_transcript(rows: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for r in rows:
        uid = r["user_id"]
        un = r.get("username") or ""
        label = f"@{un}" if un else f"user:{uid}"
        mid = r["message_id"]
        txt = (r.get("text") or "").replace("\n", " ").strip()
        lines.append(f"[{mid}] {label}: {txt}")
    return "\n".join(lines)


class ZaiDigestLLM:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        chunk_chars: int,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._chunk_chars = chunk_chars

    async def _complete(self, system: str, user: str) -> tuple[str, dict[str, Any] | None]:
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.4,
        )
        choice = resp.choices[0].message
        text = (choice.content or "").strip()
        usage = None
        if getattr(resp, "usage", None) is not None:
            u = resp.usage
            usage = {
                "prompt_tokens": getattr(u, "prompt_tokens", None),
                "completion_tokens": getattr(u, "completion_tokens", None),
                "total_tokens": getattr(u, "total_tokens", None),
            }
            logger.info("LLM usage: %s", usage)
        return text, usage

    async def summarize_day(
        self,
        *,
        transcript: str,
        local_date: str,
        tz_name: str,
    ) -> str:
        t0 = time.perf_counter()
        chunks = _chunk_text(transcript, self._chunk_chars)
        if len(chunks) == 1:
            final_user = (
                f"Дата: {local_date}, часовой пояс: {tz_name}.\n"
                "Ниже переписка за день. Составь финальный дайджест.\n\n"
                f"{transcript}"
            )
            out, _ = await self._complete(FINAL_SYSTEM, final_user)
            logger.info("Digest LLM total wall time: %.2fs (single pass)", time.perf_counter() - t0)
            return out

        partials: list[str] = []
        for idx, ch in enumerate(chunks, start=1):
            user = (
                f"Локальная дата дня: {local_date} ({tz_name}). "
                f"Фрагмент {idx}/{len(chunks)} переписки (хронологический порядок):\n\n{ch}"
            )
            part, _ = await self._complete(MAP_SYSTEM, user)
            partials.append(f"--- Сводка части {idx}/{len(chunks)} ---\n{part}")

        merged = "\n\n".join(partials)
        final_user = (
            f"Дата: {local_date}, часовой пояс: {tz_name}.\n"
            "Ниже промежуточные сводки частей одного и того же дня. "
            "Объедини их в единый финальный дайджест.\n\n"
            f"{merged}"
        )
        out, _ = await self._complete(FINAL_SYSTEM, final_user)
        logger.info("Digest LLM total wall time: %.2fs", time.perf_counter() - t0)
        return out
