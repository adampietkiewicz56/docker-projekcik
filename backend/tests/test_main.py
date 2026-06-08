"""Unit tests using SQLite in-memory — no external services required."""

import os
import sys
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Required by app.database at import time
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_HOST", "localhost")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from app import main as main_module
    from app.database import get_db
    from app.models import Base

    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(main_module, "engine", test_engine)
    monkeypatch.setattr(main_module, "redis_client", MagicMock(ping=lambda: True))
    main_module.app.dependency_overrides[get_db] = override_get_db

    with TestClient(main_module.app) as c:
        yield c

    main_module.app.dependency_overrides.clear()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready(client):
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready"}


def test_metrics_exposes_prometheus(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "notes_created_total" in r.text


def test_create_and_list_and_get(client):
    r = client.post("/notes", json={"title": "hello", "content": "world"})
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "hello"
    note_id = body["id"]

    r = client.get("/notes")
    assert r.status_code == 200
    notes = r.json()
    assert any(n["id"] == note_id for n in notes)

    r = client.get(f"/notes/{note_id}")
    assert r.status_code == 200
    assert r.json()["title"] == "hello"


def test_delete(client):
    created = client.post("/notes", json={"title": "tmp", "content": ""}).json()
    r = client.delete(f"/notes/{created['id']}")
    assert r.status_code == 204
    r = client.get(f"/notes/{created['id']}")
    assert r.status_code == 404


def test_create_validation(client):
    r = client.post("/notes", json={"title": "", "content": ""})
    assert r.status_code == 422
