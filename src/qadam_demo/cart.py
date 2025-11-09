from dataclasses import dataclass
from typing import List, Dict
from .menu import MenuItem

@dataclass
class CartItem:
    item: MenuItem
    quantity: int = 1

class Cart:
    def __init__(self):
        self.items: Dict[str, CartItem] = {}
    
    def add_item(self, item: MenuItem, quantity: int = 1):
        if item.name in self.items:
            self.items[item.name].quantity += quantity
        else:
            self.items[item.name] = CartItem(item, quantity)
    
    def remove_item(self, item_name: str):
        if item_name in self.items:
            del self.items[item_name]
    
    def update_quantity(self, item_name: str, quantity: int):
        if item_name in self.items:
            if quantity <= 0:
                self.remove_item(item_name)
            else:
                self.items[item_name].quantity = quantity
    
    def clear(self):
        self.items.clear()
    
    def get_total(self) -> int:
        return sum(item.item.price * item.quantity for item in self.items.values())
    
    def get_items(self) -> List[CartItem]:
        return list(self.items.values())
    
    def is_empty(self) -> bool:
        return len(self.items) == 0

# Dictionary to store user carts: user_id -> Cart
user_carts: Dict[int, Cart] = {}