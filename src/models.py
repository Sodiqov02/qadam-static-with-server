from pydantic import BaseModel, Field
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
    qty: int = Field(gt=0)

class Customer(BaseModel):
    name: str
    phone: str
    address: str
    comment: Optional[str] = None

class OrderIn(BaseModel):
    items: List[OrderItem]
    customer: Customer
    source: Literal["site", "bot"] = "site"
    customer_chat_id: Optional[int] = None

class OrderOut(BaseModel):
    order_id: int
    status: str = "NEW"
