def test_me_requires_login(client):
    r = client.get("/users/me")
    assert r.status_code == 401


def test_me_returns_profile(auth_client):
    r = auth_client.get("/users/me")
    assert r.status_code == 200
    assert r.get_json()["email"] == "tester@example.com"


def test_me_update_display_name(auth_client):
    r = auth_client.put("/users/me", json={"display_name": "New Name"})
    assert r.status_code == 200
    assert r.get_json()["display_name"] == "New Name"
