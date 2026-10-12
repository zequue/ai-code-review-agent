import pytest

from shop.cart import Cart, CartError


def test_add_accumulates_quantity():
    cart = Cart()
    cart.add(1, 2)
    cart.add(1, 3)
    assert cart.items == {1: 5}


def test_add_rejects_non_positive_quantity():
    with pytest.raises(CartError):
        Cart().add(1, 0)


def test_from_payload():
    cart = Cart.from_payload([{"product_id": 1, "quantity": 2}, {"product_id": 3}])
    assert cart.items == {1: 2, 3: 1}
