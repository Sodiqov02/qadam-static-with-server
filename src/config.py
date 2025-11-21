import os
from pydantic import AliasChoices, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Project-wide settings loaded from .env."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    BOT_TOKEN: str = Field(..., description="Bot token from @BotFather")
    BOT_USERNAME: str = Field(default="", description="Optional bot username")
    ADMIN_CHAT_ID: int = Field(
        ...,
        validation_alias=AliasChoices("ADMIN_CHAT_ID", "ADMIN_ID"),
        description="Admin chat ID",
    )
    API_BASE_URL: str = Field(default_factory=lambda: os.getenv("API_BASE_URL", ""))
    PORT: int = Field(default_factory=lambda: int(os.getenv("PORT", "8000")))


try:
    settings = Settings()
except ValidationError as e:
    print("Settings error: missing/invalid env vars.")
    print("Ensure BOT_TOKEN and ADMIN_CHAT_ID (or ADMIN_ID) are set in .env")
    raise
