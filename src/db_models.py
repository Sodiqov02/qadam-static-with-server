import datetime as dt
from typing import Any, Dict, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Time,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True)
    slug = Column(String(64), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    admin_chat_id = Column(BigInteger, nullable=True)
    bot_token = Column(String(255), nullable=True)
    bot_username = Column(String(255), nullable=True)
    bot_enabled = Column(Boolean, nullable=False, default=False)
    features = Column(JSON, nullable=False, default=dict)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)

    categories = relationship("MenuCategory", back_populates="tenant")
    items = relationship("MenuItem", back_populates="tenant")
    orders = relationship("Order", back_populates="tenant")


class MenuCategory(Base):
    __tablename__ = "menu_categories"
    __table_args__ = (UniqueConstraint("tenant_id", "title", name="uq_category_title_per_tenant"),)

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    sort = Column(Integer, nullable=False, default=0)
    sort_order = Column(Integer, nullable=False, default=0)

    tenant = relationship("Tenant", back_populates="categories")
    items = relationship("MenuItem", back_populates="category")


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("menu_categories.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    price = Column(Integer, nullable=False, default=0)
    description = Column(Text, nullable=True)
    image_path = Column(String(1024), nullable=True)
    image_url = Column(String(1024), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    sort = Column(Integer, nullable=False, default=0)

    tenant = relationship("Tenant", back_populates="items")
    category = relationship("MenuCategory", back_populates="items")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    source = Column(String(32), nullable=False, default="site")
    status = Column(String(32), nullable=False, default="new")
    items = Column(JSON, nullable=False, default=list)
    total = Column(Numeric(12, 2), nullable=False, default=0)
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)
    customer_name = Column(String(255), nullable=True)
    customer_phone = Column(String(64), nullable=True)
    customer_address = Column(Text, nullable=True)
    customer_chat_id = Column(BigInteger, nullable=True)
    raw_payload = Column(JSON, nullable=True)

    tenant = relationship("Tenant", back_populates="orders")


class BotUser(Base):
    __tablename__ = "bot_users"

    user_id = Column(BigInteger, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)
    slug = Column(String(64), nullable=True)
    updated_at = Column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow, nullable=False)


class Table(Base):
    __tablename__ = "tables"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    capacity = Column(Integer, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)


class Reservation(Base):
    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    table_id = Column(Integer, ForeignKey("tables.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(255), nullable=False)
    phone = Column(String(64), nullable=False)
    datetime = Column(DateTime, nullable=False)
    guests = Column(Integer, nullable=False, default=1)
    status = Column(String(32), nullable=False, default="new")
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)


class Promotion(Base):
    __tablename__ = "promotions"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(32), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    product_id = Column(Integer, ForeignKey("menu_items.id", ondelete="SET NULL"), nullable=True)
    discount_percent = Column(Integer, nullable=True)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    days_of_week = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)
