import os
from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Project-wide settings loaded from .env."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    BOT_TOKEN: Optional[str] = Field(default=None, description="Bot token from @BotFather")
    BOT_USERNAME: str = Field(default="", description="Optional bot username")
    ADMIN_CHAT_ID: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("ADMIN_CHAT_ID", "ADMIN_ID"),
        description="Admin chat ID",
    )
    API_BASE_URL: str = Field(default_factory=lambda: os.getenv("API_BASE_URL", ""))
    PORT: int = Field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    DATABASE_URL: str = Field(
        ...,
        description="Database URL (postgresql+psycopg://...)",
    )


settings = Settings()
