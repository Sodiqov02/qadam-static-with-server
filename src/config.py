import os
from types import SimpleNamespace

from dotenv import load_dotenv

# stability fix: .env is optional; environment variables still work without it.
load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
QADAM_API_BASE_URL = os.getenv("QADAM_API_BASE_URL", API_BASE_URL)
PORT = int(os.getenv("PORT", "8000"))
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable not set")

DEV_ADMIN_SECRET = "dev_only_admin_secret"
UNSAFE_ADMIN_SECRETS = {"", "change_me", DEV_ADMIN_SECRET}


def _is_production_like() -> bool:
    """Detect environments where a real operator/admin secret is mandatory."""
    named_env = (
        os.getenv("APP_ENV")
        or os.getenv("ENVIRONMENT")
        or os.getenv("QADAM_ENV")
        or os.getenv("ENV")
        or ""
    ).strip().lower()
    return bool(os.getenv("RAILWAY_ENVIRONMENT")) or named_env in {"prod", "production", "staging"}


def _admin_secret_from_env() -> str:
    # Production must fail fast instead of silently accepting a known default.
    # Local development keeps a clearly named fallback so old dev commands still boot.
    raw_secret = (os.getenv("ADMIN_SECRET") or "").strip()
    if _is_production_like() and raw_secret in UNSAFE_ADMIN_SECRETS:
        raise RuntimeError("ADMIN_SECRET must be set to a strong secret in production")
    return raw_secret or DEV_ADMIN_SECRET


# Shared operator/admin secret for protected internal routes. Never log this value.
ADMIN_SECRET = _admin_secret_from_env()

# Backward-compatible settings object used by existing imports.
settings = SimpleNamespace(
    API_BASE_URL=API_BASE_URL,
    QADAM_API_BASE_URL=QADAM_API_BASE_URL,
    PORT=PORT,
    DATABASE_URL=DATABASE_URL,
    ADMIN_SECRET=ADMIN_SECRET,
)
