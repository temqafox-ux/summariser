from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS messages (
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT,
    date_utc INTEGER NOT NULL,
    text TEXT NOT NULL,
    reply_to_message_id INTEGER,
    PRIMARY KEY (chat_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_date
    ON messages (chat_id, date_utc);

CREATE INDEX IF NOT EXISTS idx_messages_chat_user_date
    ON messages (chat_id, user_id, date_utc);

CREATE TABLE IF NOT EXISTS digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    local_date TEXT NOT NULL,
    tz TEXT NOT NULL,
    max_message_id INTEGER NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE (chat_id, local_date, tz, max_message_id, prompt_version)
);

CREATE INDEX IF NOT EXISTS idx_digests_lookup
    ON digests (chat_id, local_date, tz, prompt_version, max_message_id);

CREATE TABLE IF NOT EXISTS digest_autostart (
    chat_id INTEGER NOT NULL PRIMARY KEY,
    message_thread_id INTEGER,
    hour INTEGER NOT NULL,
    minute INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
"""


class Database:
    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = asyncio.Lock()
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        p = Path(self._path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(p))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected")
        return self._conn

    async def insert_message(
        self,
        *,
        chat_id: int,
        message_id: int,
        user_id: int,
        username: str | None,
        date_utc: int,
        text: str,
        reply_to_message_id: int | None,
    ) -> None:
        async with self._lock:
            await self.conn.execute(
                """
                INSERT INTO messages (chat_id, message_id, user_id, username, date_utc, text, reply_to_message_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, message_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    username = excluded.username,
                    date_utc = excluded.date_utc,
                    text = excluded.text,
                    reply_to_message_id = excluded.reply_to_message_id
                """,
                (
                    chat_id,
                    message_id,
                    user_id,
                    username,
                    date_utc,
                    text,
                    reply_to_message_id,
                ),
            )
            await self.conn.commit()

    async def upsert_digest_autostart(
        self,
        *,
        chat_id: int,
        message_thread_id: int | None,
        hour: int,
        minute: int,
        updated_at: int,
    ) -> None:
        async with self._lock:
            await self.conn.execute(
                """
                INSERT INTO digest_autostart (chat_id, message_thread_id, hour, minute, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    message_thread_id = excluded.message_thread_id,
                    hour = excluded.hour,
                    minute = excluded.minute,
                    updated_at = excluded.updated_at
                """,
                (chat_id, message_thread_id, hour, minute, updated_at),
            )
            await self.conn.commit()

    async def delete_digest_autostart(self, *, chat_id: int) -> None:
        async with self._lock:
            await self.conn.execute(
                "DELETE FROM digest_autostart WHERE chat_id = ?",
                (chat_id,),
            )
            await self.conn.commit()

    async def get_digest_autostart(self, *, chat_id: int) -> dict[str, Any] | None:
        async with self._lock:
            cur = await self.conn.execute(
                "SELECT chat_id, message_thread_id, hour, minute, updated_at FROM digest_autostart WHERE chat_id = ?",
                (chat_id,),
            )
            row = await cur.fetchone()
        return dict(row) if row else None

    async def list_digest_autostarts(self) -> list[dict[str, Any]]:
        async with self._lock:
            cur = await self.conn.execute(
                "SELECT chat_id, message_thread_id, hour, minute, updated_at FROM digest_autostart ORDER BY chat_id"
            )
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def fetch_messages_for_day(
        self,
        *,
        chat_id: int,
        start_utc: int,
        end_utc: int,
        limit: int | None,
    ) -> list[dict[str, Any]]:
        """
        Messages in chronological order. If limit is set, keep the newest `limit`
        rows for that day (drop older ones) so the digest reflects recent activity.
        """
        params: list[Any] = [chat_id, start_utc, end_utc]
        if limit is not None and limit > 0:
            sql = """
                SELECT chat_id, message_id, user_id, username, date_utc, text, reply_to_message_id
                FROM (
                    SELECT chat_id, message_id, user_id, username, date_utc, text, reply_to_message_id
                    FROM messages
                    WHERE chat_id = ? AND date_utc >= ? AND date_utc < ?
                    ORDER BY message_id DESC
                    LIMIT ?
                ) sub
                ORDER BY message_id ASC
                """
            params.append(limit)
        else:
            sql = """
                SELECT chat_id, message_id, user_id, username, date_utc, text, reply_to_message_id
                FROM messages
                WHERE chat_id = ? AND date_utc >= ? AND date_utc < ?
                ORDER BY message_id ASC
                """
        async with self._lock:
            cur = await self.conn.execute(sql, params)
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def fetch_messages_for_user_day(
        self,
        *,
        chat_id: int,
        user_id: int,
        start_utc: int,
        end_utc: int,
        limit: int | None,
    ) -> list[dict[str, Any]]:
        """
        Сообщения одного пользователя за локальный день, по возрастанию message_id.
        Если limit задан — берутся самые новые limit строк (остальное отбрасывается).
        """
        params: list[Any] = [chat_id, user_id, start_utc, end_utc]
        if limit is not None and limit > 0:
            sql = """
                SELECT chat_id, message_id, user_id, username, date_utc, text, reply_to_message_id
                FROM (
                    SELECT chat_id, message_id, user_id, username, date_utc, text, reply_to_message_id
                    FROM messages
                    WHERE chat_id = ? AND user_id = ? AND date_utc >= ? AND date_utc < ?
                    ORDER BY message_id DESC
                    LIMIT ?
                ) sub
                ORDER BY message_id ASC
                """
            params.append(limit)
        else:
            sql = """
                SELECT chat_id, message_id, user_id, username, date_utc, text, reply_to_message_id
                FROM messages
                WHERE chat_id = ? AND user_id = ? AND date_utc >= ? AND date_utc < ?
                ORDER BY message_id ASC
                """
        async with self._lock:
            cur = await self.conn.execute(sql, params)
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def resolve_user_id_by_username_in_day(
        self,
        *,
        chat_id: int,
        start_utc: int,
        end_utc: int,
        username: str,
    ) -> int | None:
        """
        user_id с наибольшим числом сообщений за день среди строк с тем же @username (без учёта регистра).
        """
        u = username.strip().lstrip("@").strip()
        if not u:
            return None
        async with self._lock:
            cur = await self.conn.execute(
                """
                SELECT user_id, COUNT(*) AS cnt
                FROM messages
                WHERE chat_id = ?
                  AND date_utc >= ? AND date_utc < ?
                  AND username IS NOT NULL AND LENGTH(TRIM(username)) > 0
                  AND LOWER(username) = LOWER(?)
                GROUP BY user_id
                ORDER BY cnt DESC, user_id ASC
                LIMIT 1
                """,
                (chat_id, start_utc, end_utc, u),
            )
            row = await cur.fetchone()
        return int(row["user_id"]) if row else None

    async def count_messages_for_day(
        self,
        *,
        chat_id: int,
        start_utc: int,
        end_utc: int,
    ) -> int:
        async with self._lock:
            cur = await self.conn.execute(
                """
                SELECT COUNT(*) AS c FROM messages
                WHERE chat_id = ? AND date_utc >= ? AND date_utc < ?
                """,
                (chat_id, start_utc, end_utc),
            )
            row = await cur.fetchone()
        return int(row["c"]) if row else 0

    async def get_digest(
        self,
        *,
        chat_id: int,
        local_date: str,
        tz: str,
        max_message_id: int,
        prompt_version: str,
    ) -> str | None:
        async with self._lock:
            cur = await self.conn.execute(
                """
                SELECT content FROM digests
                WHERE chat_id = ? AND local_date = ? AND tz = ?
                  AND max_message_id = ? AND prompt_version = ?
                """,
                (chat_id, local_date, tz, max_message_id, prompt_version),
            )
            row = await cur.fetchone()
        return str(row["content"]) if row else None

    async def upsert_digest(
        self,
        *,
        chat_id: int,
        local_date: str,
        tz: str,
        max_message_id: int,
        model: str,
        prompt_version: str,
        content: str,
        created_at: int,
    ) -> None:
        async with self._lock:
            await self.conn.execute(
                """
                INSERT INTO digests (
                    chat_id, local_date, tz, max_message_id, model, prompt_version, content, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, local_date, tz, max_message_id, prompt_version) DO UPDATE SET
                    model = excluded.model,
                    content = excluded.content,
                    created_at = excluded.created_at
                """,
                (
                    chat_id,
                    local_date,
                    tz,
                    max_message_id,
                    model,
                    prompt_version,
                    content,
                    created_at,
                ),
            )
            await self.conn.commit()

    async def delete_digests_for_day(
        self,
        *,
        chat_id: int,
        local_date: str,
        tz: str,
    ) -> None:
        async with self._lock:
            await self.conn.execute(
                """
                DELETE FROM digests
                WHERE chat_id = ? AND local_date = ? AND tz = ?
                """,
                (chat_id, local_date, tz),
            )
            await self.conn.commit()
