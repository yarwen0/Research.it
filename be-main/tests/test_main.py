"""Smoke tests for FastAPI health endpoints."""

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_root_health():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_detailed_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "research" in data["endpoints"]
    assert "graph" in data["endpoints"]
