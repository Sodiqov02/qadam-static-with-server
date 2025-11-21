import uvicorn
from src.api_app import app  # FastAPI application instance
from src.config import settings

# This file exposes `app` as run_server:app for process managers (e.g., Railway)

if __name__ == "__main__":
    uvicorn.run("run_server:app", host="0.0.0.0", port=settings.PORT, reload=False)
