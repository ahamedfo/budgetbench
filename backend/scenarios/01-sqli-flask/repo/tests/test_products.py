def test_list_products(client):
    r = client.get("/products")
    assert r.status_code == 200
    items = r.get_json()
    assert len(items) >= 5
    assert all("name" in p for p in items)


def test_list_products_filtered_by_category(client):
    r = client.get("/products?category=widgets")
    assert r.status_code == 200
    items = r.get_json()
    assert len(items) >= 2
    assert all("Widget" in p["name"] for p in items)


def test_list_products_unknown_category_empty(client):
    r = client.get("/products?category=does-not-exist")
    assert r.status_code == 200
    assert r.get_json() == []


def test_get_product_by_id(client):
    r = client.get("/products/1")
    assert r.status_code == 200
    assert r.get_json()["id"] == 1


def test_get_product_not_found(client):
    r = client.get("/products/9999")
    assert r.status_code == 404


def test_search_products_basic(client):
    r = client.get("/products/search?q=Widget")
    assert r.status_code == 200
    items = r.get_json()
    assert len(items) >= 2
    assert all("Widget" in p["name"] for p in items)


def test_search_products_no_match(client):
    r = client.get("/products/search?q=NotARealProductXYZ")
    assert r.status_code == 200
    assert r.get_json() == []


def test_search_products_empty_query_returns_all(client):
    r = client.get("/products/search?q=")
    assert r.status_code == 200
    assert len(r.get_json()) >= 5


def test_create_product_requires_auth(client):
    r = client.post("/products", json={"name": "X", "price_cents": 100})
    assert r.status_code == 401


def test_categories_endpoint(client):
    r = client.get("/categories")
    assert r.status_code == 200
    items = r.get_json()
    assert len(items) >= 3
