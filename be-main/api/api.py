import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import AsyncGenerator, Optional, Any, List
from enum import Enum
import tempfile
import os
import uuid

from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse, FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, field_validator
from pylatex import Document, NoEscape

from core import (
    OpenRouterClient,
    PDFExtractor,
    ReferenceParameterExtractorFallback,
    create_llm_client,
)
from db.repositories import GraphRepository, OntologyRepository, ProjectRepository
from db.session import session_scope
from config import (
    OPENROUTER_API_KEY,
    GEMINI_API_KEY,
    RATE_LIMIT_COMPILE,
    RATE_LIMIT_RESEARCH,
    RATE_LIMIT_REVIEW,
)
from rate_limit import limiter
from api.arxiv import ArxivClient, TopicGenerator, ArxivRateLimitError
from api.review import ReviewManager
from utils.graph import TrendsCreator
from utils.latex import (
    MAX_LATEX_BYTES,
    LatexCompilationError,
    LatexUnavailableError,
    compile_latex_to_pdf,
)
from utils.paths import BASE_DIR, DATA_DIR, UnsafePathError, resolve_data_path
from gap_finder import GapFinder, Paper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

router = APIRouter()


def save_processed_papers_to_json(all_processed_papers: list, user_prompt: str) -> str:
    """
    Save all processed papers to a JSON file with timestamp.
    
    Args:
        all_processed_papers: List of processed paper dictionaries
        user_prompt: Original user prompt for filename
        
    Returns:
        str: Path to the saved JSON file, relative to the backend root. The
            client echoes this back on /api/create_review, so it is kept
            relative to stay stable across restarts and deploys.
    """
    # Anchored to the backend package so the path is stable no matter which
    # working directory the server was started from.
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Create filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Clean user prompt for filename (remove special chars, limit length)
    clean_prompt = "".join(c if c.isalnum() or c in (' ', '_') else '_' for c in user_prompt)
    clean_prompt = clean_prompt.replace(' ', '_')[:50]  # Limit to 50 chars
    filename = f"processed_papers_{clean_prompt}_{timestamp}.json"
    filepath = DATA_DIR / filename
    
    # Save to JSON
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump({
            "user_prompt": user_prompt,
            "timestamp": datetime.now().isoformat(),
            "total_papers": len(all_processed_papers),
            "papers": all_processed_papers
        }, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Saved {len(all_processed_papers)} processed papers to {filepath}")
    return str(filepath.relative_to(BASE_DIR))


class StatusType(str, Enum):
    """Fixed status types for SSE updates"""
    PROCESSING = "processing"  # Initial start, reading, initializing, extracting, normalizing, mapping
    SUCCESS = "success"  # Completed successfully
    ERROR = "error"  # Error occurred
    PROGRESS = "progress"  # Intermediate progress updates with results
    COMPLETED = "completed"  # Final completion with all results


class ResearchRequest(BaseModel):
    """Model for arXiv-based research request"""
    user_prompt: str  # User's research interest or topic
    num_topics: int = 10  # Number of topics to generate when none are provided
    topics: Optional[List[str]] = None  # Optional explicit topics to process
    papers_per_topic: int = 5  # Number of papers to fetch per topic
    use_reranking: bool = True  # Whether to use vector-based reranking (default: True)
    broad_search_multiplier: int = 4  # Multiplier for broad search when reranking (fewer arXiv calls)

    @field_validator("user_prompt")
    @classmethod
    def user_prompt_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("user_prompt must not be empty")
        return stripped

    @field_validator("num_topics", "papers_per_topic", "broad_search_multiplier")
    @classmethod
    def counts_must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("must be at least 1")
        return v


class ReviewRequest(BaseModel):
    """Model for review creation request"""
    saved_filepath: str  # Path to the processed papers JSON file
    paper_index: int  # Index of the paper to review
    paper_info: dict  # Paper metadata (title, keywords, abstract)

    @field_validator("saved_filepath")
    @classmethod
    def filepath_must_stay_in_data_dir(cls, v: str) -> str:
        # The client echoes back a path it was handed earlier, so reject
        # anything outside the data directory at the boundary — before the
        # pipeline spins up — rather than at open() time.
        try:
            resolve_data_path(v)
        except UnsafePathError as exc:
            raise ValueError(str(exc)) from exc
        return v

    @field_validator("paper_index")
    @classmethod
    def paper_index_not_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("paper_index must not be negative")
        return v


class SSEUpdate(BaseModel):
    """Model for SSE updates sent to the frontend"""
    status: StatusType
    message: str
    result: Optional[dict[str, Any]] = None
    
    def to_sse(self) -> str:
        """Convert to SSE format"""
        return f"data: {self.model_dump_json()}\n\n"


async def arxiv_research_stream(
    user_prompt: str,
    topics: Optional[List[str]],
    num_topics: int,
    papers_per_topic: int,
    use_reranking: bool,
    broad_search_multiplier: int
) -> AsyncGenerator[str, None]:
    """
    Stream arXiv research extraction progress as SSE events.
    
    This function:
    1. Uses provided topics or generates them via LLM when none are supplied
    2. Searches arXiv for papers on each topic
    3. Downloads and extracts text from papers
    4. Processes each paper through the extraction pipeline
    """
    try:
        logger.info(f"Starting arXiv research stream for prompt: '{user_prompt}'")
        provided_topics = topics or []
        logger.info(
            "Parameters: provided_topics=%s, num_topics=%s, papers_per_topic=%s",
            len(provided_topics),
            num_topics,
            papers_per_topic,
        )

        project_id = uuid.uuid4().hex
        
        yield SSEUpdate(
            status=StatusType.PROCESSING,
            message="Initializing arXiv research pipeline..."
        ).to_sse()
        await asyncio.sleep(0)
        
        # Initialize clients (auto-selects Gemini when GEMINI_API_KEY is set)
        llm_client = create_llm_client()

        extractor_fallback = ReferenceParameterExtractorFallback()

        arxiv_client = ArxivClient(
            max_results_per_topic=papers_per_topic,
            reference_extractor_fallback=extractor_fallback,
            openrouter_client=llm_client
            )
        topic_generator = TopicGenerator(llm_client)
        extractor = PDFExtractor(llm_client=llm_client)

        loop = asyncio.get_event_loop()

        # The project row anchors every paper, author, edge and ontology term
        # written below, so it has to exist before any of them.
        with session_scope() as session:
            ProjectRepository(session).create(project_id, user_prompt)
        if provided_topics:
            topics_to_process = provided_topics
            yield SSEUpdate(
                status=StatusType.PROGRESS,
                message=f"Processing {len(topics_to_process)} provided topic(s)",
                result={"topics": topics_to_process}
            ).to_sse()
            await asyncio.sleep(0)
        else:
            yield SSEUpdate(
                status=StatusType.PROCESSING,
                message=f"Generating {num_topics} related research topics..."
            ).to_sse()
            await asyncio.sleep(0)

            generated_topics = await loop.run_in_executor(
                None,
                topic_generator.generate_related_topics,
                user_prompt,
                num_topics,
            )

            topics_to_process = generated_topics or [user_prompt]

            yield SSEUpdate(
                status=StatusType.PROGRESS,
                message=f"Generated {len(topics_to_process)} topics",
                result={"topics": topics_to_process}
            ).to_sse()
            await asyncio.sleep(0)
        
        # Process each topic
        all_processed_papers = []
        
        for topic_idx, topic in enumerate(topics_to_process):
            logger.info(
                "Processing topic %s/%s: '%s'",
                topic_idx + 1,
                len(topics_to_process),
                topic,
            )
            
            yield SSEUpdate(
                status=StatusType.PROCESSING,
                message=f"Searching arXiv for topic {topic_idx + 1}/{len(topics_to_process)}: {topic}"
            ).to_sse()
            await asyncio.sleep(0)
            
            # Search and download papers
            logger.debug(f"Searching and extracting papers for topic: '{topic}'")
            
            # Log reranking status
            if use_reranking:
                search_count = papers_per_topic * broad_search_multiplier
                logger.info(
                    f"Using vector-based reranking: searching {search_count} papers, "
                    f"will rerank and select top {papers_per_topic}"
                )
            
            try:
                papers = await loop.run_in_executor(
                    None,
                    arxiv_client.search_and_extract_papers,
                    topic,
                    papers_per_topic,
                    None,  # download_dir
                    None,  # max_pages - extract all pages
                    False,  # cleanup - keep downloaded PDFs
                    1.0,   # delay_between_downloads
                    None,  # progress_callback
                    use_reranking,
                    broad_search_multiplier
                )
            except ArxivRateLimitError as e:
                # arXiv is throttling/unavailable; every topic will fail the same
                # way, so report a clear error and stop instead of hanging.
                logger.error(f"Aborting research run: {e}")
                yield SSEUpdate(
                    status=StatusType.ERROR,
                    message=str(e)
                ).to_sse()
                await asyncio.sleep(0)
                return

            logger.info(f"Found and extracted {len(papers)} papers for topic: '{topic}'")
            
            yield SSEUpdate(
                status=StatusType.PROGRESS,
                message=f"Found {len(papers)} papers for topic: {topic}",
                result={"topic": topic, "paper_count": len(papers)}
            ).to_sse()
            await asyncio.sleep(0)
            
            # Process each paper through the extraction pipeline
            for paper_idx, paper_data in enumerate(papers):
                try:
                    paper_id = paper_data['paper_id']
                    paper_title = paper_data['title']
                    
                    logger.info(f"Processing paper {paper_idx + 1}/{len(papers)} for topic '{topic}': {paper_title} (ID: {paper_id})")
                    
                    yield SSEUpdate(
                        status=StatusType.PROCESSING,
                        message=f"Processing paper {paper_idx + 1}/{len(papers)}: {paper_title[:50]}..."
                    ).to_sse()
                    await asyncio.sleep(0)
                    
                    # Extract parameters from paper text
                    logger.debug(f"Extracting parameters from paper {paper_id}")
                    extraction_result = await loop.run_in_executor(
                        None, 
                        extractor.extract_from_raw_text, 
                        paper_data['text']
                    )
                    
                    # Validate extraction result before parsing
                    if not extraction_result or not extraction_result.strip():
                        raise ValueError(f"Empty extraction result from LLM for paper {paper_id}")
                    
                    try:
                        extraction_data = json.loads(extraction_result)
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse extraction result for paper {paper_id}. Error: {e}")
                        logger.error(f"Raw result (first 500 chars): {extraction_result[:500]}")
                        raise ValueError(f"Invalid JSON in extraction result: {e}")
                    
                    logger.debug(f"Extraction complete for paper {paper_id}")
                    
                    # Normalize extracted parameters
                    logger.debug(f"Normalizing parameters for paper {paper_id}")
                    normalized_result = await loop.run_in_executor(
                        None, 
                        extractor.normalize_extracted_parameters, 
                        extraction_data
                    )
                    
                    # Validate normalization result before parsing
                    if not normalized_result or not normalized_result.strip():
                        raise ValueError(f"Empty normalization result from LLM for paper {paper_id}")
                    
                    try:
                        normalized_data = json.loads(normalized_result)
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse normalization result for paper {paper_id}. Error: {e}")
                        logger.error(f"Raw result (first 500 chars): {normalized_result[:500]}")
                        raise ValueError(f"Invalid JSON in normalization result: {e}")
                    
                    logger.debug(f"Normalization complete for paper {paper_id}")
                    
                    # Map to ontology
                    logger.debug(f"Mapping to ontology for paper {paper_id}")
                    paper_id = paper_data['paper_id']

                    def map_ontology(normalized=normalized_data, pid=paper_id):
                        # A short transaction per paper: a run holding one open
                        # for its full duration would block every other writer.
                        with session_scope() as session:
                            OntologyRepository(session, project_id).map_paper(
                                normalized, pid
                            )

                    await loop.run_in_executor(None, map_ontology)
                    logger.debug(f"Ontology mapping complete for paper {paper_id}")
                    
                    processed_paper = {
                        "paper_id": paper_id,
                        "title": paper_data['title'],
                        "authors": paper_data['authors'],
                        "published": paper_data['published'],
                        "pdf_url": paper_data['pdf_url'],
                        "references": paper_data.get('references', []),
                        "topic": topic,
                        "extraction": extraction_data,
                        "normalized": normalized_data
                    }

                    all_processed_papers.append(processed_paper)
                    
                    logger.info(f"Successfully processed paper {paper_id}: {paper_title}")
                    
                    yield SSEUpdate(
                        status=StatusType.PROGRESS,
                        message=f"Completed paper: {paper_data['title'][:50]}",
                        result={"processed_paper": processed_paper}
                    ).to_sse()
                    await asyncio.sleep(0)
                    
                except Exception as e:
                    error_msg = f"Error processing paper {paper_data.get('title', 'unknown')}: {str(e)}"
                    logger.error(error_msg)
                    yield SSEUpdate(
                        status=StatusType.ERROR,
                        message=error_msg
                    ).to_sse()
                    await asyncio.sleep(0)
                    continue
        
        # Save all processed papers to JSON file
        logger.info(f"Saving {len(all_processed_papers)} processed papers to JSON...")
        saved_filepath = save_processed_papers_to_json(all_processed_papers, user_prompt)

        yield SSEUpdate(
            status=StatusType.PROCESSING,
            message="Saving Graph..."
        ).to_sse()
        await asyncio.sleep(0)
        
        def persist_graph():
            with session_scope() as session:
                GraphRepository(session, project_id).build_from_processed_papers(
                    all_processed_papers
                )

        # Hundreds of inserts for a full run — keep them off the event loop so
        # concurrent SSE streams keep flowing.
        await loop.run_in_executor(None, persist_graph)

        yield SSEUpdate(
            status=StatusType.PROCESSING,
            message="Graph updated successfully."
        ).to_sse()

        yield SSEUpdate(
            status=StatusType.PROCESSING,
            message="Generating trend analyses and visualization data..."
        ).to_sse()
        await asyncio.sleep(0)
        
        logger.info("Generating trend analysis data...")
        trends_data = {
            "user_prompt": user_prompt,
            "timestamp": datetime.now().isoformat(),
            "total_papers": len(all_processed_papers),
            "papers": all_processed_papers
        }
        
        # TrendsCreator still consumes the nested ontology shape, so rebuild it
        # from the rows this run contributed.
        with session_scope() as session:
            ontology = OntologyRepository(session, project_id).as_dict()

        # Pass LLM client to TrendsCreator for dataset validation
        trends_creator = TrendsCreator(trends_data, ontology, llm_client=llm_client)
        trends = await loop.run_in_executor(None, trends_creator.create_all_trends)
        
        logger.info(f"Generated trend analysis with {len(trends)} chart types")
        
        yield SSEUpdate(
            status=StatusType.PROGRESS,
            message=f"Generated trend analyses for visualization",
            result={"trends_generated": len(trends)}
        ).to_sse()
        await asyncio.sleep(0)
        
        # Generate dataset summary with validation and pie chart
        logger.info("Generating comprehensive dataset summary with validation...")
        dataset_summary = await loop.run_in_executor(None, trends_creator.get_dataset_summary)
        logger.info(f"Generated dataset summary with {dataset_summary['total_unique_datasets']} validated unique datasets")
        
        yield SSEUpdate(
            status=StatusType.PROGRESS,
            message=f"Compiled dataset information for {dataset_summary['total_unique_datasets']} unique datasets",
            result={"datasets_compiled": dataset_summary['total_unique_datasets']}
        ).to_sse()
        await asyncio.sleep(0)
        
        # Generate suggested papers using gap finder
        yield SSEUpdate(
            status=StatusType.PROCESSING,
            message="Analyzing research gaps and generating paper suggestions..."
        ).to_sse()
        await asyncio.sleep(0)
        
        logger.info("Running gap analysis to generate suggested papers...")
        
        def generate_suggested_papers():
            # Convert processed papers to Paper objects for gap finder
            papers = []
            for paper in all_processed_papers:
                try:
                    normalized = paper.get('normalized', {})
                    paper_obj = Paper.from_canonical({
                        "paper_id": paper.get('paper_id', ''),
                        "problem": normalized.get('problem', ''),
                        "methods": normalized.get('methods', []),
                        "datasets": normalized.get('datasets', []),
                        "limitations_implied": normalized.get('limitations_implied', []),
                        "limitations_explicit": normalized.get('limitations_explicit', []),
                        "future_work": normalized.get('future_work', [])
                    })
                    papers.append(paper_obj)
                except Exception as e:
                    logger.warning(f"Failed to convert paper {paper.get('paper_id', 'unknown')} for gap analysis: {e}")
                    continue
            
            if not papers:
                logger.warning("No papers available for gap analysis")
                return []
            
            # Run gap finder with loose mode for better suggestions
            gap_finder = GapFinder(
                papers,
                method_transfer_min_score=0,
                dataset_transfer_min_score=0,
                limitation_pressure_threshold=1,
                limitation_ratio_threshold=0.5,
                future_work_min_mentions=1,
                loose_mode=True
            )
            
            # Find all types of gaps (top 5 of each type for LLM processing)
            gaps = gap_finder.find_all_gaps(top_k_per_type=5)
            
            if not gaps:
                logger.warning("No research gaps found")
                return []
            
            # Convert gaps to dict format for paper generator
            gaps_dict = []
            for gap in gaps:
                gap_dict = {
                    "gap_type": gap.gap_type,
                    "problem": gap.problem,
                    "score": gap.score,
                    "method": gap.method,
                    "dataset": gap.dataset,
                    "limitation": gap.limitation,
                    "future_work": gap.future_work_label
                }
                gaps_dict.append(gap_dict)
            
            # Use TopicGenerator to create paper suggestions from gaps
            try:
                suggested_papers = topic_generator.generate_paper_suggestions(
                    gaps=gaps_dict,
                    user_prompt=user_prompt,
                    num_papers=min(10, len(gaps))
                )
                logger.info(f"Generated {len(suggested_papers)} paper suggestions")
                return suggested_papers
            except Exception as e:
                logger.error(f"Failed to generate paper suggestions: {e}")
                return []
        
        suggested_papers = await loop.run_in_executor(None, generate_suggested_papers)
        
        logger.info(f"Generated {len(suggested_papers)} paper suggestions from gap analysis")
        
        yield SSEUpdate(
            status=StatusType.PROGRESS,
            message=f"Generated {len(suggested_papers)} paper suggestions based on research gaps",
            result={"suggested_papers_count": len(suggested_papers)}
        ).to_sse()
        await asyncio.sleep(0)
        
        # Final summary
        logger.info(
            "arXiv research pipeline completed: %s papers processed across %s topics",
            len(all_processed_papers),
            len(topics_to_process),
        )
        
        yield SSEUpdate(
            status=StatusType.COMPLETED,
            message=(
                f"Research pipeline completed. Processed {len(all_processed_papers)} papers across "
                f"{len(topics_to_process)} topics. Results saved to {saved_filepath}."
            ),
            result={
                "user_prompt": user_prompt,
                "topics": topics_to_process,
                "total_papers": len(all_processed_papers),
                "processed_papers": all_processed_papers,
                "saved_filepath": saved_filepath,
                "trends": trends,
                "datasets": dataset_summary,
                "suggested_papers": suggested_papers,
                "project_id": project_id,
            }
        ).to_sse()
        await asyncio.sleep(0)
        
    except Exception as e:
        logger.error(f"Pipeline error: {str(e)}", exc_info=True)
        yield SSEUpdate(
            status=StatusType.ERROR,
            message=f"Pipeline error: {str(e)}"
        ).to_sse()


@router.post("/research")
@limiter.limit(RATE_LIMIT_RESEARCH)
async def research_endpoint(request: Request, payload: ResearchRequest):
    """
    SSE endpoint for arXiv-based research extraction.

    Rate limited hard: one call fans out to dozens of arXiv downloads and a
    long chain of LLM requests.

    This endpoint:
    1. Takes a user's research prompt (and optional topics) and generates topics via LLM when needed
    2. Searches arXiv for papers on each topic
    3. Downloads, extracts, and processes papers through the extraction pipeline
    4. Generates trend analysis and visualization data
    5. Streams progress updates via SSE
    
    The final COMPLETED message includes a 'trends' key with all visualization data
    ready for MUI X Charts in the React frontend.
    """
    return StreamingResponse(
        arxiv_research_stream(
            user_prompt=payload.user_prompt,
            topics=payload.topics,
            num_topics=payload.num_topics,
            papers_per_topic=payload.papers_per_topic,
            use_reranking=payload.use_reranking,
            broad_search_multiplier=payload.broad_search_multiplier
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


async def create_review_stream(
    saved_filepath: str,
    paper_index: int,
    paper_info: dict,
    num_base_papers: int = 2,
    num_arxiv_papers_per_variant: int = 5,
    num_relevant_chunks: int = 50
) -> AsyncGenerator[str, None]:
    """
    Stream review generation progress as SSE events.
    
    This function provides real-time updates for:
    1. Loading and selecting base papers
    2. Searching arXiv with diverse strategies
    3. Downloading and extracting PDFs
    4. Creating chunks with smart prioritization
    5. Selecting relevant chunks with weighted similarity
    6. Generating LaTeX review
    7. Saving review and metadata
    """
    try:
        yield SSEUpdate(
            status=StatusType.PROCESSING,
            message="Initializing literature review generation pipeline..."
        ).to_sse()
        await asyncio.sleep(0)
        
        # Initialize clients (auto-selects Gemini when GEMINI_API_KEY is set)
        llm_client = create_llm_client()

        extractor_fallback = ReferenceParameterExtractorFallback()

        arxiv_client = ArxivClient(
            max_results_per_topic=5,
            reference_extractor_fallback=extractor_fallback,
            openrouter_client=llm_client
        )
        
        # Initialize review manager
        review_manager = ReviewManager(
            openrouter_client=llm_client,
            arxiv_client=arxiv_client
        )
        
        yield SSEUpdate(
            status=StatusType.PROCESSING,
            message="Clients initialized. Starting review generation..."
        ).to_sse()
        await asyncio.sleep(0)
        
        loop = asyncio.get_event_loop()
        
        # Create review using generator - stream events in real-time
        final_result = None
        generator = review_manager.create_review_with_progress(
            saved_filepath,
            paper_index,
            paper_info,
            num_base_papers,
            num_arxiv_papers_per_variant,
            num_relevant_chunks,
            None  # No callback needed, we're using the generator
        )
        
        # Iterate through the generator in executor to avoid blocking
        def get_next_event():
            try:
                return next(generator)
            except StopIteration as e:
                return e.value
        
        while True:
            event = await loop.run_in_executor(None, get_next_event)
            
            # Check if we got the final return value (a dict with "status" key)
            if event is None:
                break
            elif isinstance(event, dict) and "status" in event and event["status"] == "success":
                # This is the final result
                final_result = event
                break
            
            # This is a progress event
            status_type = StatusType(event["status"])
            
            yield SSEUpdate(
                status=status_type,
                message=event["message"],
                result=event.get("result")
            ).to_sse()
            await asyncio.sleep(0)
        
        if final_result:
            yield SSEUpdate(
                status=StatusType.COMPLETED,
                message="Literature review generated successfully!",
                result=final_result
            ).to_sse()
            await asyncio.sleep(0)
        
    except Exception as e:
        logger.error(f"Review generation error: {str(e)}", exc_info=True)
        yield SSEUpdate(
            status=StatusType.ERROR,
            message=f"Review generation failed: {str(e)}"
        ).to_sse()


@router.post("/create_review")
@limiter.limit(RATE_LIMIT_REVIEW)
async def create_review_endpoint(request: Request, payload: ReviewRequest):
    """
    SSE endpoint for comprehensive literature review generation.
    
    This endpoint streams real-time progress updates as it:
    1. Loads base papers from the saved processed dataset
    2. Searches arXiv for additional papers with diverse strategies (date, relevance, updates)
    3. Downloads and extracts text from PDFs with smart sectioning (first/last pages)
    4. Creates text chunks with priority weighting for key sections
    5. Selects most relevant chunks using weighted semantic similarity
    6. Generates LaTeX review using LLM
    7. Saves review and metadata
    
    Request body:
    - saved_filepath: Path to the processed papers JSON file
    - paper_index: Index of the paper in the processed dataset
    - paper_info: Dictionary containing paper metadata (title, keywords, abstract, topic)
    
    The final COMPLETED message includes:
    - LaTeX review content
    - Bibliography with all cited papers
    - Metadata about the review generation process
    - Statistics on papers and chunks processed
    """
    return StreamingResponse(
        create_review_stream(
            saved_filepath=payload.saved_filepath,
            paper_index=payload.paper_index,
            paper_info=payload.paper_info,
            num_base_papers=2,
            num_arxiv_papers_per_variant=5,
            num_relevant_chunks=50
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/reviews/{review_id}")
async def get_review_endpoint(review_id: str):
    """
    Retrieve a specific review by ID.
    
    Args:
        review_id: Unique identifier for the review (timestamp)
    
    Returns:
        Review data including LaTeX content and metadata
    """
    try:
        # Initialize a minimal review manager (doesn't need full clients for retrieval)
        llm_client = create_llm_client()

        review_manager = ReviewManager(
            openrouter_client=llm_client,
            arxiv_client=None
        )

        review = review_manager.get_review(review_id)
        
        if not review:
            raise HTTPException(status_code=404, detail=f"Review not found: {review_id}")
        
        return review
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving review: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve review: {str(e)}")


@router.get("/reviews")
async def list_reviews_endpoint(saved_filepath: Optional[str] = None):
    """
    List all reviews, optionally filtered by source dataset.
    
    Query Parameters:
        saved_filepath: Optional filter by source dataset filepath
    
    Returns:
        List of review metadata dictionaries
    """
    try:
        # Initialize a minimal review manager
        llm_client = create_llm_client()

        review_manager = ReviewManager(
            openrouter_client=llm_client,
            arxiv_client=None
        )

        reviews = review_manager.list_reviews(saved_filepath)
        
        return {
            "reviews": reviews,
            "total": len(reviews)
        }
        
    except Exception as e:
        logger.error(f"Error listing reviews: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list reviews: {str(e)}")


class LatexCompileRequest(BaseModel):
    """Model for LaTeX compilation request"""
    latex_text: str  # Raw LaTeX content to compile

    @field_validator("latex_text")
    @classmethod
    def latex_text_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("latex_text must not be empty")
        if len(v.encode("utf-8")) > MAX_LATEX_BYTES:
            raise ValueError(
                f"latex_text exceeds the {MAX_LATEX_BYTES} byte limit"
            )
        return v


@router.post("/latex/compile")
@limiter.limit(RATE_LIMIT_COMPILE)
async def compile_latex_endpoint(request: Request, payload: LatexCompileRequest):
    """
    Compile LaTeX text to PDF and return the PDF file.

    Compilation is sandboxed — see `utils.latex` for what that covers.

    Request Body:
        latex_text: Raw LaTeX content to compile

    Returns:
        PDF file

    Status codes:
        400: the document could not be compiled
        503: no TeX toolchain is installed on this server
    """
    loop = asyncio.get_event_loop()

    try:
        # pdflatex is a blocking subprocess run three times over; keep it off
        # the event loop so it cannot stall concurrent SSE streams.
        pdf_content = await loop.run_in_executor(
            None, compile_latex_to_pdf, payload.latex_text
        )
    except LatexUnavailableError as e:
        logger.error("LaTeX toolchain unavailable: %s", e)
        raise HTTPException(status_code=503, detail=str(e))
    except LatexCompilationError as e:
        logger.warning("LaTeX compilation failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error compiling LaTeX: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to compile LaTeX: {str(e)}")

    # FileResponse streams from disk, so the file has to outlive this function
    # and is removed by the background task once the response is sent.
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
        tmp_file.write(pdf_content)
        tmp_file_path = tmp_file.name

    def cleanup():
        try:
            os.unlink(tmp_file_path)
        except OSError:
            pass

    return FileResponse(
        tmp_file_path,
        media_type="application/pdf",
        filename="compiled.pdf",
        background=BackgroundTask(cleanup)
    )


@router.get("/graph/{project_id}/")
async def get_graph_endpoint(project_id: str):
    """
    Endpoint to retrieve the reference graph for a given project ID.
    Returns nodes and edges as stored in the graph (including authors).
    """
    try:
        with session_scope() as session:
            graph_repo = GraphRepository(session, project_id)

            if graph_repo.is_empty():
                raise HTTPException(
                    status_code=404,
                    detail=f"Graph not found for project {project_id}",
                )

            graph_data = graph_repo.to_cytoscape()

        return {
            "status": "success",
            "project_id": project_id,
            "graph_data": graph_data
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving graph: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve graph: {str(e)}")