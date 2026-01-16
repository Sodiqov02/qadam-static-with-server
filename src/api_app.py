from pathlib import Path
from datetime import datetime
import logging
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.models import Menu, OrderIn, OrderOut
from src.db import init_db
from src.notifier import notify_admin  # asynchronous notifier
from src.notifier import notify_reservation_created, notify_reservation_updated
from src.store import (
    DEFAULT_TENANT_SLUG,
    add_order,
    create_reservation,
    ensure_default_tenant,
    get_menu_for_tenant,
    get_tenant_by_slug,
    list_reservations,
    tenant_has_feature,
    update_reservation_status,
)

app = FastAPI(title="Qadam API")
logger = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parents[1] / "web"
INDEX_FILE = WEB_DIR / "index.html"
STYLE_FILE = WEB_DIR / "style.css"
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class ReservationIn(BaseModel):
    name: str
    phone: str
    datetime: datetime
    guests: int = 1
    table_id: int | None = None


class ReservationUpdate(BaseModel):
    status: str


def _default_tenant_dep():
    tenant = get_tenant_by_slug(DEFAULT_TENANT_SLUG)
    if not tenant:
        tenant = ensure_default_tenant()
    if not tenant.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tenant inactive")
    return tenant


def _tenant_dep(slug: str):
    tenant = get_tenant_by_slug(slug)
    if not tenant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")
    if not tenant.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tenant inactive")
    return tenant


@app.on_event("startup")
def ensure_default():
    try:
        init_db()
    except Exception:
        logger.exception("init_db failed during startup")
    try:
        ensure_default_tenant()
    except Exception:
        logger.exception("ensure_default_tenant failed during startup")


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
def get_menu(default_tenant=Depends(_default_tenant_dep)):
    menu = get_menu_for_tenant(default_tenant)
    return Menu.model_validate(menu)


@app.post("/orders", response_model=OrderOut)
async def create_order(order: OrderIn, default_tenant=Depends(_default_tenant_dep)):
    oid = add_order(order.model_dump(), tenant=default_tenant)
    try:
        await notify_admin(oid)
    except Exception:
        pass
    return OrderOut(order_id=oid)


@app.get("/t/{slug}/menu", response_model=Menu)
def get_menu_by_slug(slug: str, tenant=Depends(_tenant_dep)):
    menu = get_menu_for_tenant(tenant)
    return Menu.model_validate(menu)


@app.post("/t/{slug}/orders", response_model=OrderOut)
async def create_order_by_slug(order: OrderIn, tenant=Depends(_tenant_dep)):
    oid = add_order(order.model_dump(), tenant=tenant)
    try:
        await notify_admin(oid)
    except Exception:
        pass
    return OrderOut(order_id=oid)


@app.post("/t/{slug}/reservations")
async def create_reservation_api(slug: str, reservation: ReservationIn, tenant=Depends(_tenant_dep)):
    if not tenant_has_feature(tenant, "reservations"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Feature disabled")
    rid = create_reservation(tenant, reservation.model_dump())
    await notify_reservation_created(tenant, rid)
    return {"reservation_id": rid, "status": "new"}


@app.get("/t/{slug}/reservations")
def list_reservations_api(slug: str, tenant=Depends(_tenant_dep)):
    if not tenant_has_feature(tenant, "reservations"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Feature disabled")
    return {"items": list_reservations(tenant)}


@app.patch("/t/{slug}/reservations/{rid}")
async def update_reservation_api(slug: str, rid: int, payload: ReservationUpdate, tenant=Depends(_tenant_dep)):
    if not tenant_has_feature(tenant, "reservations"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Feature disabled")
    ok = update_reservation_status(tenant, rid, payload.status)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reservation not found")
    if ok:
        await notify_reservation_updated(tenant, rid)
    return {"ok": True}
