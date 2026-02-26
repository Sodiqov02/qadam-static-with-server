import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Project-wide settings loaded from .env."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    API_BASE_URL: str = Field(default_factory=lambda: os.getenv("API_BASE_URL", ""))
    PORT: int = Field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    DATABASE_URL: str = Field(
        ...,
        description="Database URL (postgresql+psycopg://...)",
    )


settings = Settings()
