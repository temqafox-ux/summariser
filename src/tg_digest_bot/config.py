from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(validation_alias="BOT_TOKEN")
    z_ai_api_key: str = Field(validation_alias="Z_AI_API_KEY")
    z_ai_base_url: str = Field(
        default="https://api.z.ai/api/paas/v4",
        validation_alias="Z_AI_BASE_URL",
    )
    digest_model: str = Field(default="glm-5.1", validation_alias="DIGEST_MODEL")
    digest_tz: str = Field(default="Europe/Moscow", validation_alias="DIGEST_TZ")
    prompt_version: str = Field(default="1", validation_alias="PROMPT_VERSION")
    database_path: str = Field(
        default="data/bot.sqlite3",
        validation_alias="DATABASE_PATH",
    )
    digest_allowed_user_ids: str = Field(
        default="",
        validation_alias="DIGEST_ALLOWED_USER_IDS",
    )
    # Legacy name; used only if DIGEST_ALLOWED_USER_IDS is empty
    admin_user_ids: str = Field(default="", validation_alias="ADMIN_USER_IDS")
    digest_max_messages: int = Field(default=3000, validation_alias="DIGEST_MAX_MESSAGES")
    digest_chunk_chars: int = Field(
        default=32_000,
        validation_alias="DIGEST_CHUNK_CHARS",
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    @field_validator("z_ai_base_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    def parsed_digest_allowed_user_ids(self) -> set[int]:
        """Telegram numeric user ids (not @usernames, not display names)."""
        for raw in (self.digest_allowed_user_ids, self.admin_user_ids):
            ids = self._parse_csv_user_ids(raw)
            if ids:
                return ids
        return set()

    @staticmethod
    def _parse_csv_user_ids(raw: str) -> set[int]:
        raw = (raw or "").strip()
        if not raw:
            return set()
        out: set[int] = set()
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            out.add(int(part))
        return out
