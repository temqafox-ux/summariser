from __future__ import annotations

import html
import re


def llm_double_stars_to_telegram_html(text: str) -> str:
    """
    Telegram parse_mode=HTML: переводит **жирный** из типичного вывода LLM в <b>...</b>,
    остальной текст экранирует, чтобы случайные <>& не ломали разбор.
    """
    if not text:
        return ""
    parts = re.split(r"(\*\*.+?\*\*)", text, flags=re.DOTALL)
    out: list[str] = []
    for p in parts:
        if len(p) >= 4 and p.startswith("**") and p.endswith("**"):
            inner = p[2:-2]
            out.append("<b>" + html.escape(inner) + "</b>")
        else:
            out.append(html.escape(p))
    return "".join(out)
