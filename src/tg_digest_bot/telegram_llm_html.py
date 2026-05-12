from __future__ import annotations

import html
import re


def _plain_italic_stars_to_html(s: str) -> str:
    """Экранирует фрагмент и переводит *курсив* (одинарные *, без перевода строки внутри) в <i>…</i>."""
    pieces = re.split(r"(\*[^*\n]+\*)", s)
    buf: list[str] = []
    for piece in pieces:
        if (
            len(piece) >= 2
            and piece.startswith("*")
            and piece.endswith("*")
            and not piece.startswith("**")
        ):
            inner = piece[1:-1]
            if not inner.strip():
                buf.append(html.escape(piece))
            else:
                buf.append("<i>" + html.escape(inner) + "</i>")
        else:
            buf.append(html.escape(piece))
    return "".join(buf)


def llm_double_stars_to_telegram_html(text: str) -> str:
    """
    Telegram parse_mode=HTML: **жирный** → <b>…</b>, вне жирного ещё *курсив* → <i>…</i>;
    остальное экранируется (& < > и т.д.).
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
            out.append(_plain_italic_stars_to_html(p))
    return "".join(out)
