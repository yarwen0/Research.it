"""HTTP routes.

Handlers here validate input, delegate to `services/`, and shape the response.
Pipeline logic lives in the service layer so it is testable without a client
and movable behind a job queue without touching these.
"""

import asyncio
import logging
import os
import tempfile
from typing import AsyncGenerator, Optional, Any, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, field_validator

from core import create_llm_client
from db.repositories import GraphRepository
from db.session import session_scope
from config import (
    RATE_LIMIT_COMPILE,
    RATE_LIMIT_RESEARCH,
    RATE_LIMIT_REVIEW,
)
from rate_limit import limiter
from api.arxiv import ArxivClient
from api.review import ReviewManager
from core import ReferenceParameterExtractorFallback
from services.events import StatusType
from services.research_pipeline import ResearchPipeline
from utils.latex import (
    MAX_LATEX_BYTES,
    LatexCompilationError,
    LatexUnavailableError,
    compile_latex_to_pdf,
)
from utils.paths import UnsafePathError, resolve_data_path

logger = logging.getLogger(__name__)

router = APIRouter()


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
    """Adapt the research pipeline's progress events to the SSE wire format.

    The pipeline itself is in services.research_pipeline and knows nothing
    about HTTP, so moving it behind a job queue would replace this adapter
    without touching it.
    """
    pipeline = ResearchPipeline(
        user_prompt=user_prompt,
        topics=topics,
        num_topics=num_topics,
        papers_per_topic=papers_per_topic,
        use_reranking=use_reranking,
        broad_search_multiplier=broad_search_multiplier,
    )

    async for event in pipeline.run():
        yield SSEUpdate(
            status=event.status,
            message=event.message,
            result=event.result,
        ).to_sse()
        # Hand control back so the frame is flushed rather than buffered
        # behind the next stage's blocking work.
        await asyncio.sleep(0)


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