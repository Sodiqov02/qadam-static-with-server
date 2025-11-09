from typing import Dict, Any
from itertools import count

ORDERS: Dict[int, Dict[str, Any]] = {}
_COUNTER = count(1)

def add_order(data: Dict[str, Any]) -> int:
    oid = next(_COUNTER)
    ORDERS[oid] = {"id": oid, "status": "new", **data}
    return oid

def set_status(oid: int, status: str) -> bool:
    if oid in ORDERS:
        ORDERS[oid]["status"] = status
        return True
    return False

def get_order(oid: int):
    return ORDERS.get(oid)
