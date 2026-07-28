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


def test_research_rejects_blank_prompt():
    response = client.post(
        "/api/research",
        json={"user_prompt": "   ", "num_topics": 2, "papers_per_topic": 2},
    )
    assert response.status_code == 422


def test_research_rejects_non_positive_num_topics():
    response = client.post(
        "/api/research",
        json={"user_prompt": "machine learning", "num_topics": 0, "papers_per_topic": 2},
    )
    assert response.status_code == 422


def test_graph_returns_404_for_unknown_project():
    response = client.get("/api/graph/nonexistent-project-id/")
    assert response.status_code == 404
