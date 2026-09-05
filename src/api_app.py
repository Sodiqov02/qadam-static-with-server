from pathlib import Path
import asyncio
import tempfile
from dataclasses import dataclass
from datetime import datetime, time
from collections import defaultdict, deque
from io import BytesIO
import logging
import os
import re
import secrets
import threading
import time as time_module
import uuid
from typing import Literal
from urllib.parse import quote, unquote

from alembic import command
from alembic.config import Config
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from PIL import Image, UnidentifiedImageError
from sqlalchemy.exc import NoResultFound, SQLAlchemyError
from sqlalchemy import func, select, text

from src.config import ADMIN_SECRET, settings
from src.models import Menu, OrderIn, OrderOut
from src.db import engine, get_session
from src.db_models import Tenant
from src.notifier import best_effort_notify, close_bot_cache, notify_admin
from src.notifier import notify_order_status_changed, notify_reservation_created, notify_reservation_updated
from src.store import (
    add_order,
    add_order_idempotent,
    active_promotions_for_tenant,
    analytics_for_tenant,
    bootstrap_tenant,
    checkout_fingerprint,
    cleanup_expired_auth_records,
    create_admin_session,
    create_admin_login_token_for_tenant,
    create_operator_session,
    create_category_for_tenant,
    create_menu_item_for_tenant,
    create_promotion,
    create_reservation,
    consume_admin_login_token_for_slug,
    delete_category_for_tenant,
    delete_menu_item_for_tenant,
    get_menu_admin_payload,
    get_menu_item_image_path_for_tenant,
    get_menu_for_tenant,
    get_active_tenant_by_slug,
    get_tenant_by_slug,
    get_admin_session,
    get_operator_session,
    IdempotencyConflictError,
    list_categories_for_tenant,
    list_reservations,
    list_promotions,
    menu_image_path_in_use,
    normalize_days_of_week,
    normalize_reservation_status,
    normalize_timezone_name,
    revoke_admin_session,
    revoke_operator_session,
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
ONBOARDING_FILE = WEB_DIR / "onboarding.html"
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


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


def _check_directory_writable(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=".readyz-", suffix=".tmp", dir=path, delete=True) as handle:
        handle.write(b"ok")
        handle.flush()


@app.get("/readyz")
def readyz():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
        if not UPLOADS_DIR.exists() or not UPLOADS_DIR.is_dir():
            raise OSError("upload directory is unavailable")
        _check_directory_writable(UPLOADS_DIR)
        if not MENU_IMAGES_DIR.exists() or not MENU_IMAGES_DIR.is_dir():
            raise OSError("menu image directory is unavailable")
        _check_directory_writable(MENU_IMAGES_DIR)
    except (SQLAlchemyError, OSError) as exc:
        logger.exception("readiness_failed event=readyz exception_type=%s", type(exc).__name__)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Service unavailable")
    return {"status": "ok"}


class ReservationIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=1, max_length=64)
    datetime: datetime
    guests: int = Field(default=1, gt=0, le=100)
    table_id: int | None = None

    @field_validator("name", "phone", mode="before")
    @classmethod
    def required_text(cls, value: object) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("Field must not be empty")
        return normalized

    @field_validator("datetime")
    @classmethod
    def future_datetime(cls, value: datetime) -> datetime:
        now = datetime.now(value.tzinfo) if value.tzinfo else datetime.now()
        if value <= now:
            raise ValueError("Reservation datetime must be in the future")
        return value


class ReservationUpdate(BaseModel):
    status: str = Field(min_length=1, max_length=32)

    @field_validator("status", mode="before")
    @classmethod
    def valid_status(cls, value: object) -> str:
        return normalize_reservation_status(value)


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

    @field_validator("days_of_week", mode="before")
    @classmethod
    def valid_days_of_week(cls, value: object) -> list[int] | None:
        return normalize_days_of_week(value)


class PromotionUpdate(BaseModel):
    type: str | None = None
    is_active: bool | None = None
    product_id: int | None = None
    discount_percent: int | None = None
    start_time: time | None = None
    end_time: time | None = None
    days_of_week: list[int] | None = None

    @field_validator("days_of_week", mode="before")
    @classmethod
    def valid_days_of_week(cls, value: object) -> list[int] | None:
        return normalize_days_of_week(value)


class TenantPublic(BaseModel):
    name: str
    description: str | None = None
    hero_image: str | None = None
    logo_url: str | None = None
    primary_color: str | None = None
    accent_color: str | None = None
    theme_mode: str | None = None
    plan: str | None = None
    features: dict | None = None
    bot_username: str | None = None
    bot_enabled: bool | None = None
    timezone: str = "Asia/Tashkent"


class TenantAdminUpdate(BaseModel):
    description: str | None = None
    hero_image: str | None = None
    logo_url: str | None = None
    primary_color: str | None = None
    accent_color: str | None = None
    theme_mode: str | None = None
    timezone: str | None = None

    @field_validator("timezone", mode="before")
    @classmethod
    def valid_timezone(cls, value: object) -> str | None:
        if value is None:
            return None
        return normalize_timezone_name(value)


class MenuItemAdminUpdate(BaseModel):
    name: str | None = None
    price: int | None = None
    description: str | None = None
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


class AdminLoginRequest(BaseModel):
    token: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, max_length=64)


class OperatorLoginRequest(BaseModel):
    secret: str = Field(min_length=1, max_length=255)


class OnboardingTenantRequest(BaseModel):
    slug: str
    name: str
    admin_chat_id: int
    plan: str
    bot_token: str | None = None
    bot_username: str | None = None
    enable_bot: bool = False
    initial_categories: list[str] | None = None
    timezone: str = "Asia/Tashkent"

    @field_validator("timezone", mode="before")
    @classmethod
    def valid_timezone(cls, value: object) -> str:
        return normalize_timezone_name(value)


@dataclass
class AdminAuthContext:
    tenant_id: int | None
    source: str


ADMIN_SESSION_COOKIE = "admin_session"
ADMIN_SESSION_MAX_AGE = 7 * 24 * 60 * 60
OPERATOR_SESSION_COOKIE = "operator_session"
OPERATOR_SESSION_MAX_AGE = 12 * 60 * 60
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PLACEHOLDER_TOKENS = {"<paste_token_locally>", "paste_token_locally", "<token>", "token", "your_token", "bot_token"}
VALID_PLANS = {"basic", "standard", "vip"}
BOT_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
IMAGE_SUFFIXES = {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif", "WEBP": ".webp"}
AUTH_CLEANUP_INTERVAL_SECONDS = 60 * 60


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._windows: dict[str, int] = {}
        self._lock = threading.Lock()
        self._checks_since_cleanup = 0

    def cleanup_expired(self, now: float | None = None, max_keys: int | None = None) -> int:
        current = time_module.monotonic() if now is None else now
        removed = 0
        with self._lock:
            keys = list(self._events)
            if max_keys is not None:
                keys = keys[:max_keys]
            for key in keys:
                events = self._events.get(key)
                if events is None:
                    continue
                cutoff = current - self._windows.get(key, 300)
                while events and events[0] <= cutoff:
                    events.popleft()
                if not events:
                    self._events.pop(key, None)
                    self._windows.pop(key, None)
                    removed += 1
                elif max_keys is not None:
                    self._events[key] = self._events.pop(key)
                    self._windows[key] = self._windows.pop(key)
        return removed

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = time_module.monotonic()
        cutoff = now - window_seconds
        self._checks_since_cleanup += 1
        if self._checks_since_cleanup >= 256:
            self.cleanup_expired(now=now, max_keys=256)
            self._checks_since_cleanup = 0
        with self._lock:
            events = self._events[key]
            self._windows[key] = max(window_seconds, self._windows.get(key, 0))
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests")
            events.append(now)


rate_limiter = InMemoryRateLimiter()


class AuthCleanupThrottle:
    def __init__(self, interval_seconds: float = AUTH_CLEANUP_INTERVAL_SECONDS) -> None:
        self._interval_seconds = interval_seconds
        self._next_run = 0.0
        self._lock = threading.Lock()

    def defer(self, now: float | None = None) -> None:
        current = time_module.monotonic() if now is None else now
        with self._lock:
            self._next_run = current + self._interval_seconds

    def maybe_cleanup(self, cleanup_call=None, now: float | None = None) -> bool:
        cleanup = cleanup_call or cleanup_expired_auth_records
        current = time_module.monotonic() if now is None else now
        if current < self._next_run or not self._lock.acquire(blocking=False):
            return False
        try:
            if current < self._next_run:
                return False
            self._next_run = current + self._interval_seconds
            try:
                counts = cleanup()
                if any(counts.values()):
                    logger.info("auth_cleanup counts=%s", counts)
            except SQLAlchemyError:
                logger.exception("auth_cleanup_failed")
            return True
        finally:
            self._lock.release()


auth_cleanup_throttle = AuthCleanupThrottle()


def _rate_limit(request: Request, scope: str, limit: int, window_seconds: int) -> None:
    client_host = request.client.host if request.client else "unknown"
    rate_limiter.check(f"{scope}:{client_host}", limit, window_seconds)


def _rate_limit_upload(request: Request, tenant: Tenant, admin: AdminAuthContext, scope: str) -> None:
    client_host = request.client.host if request.client else "unknown"
    admin_key = admin.tenant_id if admin.tenant_id is not None else admin.source
    rate_limiter.check(f"{scope}:tenant={tenant.id}:admin={admin_key}:ip={client_host}", 10, 300)


def _normalize_slug(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    raw = re.sub(r"[^a-z0-9-]+", "-", raw)
    raw = re.sub(r"-{2,}", "-", raw).strip("-")
    return raw[:64]


def _slug_check(value: str | None) -> dict:
    normalized = _normalize_slug(value)
    if not normalized:
        return {"normalized_slug": normalized, "available": False, "reason": "Slug is required."}
    if len(normalized) < 3:
        return {"normalized_slug": normalized, "available": False, "reason": "Slug must be at least 3 characters."}
    if not SLUG_RE.fullmatch(normalized):
        return {"normalized_slug": normalized, "available": False, "reason": "Slug can use lowercase letters, numbers and hyphens."}
    if get_tenant_by_slug(normalized):
        return {"normalized_slug": normalized, "available": False, "reason": "Slug is already taken."}
    return {"normalized_slug": normalized, "available": True, "reason": ""}


def _is_placeholder_token(value: str | None) -> bool:
    normalized = str(value or "").strip().lower()
    return not normalized or normalized in PLACEHOLDER_TOKENS or normalized.startswith("<") or normalized.endswith(">")


def require_operator(x_admin_token: str | None = Header(default=None)) -> None:
    if x_admin_token != ADMIN_SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def _set_operator_session_cookie(response: Response, session_value: str) -> None:
    api_base_url = str(getattr(settings, "API_BASE_URL", "") or "").strip().lower()
    secure_cookie = api_base_url.startswith("https://") or bool(os.getenv("RAILWAY_ENVIRONMENT"))
    response.set_cookie(
        key=OPERATOR_SESSION_COOKIE,
        value=session_value,
        max_age=OPERATOR_SESSION_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=secure_cookie,
        path="/",
    )


def _onboarding_headers(response: Response) -> None:
    response.headers["Referrer-Policy"] = "no-referrer"


def require_operator_session(request: Request) -> None:
    session_value = request.cookies.get(OPERATOR_SESSION_COOKIE)
    if not session_value or get_operator_session(session_value) is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def _public_base_url() -> str:
    base_url = str(getattr(settings, "API_BASE_URL", "") or "").strip().rstrip("/")
    if base_url.endswith("/api"):
        base_url = base_url[:-4]
    return base_url


def _absolute_or_path(path: str) -> str:
    base_url = _public_base_url()
    return f"{base_url}{path}" if base_url else path


def _tenant_public(tenant):
    features = getattr(tenant, "features", {}) or {}
    description = features.get("description") if isinstance(features.get("description"), str) else None
    hero_image = features.get("hero_image") if isinstance(features.get("hero_image"), str) else None
    return TenantPublic(
        name=tenant.name,
        description=description,
        hero_image=hero_image,
        logo_url=getattr(tenant, "logo_url", None),
        primary_color=getattr(tenant, "primary_color", None),
        accent_color=getattr(tenant, "accent_color", None),
        theme_mode=getattr(tenant, "theme_mode", None) or "default",
        plan=tenant_plan(tenant),
        features=tenant_public_features(tenant),
        bot_username=getattr(tenant, "bot_username", None),
        bot_enabled=getattr(tenant, "bot_enabled", None),
        timezone=getattr(tenant, "timezone", None) or "Asia/Tashkent",
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


def _set_admin_session_cookie(response: Response, session_token: str) -> None:
    api_base_url = str(getattr(settings, "API_BASE_URL", "") or "").strip().lower()
    secure_cookie = api_base_url.startswith("https://") or bool(os.getenv("RAILWAY_ENVIRONMENT"))
    response.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=session_token,
        max_age=ADMIN_SESSION_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=secure_cookie,
        path="/",
    )


def _clear_admin_session_cookie(response: Response) -> None:
    response.delete_cookie(key=ADMIN_SESSION_COOKIE, path="/", samesite="Lax")


def _assert_admin_access(admin: AdminAuthContext, tenant: Tenant) -> None:
    if admin.tenant_id is None:
        return
    if int(admin.tenant_id) != int(tenant.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


@app.middleware("http")
async def admin_session_middleware(request: Request, call_next):
    if (
        request.cookies.get(ADMIN_SESSION_COOKIE)
        or request.cookies.get(OPERATOR_SESSION_COOKIE)
        or request.headers.get("x-admin-token")
        or request.url.path.startswith(("/admin/auth/", "/api/onboarding/operator-"))
    ):
        auth_cleanup_throttle.maybe_cleanup()
    request.state.admin_session = None
    request.state.clear_admin_session_cookie = False
    session_token = request.cookies.get(ADMIN_SESSION_COOKIE)
    if session_token:
        admin_session = get_admin_session(session_token)
        if admin_session:
            request.state.admin_session = admin_session
        else:
            request.state.clear_admin_session_cookie = True

    response = await call_next(request)
    if getattr(request.state, "clear_admin_session_cookie", False):
        _clear_admin_session_cookie(response)
    return response


def require_admin(request: Request, x_admin_token: str | None = Header(default=None)) -> AdminAuthContext:
    admin_session = getattr(request.state, "admin_session", None)
    if admin_session is not None:
        return AdminAuthContext(tenant_id=admin_session.tenant_id, source="session")

    # Deprecated fallback for existing admin clients.
    if x_admin_token != ADMIN_SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    return AdminAuthContext(tenant_id=None, source="legacy_token")


def require_operator_or_admin(
    request: Request,
    x_admin_token: str | None = Header(default=None),
) -> AdminAuthContext:
    admin_session = getattr(request.state, "admin_session", None)
    if admin_session is not None:
        return AdminAuthContext(tenant_id=admin_session.tenant_id, source="session")

    operator_session = request.cookies.get(OPERATOR_SESSION_COOKIE)
    if operator_session and get_operator_session(operator_session) is not None:
        return AdminAuthContext(tenant_id=None, source="operator")

    if x_admin_token == ADMIN_SECRET:
        return AdminAuthContext(tenant_id=None, source="legacy_token")
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def _admin_tenant_dep(
    slug: str,
    tenant=Depends(_tenant_dep),
    admin: AdminAuthContext = Depends(require_admin),
):
    _assert_admin_access(admin, tenant)
    return tenant


def _operator_or_admin_tenant_dep(
    slug: str,
    tenant=Depends(_tenant_dep),
    admin: AdminAuthContext = Depends(require_operator_or_admin),
):
    _assert_admin_access(admin, tenant)
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


async def _validated_image(file: UploadFile) -> tuple[bytes, str]:
    data = await file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Image file is too large")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Image file is empty")
    try:
        with Image.open(BytesIO(data)) as image:
            suffix = IMAGE_SUFFIXES.get(str(image.format or "").upper())
            if not suffix:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported image format")
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Image dimensions are not allowed")
            image.verify()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid image file")
    return data, suffix


def _atomic_write(destination: Path, data: bytes) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".upload-",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError as exc:
                logger.warning(
                    "partial_upload_cleanup_failed path=%s exception_type=%s",
                    temporary_path,
                    type(exc).__name__,
                )


async def _save_menu_image_file(slug: str, file: UploadFile) -> tuple[str, str]:
    data, suffix = await _validated_image(file)
    filename = f"{uuid.uuid4().hex}{suffix}"
    folder = _menu_image_dir(slug)
    destination = folder / filename
    await asyncio.to_thread(_atomic_write, destination, data)
    image_path = f"{slug}/{filename}"
    image_url = f"{_menu_images_url_prefix(slug)}{filename}"
    return image_path, image_url


async def _save_hero_image_file(slug: str, file: UploadFile) -> str:
    data, suffix = await _validated_image(file)
    filename = f"{uuid.uuid4().hex}{suffix}"
    destination = _upload_dir(slug, "hero") / filename
    await asyncio.to_thread(_atomic_write, destination, data)
    return f"{_uploads_url_prefix(slug, 'hero')}{filename}"


def _managed_menu_image_file(image_path: str | None, slug: str) -> Path | None:
    normalized = str(image_path or "").strip().strip("/")
    parts = Path(normalized).parts
    if len(parts) != 2 or parts[0] != slug or ".." in parts:
        return None
    root = MENU_IMAGES_DIR.resolve()
    tenant_root = (root / slug).resolve()
    target = (tenant_root / parts[1]).resolve()
    if target.parent != tenant_root or root not in target.parents:
        return None
    return target


def _managed_upload_file(upload_url: str | None, slug: str, kind: str) -> Path | None:
    value = str(upload_url or "").strip()
    prefix = _uploads_url_prefix(slug, kind)
    if not value.startswith(prefix):
        return None
    filename = unquote(value[len(prefix):])
    if not filename or len(Path(filename).parts) != 1 or ".." in Path(filename).parts:
        return None
    root = UPLOADS_DIR.resolve()
    tenant_root = (root / slug / kind).resolve()
    target = (tenant_root / filename).resolve()
    if target.parent != tenant_root or root not in target.parents:
        return None
    return target


def _delete_managed_file(path: Path | None, *, event: str, tenant_slug: str) -> None:
    if path is None or not path.is_file():
        return
    try:
        path.unlink()
    except OSError as exc:
        logger.warning(
            "managed_file_delete_failed event=%s tenant=%s path=%s exception_type=%s",
            event,
            tenant_slug,
            path,
            type(exc).__name__,
        )


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
    # Demo startup migrations are for the current single-worker setup only.
    # Do not run multiple Uvicorn workers on SQLite without a separate migration review.
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
    cleanup_counts = cleanup_expired_auth_records()
    auth_cleanup_throttle.defer()
    if any(cleanup_counts.values()):
        logger.info("auth_cleanup counts=%s", cleanup_counts)
    try:
        with get_session() as session:
            count = session.execute(select(func.count(Tenant.id))).scalar_one()
        logger.info("tenant_count=%s", count)
    except SQLAlchemyError:
        logger.exception("tenant_count check failed during startup")


@app.on_event("shutdown")
async def shutdown_clients():
    await close_bot_cache()


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


@app.get("/admin/onboarding", include_in_schema=False)
def serve_onboarding(response: Response):
    if not ONBOARDING_FILE.exists():
        raise HTTPException(404, "Onboarding page not found")
    file_response = FileResponse(ONBOARDING_FILE)
    file_response.headers["Referrer-Policy"] = "no-referrer"
    return file_response


@app.post("/api/onboarding/operator-login")
def onboarding_operator_login(payload: OperatorLoginRequest, response: Response, request: Request):
    _rate_limit(request, "operator-login", 10, 300)
    if not secrets.compare_digest(str(payload.secret or ""), str(ADMIN_SECRET)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    session_value = create_operator_session()
    _set_operator_session_cookie(response, session_value)
    _onboarding_headers(response)
    return {"ok": True}


@app.post("/api/onboarding/operator-logout")
def onboarding_operator_logout(request: Request, response: Response):
    session_value = request.cookies.get(OPERATOR_SESSION_COOKIE)
    if session_value:
        revoke_operator_session(session_value)
    response.delete_cookie(key=OPERATOR_SESSION_COOKIE, path="/", samesite="Lax")
    _onboarding_headers(response)
    return {"ok": True}


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


@app.get("/api/onboarding/slug-check")
def onboarding_slug_check(response: Response, slug: str, _: None = Depends(require_operator_session)):
    _onboarding_headers(response)
    return _slug_check(slug)


@app.post("/api/onboarding/tenants")
def onboarding_create_tenant(payload: OnboardingTenantRequest, response: Response, _: None = Depends(require_operator_session)):
    _onboarding_headers(response)
    slug_result = _slug_check(payload.slug)
    normalized_slug = slug_result["normalized_slug"]
    if not slug_result["available"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, slug_result["reason"])

    name = str(payload.name or "").strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Restaurant name is required.")
    if int(payload.admin_chat_id or 0) <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Admin chat ID must be a positive number.")

    plan = str(payload.plan or "").strip().lower()
    if plan not in VALID_PLANS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Plan must be one of: basic, standard, vip.")

    bot_token = str(payload.bot_token or "").strip()
    bot_username = str(payload.bot_username or "").strip().lstrip("@") or None
    if bot_username and not BOT_USERNAME_RE.fullmatch(bot_username):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bot username is invalid.")
    enable_bot = bool(payload.enable_bot)
    if bot_token and _is_placeholder_token(bot_token):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bot token is a placeholder. Paste a real Telegram bot token or leave it empty.")
    if enable_bot and not bot_token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bot token is required when bot is enabled.")

    category_seen: set[str] = set()
    categories: list[str] = []
    for item in payload.initial_categories or []:
        title = str(item or "").strip()
        if not title:
            continue
        key = title.casefold()
        if key in category_seen:
            continue
        category_seen.add(key)
        categories.append(title)

    result = bootstrap_tenant(
        slug=normalized_slug,
        name=name,
        admin_chat_id=payload.admin_chat_id,
        bot_token=bot_token or None,
        bot_username=bot_username,
        bot_enabled=enable_bot,
        timezone_name=payload.timezone,
        features={"plan": plan, "reservations": plan in {"standard", "vip"}},
        category_titles=categories,
    )
    tenant = get_tenant_by_slug(normalized_slug)
    if tenant is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Tenant created but could not be loaded.")

    menu_login_token = create_admin_login_token_for_tenant(tenant)
    dashboard_login_token = create_admin_login_token_for_tenant(tenant)
    admin_menu_path = f"/admin/menu/{quote(normalized_slug, safe='')}?admin_token={quote(menu_login_token.token, safe='')}"
    admin_dashboard_path = f"/t/{quote(normalized_slug, safe='')}/admin?admin_token={quote(dashboard_login_token.token, safe='')}"
    public_menu_path = f"/t/{quote(normalized_slug, safe='')}"

    return {
        "public_menu_url": _absolute_or_path(public_menu_path),
        "admin_menu_url": _absolute_or_path(admin_menu_path),
        "admin_dashboard_url": _absolute_or_path(admin_dashboard_path),
        "bot_url": f"https://t.me/{bot_username}" if bot_username else None,
        "bot_enabled": bool(tenant.bot_enabled),
        "tenant": {
            "id": tenant.id,
            "slug": tenant.slug,
            "name": tenant.name,
            "admin_chat_id": tenant.admin_chat_id,
            "bot_username": tenant.bot_username,
            "plan": tenant_plan(tenant),
            "created": bool(result.get("created")),
            "categories_created": int(result.get("categories_created") or 0),
        },
    }


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


@app.post("/admin/auth/login")
def admin_auth_login(payload: AdminLoginRequest, response: Response, request: Request):
    _rate_limit(request, "admin-login", 20, 300)
    raw_token = str(payload.token or "").strip()
    normalized_slug = str(payload.slug or "").strip() or None
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")

    tenant: Tenant | None = None
    consumed_tenant_id = consume_admin_login_token_for_slug(raw_token, normalized_slug)
    if consumed_tenant_id is not None:
        with get_session() as session:
            tenant = session.execute(
                select(Tenant).where(Tenant.id == consumed_tenant_id, Tenant.is_active.is_(True))
            ).scalar_one_or_none()
        if tenant is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")
        if normalized_slug and tenant.slug != normalized_slug:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")
    elif raw_token == ADMIN_SECRET:
        if not normalized_slug:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="slug is required for legacy admin token")
        tenant = _admin_tenant_lookup(normalized_slug)

    if tenant is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired admin token")

    admin_session = create_admin_session(tenant.id)
    _set_admin_session_cookie(response, admin_session.session_token)
    return {"ok": True, "tenant_slug": tenant.slug, "expires_at": admin_session.expires_at.isoformat()}


@app.post("/admin/auth/logout")
def admin_auth_logout(request: Request, response: Response):
    session_token = request.cookies.get(ADMIN_SESSION_COOKIE)
    if session_token:
        revoke_admin_session(session_token)
    _clear_admin_session_cookie(response)
    return {"ok": True}


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
    request: Request,
    upload_type: Literal["hero", "menu"] = Form(..., alias="type"),
    file: UploadFile = File(...),
    admin: AdminAuthContext = Depends(require_admin),
    tenant=Depends(_tenant_dep),
):
    _assert_admin_access(admin, tenant)
    _rate_limit_upload(request, tenant, admin, "admin-upload")
    try:
        if upload_type == "menu":
            _, public_url = await _save_menu_image_file(tenant.slug, file)
        else:
            public_url = await _save_hero_image_file(tenant.slug, file)
    finally:
        await file.close()

    return {"url": public_url}


@app.post("/admin/upload-image/{tenant}")
async def upload_menu_image_admin(
    tenant: str,
    request: Request,
    file: UploadFile = File(...),
    admin: AdminAuthContext = Depends(require_admin),
):
    tenant_obj = _admin_tenant_lookup(tenant)
    _assert_admin_access(admin, tenant_obj)
    _rate_limit_upload(request, tenant_obj, admin, "admin-upload")
    try:
        image_path, image_url = await _save_menu_image_file(tenant_obj.slug, file)
    finally:
        await file.close()
    return {
        "image_path": image_path,
        "image": image_url,
    }


@app.patch("/t/{slug}/api/admin/tenant", response_model=TenantPublic)
def admin_update_tenant(slug: str, payload: TenantAdminUpdate, tenant=Depends(_admin_tenant_dep)):
    update_data = payload.model_dump(exclude_unset=True)
    old_hero_image = None
    if "hero_image" in update_data and isinstance(tenant.features, dict):
        old_hero_image = tenant.features.get("hero_image")
    hero_image = update_data.get("hero_image")
    if hero_image and not _is_tenant_upload_url(hero_image, tenant.slug, kind="hero"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "hero_image must point to this tenant hero upload path")
    logo_url = update_data.get("logo_url")
    if logo_url and not (
        _is_tenant_upload_url(logo_url, tenant.slug)
        or logo_url.startswith("http://")
        or logo_url.startswith("https://")
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "logo_url must be http(s) or tenant upload path")
    try:
        updated = update_tenant_public_profile(tenant, update_data)
    except NoResultFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    new_hero_image = updated.features.get("hero_image") if isinstance(updated.features, dict) else None
    if old_hero_image and old_hero_image != new_hero_image and old_hero_image != updated.logo_url:
        _delete_managed_file(
            _managed_upload_file(old_hero_image, tenant.slug, "hero"),
            event="hero_replaced",
            tenant_slug=tenant.slug,
        )
    return _tenant_public(updated)


@app.patch("/t/{slug}/api/admin/menu-items/{item_id}")
def admin_update_menu_item(slug: str, item_id: int, payload: MenuItemAdminUpdate, tenant=Depends(_admin_tenant_dep)):
    update_data = payload.model_dump(exclude_unset=True)
    old_image_path = get_menu_item_image_path_for_tenant(tenant, item_id)
    image_url = update_data.get("image_url")
    if image_url and not _is_tenant_menu_image_url(image_url, tenant.slug):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "image_url must point to this tenant menu image path")
    try:
        item = update_menu_item_for_tenant(tenant, item_id, update_data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    except NoResultFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Menu item not found")
    if old_image_path and old_image_path != item.image_path and not menu_image_path_in_use(tenant, old_image_path):
        _delete_managed_file(
            _managed_menu_image_file(old_image_path, tenant.slug),
            event="menu_image_replaced",
            tenant_slug=tenant.slug,
        )
    return serialize_menu_item(item)


@app.get("/admin/api/menu/{tenant}")
def admin_menu_get(
    tenant: str,
    include_inactive: bool = False,
    admin: AdminAuthContext = Depends(require_admin),
):
    tenant_obj = _admin_tenant_lookup(tenant)
    _assert_admin_access(admin, tenant_obj)
    return get_menu_admin_payload(tenant_obj, include_inactive=include_inactive)


@app.post("/admin/api/menu/{tenant}")
def admin_menu_create(
    tenant: str,
    payload: MenuItemAdminPayload,
    admin: AdminAuthContext = Depends(require_admin),
):
    tenant_obj = _admin_tenant_lookup(tenant)
    _assert_admin_access(admin, tenant_obj)
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
    admin: AdminAuthContext = Depends(require_admin),
):
    tenant_obj = _admin_tenant_lookup(tenant)
    _assert_admin_access(admin, tenant_obj)
    data = payload.model_dump()
    data["image_path"] = _validate_menu_image_path(data.get("image_path"), tenant_obj.slug)
    old_image_path = get_menu_item_image_path_for_tenant(tenant_obj, item_id)
    try:
        item = update_menu_item_for_tenant(tenant_obj, item_id, data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    except NoResultFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Menu item not found")
    if old_image_path and old_image_path != item.image_path and not menu_image_path_in_use(tenant_obj, old_image_path):
        _delete_managed_file(
            _managed_menu_image_file(old_image_path, tenant_obj.slug),
            event="menu_image_replaced",
            tenant_slug=tenant_obj.slug,
        )
    return serialize_menu_item(item)


@app.delete("/admin/api/menu/{tenant}/{item_id}")
def admin_menu_delete(
    tenant: str,
    item_id: int,
    admin: AdminAuthContext = Depends(require_admin),
):
    tenant_obj = _admin_tenant_lookup(tenant)
    _assert_admin_access(admin, tenant_obj)
    old_image_path = get_menu_item_image_path_for_tenant(tenant_obj, item_id)
    ok = delete_menu_item_for_tenant(tenant_obj, item_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Menu item not found")
    if old_image_path and not menu_image_path_in_use(tenant_obj, old_image_path):
        _delete_managed_file(
            _managed_menu_image_file(old_image_path, tenant_obj.slug),
            event="menu_item_deleted",
            tenant_slug=tenant_obj.slug,
        )
    return {"ok": True}


@app.post("/t/{slug}/orders", response_model=OrderOut)
async def create_order_by_slug(
    slug: str,
    order: OrderIn,
    request: Request,
    background_tasks: BackgroundTasks,
    x_internal_token: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    tenant=Depends(_tenant_dep),
):
    _rate_limit(request, f"create-order:{slug}", 30, 60)
    order_data = order.model_dump()
    trusted_bot_request = bool(x_internal_token) and secrets.compare_digest(x_internal_token, ADMIN_SECRET)
    order_data["source"] = "bot" if trusted_bot_request else "site"
    if not trusted_bot_request:
        order_data["customer_chat_id"] = None
    normalized_key = idempotency_key.strip() if isinstance(idempotency_key, str) else None
    normalized_key = normalized_key or None
    if normalized_key is not None and len(normalized_key) > 255:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Idempotency-Key must not exceed 255 characters")
    try:
        if normalized_key is None:
            oid = add_order(order_data, tenant=tenant)
            created = True
        else:
            oid, created = add_order_idempotent(
                order_data,
                tenant=tenant,
                key=normalized_key,
                fingerprint=checkout_fingerprint(order_data),
            )
    except IdempotencyConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if created:
        logger.info("[TENANT=%s] Order created id=%s", slug, oid)
        background_tasks.add_task(
            best_effort_notify,
            lambda: notify_admin(oid, tenant.id),
            event="order_created",
            tenant_id=tenant.id,
            tenant_slug=slug,
            order_id=oid,
        )
    return OrderOut(order_id=oid)


@app.post("/t/{slug}/reservations")
async def create_reservation_api(
    slug: str,
    reservation: ReservationIn,
    request: Request,
    background_tasks: BackgroundTasks,
    tenant=Depends(_tenant_dep),
):
    _rate_limit(request, f"create-reservation:{slug}", 15, 60)
    if not tenant_has_plan(tenant, "standard"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Plan does not include reservations")
    if not tenant_has_feature(tenant, "reservations"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Feature disabled")
    try:
        rid = create_reservation(tenant, reservation.model_dump())
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    background_tasks.add_task(
        best_effort_notify,
        lambda: notify_reservation_created(tenant, rid),
        event="reservation_created",
        tenant_id=tenant.id,
        tenant_slug=slug,
        reservation_id=rid,
    )
    return {"reservation_id": rid, "status": "new"}


@app.get("/t/{slug}/reservations")
def list_reservations_api(slug: str, tenant=Depends(_operator_or_admin_tenant_dep)):
    if not tenant_has_plan(tenant, "standard"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Plan does not include reservations")
    if not tenant_has_feature(tenant, "reservations"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Feature disabled")
    return {"items": list_reservations(tenant)}


@app.patch("/t/{slug}/reservations/{rid}")
async def update_reservation_api(
    slug: str,
    rid: int,
    payload: ReservationUpdate,
    tenant=Depends(_operator_or_admin_tenant_dep),
):
    if not tenant_has_plan(tenant, "standard"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Plan does not include reservations")
    if not tenant_has_feature(tenant, "reservations"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Feature disabled")
    ok = update_reservation_status(tenant, rid, payload.status)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reservation not found")
    await best_effort_notify(
        lambda: notify_reservation_updated(tenant, rid),
        event="reservation_updated",
        tenant_id=tenant.id,
        tenant_slug=slug,
        reservation_id=rid,
    )
    return {"ok": True}


@app.get("/t/{slug}/api/orders/history")
def order_history(slug: str, request: Request, phone: str, limit: int = 20, tenant=Depends(_tenant_dep)):
    _rate_limit(request, f"order-history:{slug}", 10, 60)
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Order history is unavailable until phone ownership verification is implemented",
    )


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
    await best_effort_notify(
        lambda: notify_order_status_changed(order.id, tenant.id, prev, new),
        event="order_status_changed",
        tenant_id=tenant.id,
        tenant_slug=slug,
        order_id=order.id,
    )
    logger.info("[TENANT=%s] Order status updated id=%s %s->%s", slug, oid, prev, new)
    return {"ok": True, "status": new}
