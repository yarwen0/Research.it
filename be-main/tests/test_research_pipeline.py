"""End-to-end tests for the research pipeline service.

Every external dependency is stubbed — no arXiv, no LLM, no network — so the
orchestration itself is under test: stage ordering, error containment, and
what ends up in the database.
"""

from __future__ import annotations

import json
from typing import ClassVar

import pytest
from sqlalchemy import func, select

from db.models import Citation, OntologyTerm, Paper, Project
from db.session import session_scope
from services.events import StatusType
from services.research_pipeline import ResearchPipeline


def _arxiv_paper(paper_id: str, title: str, references=None) -> dict:
    return {
        "paper_id": paper_id,
        "title": title,
        "authors": ["Jane Doe"],
        "published": "2024-01-01",
        "pdf_url": f"https://arxiv.org/pdf/{paper_id}",
        "text": f"full text of {title}",
        "references": references or [{"title": "Attention Is All You Need"}],
    }


class StubExtractor:
    """Returns the JSON strings the real PDFExtractor would produce.

    Successive papers get different method/dataset pairings so the corpus has
    enough structure for gap detection to find anything — a corpus where every
    paper is identical has no untried combinations in it.
    """

    NORMALIZED: ClassVar[list[dict]] = [
        {
            "problem": "pose_estimation",
            "methods": [["diffusion", "Diffusion Models"]],
            "datasets": [["human36m", "Human3.6M"]],
            "limitations_explicit": [["occlusion", "Occlusion sensitivity"]],
            "future_work": [["temporal", "Add temporal modelling"]],
        },
        {
            "problem": "pose_estimation",
            "methods": [["transformer", "Transformer lifting"]],
            "datasets": [["mpii", "MPII"]],
            "limitations_explicit": [["occlusion", "Occlusion sensitivity"]],
            "future_work": [["temporal", "Extend to video"]],
        },
    ]

    def __init__(self, *, extraction=None, normalized=None):
        self._extraction = extraction if extraction is not None else {"problem": "p"}
        self._normalized = normalized
        self._index = 0

    def extract_from_raw_text(self, _text):
        return json.dumps(self._extraction)

    def normalize_extracted_parameters(self, _data):
        if self._normalized is not None:
            return json.dumps(self._normalized)
        payload = self.NORMALIZED[self._index % len(self.NORMALIZED)]
        self._index += 1
        return json.dumps(payload)


class StubArxivClient:
    def __init__(self, papers_by_topic):
        self.papers_by_topic = papers_by_topic
        self.calls = []

    def search_and_extract_papers(self, topic, *args):
        self.calls.append(topic)
        return self.papers_by_topic.get(topic, [])


class ProgressReportingArxivClient(StubArxivClient):
    """Fires the progress callback the way the real client does.

    The plain stub ignores it, so without this the draining loop in
    _process_topic would go uncovered.
    """

    def search_and_extract_papers(self, topic, *args):
        self.calls.append(topic)
        papers = self.papers_by_topic.get(topic, [])
        # Located by type rather than position, so a change to the
        # client's signature does not silently stop exercising this.
        callback = next((a for a in args if callable(a)), None)
        if callback:
            for i, _ in enumerate(papers, start=1):
                callback(i, len(papers))
        return papers


class StubTopicGenerator:
    def __init__(self, topics=None, suggestions=None):
        # `is None` rather than falsy: an empty list is a meaningful case
        # (expansion produced nothing) and must not fall back to the default.
        self._topics = ["topic-a", "topic-b"] if topics is None else topics
        self._suggestions = suggestions if suggestions is not None else [{"title": "S1"}]

    def generate_related_topics(self, _prompt, _n):
        return self._topics

    def generate_paper_suggestions(self, **_kwargs):
        return self._suggestions


class StubTrendsCreator:
    def __init__(self, *_args, **_kwargs):
        pass

    def create_all_trends(self):
        return {"timeline": {}, "methods": {}}

    def get_dataset_summary(self):
        return {"total_unique_datasets": 3, "datasets": []}


@pytest.fixture
def pipeline(monkeypatch):
    """A pipeline with every external dependency replaced."""

    def build(
        *,
        papers_by_topic=None,
        extractor=None,
        topics=None,
        suggestions=None,
        arxiv_client=None,
        topic_generator=None,
        **kwargs,
    ):
        papers_by_topic = papers_by_topic or {
            "topic-a": [_arxiv_paper("2301.001", "Paper A")],
            "topic-b": [_arxiv_paper("2301.002", "Paper B")],
        }
        arxiv = arxiv_client or StubArxivClient(papers_by_topic)
        generator = topic_generator or StubTopicGenerator(
            topics=topics, suggestions=suggestions
        )

        pipeline = ResearchPipeline(user_prompt="diffusion models", **kwargs)

        def build_clients():
            pipeline.llm_client = object()
            pipeline.arxiv_client = arxiv
            pipeline.topic_generator = generator
            pipeline.extractor = extractor or StubExtractor()

        monkeypatch.setattr(pipeline, "_build_clients", build_clients)
        monkeypatch.setattr(
            "services.research_pipeline.TrendsCreator", StubTrendsCreator
        )
        pipeline._stub_arxiv = arxiv
        return pipeline

    return build


async def _collect(pipeline):
    return [event async for event in pipeline.run()]


@pytest.mark.asyncio
class TestHappyPath:
    async def test_emits_a_completed_event_last(self, pipeline):
        events = await _collect(pipeline())
        assert events[-1].status == StatusType.COMPLETED

    async def test_completed_result_carries_the_full_payload(self, pipeline):
        events = await _collect(pipeline())
        result = events[-1].result

        assert result["total_papers"] == 2
        assert result["project_id"]
        assert result["topics"] == ["topic-a", "topic-b"]
        assert result["saved_filepath"].startswith("data/")
        assert result["suggested_papers"] == [{"title": "S1"}]
        assert result["datasets"]["total_unique_datasets"] == 3

    async def test_no_error_events_on_a_clean_run(self, pipeline):
        events = await _collect(pipeline())
        assert [e for e in events if e.status == StatusType.ERROR] == []

    async def test_persists_project_papers_and_citations(self, pipeline):
        p = pipeline()
        await _collect(p)

        with session_scope() as session:
            assert session.get(Project, p.project_id) is not None
            papers = session.scalars(
                select(Paper).where(Paper.project_id == p.project_id)
            ).all()
            # Two processed papers, plus the reference they share.
            assert len(papers) == 3
            assert sum(1 for x in papers if x.is_processed) == 2

            citations = session.scalar(
                select(func.count())
                .select_from(Citation)
                .where(Citation.project_id == p.project_id)
            )
            assert citations == 2

    async def test_records_ontology_terms(self, pipeline):
        p = pipeline()
        await _collect(p)

        with session_scope() as session:
            count = session.scalar(
                select(func.count())
                .select_from(OntologyTerm)
                .where(OntologyTerm.project_id == p.project_id)
            )
            # Four term-bearing fields per paper (methods, datasets,
            # limitations_explicit, future_work) across two papers. `problem`
            # is free text and deliberately not folded into the ontology.
            assert count == 8


@pytest.mark.asyncio
class TestTopicHandling:
    async def test_uses_provided_topics_without_calling_the_generator(self, pipeline):
        p = pipeline(
            papers_by_topic={"given": [_arxiv_paper("2301.001", "A")]},
            topics=["should-not-be-used"],
        )
        p.provided_topics = ["given"]

        events = await _collect(p)
        assert p._stub_arxiv.calls == ["given"]
        assert events[-1].result["topics"] == ["given"]

    async def test_falls_back_to_the_prompt_when_expansion_returns_nothing(
        self, pipeline
    ):
        p = pipeline(
            papers_by_topic={"diffusion models": [_arxiv_paper("2301.001", "A")]},
            topics=[],
        )
        events = await _collect(p)
        assert events[-1].result["topics"] == ["diffusion models"]


@pytest.mark.asyncio
class TestErrorContainment:
    async def test_one_unparseable_paper_does_not_end_the_run(self, pipeline):
        class BrokenOnFirst(StubExtractor):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def extract_from_raw_text(self, text):
                self.calls += 1
                if self.calls == 1:
                    return "not json at all"
                return super().extract_from_raw_text(text)

        p = pipeline(extractor=BrokenOnFirst())
        events = await _collect(p)

        assert any(e.status == StatusType.ERROR for e in events)
        # ...and the run still completes with the surviving paper.
        assert events[-1].status == StatusType.COMPLETED
        assert events[-1].result["total_papers"] == 1

    async def test_empty_llm_output_is_reported_not_swallowed(self, pipeline):
        class EmptyExtractor(StubExtractor):
            def extract_from_raw_text(self, _text):
                return "   "

        events = await _collect(pipeline(extractor=EmptyExtractor()))
        errors = [e for e in events if e.status == StatusType.ERROR]
        assert errors
        assert "Empty extraction result" in errors[0].message

    async def test_arxiv_rate_limit_aborts_the_whole_run(self, pipeline):
        from api.arxiv import ArxivRateLimitError

        class ThrottledClient(StubArxivClient):
            def search_and_extract_papers(self, topic, *args):
                self.calls.append(topic)
                raise ArxivRateLimitError("arXiv is throttling requests")

        throttled = ThrottledClient({})
        events = await _collect(pipeline(arxiv_client=throttled))

        # Every topic would fail identically, so it stops after the first
        # rather than grinding through the rest.
        assert events[-1].status == StatusType.ERROR
        assert "throttling" in events[-1].message
        assert len(throttled.calls) == 1

    async def test_failed_suggestions_do_not_fail_the_run(self, pipeline):
        class FailingGenerator(StubTopicGenerator):
            def generate_paper_suggestions(self, **_kwargs):
                raise RuntimeError("LLM unavailable")

        events = await _collect(pipeline(topic_generator=FailingGenerator()))
        assert events[-1].status == StatusType.COMPLETED
        assert events[-1].result["suggested_papers"] == []


@pytest.mark.asyncio
class TestFetchProgress:
    """Progress during the slowest stage.

    Search, download and extraction for a topic all happen inside one blocking
    call — minutes per paper. It used to be given no progress callback, so the
    stream went silent for the whole stage and the UI looked wedged.
    """

    async def test_emits_a_fetch_event_per_paper(self, pipeline):
        papers = {"topic-a": [_arxiv_paper("2301.001", "A1"), _arxiv_paper("2301.002", "A2")], "topic-b": []}
        p = pipeline(arxiv_client=ProgressReportingArxivClient(papers))
        events = await _collect(p)
        fetched = [e for e in events if "Fetched" in e.message]
        assert [e.result["fetched"] for e in fetched] == [1, 2]
        assert all(e.result["total"] == 2 for e in fetched)

    async def test_fetch_events_precede_the_papers_found_event(self, pipeline):
        papers = {"topic-a": [_arxiv_paper("2301.001", "A1")], "topic-b": []}
        p = pipeline(arxiv_client=ProgressReportingArxivClient(papers))
        events = await _collect(p)
        messages = [e.message for e in events]
        first_fetch = next(i for i, m in enumerate(messages) if "Fetched" in m)
        found = next(i for i, m in enumerate(messages) if m.startswith("Found "))
        assert first_fetch < found

    async def test_run_still_completes(self, pipeline):
        papers = {"topic-a": [_arxiv_paper("2301.001", "A1")], "topic-b": []}
        p = pipeline(arxiv_client=ProgressReportingArxivClient(papers))
        events = await _collect(p)
        assert events[-1].status == StatusType.COMPLETED
