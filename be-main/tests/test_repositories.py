"""Tests for the ORM repositories that replaced the JSON storage classes."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from db.models import Author, Citation, OntologyTerm, Paper, Project
from db.repositories import (
    GraphRepository,
    OntologyRepository,
    ProjectRepository,
    ReviewRepository,
    author_node_id,
)

PROJECT_ID = "proj0123456789abcdef"


@pytest.fixture
def project(session):
    return ProjectRepository(session).create(PROJECT_ID, "diffusion models", ["a", "b"])


@pytest.fixture
def graph(session, project):
    return GraphRepository(session, PROJECT_ID)


def _paper(paper_id: str, title: str, *, authors=None, references=None) -> dict:
    return {
        "paper_id": paper_id,
        "title": title,
        "authors": authors or [],
        "published": "2024-01-01",
        "pdf_url": f"https://arxiv.org/pdf/{paper_id}",
        "topic": "diffusion",
        "extraction": {"problem": "p"},
        "normalized": {"methods": [["diffusion", "Diffusion Models"]]},
        "references": references or [],
    }


class TestAuthorNodeId:
    def test_matches_the_legacy_id_format(self):
        # The frontend renders these ids; changing the format would orphan
        # graphs generated before the storage migration.
        assert author_node_id("Jane A. Doe") == "author_jane_a_doe"

    def test_is_stable_for_the_same_name(self):
        assert author_node_id("Yann LeCun") == author_node_id("Yann LeCun")


class TestProjectRepository:
    def test_creates_and_reads_back(self, session):
        repo = ProjectRepository(session)
        repo.create(PROJECT_ID, "prompt", ["t1"])
        stored = repo.get(PROJECT_ID)
        assert stored is not None
        assert stored.user_prompt == "prompt"
        assert stored.topics == ["t1"]

    def test_exists_is_false_for_unknown_project(self, session):
        assert ProjectRepository(session).exists("nope") is False


class TestGraphWrites:
    def test_persists_paper_and_authors(self, session, graph):
        graph.add_processed_paper(_paper("2301.001", "Attention", authors=["Jane Doe"]))
        session.flush()

        paper = session.scalar(select(Paper).where(Paper.external_id == "2301.001"))
        assert paper.is_processed is True
        assert [a.name for a in paper.authors] == ["Jane Doe"]

    def test_shared_author_is_stored_once(self, session, graph):
        graph.add_processed_paper(_paper("2301.001", "A", authors=["Jane Doe"]))
        graph.add_processed_paper(_paper("2301.002", "B", authors=["Jane Doe"]))
        session.flush()

        assert session.scalar(select(func.count()).select_from(Author)) == 1

    def test_reprocessing_a_paper_updates_rather_than_duplicates(self, session, graph):
        graph.add_processed_paper(_paper("2301.001", "Old title"))
        graph.add_processed_paper(_paper("2301.001", "New title"))
        session.flush()

        papers = session.scalars(select(Paper)).all()
        assert len(papers) == 1
        assert papers[0].title == "New title"

    def test_ignores_references_with_noise_titles(self, session, graph):
        source = graph.add_processed_paper(_paper("2301.001", "A"))
        assert graph.add_reference(source, {"title": "ibid."}) is None
        session.flush()
        assert session.scalar(select(func.count()).select_from(Citation)) == 0

    def test_shared_reference_becomes_one_node_with_two_edges(self, session, graph):
        """The file-based version minted a fresh uuid per reference, so a work
        cited by two papers produced two disconnected nodes."""
        a = graph.add_processed_paper(_paper("2301.001", "A"))
        b = graph.add_processed_paper(_paper("2301.002", "B"))
        graph.add_reference(a, {"title": "Attention Is All You Need"})
        graph.add_reference(b, {"title": "attention is all you need"})
        session.flush()

        references = session.scalars(
            select(Paper).where(Paper.is_processed.is_(False))
        ).all()
        assert len(references) == 1
        assert session.scalar(select(func.count()).select_from(Citation)) == 2

    def test_duplicate_edge_is_not_written_twice(self, session, graph):
        a = graph.add_processed_paper(_paper("2301.001", "A"))
        graph.add_reference(a, {"title": "Attention Is All You Need"})
        graph.add_reference(a, {"title": "Attention Is All You Need"})
        session.flush()

        assert session.scalar(select(func.count()).select_from(Citation)) == 1

    def test_build_from_processed_papers_wires_the_whole_run(self, session, graph):
        graph.build_from_processed_papers(
            [
                _paper(
                    "2301.001",
                    "A",
                    authors=["Jane Doe"],
                    references=[{"title": "Attention Is All You Need"}],
                )
            ]
        )
        session.flush()

        assert session.scalar(select(func.count()).select_from(Paper)) == 2
        assert session.scalar(select(func.count()).select_from(Citation)) == 1


class TestGraphReads:
    def test_reports_empty_before_any_writes(self, graph):
        assert graph.is_empty() is True

    def test_cytoscape_shape_has_paper_and_author_nodes(self, session, graph):
        graph.build_from_processed_papers(
            [
                _paper(
                    "2301.001",
                    "A",
                    authors=["Jane Doe"],
                    references=[{"title": "Attention Is All You Need"}],
                )
            ]
        )
        session.flush()

        rendered = graph.to_cytoscape()
        kinds = [n["data"]["node_type"] for n in rendered["nodes"]]
        assert kinds.count("author") == 1
        assert kinds.count("paper") == 2  # the processed paper plus its reference

        edge_kinds = [e["data"]["edge_type"] for e in rendered["edges"]]
        assert "authorship" in edge_kinds
        assert "citation" in edge_kinds

    def test_cytoscape_fills_in_refs_to_and_refs_from(self, session, graph):
        graph.build_from_processed_papers(
            [_paper("2301.001", "A", references=[{"title": "Attention Is All You Need"}])]
        )
        session.flush()

        nodes = {n["data"]["id"]: n["data"] for n in graph.to_cytoscape()["nodes"]}
        source = nodes["2301.001"]
        assert len(source["refs_to"]) == 1
        assert source["refs_from"] == []

        target_id = source["refs_to"][0]
        assert nodes[target_id]["refs_from"] == ["2301.001"]

    def test_author_node_appears_once_across_papers(self, session, graph):
        graph.build_from_processed_papers(
            [
                _paper("2301.001", "A", authors=["Jane Doe"]),
                _paper("2301.002", "B", authors=["Jane Doe"]),
            ]
        )
        session.flush()

        rendered = graph.to_cytoscape()
        author_nodes = [n for n in rendered["nodes"] if n["data"]["node_type"] == "author"]
        assert len(author_nodes) == 1
        # ...but both papers still link to them.
        authorship = [
            e for e in rendered["edges"] if e["data"]["edge_type"] == "authorship"
        ]
        assert len(authorship) == 2


class TestProjectIsolation:
    def test_two_projects_can_hold_the_same_paper(self, session):
        repo = ProjectRepository(session)
        repo.create("p1", "one")
        repo.create("p2", "two")

        GraphRepository(session, "p1").add_processed_paper(_paper("2301.001", "A"))
        GraphRepository(session, "p2").add_processed_paper(_paper("2301.001", "A"))
        session.flush()

        assert session.scalar(select(func.count()).select_from(Paper)) == 2

    def test_graph_read_is_scoped_to_its_project(self, session):
        repo = ProjectRepository(session)
        repo.create("p1", "one")
        repo.create("p2", "two")
        GraphRepository(session, "p1").add_processed_paper(_paper("2301.001", "A"))
        session.flush()

        assert GraphRepository(session, "p2").to_cytoscape()["nodes"] == []

    def test_deleting_a_project_cascades(self, session):
        repo = ProjectRepository(session)
        repo.create("p1", "one")
        GraphRepository(session, "p1").build_from_processed_papers(
            [_paper("2301.001", "A", authors=["Jane Doe"], references=[{"title": "Some Real Title"}])]
        )
        session.commit()

        session.delete(session.get(Project, "p1"))
        session.commit()

        assert session.scalar(select(func.count()).select_from(Paper)) == 0
        assert session.scalar(select(func.count()).select_from(Author)) == 0
        assert session.scalar(select(func.count()).select_from(Citation)) == 0


class TestOntologyRepository:
    def test_records_terms_contributed_by_a_paper(self, session, project):
        repo = OntologyRepository(session, PROJECT_ID)
        repo.map_paper(
            {
                "problem": "ignored free text",
                "methods": [["diffusion", "Diffusion Models"]],
                "datasets": [["imagenet", "ImageNet-1k"]],
            },
            "2301.001",
        )
        session.flush()

        assert repo.terms_for(["methods"]) == {"methods": ["diffusion"]}
        assert session.scalar(select(func.count()).select_from(OntologyTerm)) == 2

    def test_skips_the_free_text_problem_field(self, session, project):
        repo = OntologyRepository(session, PROJECT_ID)
        repo.map_paper({"problem": "some prose"}, "2301.001")
        session.flush()
        assert session.scalar(select(func.count()).select_from(OntologyTerm)) == 0

    def test_tolerates_malformed_items(self, session, project):
        repo = OntologyRepository(session, PROJECT_ID)
        repo.map_paper(
            {"methods": [["ok", "Okay"], "not-a-pair", ["only-one"], ["", "blank"]]},
            "2301.001",
        )
        session.flush()
        assert repo.terms_for(["methods"]) == {"methods": ["ok"]}

    def test_terms_are_scoped_per_project(self, session):
        repo_factory = ProjectRepository(session)
        repo_factory.create("p1", "one")
        repo_factory.create("p2", "two")

        OntologyRepository(session, "p1").map_paper(
            {"methods": [["only_in_p1", "x"]]}, "2301.001"
        )
        session.flush()

        # The global ontology.json meant one run's terms bled into every other.
        assert OntologyRepository(session, "p2").terms_for(["methods"]) == {}

    def test_as_dict_rebuilds_the_nested_shape(self, session, project):
        repo = OntologyRepository(session, PROJECT_ID)
        repo.map_paper({"methods": [["diffusion", "Diffusion Models"]]}, "2301.001")
        repo.map_paper({"methods": [["diffusion", "diffusion model"]]}, "2301.002")
        session.flush()

        assert repo.as_dict() == {
            "methods": {
                "diffusion": [
                    {"paper_id": "2301.001", "original": "Diffusion Models"},
                    {"paper_id": "2301.002", "original": "diffusion model"},
                ]
            }
        }

    def test_terms_for_returns_empty_without_parameters(self, session, project):
        assert OntologyRepository(session, PROJECT_ID).terms_for([]) == {}


class TestReviewRepository:
    def test_saves_and_reads_back(self, session):
        repo = ReviewRepository(session)
        repo.save("20260101_000000", r"\documentclass{article}", title="A Review")
        session.flush()

        stored = repo.get("20260101_000000")
        assert stored is not None
        assert stored.title == "A Review"

    def test_saving_the_same_id_updates_in_place(self, session):
        repo = ReviewRepository(session)
        repo.save("rev1", "v1")
        repo.save("rev1", "v2")
        session.flush()

        assert len(repo.list()) == 1
        assert repo.get("rev1").latex_content == "v2"

    def test_list_filters_by_source_dataset(self, session):
        repo = ReviewRepository(session)
        repo.save("rev1", "x", source_filepath="data/a.json")
        repo.save("rev2", "y", source_filepath="data/b.json")
        session.flush()

        assert [r.review_id for r in repo.list("data/a.json")] == ["rev1"]
        assert len(repo.list()) == 2

    def test_delete_reports_whether_anything_was_removed(self, session):
        repo = ReviewRepository(session)
        repo.save("rev1", "x")
        session.flush()

        assert repo.delete("rev1") is True
        assert repo.delete("rev1") is False
