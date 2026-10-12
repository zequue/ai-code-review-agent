def test_search_by_name(client):
    resp = client.get("/products/search?q=Gorra")
    assert [p["name"] for p in resp.get_json()] == ["Gorra"]


def test_admin_adds_product(client):
    resp = client.post(
        "/admin/products",
        json={"name": "Medias", "category": "ropa", "price_cents": 899, "stock": 40},
    )
    assert resp.status_code == 201
    product_id = resp.get_json()["id"]
    assert client.get(f"/products/{product_id}").get_json()["price_cents"] == 899
