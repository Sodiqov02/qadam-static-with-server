from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple
import logging

from sqlalchemy import select, update
from sqlalchemy.exc import NoResultFound

from src.db import get_session
from src.db_models import (
    BotUser,
    MenuCategory,
    MenuItem,
    Order,
    Promotion,
    Reservation,
    Tenant,
)

PLAN_ORDER = {"basic": 0, "standard": 1, "vip": 2}
ORDER_STATUSES = ("NEW", "ACCEPTED", "COOKING", "READY", "COMPLETED", "CANCELED")
COMPLETED_STATUSES = {"COMPLETED", "DONE", "APPROVED"}
PROMOTION_TYPES = {"item_of_the_day", "happy_hours"}
LEGACY_STATUS_MAP = {
    "new": "NEW",
    "approved": "ACCEPTED",
    "accept": "ACCEPTED",
    "accepted": "ACCEPTED",
    "cooking": "COOKING",
    "ready": "READY",
    "done": "COMPLETED",
    "completed": "COMPLETED",
    "rejected": "CANCELED",
    "canceled": "CANCELED",
    "cancelled": "CANCELED",
}
STATUS_TRANSITIONS = {
    "NEW": {"ACCEPTED", "CANCELED"},
    "ACCEPTED": {"COOKING", "CANCELED"},
    "COOKING": {"READY"},
    "READY": {"COMPLETED"},
    "COMPLETED": set(),
    "CANCELED": set(),
}
logger = logging.getLogger(__name__)


def get_tenant_by_slug(slug: str) -> Optional[Tenant]:
    with get_session() as session:
        return session.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none()


def get_active_tenant_by_slug(slug: str) -> Optional[Tenant]:
    with get_session() as session:
        return (
            session.execute(select(Tenant).where(Tenant.slug == slug, Tenant.is_active.is_(True)))
            .scalar_one_or_none()
        )


def get_tenant_by_bot_token(token: str) -> Optional[Tenant]:
    if not token:
        return None
    with get_session() as session:
        return (
            session.execute(select(Tenant).where(Tenant.bot_token == token, Tenant.bot_enabled.is_(True)))
            .scalar_one_or_none()
        )


def list_enabled_bot_tenants() -> List[Tenant]:
    with get_session() as session:
        return (
            session.execute(
                select(Tenant).where(Tenant.bot_enabled.is_(True), Tenant.bot_token.is_not(None))
            )
            .scalars()
            .all()
        )


def bootstrap_tenant(
    *,
    slug: str,
    name: str,
    admin_chat_id: int | None,
    bot_token: str | None,
    bot_username: str | None,
    bot_enabled: bool,
    features: Dict[str, Any] | None = None,
    category_titles: Iterable[str] | None = None,
) -> Dict[str, Any]:
    feature_flags = features or {}
    normalized_categories = [x.strip() for x in (category_titles or []) if isinstance(x, str) and x.strip()]
    if not normalized_categories:
        normalized_categories = ["Main"]

    with get_session() as session:
        tenant = session.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none()
        created = tenant is None
        if tenant is None:
            tenant = Tenant(
                slug=slug,
                name=name,
                admin_chat_id=admin_chat_id,
                bot_token=bot_token,
                bot_username=bot_username,
                bot_enabled=bot_enabled,
                features=feature_flags,
                is_active=True,
            )
            session.add(tenant)
            session.flush()
        else:
            tenant.name = name or tenant.name
            tenant.admin_chat_id = admin_chat_id
            if bot_token is not None:
                tenant.bot_token = bot_token
            if bot_username is not None:
                tenant.bot_username = bot_username
            tenant.bot_enabled = bot_enabled
            merged_features: Dict[str, Any] = {}
            if isinstance(tenant.features, dict):
                merged_features.update(tenant.features)
            merged_features.update(feature_flags)
            tenant.features = merged_features
            tenant.is_active = True
            session.flush()

        existing_titles = {
            row[0]
            for row in session.execute(
                select(MenuCategory.title).where(MenuCategory.tenant_id == tenant.id)
            ).all()
        }
        categories_created = 0
        next_sort = session.execute(
            select(MenuCategory.sort)
            .where(MenuCategory.tenant_id == tenant.id)
            .order_by(MenuCategory.sort.desc(), MenuCategory.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        sort_value = int(next_sort or -1) + 1
        for title in normalized_categories:
            if title in existing_titles:
                continue
            session.add(
                MenuCategory(
                    tenant_id=tenant.id,
                    title=title,
                    sort=sort_value,
                )
            )
            sort_value += 1
            categories_created += 1

        session.flush()
        return {
            "tenant_id": tenant.id,
            "slug": tenant.slug,
            "created": created,
            "categories_created": categories_created,
        }


def _menu_from_db(tenant_id: int) -> List[Dict[str, Any]]:
    with get_session() as session:
        categories = session.execute(
            select(MenuCategory).where(MenuCategory.tenant_id == tenant_id).order_by(MenuCategory.sort, MenuCategory.id)
        ).scalars().all()
        if not categories:
            return []
        items = session.execute(
            select(MenuItem).where(MenuItem.tenant_id == tenant_id, MenuItem.is_active.is_(True))
        ).scalars().all()
        items_by_cat: Dict[int, List[MenuItem]] = {}
        for item in items:
            items_by_cat.setdefault(item.category_id, []).append(item)
        result = []
        for cat in categories:
            cat_items = sorted(items_by_cat.get(cat.id, []), key=lambda x: (x.sort, x.id))
            result.append(
                {
                    "id": str(cat.id),
                    "title": cat.title,
                    "items": [
                        {
                            "id": str(it.id),
                            "name": it.title,
                            "price": int(it.price or 0),
                            "description": it.description or "",
                        }
                        for it in cat_items
                    ],
                }
            )
        return result


def get_menu_for_tenant(tenant: Tenant) -> dict:
    menu_from_db = _menu_from_db(tenant.id)
    if not menu_from_db:
        raise ValueError("Menu is not configured for tenant")
    return {"categories": menu_from_db}


def _price_lookup(tenant: Tenant) -> Dict[str, Dict[str, Any]]:
    menu = get_menu_for_tenant(tenant)
    mapping: Dict[str, Dict[str, Any]] = {}
    for cat in menu.get("categories", []):
        for it in cat.get("items", []):
            mapping[str(it.get("id"))] = {
                "name": it.get("name", ""),
                "price": int(it.get("price") or 0),
            }
    return mapping


def _time_in_window(now_time, start_time, end_time) -> bool:
    if not start_time or not end_time:
        return True
    if end_time >= start_time:
        return start_time <= now_time <= end_time
    return now_time >= start_time or now_time <= end_time


def list_promotions(tenant: Tenant, include_inactive: bool = False) -> List[Promotion]:
    with get_session() as session:
        query = select(Promotion).where(Promotion.tenant_id == tenant.id)
        if not include_inactive:
            query = query.where(Promotion.is_active.is_(True))
        return session.execute(query.order_by(Promotion.created_at.desc())).scalars().all()


def serialize_promotion(promo: Promotion) -> Dict[str, Any]:
    return {
        "id": promo.id,
        "type": promo.type,
        "is_active": promo.is_active,
        "product_id": promo.product_id,
        "discount_percent": promo.discount_percent,
        "start_time": promo.start_time.isoformat() if promo.start_time else None,
        "end_time": promo.end_time.isoformat() if promo.end_time else None,
        "days_of_week": promo.days_of_week,
    }


def active_promotions_for_tenant(tenant: Tenant) -> List[Promotion]:
    now = datetime.utcnow()
    weekday = now.weekday()
    now_time = now.time()
    promos = list_promotions(tenant, include_inactive=False)
    active = []
    for promo in promos:
        if promo.type == "happy_hours":
            days = promo.days_of_week or []
            if isinstance(days, list) and days and weekday not in days:
                continue
            if not _time_in_window(now_time, promo.start_time, promo.end_time):
                continue
        active.append(promo)
    return active


def create_promotion(tenant: Tenant, payload: Dict[str, Any]) -> Promotion:
    promo_type = str(payload.get("type") or "").strip().lower()
    if promo_type not in PROMOTION_TYPES:
        raise ValueError("Invalid promotion type")
    discount = payload.get("discount_percent")
    if discount is not None:
        discount = int(discount)
        if discount < 0 or discount > 100:
            raise ValueError("Invalid discount percent")
    days = payload.get("days_of_week")
    if days is not None and not isinstance(days, list):
        raise ValueError("days_of_week must be list")
    promo = Promotion(
        tenant_id=tenant.id,
        type=promo_type,
        is_active=bool(payload.get("is_active", True)),
        product_id=payload.get("product_id"),
        discount_percent=discount,
        start_time=payload.get("start_time"),
        end_time=payload.get("end_time"),
        days_of_week=days,
    )
    with get_session() as session:
        session.add(promo)
        session.flush()
        session.refresh(promo)
    return promo


def update_promotion(tenant: Tenant, promo_id: int, payload: Dict[str, Any]) -> Promotion:
    with get_session() as session:
        promo = (
            session.execute(
                select(Promotion).where(Promotion.tenant_id == tenant.id, Promotion.id == promo_id)
            )
            .scalars()
            .first()
        )
        if not promo:
            raise NoResultFound()
        if "type" in payload:
            promo_type = str(payload.get("type") or "").strip().lower()
            if promo_type not in PROMOTION_TYPES:
                raise ValueError("Invalid promotion type")
            promo.type = promo_type
        if "is_active" in payload:
            promo.is_active = bool(payload.get("is_active"))
        if "product_id" in payload:
            promo.product_id = payload.get("product_id")
        if "discount_percent" in payload:
            discount = payload.get("discount_percent")
            if discount is not None:
                discount = int(discount)
                if discount < 0 or discount > 100:
                    raise ValueError("Invalid discount percent")
            promo.discount_percent = discount
        if "start_time" in payload:
            promo.start_time = payload.get("start_time")
        if "end_time" in payload:
            promo.end_time = payload.get("end_time")
        if "days_of_week" in payload:
            days = payload.get("days_of_week")
            if days is not None and not isinstance(days, list):
                raise ValueError("days_of_week must be list")
            promo.days_of_week = days
        session.flush()
        session.refresh(promo)
        return promo


def _apply_promotions(tenant: Tenant, subtotal: Decimal) -> Tuple[Decimal, List[Dict[str, Any]]]:
    if not tenant_has_plan(tenant, "standard"):
        return subtotal, []
    promos = active_promotions_for_tenant(tenant)
    applied: List[Dict[str, Any]] = []
    discount_percent = 0
    for promo in promos:
        if promo.type == "happy_hours" and promo.discount_percent:
            discount_percent = max(discount_percent, int(promo.discount_percent))
            applied.append(
                {"id": promo.id, "type": promo.type, "discount_percent": int(promo.discount_percent)}
            )
        elif promo.type == "item_of_the_day":
            applied.append({"id": promo.id, "type": promo.type, "product_id": promo.product_id})

    if discount_percent <= 0:
        return subtotal, applied
    discount_total = (subtotal * Decimal(discount_percent) / Decimal(100)).quantize(Decimal("0.01"))
    return (subtotal - discount_total).quantize(Decimal("0.01")), applied


def add_order(data: Dict[str, Any], tenant: Tenant) -> int:
    price_map = _price_lookup(tenant)
    subtotal = Decimal(0)
    items_payload = []
    unknown_items: List[str] = []
    for it in data.get("items", []):
        qty = int(it.get("qty") or 0)
        item_id = str(it.get("item_id"))
        if qty <= 0:
            raise ValueError("Item qty must be positive")
        if item_id not in price_map:
            unknown_items.append(item_id)
            continue
        meta = price_map.get(item_id, {})
        price = Decimal(meta.get("price", 0))
        line_total = price * qty
        subtotal += line_total
        items_payload.append({"item_id": item_id, "qty": qty})
    if unknown_items:
        raise ValueError(f"Unknown item ids for tenant: {', '.join(unknown_items)}")
    if not items_payload:
        raise ValueError("Order must contain at least one item")
    subtotal = subtotal.quantize(Decimal("0.01"))
    total, applied_promos = _apply_promotions(tenant, subtotal)
    raw_payload = dict(data)
    if applied_promos:
        raw_payload["applied_promotions"] = applied_promos

    order = Order(
        tenant_id=tenant.id,
        source=data.get("source") or "site",
        status="NEW",
        items=items_payload,
        total=total,
        customer_name=data.get("customer", {}).get("name"),
        customer_phone=data.get("customer", {}).get("phone"),
        customer_address=data.get("customer", {}).get("address"),
        customer_chat_id=data.get("customer_chat_id"),
        raw_payload=raw_payload,
    )
    with get_session() as session:
        session.add(order)
        session.flush()
        logger.info("[TENANT=%s] Order created id=%s source=%s", tenant.slug, order.id, order.source)
        return order.id


def get_order(oid: int, tenant_id: int) -> Optional[Dict[str, Any]]:
    with get_session() as session:
        query = (
            select(Order, Tenant)
            .join(Tenant, Tenant.id == Order.tenant_id)
            .where(Order.id == oid, Order.tenant_id == tenant_id)
        )
        row = session.execute(query).first()
        if not row:
            return None
        order, tenant = row
        return {
            "id": order.id,
            "tenant": tenant,
            "tenant_id": order.tenant_id,
            "status": order.status,
            "items": order.items or [],
            "total": float(order.total or 0),
            "customer": {
                "name": order.customer_name,
                "phone": order.customer_phone,
                "address": order.customer_address,
                "chat_id": order.customer_chat_id,
                "comment": (order.raw_payload or {}).get("customer", {}).get("comment") if order.raw_payload else None,
            },
            "source": order.source,
        }

def normalize_status(value: str | None) -> str | None:
    if not value:
        return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        upper = raw.upper()
        if upper in ORDER_STATUSES:
            return upper
        return LEGACY_STATUS_MAP.get(raw.lower())
    return None


def _transition_allowed(current: str, target: str) -> bool:
    if current == target:
        return True
    return target in STATUS_TRANSITIONS.get(current, set())


def update_order_status(
    oid: int,
    status: str,
    tenant_id: int,
    admin_chat_id: Optional[int] = None,
    *,
    enforce_workflow: bool = True,
) -> Tuple[bool, Optional[Order], Optional[Tenant], Optional[str], Optional[str]]:
    with get_session() as session:
        query = (
            select(Order, Tenant)
            .join(Tenant, Tenant.id == Order.tenant_id)
            .where(Order.id == oid, Order.tenant_id == tenant_id)
        )
        row = session.execute(query).first()
        if not row:
            return False, None, None, None, None
        order, tenant = row
        if admin_chat_id and tenant.admin_chat_id and tenant.admin_chat_id != admin_chat_id:
            return False, order, tenant, None, None

        current = normalize_status(order.status) or "NEW"
        target = normalize_status(status)
        if not target:
            return False, order, tenant, current, None

        if enforce_workflow and not tenant_has_plan(tenant, "standard"):
            if target not in {"NEW", "COMPLETED"}:
                return False, order, tenant, current, target
            if current not in {"NEW", "COMPLETED"} and target == "COMPLETED":
                return False, order, tenant, current, target
        elif enforce_workflow:
            if not _transition_allowed(current, target):
                return False, order, tenant, current, target

        session.execute(update(Order).where(Order.id == oid).values(status=target))
        logger.info("[TENANT=%s] Order status changed id=%s %s->%s", tenant.slug, oid, current, target)
        return True, order, tenant, current, target


def tenant_has_feature(tenant: Tenant, feature: str) -> bool:
    feat = (tenant.features or {}).get(feature)
    return bool(feat) if isinstance(feat, (bool, int)) else False


def tenant_plan(tenant: Tenant) -> str:
    features = tenant.features or {}
    plan = features.get("plan") or features.get("tier") or "basic"
    if isinstance(plan, str):
        plan = plan.strip().lower()
    if plan not in PLAN_ORDER:
        return "basic"
    return plan


def tenant_has_plan(tenant: Tenant, required_plan: str) -> bool:
    required = required_plan.strip().lower()
    return PLAN_ORDER.get(tenant_plan(tenant), 0) >= PLAN_ORDER.get(required, 0)


def tenant_public_features(tenant: Tenant) -> dict:
    features = tenant.features or {}
    public = {}
    for key, value in features.items():
        if isinstance(value, (bool, int)):
            public[key] = bool(value)
    public["plan"] = tenant_plan(tenant)
    return public


def create_reservation(tenant: Tenant, payload: Dict[str, Any]) -> int:
    if not tenant_has_feature(tenant, "reservations"):
        raise PermissionError("Feature disabled")
    res = Reservation(
        tenant_id=tenant.id,
        table_id=payload.get("table_id"),
        name=payload.get("name"),
        phone=payload.get("phone"),
        datetime=payload.get("datetime"),
        guests=payload.get("guests", 1),
        status="new",
    )
    with get_session() as session:
        session.add(res)
        session.flush()
        return res.id


def list_reservations(tenant: Tenant) -> List[Dict[str, Any]]:
    with get_session() as session:
        reservations = session.execute(
            select(Reservation).where(Reservation.tenant_id == tenant.id).order_by(Reservation.created_at.desc())
        ).scalars()
        return [
            {
                "id": r.id,
                "table_id": r.table_id,
                "name": r.name,
                "phone": r.phone,
                "datetime": r.datetime.isoformat() if r.datetime else None,
                "guests": r.guests,
                "status": r.status,
            }
            for r in reservations
        ]


def update_reservation_status(tenant: Tenant, rid: int, status: str) -> bool:
    with get_session() as session:
        res = session.execute(
            select(Reservation).where(Reservation.tenant_id == tenant.id, Reservation.id == rid)
        ).scalar_one_or_none()
        if not res:
            return False
        res.status = status
        logger.info("[TENANT=%s] Reservation status changed id=%s -> %s", tenant.slug, rid, status)
        return True


def set_user_tenant(user_id: int, slug: str) -> Optional[Tenant]:
    with get_session() as session:
        tenant = session.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none()
        if not tenant:
            return None
        existing = session.execute(select(BotUser).where(BotUser.user_id == user_id)).scalar_one_or_none()
        if existing:
            existing.tenant_id = tenant.id
            existing.slug = slug
        else:
            session.add(BotUser(user_id=user_id, tenant_id=tenant.id, slug=slug))
        return tenant


def get_user_tenant(user_id: int) -> Optional[Tenant]:
    with get_session() as session:
        bot_user = session.execute(select(BotUser).where(BotUser.user_id == user_id)).scalar_one_or_none()
        if not bot_user or not bot_user.slug:
            return None
        return session.execute(select(Tenant).where(Tenant.id == bot_user.tenant_id)).scalar_one_or_none()


def is_admin_chat(chat_id: int) -> bool:
    with get_session() as session:
        return (
            session.execute(select(Tenant).where(Tenant.admin_chat_id == chat_id)).scalar_one_or_none() is not None
        )


def _range_start(range_key: str) -> datetime:
    now = datetime.utcnow()
    key = (range_key or "").lower()
    if key == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if key == "7d":
        return now - timedelta(days=7)
    if key == "30d":
        return now - timedelta(days=30)
    raise ValueError("Invalid range")


def analytics_for_tenant(tenant: Tenant, range_key: str) -> dict:
    start = _range_start(range_key)
    with get_session() as session:
        orders = session.execute(
            select(Order)
            .where(Order.tenant_id == tenant.id, Order.created_at >= start)
            .order_by(Order.created_at.desc())
        ).scalars().all()

    orders_count = len(orders)
    revenue = Decimal(0)
    for order in orders:
        status = normalize_status(order.status) or "NEW"
        if status in COMPLETED_STATUSES:
            revenue += Decimal(order.total or 0)
    avg_check = (revenue / orders_count) if orders_count else Decimal(0)

    price_map = _price_lookup(tenant)
    item_stats: Dict[str, Dict[str, Any]] = {}
    for order in orders:
        for it in order.items or []:
            item_id = str(it.get("item_id"))
            qty = int(it.get("qty") or 0)
            if qty <= 0:
                continue
            meta = price_map.get(item_id, {})
            name = meta.get("name") or item_id
            price = Decimal(meta.get("price") or 0)
            stats = item_stats.setdefault(item_id, {"item_id": item_id, "name": name, "qty": 0, "revenue": 0})
            stats["qty"] += qty
            stats["revenue"] += int(price * qty)

    top_items = sorted(item_stats.values(), key=lambda x: (x["qty"], x["revenue"]), reverse=True)[:5]
    return {
        "range": range_key,
        "orders": orders_count,
        "revenue": float(revenue),
        "average_check": float(avg_check),
        "top_items": top_items,
    }


def list_orders_by_phone(tenant: Tenant, phone: str, limit: int = 20) -> List[Order]:
    with get_session() as session:
        return (
            session.execute(
                select(Order)
                .where(Order.tenant_id == tenant.id, Order.customer_phone == phone)
                .order_by(Order.created_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )


def get_order_for_tenant(tenant: Tenant, oid: int) -> Optional[Order]:
    with get_session() as session:
        return (
            session.execute(select(Order).where(Order.tenant_id == tenant.id, Order.id == oid))
            .scalars()
            .first()
        )


def order_history_for_phone(tenant: Tenant, phone: str, limit: int = 20) -> List[Dict[str, Any]]:
    orders = list_orders_by_phone(tenant, phone, limit=limit)
    item_map = _price_lookup(tenant)
    result: List[Dict[str, Any]] = []
    for order in orders:
        order_items = []
        for item in order.items or []:
            item_id = str(item.get("item_id"))
            qty = int(item.get("qty") or 0)
            meta = item_map.get(item_id, {})
            price = int(meta.get("price") or 0)
            order_items.append(
                {
                    "item_id": item_id,
                    "name": meta.get("name") or item_id,
                    "qty": qty,
                    "price": price,
                    "line_total": price * qty,
                }
            )
        result.append(
            {
                "id": order.id,
                "status": order.status,
                "total": float(order.total or 0),
                "created_at": order.created_at.isoformat() if order.created_at else None,
                "items": order_items,
            }
        )
    return result


def create_reorder_for_phone(tenant: Tenant, oid: int, phone: str) -> int:
    order = get_order_for_tenant(tenant, oid)
    if not order:
        raise LookupError("Order not found")
    if not order.customer_phone or order.customer_phone != phone:
        raise PermissionError("Customer phone mismatch")
    payload = {
        "items": order.items or [],
        "customer": {
            "name": order.customer_name or "",
            "phone": order.customer_phone or "",
            "address": order.customer_address or "",
            "comment": "Reorder",
        },
        "source": "site",
        "customer_chat_id": order.customer_chat_id,
    }
    return add_order(payload, tenant=tenant)
