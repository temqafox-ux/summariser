from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tg_digest_bot.filtered_day import DayViewFilter


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
    prompt_version: str = Field(default="4", validation_alias="PROMPT_VERSION")
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
    digest_filter_max_message_chars: int = Field(
        default=400,
        validation_alias="DIGEST_FILTER_MAX_MESSAGE_CHARS",
    )
    digest_filter_min_message_chars: int = Field(
        default=1,
        validation_alias="DIGEST_FILTER_MIN_MESSAGE_CHARS",
    )
    digest_filter_max_messages_per_user: int = Field(
        default=0,
        validation_alias="DIGEST_FILTER_MAX_MESSAGES_PER_USER",
    )
    http_user_agent: str = Field(
        default="tg-digest-bot/0.1 (+https://github.com/)",
        validation_alias="HTTP_USER_AGENT",
    )
    poe2_scout_base_url: str = Field(
        default="https://poe2scout.com/api",
        validation_alias="POE2_SCOUT_BASE_URL",
    )
    poe2_scout_realm: str = Field(default="poe2", validation_alias="POE2_SCOUT_REALM")
    poe2_market_league: str = Field(
        default="",
        validation_alias="POE2_MARKET_LEAGUE",
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    @field_validator("poe2_scout_base_url", "z_ai_base_url")
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

    def day_view_filter(self) -> DayViewFilter:
        return DayViewFilter(
            max_message_chars=self.digest_filter_max_message_chars,
            min_message_chars=self.digest_filter_min_message_chars,
            max_messages_per_user=self.digest_filter_max_messages_per_user,
        )

    def digest_cache_key(self) -> str:
        """Значение для колонки digests.prompt_version: учитывает фильтр и PROMPT_VERSION."""
        flt = self.day_view_filter()
        return (
            f"fv1:{self.prompt_version}:"
            f"{flt.max_message_chars}-{flt.min_message_chars}-{flt.max_messages_per_user}"
        )
