import json
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.models import Menu, OrderIn, OrderOut
from src.notifier import notify_admin  # asynchronous notifier
from src.store import add_order, get_order

app = FastAPI(title="Qadam API")

MENU_PATH = Path(__file__).resolve().parents[1] / "data" / "menu.json"
WEB_DIR = Path(__file__).resolve().parents[1] / "web"
INDEX_FILE = WEB_DIR / "index.html"
STYLE_FILE = WEB_DIR / "style.css"

if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/", include_in_schema=False)
def serve_index():
    if not INDEX_FILE.exists():
        raise HTTPException(404, "Frontend not found")
    return FileResponse(INDEX_FILE)

@app.get("/style.css", include_in_schema=False)
def serve_style():
    if not STYLE_FILE.exists():
        raise HTTPException(404, "Style not found")
    return FileResponse(STYLE_FILE, media_type="text/css")

@app.get("/menu", response_model=Menu)
def get_menu():
    if not MENU_PATH.exists():
        raise HTTPException(500, "menu.json not found")
    return Menu.model_validate(json.loads(MENU_PATH.read_text(encoding="utf-8")))

@app.post("/orders", response_model=OrderOut)
async def create_order(order: OrderIn):
    oid = add_order(order.model_dump())
    # notify admin (fire-and-forget)
    try:
        await notify_admin(oid)
    except Exception:
        pass
    return OrderOut(order_id=oid)
