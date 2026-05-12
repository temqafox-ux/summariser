from __future__ import annotations

import html
import re

# Маркеры заголовков «# …» без склейки с ** внутри заголовка
_HDR_MARK = "__HDR_{}__"


def _atx_headers_to_placeholders(text: str) -> tuple[str, list[str]]:
    """Заголовки #/##/### → плейсхолдер + HTML-кусок для подстановки в конце."""
    hdrs: list[str] = []
    out_lines: list[str] = []
    for line in text.split("\n"):
        m = re.match(r"^(#{1,3})\s+(.+)$", line)
        if m:
            title = m.group(2).strip()
            if title:
                i = len(hdrs)
                hdrs.append("<b>" + html.escape(title) + "</b>")
                out_lines.append(_HDR_MARK.format(i))
            else:
                out_lines.append(line)
        else:
            out_lines.append(line)
    return "\n".join(out_lines), hdrs


def _restore_hdr_placeholders(s: str, hdrs: list[str]) -> str:
    for i, chunk in enumerate(hdrs):
        s = s.replace(_HDR_MARK.format(i), chunk)
    return s


def _plain_italic_stars_to_html(s: str) -> str:
    """Экранирует фрагмент и переводит *курсив* в <i>…</i>."""
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


def _plain_code_then_italic_to_html(s: str) -> str:
    """Инлайн `код`, затем *курсив*; остальное экранируется."""
    pieces = re.split(r"(`[^`]+`)", s)
    buf: list[str] = []
    for piece in pieces:
        if len(piece) >= 2 and piece.startswith("`") and piece.endswith("`"):
            inner = piece[1:-1]
            buf.append("<code>" + html.escape(inner) + "</code>")
        else:
            buf.append(_plain_italic_stars_to_html(piece))
    return "".join(buf)


def llm_double_stars_to_telegram_html(text: str) -> str:
    """
    Telegram parse_mode=HTML из типичного вывода LLM:
    - строки «# … / ## … / ### …» → <b>заголовок</b> (отдельная строка);
    - **жирный** → <b>…</b>;
    - `код` → <code>…</code>;
    - *курсив* → <i>…</i>.
    """
    if not text:
        return ""
    t, hdrs = _atx_headers_to_placeholders(text)
    parts = re.split(r"(\*\*.+?\*\*)", t, flags=re.DOTALL)
    out: list[str] = []
    for p in parts:
        if len(p) >= 4 and p.startswith("**") and p.endswith("**"):
            inner = p[2:-2]
            out.append("<b>" + html.escape(inner) + "</b>")
        else:
            out.append(_plain_code_then_italic_to_html(p))
    return _restore_hdr_placeholders("".join(out), hdrs)
