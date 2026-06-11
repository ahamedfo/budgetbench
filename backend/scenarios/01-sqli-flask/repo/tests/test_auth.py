def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json() == {"status": "ok"}


def test_signup_and_login(client):
    r = client.post(
        "/auth/signup",
        json={"email": "new@example.com", "password": "abcd1234"},
    )
    assert r.status_code == 201
    assert r.get_json()["email"] == "new@example.com"

    r = client.post(
        "/auth/login",
        json={"email": "new@example.com", "password": "abcd1234"},
    )
    assert r.status_code == 200


def test_login_wrong_password(client):
    client.post(
        "/auth/signup",
        json={"email": "u@example.com", "password": "abcd1234"},
    )
    r = client.post(
        "/auth/login",
        json={"email": "u@example.com", "password": "WRONG"},
    )
    assert r.status_code == 401


def test_signup_requires_email_and_password(client):
    r = client.post("/auth/signup", json={"email": "no-pw@example.com"})
    assert r.status_code == 400


def test_signup_rejects_short_password(client):
    r = client.post(
        "/auth/signup",
        json={"email": "shortpw@example.com", "password": "abc"},
    )
    assert r.status_code == 400


def test_password_reset_does_not_leak_user(client):
    r = client.post("/auth/password-reset", json={"email": "nope@example.com"})
    assert r.status_code == 200
    assert "reset link has been sent" in r.get_json()["status"]
