def test_cart_requires_auth(client):
    r = client.post("/orders/cart", json={"product_id": 1, "quantity": 1})
    assert r.status_code == 401


def test_add_to_cart_and_checkout(auth_client):
    r = auth_client.post(
        "/orders/cart", json={"product_id": 1, "quantity": 2}
    )
    assert r.status_code == 200
    cart = r.get_json()
    assert cart["status"] == "cart"
    assert len(cart["items"]) == 1
    assert cart["items"][0]["quantity"] == 2

    r = auth_client.post("/orders/checkout")
    assert r.status_code == 200
    order = r.get_json()
    assert order["status"] == "placed"
    assert order["total_cents"] > 0


def test_add_to_cart_unknown_product(auth_client):
    r = auth_client.post("/orders/cart", json={"product_id": 99999, "quantity": 1})
    assert r.status_code == 404


def test_add_to_cart_invalid_quantity(auth_client):
    r = auth_client.post("/orders/cart", json={"product_id": 1, "quantity": 0})
    assert r.status_code == 400


def test_history_empty_initially(auth_client):
    r = auth_client.get("/orders/history")
    assert r.status_code == 200
    assert r.get_json() == []


def test_history_after_checkout(auth_client):
    auth_client.post("/orders/cart", json={"product_id": 1, "quantity": 1})
    auth_client.post("/orders/checkout")
    r = auth_client.get("/orders/history")
    assert r.status_code == 200
    history = r.get_json()
    assert len(history) == 1
    assert history[0]["status"] == "placed"
