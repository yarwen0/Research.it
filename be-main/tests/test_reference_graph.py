"""Tests for ReferenceGraph node/edge construction.

Exercises the in-memory graph logic. ReferenceGraph persists under
``be-main/data/<project_id>/`` (gitignored); the fixture removes that directory.
"""

from __future__ import annotations

import os
import shutil

import pytest

from core import ReferenceGraph

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


@pytest.fixture
def project_id():
    pid = "pytest_refgraph_tmp"
    shutil.rmtree(os.path.join(DATA_DIR, pid), ignore_errors=True)
    yield pid
    shutil.rmtree(os.path.join(DATA_DIR, pid), ignore_errors=True)


def test_nodes_and_edge_populate_refs_both_ways(project_id):
    graph = ReferenceGraph(project_id=project_id)
    graph.create_node_no_sync("a", {"title": "A"}, True)
    graph.create_node_no_sync("b", {"title": "B"}, False)
    graph.create_edge_no_sync("a", "b", edge_type="citation")

    nodes = graph.graph["nodes"]
    assert nodes["a"]["refs_to"] == ["b"]
    # refs_from is what the /graph API surfaces as incoming references.
    assert nodes["b"]["refs_from"] == ["a"]
    assert nodes["a"]["data"]["title"] == "A"

    edges = graph.graph["edges"]
    assert len(edges) == 1
    assert edges[0]["source"] == "a"
    assert edges[0]["target"] == "b"
    assert edges[0]["edge_type"] == "citation"


def test_edge_requires_both_nodes_to_exist(project_id):
    graph = ReferenceGraph(project_id=project_id)
    graph.create_node_no_sync("a", {}, True)
    with pytest.raises(ValueError):
        graph.create_edge_no_sync("a", "missing")
