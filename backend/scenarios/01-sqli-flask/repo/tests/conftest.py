import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.utils.seed import seed_if_empty


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        seed_if_empty()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(app, client):
    client.post(
        "/auth/signup",
        json={"email": "tester@example.com", "password": "testpass123",
              "display_name": "Tester"},
    )
    client.post(
        "/auth/login",
        json={"email": "tester@example.com", "password": "testpass123"},
    )
    return client
