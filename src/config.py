from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_CHAT_ID: int
    API_BASE_URL: str = "http://127.0.0.1:8000"
    PORT: int = 8000

    class Config:
        env_file = ".env"

settings = Settings()
