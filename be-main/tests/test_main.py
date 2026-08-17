"""Smoke tests for FastAPI health endpoints and request validation."""

import pytest
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


def test_research_rejects_non_positive_papers_per_topic():
    response = client.post(
        "/api/research",
        json={"user_prompt": "machine learning", "num_topics": 2, "papers_per_topic": 0},
    )
    assert response.status_code == 422


def test_graph_returns_404_for_unknown_project():
    response = client.get("/api/graph/nonexistent-project-id/")
    assert response.status_code == 404


class TestCreateReviewPathContainment:
    """`saved_filepath` round-trips through the browser, so it is untrusted."""

    @staticmethod
    def _payload(saved_filepath: str) -> dict:
        return {
            "saved_filepath": saved_filepath,
            "paper_index": 0,
            "paper_info": {"title": "t", "keywords": [], "abstract": "a"},
        }

    @pytest.mark.parametrize(
        "saved_filepath",
        [
            "/etc/passwd",
            "data/../../etc/passwd",
            "data/../.env",
            "../config.py",
            "   ",
        ],
    )
    def test_rejects_paths_outside_data_dir(self, saved_filepath):
        response = client.post("/api/create_review", json=self._payload(saved_filepath))
        assert response.status_code == 422

    def test_rejects_negative_paper_index(self):
        payload = self._payload("data/processed_papers_x.json")
        payload["paper_index"] = -1
        response = client.post("/api/create_review", json=payload)
        assert response.status_code == 422
