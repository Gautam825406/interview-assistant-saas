"""Test setup: env vars set BEFORE importing the app; isolated in-memory
SQLite DB, recreated for every test. No real Cashfree/provider calls —
HTTP is mocked in the tests that need it.
"""
import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-jwt-secret-for-tests-only"
os.environ["CASHFREE_APP_ID"] = "test-app-id"
os.environ["CASHFREE_SECRET_KEY"] = "test-secret-key"
os.environ["CASHFREE_ENV"] = "SANDBOX"

from cryptography.fernet import Fernet

os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.seed import seed_plans
from app.security import encrypt_value
from app.settings_util import KEY_ATTRS, get_provider_settings
from main import app

test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def _reset_db():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()
    seed_plans(db)
    db.close()
    yield


@pytest.fixture()
def db():
    s = TestingSessionLocal()
    yield s
    s.close()


@pytest.fixture()
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def signup(client, email, password="secret123", name="Test User"):
    r = client.post(
        "/api/auth/signup",
        json={"name": name, "email": email, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def set_provider_key(db, provider, key):
    row = get_provider_settings(db)
    setattr(row, KEY_ATTRS[provider], encrypt_value(key))
    db.commit()


@pytest.fixture()
def admin(client):
    return signup(client, "admin@test.local", name="Admin")


@pytest.fixture()
def user(client, admin):
    return signup(client, "user@test.local", name="Regular User")
