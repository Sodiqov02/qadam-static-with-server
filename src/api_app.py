from pathlib import Path
from datetime import datetime, time
import logging
import shutil
import uuid
from typing import Literal
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.exc import NoResultFound
from sqlalchemy import func, select

from src.models import Menu, OrderIn, OrderOut
from src.db import get_session
from src.db_models import Tenant
from src.notifier import notify_admin
from src.notifier import notify_order_status_changed, notify_reservation_created, notify_reservation_updated
from src.store import (
    add_order,
    active_promotions_for_tenant,
    analytics_for_tenant,
    create_reorder_for_phone,
    create_promotion,
    create_reservation,
    get_menu_for_tenant,
    get_active_tenant_by_slug,
    order_history_for_phone,
    list_reservations,
    list_promotions,
    serialize_menu_item,
    serialize_promotion,
    update_menu_item_for_tenant,
    update_tenant_public_profile,
    update_order_status,
    update_promotion,
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
MY_ORDERS_FILE = WEB_DIR / "my_orders.html"
ADMIN_FILE = WEB_DIR / "admin.html"
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
UPLOADS_DIR = Path("/data/uploads")

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory="/data/uploads"), name="uploads")


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


class PromotionIn(BaseModel):
    type: str
    is_active: bool = True
    product_id: int | None = None
    discount_percent: int | None = None
    start_time: time | None = None
    end_time: time | None = None
    days_of_week: list[int] | None = None


class PromotionUpdate(BaseModel):
    type: str | None = None
    is_active: bool | None = None
    product_id: int | None = None
    discount_percent: int | None = None
    start_time: time | None = None
    end_time: time | None = None
    days_of_week: list[int] | None = None


class TenantPublic(BaseModel):
    name: str
    description: str | None = None
    hero_image: str | None = None
    plan: str | None = None
    features: dict | None = None
    bot_username: str | None = None
    bot_enabled: bool | None = None


class TenantAdminUpdate(BaseModel):
    description: str | None = None
    hero_image: str | None = None


class MenuItemAdminUpdate(BaseModel):
    name: str | None = None
    price: int | None = None
    image_url: str | None = None
    is_available: bool | None = None


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
        bot_username=getattr(tenant, "bot_username", None),
        bot_enabled=getattr(tenant, "bot_enabled", None),
    )


def _tenant_dep(slug: str):
    tenant = get_active_tenant_by_slug(slug)
    if not tenant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")
    if not tenant.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tenant inactive")
    return tenant


def _admin_tenant_dep(
    slug: str,
    tenant=Depends(_tenant_dep),
    x_admin_chat_id: str | None = Header(default=None),
):
    if not x_admin_chat_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    if not tenant.admin_chat_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access not configured")
    if str(tenant.admin_chat_id) != str(x_admin_chat_id).strip():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access denied")
    return tenant


def _uploads_url_prefix(slug: str, kind: str | None = None) -> str:
    encoded_slug = quote(slug, safe="")
    if kind:
        return f"/uploads/{encoded_slug}/{kind}/"
    return f"/uploads/{encoded_slug}/"


def _upload_dir(slug: str, kind: Literal["hero", "menu"]) -> Path:
    root = UPLOADS_DIR.resolve()
    target = (UPLOADS_DIR / slug / kind).resolve()
    if target != root and root not in target.parents:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid upload path")
    target.mkdir(parents=True, exist_ok=True)
    return target


def _is_tenant_upload_url(value: str, slug: str, *, kind: str | None = None) -> bool:
    prefix = _uploads_url_prefix(slug, kind)
    return value.startswith(prefix)


@app.on_event("startup")
def startup_checks():
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


@app.get("/t/{slug}", include_in_schema=False)
def serve_tenant_page(slug: str):
    return FileResponse(INDEX_FILE)


@app.get("/t/{slug}/my-orders", include_in_schema=False)
def serve_tenant_my_orders(slug: str):
    return FileResponse(MY_ORDERS_FILE)


@app.get("/t/{slug}/admin", include_in_schema=False)
def serve_tenant_admin(slug: str):
    return FileResponse(ADMIN_FILE)


@app.get("/my-orders", include_in_schema=False)
def serve_my_orders():
    if not MY_ORDERS_FILE.exists():
        raise HTTPException(404, "My orders page not found")
    return FileResponse(MY_ORDERS_FILE)


@app.get("/admin", include_in_schema=False)
def serve_admin():
    if not ADMIN_FILE.exists():
        raise HTTPException(404, "Admin page not found")
    return FileResponse(ADMIN_FILE)


@app.get("/t/{slug}/menu", response_model=Menu)
def get_menu_by_slug(slug: str, tenant=Depends(_tenant_dep)):
    logger.info("menu_request slug=%s", slug)
    try:
        menu = get_menu_for_tenant(tenant)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return Menu.model_validate(menu)


@app.get("/t/{slug}/tenant", response_model=TenantPublic)
def get_tenant_by_slug_public(slug: str, tenant=Depends(_tenant_dep)):
    return _tenant_public(tenant)


@app.post("/t/{slug}/api/admin/upload")
async def admin_upload_file(
    slug: str,
    upload_type: Literal["hero", "menu"] = Form(..., alias="type"),
    file: UploadFile = File(...),
    tenant=Depends(_admin_tenant_dep),
):
    content_type = (file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only image files are allowed")

    suffix = Path(file.filename or "").suffix.lower()
    if not suffix:
        inferred = content_type.split("/", 1)[1].split("+", 1)[0].strip()
        suffix = f".{inferred}" if inferred else ".img"
    if suffix == ".jpe":
        suffix = ".jpg"
    if not suffix.startswith("."):
        suffix = f".{suffix}"

    filename = f"{uuid.uuid4().hex}{suffix}"
    folder = _upload_dir(tenant.slug, upload_type)
    destination = folder / filename

    with destination.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    await file.close()

    url = f"{_uploads_url_prefix(tenant.slug, upload_type)}{filename}"
    return {"url": url}


@app.patch("/t/{slug}/api/admin/tenant", response_model=TenantPublic)
def admin_update_tenant(slug: str, payload: TenantAdminUpdate, tenant=Depends(_admin_tenant_dep)):
    update_data = payload.model_dump(exclude_unset=True)
    hero_image = update_data.get("hero_image")
    if hero_image and not _is_tenant_upload_url(hero_image, tenant.slug, kind="hero"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "hero_image must point to this tenant hero upload path")
    try:
        updated = update_tenant_public_profile(tenant, update_data)
    except NoResultFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")
    return _tenant_public(updated)


@app.patch("/t/{slug}/api/admin/menu-items/{item_id}")
def admin_update_menu_item(slug: str, item_id: int, payload: MenuItemAdminUpdate, tenant=Depends(_admin_tenant_dep)):
    update_data = payload.model_dump(exclude_unset=True)
    image_url = update_data.get("image_url")
    if image_url and not _is_tenant_upload_url(image_url, tenant.slug, kind="menu"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "image_url must point to this tenant menu upload path")
    try:
        item = update_menu_item_for_tenant(tenant, item_id, update_data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    except NoResultFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Menu item not found")
    return serialize_menu_item(item)


@app.post("/t/{slug}/orders", response_model=OrderOut)
async def create_order_by_slug(slug: str, order: OrderIn, tenant=Depends(_tenant_dep)):
    try:
        oid = add_order(order.model_dump(), tenant=tenant)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    logger.info("[TENANT=%s] Order created id=%s", slug, oid)
    try:
        await notify_admin(oid, tenant.id)
    except Exception:
        logger.exception("notify_admin_failed tenant=%s order_id=%s", slug, oid)
    return OrderOut(order_id=oid)


@app.post("/t/{slug}/reservations")
async def create_reservation_api(slug: str, reservation: ReservationIn, tenant=Depends(_tenant_dep)):
    if not tenant_has_plan(tenant, "standard"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Plan does not include reservations")
    if not tenant_has_feature(tenant, "reservations"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Feature disabled")
    rid = create_reservation(tenant, reservation.model_dump())
    await notify_reservation_created(tenant, rid)
    return {"reservation_id": rid, "status": "new"}


@app.get("/t/{slug}/reservations")
def list_reservations_api(slug: str, tenant=Depends(_tenant_dep)):
    if not tenant_has_plan(tenant, "standard"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Plan does not include reservations")
    if not tenant_has_feature(tenant, "reservations"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Feature disabled")
    return {"items": list_reservations(tenant)}


@app.patch("/t/{slug}/reservations/{rid}")
async def update_reservation_api(slug: str, rid: int, payload: ReservationUpdate, tenant=Depends(_tenant_dep)):
    if not tenant_has_plan(tenant, "standard"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Plan does not include reservations")
    if not tenant_has_feature(tenant, "reservations"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Feature disabled")
    ok = update_reservation_status(tenant, rid, payload.status)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reservation not found")
    await notify_reservation_updated(tenant, rid)
    return {"ok": True}


@app.get("/t/{slug}/api/orders/history")
def order_history(slug: str, phone: str, limit: int = 20, tenant=Depends(_tenant_dep)):
    if not tenant_has_plan(tenant, "standard"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Plan does not include order history")
    try:
        items = order_history_for_phone(tenant, phone, limit=limit)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return {"items": items}


@app.post("/t/{slug}/api/orders/{oid}/reorder")
def reorder_order(slug: str, oid: int, phone: str, tenant=Depends(_tenant_dep)):
    if not tenant_has_plan(tenant, "standard"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Plan does not include reorder")
    try:
        new_id = create_reorder_for_phone(tenant, oid, phone)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    logger.info("[TENANT=%s] Order created id=%s", slug, new_id)
    return {"order_id": new_id}


@app.get("/t/{slug}/api/promotions")
def list_active_promotions(slug: str, tenant=Depends(_tenant_dep)):
    if not tenant_has_plan(tenant, "standard"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Plan does not include promotions")
    promos = active_promotions_for_tenant(tenant)
    return {"items": [serialize_promotion(p) for p in promos]}


@app.get("/t/{slug}/api/admin/promotions")
def admin_list_promotions(slug: str, tenant=Depends(_admin_tenant_dep)):
    if not tenant_has_plan(tenant, "standard"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Plan does not include promotions")
    promos = list_promotions(tenant, include_inactive=True)
    return {"items": [serialize_promotion(p) for p in promos]}


@app.post("/t/{slug}/api/admin/promotions")
def admin_create_promotion(slug: str, payload: PromotionIn, tenant=Depends(_admin_tenant_dep)):
    if not tenant_has_plan(tenant, "standard"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Plan does not include promotions")
    try:
        promo = create_promotion(tenant, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return serialize_promotion(promo)


@app.patch("/t/{slug}/api/admin/promotions/{pid}")
def admin_update_promotion(slug: str, pid: int, payload: PromotionUpdate, tenant=Depends(_admin_tenant_dep)):
    if not tenant_has_plan(tenant, "standard"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Plan does not include promotions")
    try:
        promo = update_promotion(tenant, pid, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    except Exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Promotion not found")
    return serialize_promotion(promo)


@app.get("/t/{slug}/api/admin/analytics")
def admin_analytics(slug: str, range: str = "7d", tenant=Depends(_admin_tenant_dep)):
    if not tenant_has_plan(tenant, "standard"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Plan does not include analytics")
    try:
        return analytics_for_tenant(tenant, range)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid range")


@app.patch("/t/{slug}/api/admin/orders/{oid}/status")
async def update_order_status_api(slug: str, oid: int, payload: OrderStatusUpdate, tenant=Depends(_admin_tenant_dep)):
    ok, order, _, prev, new = update_order_status(
        oid,
        payload.status,
        tenant_id=tenant.id,
        admin_chat_id=tenant.admin_chat_id,
        enforce_workflow=True,
    )
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    if not ok or not new:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid status transition or plan restriction")
    await notify_order_status_changed(order.id, tenant.id, prev, new)
    logger.info("[TENANT=%s] Order status updated id=%s %s->%s", slug, oid, prev, new)
    return {"ok": True, "status": new}
