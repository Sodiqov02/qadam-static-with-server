from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Literal, Optional

class MenuItem(BaseModel):
    id: str
    name: str
    price: int
    description: Optional[str] = None
    image: Optional[str] = None
    image_url: Optional[str] = None

class MenuCategory(BaseModel):
    id: str
    title: str
    items: List[MenuItem]

class Menu(BaseModel):
    categories: List[MenuCategory]

class OrderItem(BaseModel):
    item_id: str
    qty: int = Field(gt=0, le=100)

class Customer(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=1, max_length=64)
    address: str = Field(min_length=1, max_length=2000)
    comment: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("name", "phone", "address", mode="before")
    @classmethod
    def required_text(cls, value: object) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("Field must not be empty")
        return normalized

    @field_validator("comment", mode="before")
    @classmethod
    def optional_text(cls, value: object) -> Optional[str]:
        if value is None:
            return None
        return str(value).strip()

class OrderIn(BaseModel):
    items: List[OrderItem] = Field(min_length=1, max_length=100)
    customer: Customer
    source: Literal["site", "bot"] = "site"
    customer_chat_id: Optional[int] = None

    @model_validator(mode="after")
    def normalize_item_quantities(self) -> "OrderIn":
        quantities: dict[str, int] = {}
        item_order: list[str] = []
        for item in self.items:
            if item.item_id not in quantities:
                quantities[item.item_id] = 0
                item_order.append(item.item_id)
            quantities[item.item_id] += item.qty
            if quantities[item.item_id] > 100:
                raise ValueError("Combined item qty must not exceed 100")

        self.items = [OrderItem(item_id=item_id, qty=quantities[item_id]) for item_id in item_order]
        return self

class OrderOut(BaseModel):
    order_id: int
    status: str = "NEW"
