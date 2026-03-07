import os
from types import SimpleNamespace

from dotenv import load_dotenv

# stability fix: .env is optional; environment variables still work without it.
load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL", "")
PORT = int(os.getenv("PORT", "8000"))
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable not set")

# security fix: shared admin token for protected admin API routes.
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "change_me")

# Backward-compatible settings object used by existing imports.
settings = SimpleNamespace(
    API_BASE_URL=API_BASE_URL,
    PORT=PORT,
    DATABASE_URL=DATABASE_URL,
    ADMIN_SECRET=ADMIN_SECRET,
)
