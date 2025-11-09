from dataclasses import dataclass
from typing import List

@dataclass
class MenuItem:
    name: str
    price: int
    description: str = ""
    image: str = ""

class Menu:
    _items: List[MenuItem] = [
        MenuItem(
            name="Pepperoni", 
            price=65000, 
            description="🍕 Pepperoni pitsasi"
        ),
        MenuItem(
            name="Cheeseburger", 
            price=45000, 
            description="🍔 Pishloqli burger"
        ),
        MenuItem(
            name="Shawarma", 
            price=38000, 
            description="🌯 Shaurma"
        ),
        MenuItem(
            name="Cola 1L", 
            price=12000, 
            description="🥤 Koka-kola 1 litr"
        ),
    ]

    @classmethod
    def get_all(cls) -> List[MenuItem]:
        return cls._items

    @classmethod
    def get_by_name(cls, name: str) -> MenuItem | None:
        return next((item for item in cls._items if item.name == name), None)