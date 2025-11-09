import json
from pathlib import Path
from fastapi import FastAPI, HTTPException
from src.models import Menu, OrderIn, OrderOut
from src.store import add_order, get_order
from src.notifier import notify_admin  # asynchronous notifier

app = FastAPI(title="Qadam API")

MENU_PATH = Path(__file__).resolve().parents[1] / "data" / "menu.json"

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
