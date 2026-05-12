from __future__ import annotations

import logging
from typing import Any

import httpx

from tg_digest_bot.config import Settings

logger = logging.getLogger(__name__)


def _is_hardcore_league(name: str | None) -> bool:
    n = (name or "").strip().lower()
    return n.startswith("hc ") or n == "hardcore"


def pick_league_row(rows: list[dict[str, Any]], *, league_override: str) -> dict[str, Any]:
    if not rows:
        raise ValueError("empty_leagues")
    ov = (league_override or "").strip()
    if ov:
        for r in rows:
            if str(r.get("Value", "")).strip() == ov:
                return r
        ov_lower = ov.lower()
        for r in rows:
            if str(r.get("Value", "")).strip().lower() == ov_lower:
                return r
        raise ValueError(f"league_not_found:{ov}")
    for r in rows:
        if r.get("IsCurrent") and not _is_hardcore_league(str(r.get("Value"))):
            return r
    for r in rows:
        if r.get("IsCurrent"):
            return r
    return rows[0]


def snapshot_for_llm(row: dict[str, Any]) -> dict[str, Any]:
    """Компактный JSON для LLM без имён сторонних сайтов (только цифры и лига)."""
    return {
        "league_name": row.get("Value"),
        "league_marked_current_in_feed": row.get("IsCurrent"),
        "approx_divine_in_trade_currency": row.get("DivinePrice"),
        "approx_chaos_per_one_divine": row.get("ChaosDivinePrice"),
        "trade_currency_name": row.get("BaseCurrencyText"),
        "internal_note_for_model": (
            "Цифры — снимок по торговым листингам, не официальный прайс GGG. "
            "В ответе пользователю: не называй сайты, парсеры и сторонние бренды; "
            "поле chaos_per_divine = сколько хаосов за 1 дивайн по этому снимку."
        ),
    }


async def fetch_leagues(settings: Settings) -> list[dict[str, Any]]:
    base = settings.poe2_scout_base_url
    realm = settings.poe2_scout_realm.strip("/").strip() or "poe2"
    url = f"{base}/{realm}/Leagues"
    headers = {"User-Agent": settings.http_user_agent}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers, timeout=25.0)
        resp.raise_for_status()
        data = resp.json()
    if not isinstance(data, list):
        raise ValueError("unexpected_leagues_shape")
    logger.info("leagues feed fetched count=%s url=%s", len(data), url)
    return data


def build_leagues_catalog_text(rows: list[dict[str, Any]]) -> str:
    """Плоский список имён лиг для ответа в Telegram (без parse_mode)."""
    lines = [
        "Лиги из фида (имя копируй один в один, регистр можно как угодно):",
        "",
        "Сводка рынка: /poe2market имя_лиги",
        "Без аргумента — из POE2_MARKET_LEAGUE в .env или авто «текущая» софткор.",
        "",
    ]
    for r in rows:
        v = str(r.get("Value", "")).strip()
        if not v:
            continue
        tag = " [помечена как текущая]" if r.get("IsCurrent") else ""
        lines.append(f"• {v}{tag}")
    return "\n".join(lines)
