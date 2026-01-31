from pathlib import Path
from datetime import datetime
import logging
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, select

from src.models import Menu, OrderIn, OrderOut
from src.db import get_session, init_db
from src.db_models import Tenant
from src.notifier import notify_admin  # asynchronous notifier
from src.notifier import notify_order_status_changed, notify_reservation_created, notify_reservation_updated
from src.store import (
    DEFAULT_TENANT_SLUG,
    add_order,
    analytics_for_tenant,
    create_reservation,
    ensure_default_tenant,
    get_menu_for_tenant,
    get_tenant_by_slug,
    list_reservations,
    update_order_status,
    tenant_plan,
    tenant_public_features,
    tenant_has_plan,
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


class OrderStatusUpdate(BaseModel):
    status: str


class TenantPublic(BaseModel):
    name: str
    description: str | None = None
    hero_image: str | None = None
    plan: str | None = None
    features: dict | None = None


def _tenant_public(tenant):
    features = getattr(tenant, "features", {}) or {}
    description = features.get("description") if isinstance(features.get("description"), str) else None
    hero_image = features.get("hero_image") if isinstance(features.get("hero_image"), str) else None
    return TenantPublic(
        name=tenant.name,
        description=description,
        hero_image=hero_image,
        plan=tenant_plan(tenant),
        features=tenant_public_features(tenant),
    )


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


def _resolve_admin_tenant(request: Request, tenant_slug: str | None):
    slug = tenant_slug or request.headers.get("x-tenant-slug") or DEFAULT_TENANT_SLUG
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
    try:
        with get_session() as session:
            count = session.execute(select(func.count(Tenant.id))).scalar_one()
        logger.info("tenant_count=%s", count)
    except Exception:
        logger.exception("tenant_count check failed during startup")


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
    logger.info("menu_request slug=%s", getattr(default_tenant, "slug", DEFAULT_TENANT_SLUG))
    menu = get_menu_for_tenant(default_tenant)
    return Menu.model_validate(menu)


@app.get("/tenant", response_model=TenantPublic)
def get_default_tenant(default_tenant=Depends(_default_tenant_dep)):
    return _tenant_public(default_tenant)


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
    logger.info("menu_request slug=%s", slug)
    menu = get_menu_for_tenant(tenant)
    return Menu.model_validate(menu)


@app.get("/t/{slug}/tenant", response_model=TenantPublic)
def get_tenant_by_slug_public(slug: str, tenant=Depends(_tenant_dep)):
    return _tenant_public(tenant)


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


@app.get("/api/admin/analytics")
def admin_analytics(request: Request, range: str = "7d", tenant: str | None = None):
    tenant_obj = _resolve_admin_tenant(request, tenant)
    if not tenant_has_plan(tenant_obj, "standard"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Plan does not include analytics")
    try:
        return analytics_for_tenant(tenant_obj, range)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid range")


@app.patch("/api/admin/orders/{oid}/status")
async def update_order_status_api(oid: int, payload: OrderStatusUpdate):
    ok, order, _, prev, new = update_order_status(oid, payload.status, enforce_workflow=True)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    if not ok or not new:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid status transition or plan restriction")
    await notify_order_status_changed(order.id, prev, new)
    return {"ok": True, "status": new}
