import uvicorn
from src.config import settings

# replaced old Flask run with FastAPI uvicorn runner

if __name__ == "__main__":
    # Run FastAPI app via uvicorn
    uvicorn.run("src.api_app:app", host="0.0.0.0", port=settings.PORT, reload=False)