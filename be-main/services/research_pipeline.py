"""The arXiv research pipeline.

Topic expansion → arXiv search → PDF extraction → normalization → ontology
mapping → citation graph → trends → gap analysis.

Emits :class:`PipelineEvent` rather than writing to a transport, so the SSE
endpoint is a translation layer and nothing here knows about HTTP.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any, AsyncGenerator, Optional

from api.arxiv import ArxivClient, ArxivRateLimitError, TopicGenerator
from core import PDFExtractor, ReferenceParameterExtractorFallback, create_llm_client
from db.repositories import GraphRepository, OntologyRepository, ProjectRepository
from db.session import session_scope
from services import gaps as gap_service
from services.artifacts import save_processed_papers
from services.events import PipelineEvent, completed, error, processing, progress
from utils.graph import TrendsCreator

logger = logging.getLogger(__name__)


class ResearchPipeline:
    """One research run.

    Constructed per request; not reusable, since it accumulates the run's
    papers as it goes.
    """

    def __init__(
        self,
        *,
        user_prompt: str,
        topics: Optional[list[str]] = None,
        num_topics: int = 10,
        papers_per_topic: int = 5,
        use_reranking: bool = True,
        broad_search_multiplier: int = 4,
    ) -> None:
        self.user_prompt = user_prompt
        self.provided_topics = topics or []
        self.num_topics = num_topics
        self.papers_per_topic = papers_per_topic
        self.use_reranking = use_reranking
        self.broad_search_multiplier = broad_search_multiplier

        self.project_id = uuid.uuid4().hex
        self.processed_papers: list[dict[str, Any]] = []

    # -- setup -------------------------------------------------------------

    def _build_clients(self) -> None:
        # Auto-selects Gemini when GEMINI_API_KEY is set.
        self.llm_client = create_llm_client()
        self.arxiv_client = ArxivClient(
            max_results_per_topic=self.papers_per_topic,
            reference_extractor_fallback=ReferenceParameterExtractorFallback(),
            openrouter_client=self.llm_client,
        )
        self.topic_generator = TopicGenerator(self.llm_client)
        self.extractor = PDFExtractor(llm_client=self.llm_client)

    async def _run_blocking(self, fn, *args):
        """Push blocking work onto the executor, off the event loop."""
        return await asyncio.get_event_loop().run_in_executor(None, fn, *args)

    # -- stages ------------------------------------------------------------

    async def _resolve_topics(self) -> AsyncGenerator[PipelineEvent, None]:
        if self.provided_topics:
            self.topics_to_process = self.provided_topics
            yield progress(
                f"Processing {len(self.topics_to_process)} provided topic(s)",
                {"topics": self.topics_to_process},
            )
            return

        yield processing(f"Generating {self.num_topics} related research topics...")

        generated = await self._run_blocking(
            self.topic_generator.generate_related_topics,
            self.user_prompt,
            self.num_topics,
        )
        # Fall back to the raw prompt so a failed expansion still searches.
        self.topics_to_process = generated or [self.user_prompt]

        yield progress(
            f"Generated {len(self.topics_to_process)} topics",
            {"topics": self.topics_to_process},
        )

    async def _process_paper(self, paper_data: dict[str, Any], topic: str) -> dict[str, Any]:
        """Extract → normalize → map one paper. Raises on unusable LLM output."""
        paper_id = paper_data["paper_id"]

        extraction_data = self._parse_llm_json(
            await self._run_blocking(
                self.extractor.extract_from_raw_text, paper_data["text"]
            ),
            stage="extraction",
            paper_id=paper_id,
        )

        normalized_data = self._parse_llm_json(
            await self._run_blocking(
                self.extractor.normalize_extracted_parameters, extraction_data
            ),
            stage="normalization",
            paper_id=paper_id,
        )

        def map_ontology():
            # A short transaction per paper: one held open for the whole run
            # would block every other writer for minutes.
            with session_scope() as session:
                OntologyRepository(session, self.project_id).map_paper(
                    normalized_data, paper_id
                )

        await self._run_blocking(map_ontology)

        return {
            "paper_id": paper_id,
            "title": paper_data["title"],
            "authors": paper_data["authors"],
            "published": paper_data["published"],
            "pdf_url": paper_data["pdf_url"],
            "references": paper_data.get("references", []),
            "topic": topic,
            "extraction": extraction_data,
            "normalized": normalized_data,
        }

    @staticmethod
    def _parse_llm_json(raw: str, *, stage: str, paper_id: str) -> dict[str, Any]:
        """Parse a JSON response, with the failure attributable to a stage."""
        if not raw or not raw.strip():
            raise ValueError(f"Empty {stage} result from LLM for paper {paper_id}")

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error(
                "Failed to parse %s result for paper %s: %s", stage, paper_id, exc
            )
            logger.error("Raw result (first 500 chars): %s", raw[:500])
            raise ValueError(f"Invalid JSON in {stage} result: {exc}") from exc

    async def _process_topic(
        self, topic: str, index: int
    ) -> AsyncGenerator[PipelineEvent, None]:
        total = len(self.topics_to_process)
        yield processing(f"Searching arXiv for topic {index + 1}/{total}: {topic}")

        if self.use_reranking:
            logger.info(
                "Using vector-based reranking: searching %s papers, keeping top %s",
                self.papers_per_topic * self.broad_search_multiplier,
                self.papers_per_topic,
            )

        papers = await self._run_blocking(
            self.arxiv_client.search_and_extract_papers,
            topic,
            self.papers_per_topic,
            None,  # download_dir
            None,  # max_pages — extract all
            False,  # cleanup — keep downloaded PDFs
            1.0,  # delay_between_downloads
            None,  # progress_callback
            self.use_reranking,
            self.broad_search_multiplier,
        )

        logger.info("Found and extracted %s papers for topic '%s'", len(papers), topic)
        yield progress(
            f"Found {len(papers)} papers for topic: {topic}",
            {"topic": topic, "paper_count": len(papers)},
        )

        for paper_idx, paper_data in enumerate(papers):
            title = paper_data.get("title", "unknown")
            try:
                yield processing(
                    f"Processing paper {paper_idx + 1}/{len(papers)}: {title[:50]}..."
                )
                processed = await self._process_paper(paper_data, topic)
            except Exception as exc:
                # One bad paper should not end the run.
                logger.error("Error processing paper %s: %s", title, exc)
                yield error(f"Error processing paper {title}: {exc}")
                continue

            self.processed_papers.append(processed)
            yield progress(
                f"Completed paper: {title[:50]}", {"processed_paper": processed}
            )

    async def _persist_graph(self) -> AsyncGenerator[PipelineEvent, None]:
        yield processing("Saving Graph...")

        def build():
            with session_scope() as session:
                GraphRepository(session, self.project_id).build_from_processed_papers(
                    self.processed_papers
                )

        # Hundreds of inserts for a full run; keep them off the event loop.
        await self._run_blocking(build)
        yield processing("Graph updated successfully.")

    async def _analyze(self) -> AsyncGenerator[PipelineEvent, None]:
        yield processing("Generating trend analyses and visualization data...")

        with session_scope() as session:
            ontology = OntologyRepository(session, self.project_id).as_dict()

        trends_creator = TrendsCreator(
            {
                "user_prompt": self.user_prompt,
                "timestamp": datetime.now().isoformat(),
                "total_papers": len(self.processed_papers),
                "papers": self.processed_papers,
            },
            ontology,
            llm_client=self.llm_client,
        )

        self.trends = await self._run_blocking(trends_creator.create_all_trends)
        yield progress(
            "Generated trend analyses for visualization",
            {"trends_generated": len(self.trends)},
        )

        self.dataset_summary = await self._run_blocking(
            trends_creator.get_dataset_summary
        )
        total_datasets = self.dataset_summary["total_unique_datasets"]
        yield progress(
            f"Compiled dataset information for {total_datasets} unique datasets",
            {"datasets_compiled": total_datasets},
        )

        yield processing("Analyzing research gaps and generating paper suggestions...")
        self.suggested_papers = await self._run_blocking(
            gap_service.generate_suggested_papers,
            self.processed_papers,
            self.user_prompt,
            self.topic_generator,
        )
        yield progress(
            f"Generated {len(self.suggested_papers)} paper suggestions "
            "based on research gaps",
            {"suggested_papers_count": len(self.suggested_papers)},
        )

    # -- entry point -------------------------------------------------------

    async def run(self) -> AsyncGenerator[PipelineEvent, None]:
        """Execute the pipeline, emitting progress as it goes."""
        try:
            logger.info("Starting research pipeline for prompt: %r", self.user_prompt)
            yield processing("Initializing arXiv research pipeline...")

            self._build_clients()

            # The project row anchors every paper, author, edge and ontology
            # term written below, so it must exist before any of them.
            with session_scope() as session:
                ProjectRepository(session).create(self.project_id, self.user_prompt)

            async for event in self._resolve_topics():
                yield event

            for index, topic in enumerate(self.topics_to_process):
                logger.info(
                    "Processing topic %s/%s: %r",
                    index + 1,
                    len(self.topics_to_process),
                    topic,
                )
                try:
                    async for event in self._process_topic(topic, index):
                        yield event
                except ArxivRateLimitError as exc:
                    # arXiv is throttling; every remaining topic fails the same
                    # way, so stop rather than grinding through them.
                    logger.error("Aborting research run: %s", exc)
                    yield error(str(exc))
                    return

            logger.info("Saving %s processed papers", len(self.processed_papers))
            saved_filepath = save_processed_papers(
                self.processed_papers, self.user_prompt
            )

            async for event in self._persist_graph():
                yield event

            async for event in self._analyze():
                yield event

            logger.info(
                "Pipeline completed: %s papers across %s topics",
                len(self.processed_papers),
                len(self.topics_to_process),
            )
            yield completed(
                f"Research pipeline completed. Processed {len(self.processed_papers)} "
                f"papers across {len(self.topics_to_process)} topics. "
                f"Results saved to {saved_filepath}.",
                {
                    "user_prompt": self.user_prompt,
                    "topics": self.topics_to_process,
                    "total_papers": len(self.processed_papers),
                    "processed_papers": self.processed_papers,
                    "saved_filepath": saved_filepath,
                    "trends": self.trends,
                    "datasets": self.dataset_summary,
                    "suggested_papers": self.suggested_papers,
                    "project_id": self.project_id,
                },
            )

        except Exception as exc:
            logger.error("Pipeline error: %s", exc, exc_info=True)
            yield error(f"Pipeline error: {exc}")
