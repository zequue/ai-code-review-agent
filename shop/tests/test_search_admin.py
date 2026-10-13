import pytest

from shop.app import create_app


@pytest.fixture
def admin_client(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    return create_app(str(tmp_path / "admin.db")).test_client()


def test_search_by_name(client):
    resp = client.get("/products/search?q=Gorra")
    assert [p["name"] for p in resp.get_json()] == ["Gorra"]


def test_search_treats_input_as_text(client):
    resp = client.get("/products/search", query_string={"q": "' OR '1'='1"})
    assert resp.get_json() == []


def test_admin_requires_token(admin_client):
    resp = admin_client.post("/admin/products", json={"name": "X", "category": "y"})
    assert resp.status_code == 401


def test_admin_rejects_wrong_token(admin_client):
    resp = admin_client.post(
        "/admin/products", json={}, headers={"X-Admin-Token": "otro-token"}
    )
    assert resp.status_code == 401


def test_admin_adds_product(admin_client):
    resp = admin_client.post(
        "/admin/products",
        json={"name": "Medias", "category": "ropa", "price_cents": 899, "stock": 40},
        headers={"X-Admin-Token": "test-token"},
    )
    assert resp.status_code == 201
    product_id = resp.get_json()["id"]
    assert admin_client.get(f"/products/{product_id}").get_json()["price_cents"] == 899
