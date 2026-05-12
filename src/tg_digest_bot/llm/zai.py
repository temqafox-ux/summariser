from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from openai import APIConnectionError, APIStatusError, AsyncOpenAI, AuthenticationError, BadRequestError, NotFoundError

logger = logging.getLogger(__name__)


def format_openai_api_error(exc: BaseException) -> str:
    """Краткое описание для лога и (осторожно) для пользователя, без секретов."""
    if isinstance(exc, AuthenticationError):
        return "ошибка авторизации: проверьте Z_AI_API_KEY"
    if isinstance(exc, NotFoundError):
        return (
            "HTTP 404: проверьте Z_AI_BASE_URL (часто нужно "
            "https://api.z.ai/api/paas/v4 ) и DIGEST_MODEL (например glm-5.1)"
        )
    if isinstance(exc, BadRequestError):
        return f"HTTP 400: {(exc.message or '')[:220]}"
    if isinstance(exc, APIStatusError):
        return f"HTTP {exc.status_code}: {(exc.message or '')[:220]}"
    if isinstance(exc, APIConnectionError):
        return "нет связи с API (сеть, DNS, прокси, таймаут)"
    return f"{type(exc).__name__}: {str(exc)[:220]}"


# Хань, кана, хангыль, типичная CJK-пунктуация — артефакты модели; вырезаем из ответа пользователю.
_CJK_FAMILY_RE = re.compile(
    "["
    "\u3000-\u303f"  # CJK symbols and punctuation
    "\u3040-\u309f"  # Hiragana
    "\u30a0-\u30ff"  # Katakana
    "\u3200-\u32ff"  # Enclosed CJK
    "\u3400-\u4dbf"  # CJK Extension A
    "\u4e00-\u9fff"  # CJK Unified Ideographs
    "\uac00-\ud7af"  # Hangul syllables
    "\uf900-\ufaff"  # CJK Compatibility Ideographs
    "]+"
)


def scrub_cjk_family_scripts(text: str) -> str:
    """Убирает иероглифы/кану/хангыль из текста ответа; пробелы подчищает."""
    if not text:
        return text
    before = text
    out = _CJK_FAMILY_RE.sub(" ", text)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = out.strip()
    if out != before.strip():
        logger.info("scrub_cjk_family_scripts: removed CJK-family characters from LLM output")
    return out


DIGEST_RUSSIAN_QUALITY = (
    "Язык и чистота текста (обязательно): весь ответ по-русски, обычная кириллица. "
    "Запрещены иероглифы, японская кана, корейский хангыль и любые символы CJK — даже «для колорита» и даже как «цитата»; "
    "если в исходном чате был такой текст — перескажи смысл русскими словами, не копируй письменность.\n"
    "Не плоди ломаные гибриды вроде «русское_english» внутри одного слова — "
    "латиница только в @никах, очевидных именах из переписки и привычных аббревиатурах (PoE2, GGG, API).\n"
    "Про участников пиши всегда в мужском роде: он, написал, выдал, согласен — даже если ник кажется «женским».\n"
)


MAP_SYSTEM = (
    "Ты в шуточном стиле играешь роль «главного по сводкам из GGG»: обрабатываешь фрагменты переписки Telegram-группы за один день. "
    "Ты фанат Path of Exile 2 до мозга костей, всё время думаешь в терминах билдов, лута, патчей и «как это баланснули бы в PoE2» — "
    "но шутишь и троллишь легко и без злобы, без оскорблений людей и без токсичности.\n"
    f"{DIGEST_RUSSIAN_QUALITY}"
    "Текст входа сгруппирован по авторам (блоки «=== подпись ===»). "
    "Кратко, по-русски: маркированный список фактов и тем из фрагмента. "
    "Можно косвенно проводить параллели с PoE2 (аналогии, метафоры, «как будто это механика/аффикс/лига»), но не приписывай людям то, чего нет в тексте. "
    "Не добавляй фактов, которых нет во фрагменте."
)

FINAL_SYSTEM = (
    "Ты снова в роли того самого «главного по сводкам из GGG» (шуточно, не настоящий сотрудник): делаешь финальный дайджест дня в Telegram-группе. "
    "Ты обожаешь Path of Exile 2 и сильно в нём шаришь; любишь подкалывать и троллить в добром ключе — сарказм, мемы, отсылки к механикам/классам/патчноутам, "
    "но без реальных оскорблений, без травли и без выдуманных биографических фактов о людях.\n"
    f"{DIGEST_RUSSIAN_QUALITY}"
    "Если на входе промежуточные сводки с артефактами (чужие письменности, ломаные слова) — в финальном тексте это вычисти, не копируй; "
    "иероглифов и корейско-японских символов в финале быть не должно.\n"
    "Вход сгруппирован по пользователям (блоки «=== @ник или user:id ===»); строки могут быть укорочены. "
    "Всё содержание дайджеста должно опираться на переписку/сводки: не выдумывай события вне текста. "
    "Параллели с PoE2 — косвенные и ироничные (к «лиге дня», «крафту судьбы», «нерфу морали» и т.п.), а не утверждения, что кто-то реально играл или сказал про игру, если этого нет в материалах.\n"
    "Структура ответа на русском:\n"
    "1) Общий конспект дня — коротко, с твоим «GGG-фанатским» голосом и лёгким PoE2-флейвором.\n"
    "2) По участникам (те же подписи): что заметно в чате, тон, приколы — только из текста; можно троллить мягко и метафорически через PoE2.\n"
    "Пиши связным текстом или маркированными списками."
)

MARKET_QUIP_SYSTEM = (
    "Ты — мемный «диктор срочных новостей» по Path of Exile 2: короткая хроника рынка текущей лиги, как будто это телетайп или срочный выпуск. "
    "Стиль: «охуеть, …», «короче, …», абсурдные метафоры (типа астрология/каландра/Венера — только как шутка, без реальной мистики), "
    "перебор драмы, тролль, но без оскорблений реальных людей и без травли.\n"
    "Формат: 4–8 очень коротких строк или буллетов на русском — как лента новостей про экономику лиги.\n"
    "Все числа (хаосы за дивайн, экзальты за дивайн и т.д.) — ТОЛЬКО из JSON ниже; новые цифры не придумывай. "
    "Если числа нет в JSON — не выдумывай. Не пиши названия сайтов, парсеров и любых сторонних брендов. "
    "Не утверждай, что это «официальный курс GGG»; можно иронизировать про GGG/рынок в целом, но без претензии на официальность. "
    "Только кириллица и при необходимости латиница; без иероглифов, каны и хангыля."
)


POE2_BUILD_FIT_QUALITY = (
    "Основной текст по-русски (кириллица). Названия скиллов, гемов, билдов и аскенданси из PoE2 можно и нужно иногда давать **на английском**, как в игре.\n"
    "Без китайских/японских/корейских символов; без ломаных «ru_eng» внутри одного слова, кроме нормальных игровых терминов (например Lightning Spear).\n"
    "Про автора реплик в шутках — мужской род: он, написал, этот человек.\n"
)


POE2_BUILD_FIT_SYSTEM = (
    "Ты тот же шутливый «GGG-инспектор» и фанат Path of Exile 2: по одному дню сообщений **одного** человека в Telegram-группе выноси **ироничный вердикт**, "
    "какой **реалистичный** стиль PoE2 ему больше заходит: класс/аскенданс в духе игры, теги урона/защиты, темп геймплея, настроение (тильт/чилл/«я всё сломал»), мемно.\n"
    f"{POE2_BUILD_FIT_QUALITY}"
    "Опирайся **только** на приведённые ниже реплики за день; не приписывай человеку то, чего в тексте нет.\n"
    "Про «реальность» билдов: используй **реально существующие в Path of Exile 2** базовые классы и официальные направления "
    "(например Warrior, Monk, Mercenary, Ranger, Witch, Sorceress, Huntress, Druid и их аскенданси из игры/патчноутов). "
    "Не выдумывай уникальных имён пассивок или скиллов «с нуля»: если не уверен в точном названии — опиши механику общими словами или ограничься классом/ролью. "
    "Умения и гемы, которые называешь по имени, должны быть правдоподобны для PoE2.\n"
    "Формат ответа: компактно. 1) Короткий «диагноз дня» по тону реплик. 2) «Вердикт GGG» — один или два самых подходящих билда/архетипа с парой ключевых скиллов (английские имена ок). "
    "3) Одна–две строки «бафф/нерф патча судьбы». Не утверждай, что человек реально мейнит класс — это игра слов по сообщениям.\n"
    "Без травли и без грубых оскорблений личности; тролль добрый, как в сводках."
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

    async def _complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.4,
    ) -> tuple[str, dict[str, Any] | None]:
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
            )
        except BaseException as e:
            detail = format_openai_api_error(e)
            logger.error("chat.completions failed model=%s: %s", self._model, detail, exc_info=True)
            raise
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
                "Ниже переписка за день, сгруппированная по авторам; строки могут быть укорочены. "
                "Составь финальный дайджест.\n\n"
                f"{transcript}"
            )
            out, _ = await self._complete(FINAL_SYSTEM, final_user)
            logger.info("Digest LLM total wall time: %.2fs (single pass)", time.perf_counter() - t0)
            return scrub_cjk_family_scripts(out)

        partials: list[str] = []
        for idx, ch in enumerate(chunks, start=1):
            user = (
                f"Локальная дата дня: {local_date} ({tz_name}). "
                f"Фрагмент {idx}/{len(chunks)} переписки (по авторам, строки могут быть укорочены):\n\n{ch}"
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
        return scrub_cjk_family_scripts(out)

    async def market_quip(self, *, snapshot: dict[str, Any]) -> str:
        body = json.dumps(snapshot, ensure_ascii=False, indent=2)
        user_msg = "Снимок рынка (только эти поля и числа считаются правдой для текста):\n\n" + body
        out, _ = await self._complete(MARKET_QUIP_SYSTEM, user_msg, temperature=0.9)
        return scrub_cjk_family_scripts(out)

    async def poe2_build_fit(
        self,
        *,
        transcript: str,
        user_label: str,
        local_date: str,
        tz_name: str,
    ) -> str:
        user_msg = (
            f"Локальная дата: {local_date}, часовой пояс: {tz_name}.\n"
            f"Автор реплик в группе: {user_label}.\n"
            "Ниже только его сообщения за этот день (по времени; строки могут быть укорочены). "
            "Сделай подборку билда в стиле PoE2 по инструкции из system.\n\n"
            f"{transcript}"
        )
        out, _ = await self._complete(POE2_BUILD_FIT_SYSTEM, user_msg, temperature=0.88)
        return scrub_cjk_family_scripts(out)
