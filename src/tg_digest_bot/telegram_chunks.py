from __future__ import annotations

TG_MAX_MESSAGE = 4096


def split_telegram_chunks(text: str, max_len: int = TG_MAX_MESSAGE) -> list[str]:
    if len(text) <= max_len:
        return [text]
    parts: list[str] = []
    rest = text
    while rest:
        if len(rest) <= max_len:
            parts.append(rest)
            break
        chunk = rest[:max_len]
        cut = chunk.rfind("\n")
        if cut < max_len // 2:
            cut = max_len
        parts.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    return parts
