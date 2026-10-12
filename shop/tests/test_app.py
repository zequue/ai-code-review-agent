def test_list_products(client):
    resp = client.get("/products")
    assert resp.status_code == 200
    assert len(resp.get_json()) == 5


def test_product_not_found(client):
    assert client.get("/products/999").status_code == 404


def test_checkout_endpoint(client):
    resp = client.post("/checkout", json={"items": [{"product_id": 2, "quantity": 1}]})
    assert resp.status_code == 201
    assert resp.get_json()["total_cents"] == 4599


def test_checkout_endpoint_bad_request(client):
    resp = client.post("/checkout", json={"items": []})
    assert resp.status_code == 400
