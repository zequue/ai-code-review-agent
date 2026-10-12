from dataclasses import dataclass, field


class CartError(ValueError):
    pass


@dataclass
class Cart:
    items: dict[int, int] = field(default_factory=dict)  # product_id -> quantity

    def add(self, product_id: int, quantity: int = 1) -> None:
        if quantity <= 0:
            raise CartError("quantity must be positive")
        self.items[product_id] = self.items.get(product_id, 0) + quantity

    def remove(self, product_id: int) -> None:
        self.items.pop(product_id, None)

    def is_empty(self) -> bool:
        return not self.items

    @classmethod
    def from_payload(cls, payload: list[dict]) -> "Cart":
        cart = cls()
        for item in payload:
            cart.add(int(item["product_id"]), int(item.get("quantity", 1)))
        return cart
