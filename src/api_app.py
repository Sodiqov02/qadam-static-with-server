from pathlib import Path
from datetime import datetime, time
import logging
import os
import shutil
import uuid
from typing import Literal
from urllib.parse import quote

from alembic import command
from alembic.config import Config
from aiogram.exceptions import TelegramAPIError
from aiogram.utils.token import TokenValidationError
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.exc import NoResultFound, SQLAlchemyError
from sqlalchemy import func, select

from src.config import ADMIN_SECRET, settings
from src.models import Menu, OrderIn, OrderOut
from src.db import get_session
from src.db_models import Tenant
from src.notifier import notify_admin
from src.notifier import notify_order_status_changed, notify_reservation_created, notify_reservation_updated
from src.store import (
    add_order,
    active_promotions_for_tenant,
    analytics_for_tenant,
    create_category_for_tenant,
    create_menu_item_for_tenant,
    create_reorder_for_phone,
    create_promotion,
    create_reservation,
    delete_category_for_tenant,
    delete_menu_item_for_tenant,
    get_menu_admin_payload,
    get_menu_for_tenant,
    get_active_tenant_by_slug,
    list_categories_for_tenant,
    order_history_for_phone,
    list_reservations,
    list_promotions,
    serialize_menu_item,
    serialize_promotion,
    update_category_for_tenant,
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
ADMIN_MENU_FILE = WEB_DIR / "admin_menu.html"
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", "/data/uploads"))
MENU_IMAGES_DIR = Path(os.getenv("MENU_IMAGES_DIR", "/data/menu_images"))
try:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    # stability fix: local/dev fallback when /data is unavailable.
    UPLOADS_DIR = Path(__file__).resolve().parents[1] / "data" / "uploads"
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    logger.warning("uploads_dir_fallback path=%s", UPLOADS_DIR)
try:
    MENU_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    MENU_IMAGES_DIR = Path(__file__).resolve().parents[1] / "data" / "menu_images"
    MENU_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    logger.warning("menu_images_dir_fallback path=%s", MENU_IMAGES_DIR)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
app.mount("/menu-images", StaticFiles(directory=str(MENU_IMAGES_DIR)), name="menu-images")


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


class MenuItemAdminPayload(BaseModel):
    name: str
    price: int
    category_id: int
    image_path: str | None = None
    description: str | None = None
    is_available: bool = True


class CategoryPayload(BaseModel):
    title: str
    sort_order: int | None = None


class CategoryUpdatePayload(BaseModel):
    title: str | None = None
    sort_order: int | None = None


class CategoryOut(BaseModel):
    id: int
    title: str
    sort: int
    sort_order: int
    items_count: int = 0


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


def _admin_tenant_lookup(slug: str) -> Tenant:
    tenant = get_active_tenant_by_slug(slug)
    if not tenant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")
    if not tenant.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tenant inactive")
    return tenant


def require_admin(x_admin_token: str | None = Header(default=None)):
    # security fix
    if x_admin_token != ADMIN_SECRET:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


def _admin_tenant_dep(
    slug: str,
    tenant=Depends(_tenant_dep),
    _=Depends(require_admin),
):
    return tenant


def _uploads_url_prefix(slug: str, kind: str | None = None) -> str:
    encoded_slug = quote(slug, safe="")
    if kind:
        return f"/uploads/{encoded_slug}/{kind}/"
    return f"/uploads/{encoded_slug}/"


def _menu_images_url_prefix(slug: str) -> str:
    encoded_slug = quote(slug, safe="")
    return f"/menu-images/{encoded_slug}/"


def _upload_dir(slug: str, kind: Literal["hero"]) -> Path:
    root = UPLOADS_DIR.resolve()
    target = (UPLOADS_DIR / slug / kind).resolve()
    if target != root and root not in target.parents:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid upload path")
    target.mkdir(parents=True, exist_ok=True)
    return target


def _menu_image_dir(slug: str) -> Path:
    root = MENU_IMAGES_DIR.resolve()
    target = (MENU_IMAGES_DIR / slug).resolve()
    if target != root and root not in target.parents:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid menu image path")
    target.mkdir(parents=True, exist_ok=True)
    return target


def _is_tenant_upload_url(value: str, slug: str, *, kind: str | None = None) -> bool:
    prefix = _uploads_url_prefix(slug, kind)
    return value.startswith(prefix)


def _is_tenant_menu_image_url(value: str, slug: str) -> bool:
    prefix = _menu_images_url_prefix(slug)
    legacy_prefix = _uploads_url_prefix(slug, "menu")
    return value.startswith(prefix) or value.startswith(legacy_prefix)


def _save_menu_image_file(slug: str, file: UploadFile) -> tuple[str, str]:
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
    folder = _menu_image_dir(slug)
    destination = folder / filename
    with destination.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    image_path = f"{slug}/{filename}"
    image_url = f"{_menu_images_url_prefix(slug)}{filename}"
    return image_path, image_url


def _validate_menu_image_path(image_path: str | None, slug: str) -> str | None:
    if not image_path:
        return None
    normalized = str(image_path).strip().strip("/")
    if not normalized:
        return None
    if not normalized.startswith(f"{slug}/"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "image_path must point to this tenant menu image path")
    if ".." in Path(normalized).parts:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "image_path contains invalid path segments")
    return normalized


def run_migrations() -> None:
    alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    alembic_dir = Path(__file__).resolve().parents[1] / "alembic"
    config = Config(str(alembic_ini))
    config.set_main_option("script_location", str(alembic_dir))
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    logger.info("running_migrations target=head")
    command.upgrade(config, "head")


@app.on_event("startup")
async def startup_checks():
    run_migrations()
    try:
        with get_session() as session:
            count = session.execute(select(func.count(Tenant.id))).scalar_one()
        logger.info("tenant_count=%s", count)
    except SQLAlchemyError:
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


@app.get("/admin/menu/{tenant_slug}", include_in_schema=False)
def serve_admin_menu(tenant_slug: str):
    if not ADMIN_MENU_FILE.exists():
        raise HTTPException(404, "Admin menu page not found")
    return FileResponse(ADMIN_MENU_FILE)


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


@app.get("/t/{slug}/categories")
def get_categories_by_slug(slug: str, tenant=Depends(_tenant_dep)):
    return {"items": list_categories_for_tenant(tenant)}


@app.post("/t/{slug}/categories", response_model=CategoryOut)
def create_category_api(slug: str, payload: CategoryPayload, tenant=Depends(_admin_tenant_dep)):
    try:
        category = create_category_for_tenant(tenant, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    category_payload = next((item for item in list_categories_for_tenant(tenant) if item["id"] == category.id), None)
    if not category_payload:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Category created but could not be loaded")
    return category_payload


@app.patch("/t/{slug}/categories/{category_id}", response_model=CategoryOut)
def update_category_api(
    slug: str,
    category_id: int,
    payload: CategoryUpdatePayload,
    tenant=Depends(_admin_tenant_dep),
):
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No category fields provided")
    try:
        category = update_category_for_tenant(tenant, category_id, update_data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    except NoResultFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    category_payload = next((item for item in list_categories_for_tenant(tenant) if item["id"] == category.id), None)
    if not category_payload:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Category updated but could not be loaded")
    return category_payload


@app.delete("/t/{slug}/categories/{category_id}")
def delete_category_api(slug: str, category_id: int, tenant=Depends(_admin_tenant_dep)):
    ok, reason = delete_category_for_tenant(tenant, category_id)
    if reason == "not_found":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    if reason == "has_items":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Category contains menu items")
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Category could not be deleted")
    return {"ok": True}


@app.post("/t/{slug}/api/admin/upload")
async def admin_upload_file(
    slug: str,
    upload_type: Literal["hero", "menu"] = Form(..., alias="type"),
    file: UploadFile = File(...),
    tenant=Depends(_admin_tenant_dep),
):
    if upload_type == "menu":
        _, public_url = _save_menu_image_file(tenant.slug, file)
    else:
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
        folder = _upload_dir(tenant.slug, "hero")
        public_url = f"{_uploads_url_prefix(tenant.slug, 'hero')}{filename}"
        destination = folder / filename

        with destination.open("wb") as out:
            shutil.copyfileobj(file.file, out)
    await file.close()

    return {"url": public_url}


@app.post("/admin/upload-image/{tenant}")
async def upload_menu_image_admin(
    tenant: str,
    file: UploadFile = File(...),
    _=Depends(require_admin),
):
    tenant_obj = _admin_tenant_lookup(tenant)
    image_path, image_url = _save_menu_image_file(tenant_obj.slug, file)
    await file.close()
    return {
        "image_path": image_path,
        "image": image_url,
    }


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
    if image_url and not _is_tenant_menu_image_url(image_url, tenant.slug):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "image_url must point to this tenant menu image path")
    try:
        item = update_menu_item_for_tenant(tenant, item_id, update_data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    except NoResultFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Menu item not found")
    return serialize_menu_item(item)


@app.get("/admin/api/menu/{tenant}")
def admin_menu_get(
    tenant: str,
    include_inactive: bool = False,
    _=Depends(require_admin),
):
    tenant_obj = _admin_tenant_lookup(tenant)
    return get_menu_admin_payload(tenant_obj, include_inactive=include_inactive)


@app.post("/admin/api/menu/{tenant}")
def admin_menu_create(
    tenant: str,
    payload: MenuItemAdminPayload,
    _=Depends(require_admin),
):
    tenant_obj = _admin_tenant_lookup(tenant)
    data = payload.model_dump()
    data["image_path"] = _validate_menu_image_path(data.get("image_path"), tenant_obj.slug)
    try:
        item = create_menu_item_for_tenant(tenant_obj, data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return serialize_menu_item(item)


@app.put("/admin/api/menu/{tenant}/{item_id}")
def admin_menu_update(
    tenant: str,
    item_id: int,
    payload: MenuItemAdminPayload,
    _=Depends(require_admin),
):
    tenant_obj = _admin_tenant_lookup(tenant)
    data = payload.model_dump()
    data["image_path"] = _validate_menu_image_path(data.get("image_path"), tenant_obj.slug)
    try:
        item = update_menu_item_for_tenant(tenant_obj, item_id, data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    except NoResultFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Menu item not found")
    return serialize_menu_item(item)


@app.delete("/admin/api/menu/{tenant}/{item_id}")
def admin_menu_delete(
    tenant: str,
    item_id: int,
    _=Depends(require_admin),
):
    tenant_obj = _admin_tenant_lookup(tenant)
    ok = delete_menu_item_for_tenant(tenant_obj, item_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Menu item not found")
    return {"ok": True}


@app.post("/t/{slug}/orders", response_model=OrderOut)
async def create_order_by_slug(slug: str, order: OrderIn, tenant=Depends(_tenant_dep)):
    try:
        oid = add_order(order.model_dump(), tenant=tenant)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    logger.info("[TENANT=%s] Order created id=%s", slug, oid)
    try:
        await notify_admin(oid, tenant.id)
    except (TelegramAPIError, TokenValidationError, ValueError):
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
    except NoResultFound:
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
