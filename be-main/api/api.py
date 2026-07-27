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

from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, field_validator
from pylatex import Document, NoEscape

from core import (
    OpenRouterClient,
    PDFExtractor,
    OntologyStorage,
    ReferenceParameterExtractorFallback,
    ReferenceGraph,
    create_llm_client,
)
from config import OPENROUTER_API_KEY, GEMINI_API_KEY
from api.arxiv import ArxivClient, TopicGenerator, ArxivRateLimitError
from api.review import ReviewManager
from utils.graph import TrendsCreator
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
        str: Path to the saved JSON file
    """
    # Create data directory if it doesn't exist
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    
    # Create filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Clean user prompt for filename (remove special chars, limit length)
    clean_prompt = "".join(c if c.isalnum() or c in (' ', '_') else '_' for c in user_prompt)
    clean_prompt = clean_prompt.replace(' ', '_')[:50]  # Limit to 50 chars
    filename = f"processed_papers_{clean_prompt}_{timestamp}.json"
    filepath = data_dir / filename
    
    # Save to JSON
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump({
            "user_prompt": user_prompt,
            "timestamp": datetime.now().isoformat(),
            "total_papers": len(all_processed_papers),
            "papers": all_processed_papers
        }, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Saved {len(all_processed_papers)} processed papers to {filepath}")
    return str(filepath)


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

        reference_graph = ReferenceGraph(project_id=project_id)

        extractor_fallback = ReferenceParameterExtractorFallback()
        
        arxiv_client = ArxivClient(
            max_results_per_topic=papers_per_topic,
            reference_extractor_fallback=extractor_fallback,
            openrouter_client=llm_client
            )
        topic_generator = TopicGenerator(llm_client)
        extractor = PDFExtractor(llm_client=llm_client)
        ontology_store = OntologyStorage()
        
        loop = asyncio.get_event_loop()
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
                    await loop.run_in_executor(
                        None, 
                        ontology_store.map_to_ontology, 
                        normalized_data, 
                        paper_id
                    )
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
        
        # Helper function to create author ID
        def create_author_id(author_name: str) -> str:
            """Create a consistent ID for an author."""
            return f"author_{author_name.replace(' ', '_').replace('.', '').lower()}"
        
        # Track created authors to avoid duplicates
        created_authors = set()
        
        for paper in all_processed_papers:
            paper_id = paper["paper_id"]
            
            # Create paper node
            reference_graph.create_node_no_sync(paper_id, paper, True)
            
            # Create author nodes and authorship edges for this paper
            authors = paper.get("authors", [])
            if authors and isinstance(authors, list):
                for author in authors:
                    if author and isinstance(author, str):
                        author_id = create_author_id(author)
                        
                        # Create author node if not already created
                        if author_id not in created_authors:
                            author_data = {
                                "title": author,
                                "label": author,
                                "node_type": "author"
                            }
                            reference_graph.create_node_no_sync(author_id, author_data, False)
                            created_authors.add(author_id)
                        
                        # Create authorship edge from paper to author
                        reference_graph.create_edge_no_sync(paper_id, author_id, edge_type="authorship")
            
            # Create reference nodes and citation edges
            for ref in paper.get("references", []):
                if len(ref.get("title", "")) > 6:
                    ref_paper_id = uuid.uuid4().hex
                    reference_graph.create_node_no_sync(ref_paper_id, ref, False)
                    reference_graph.create_edge_no_sync(paper_id, ref_paper_id, edge_type="citation")
                    
                    # Create author nodes and authorship edges for reference authors
                    ref_authors = ref.get("authors", [])
                    if ref_authors and isinstance(ref_authors, list):
                        for author in ref_authors:
                            if author and isinstance(author, str):
                                author_id = create_author_id(author)
                                
                                # Create author node if not already created
                                if author_id not in created_authors:
                                    author_data = {
                                        "title": author,
                                        "label": author,
                                        "node_type": "author"
                                    }
                                    reference_graph.create_node_no_sync(author_id, author_data, False)
                                    created_authors.add(author_id)
                                
                                # Create authorship edge from reference to author
                                reference_graph.create_edge_no_sync(ref_paper_id, author_id, edge_type="authorship")
        
        reference_graph.sync_to_disk()

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
        
        # Pass LLM client to TrendsCreator for dataset validation
        trends_creator = TrendsCreator(trends_data, ontology_store.ontology, llm_client=llm_client)
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
async def research_endpoint(request: ResearchRequest):
    """
    SSE endpoint for arXiv-based research extraction.
    
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
            user_prompt=request.user_prompt,
            topics=request.topics,
            num_topics=request.num_topics,
            papers_per_topic=request.papers_per_topic,
            use_reranking=request.use_reranking,
            broad_search_multiplier=request.broad_search_multiplier
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
async def create_review_endpoint(request: ReviewRequest):
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
            saved_filepath=request.saved_filepath,
            paper_index=request.paper_index,
            paper_info=request.paper_info,
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


@router.post("/latex/compile")
async def compile_latex_endpoint(request: LatexCompileRequest):
    """
    Compile LaTeX text to PDF and return the PDF file.
    
    Request Body:
        latex_text: Raw LaTeX content to compile
    
    Returns:
        PDF file
    """
    import subprocess
    
    try:
        # Create a temporary directory for LaTeX compilation
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Write the raw LaTeX content directly to a .tex file
            tex_filename = "output.tex"
            tex_path = temp_path / tex_filename
            
            with open(tex_path, 'w', encoding='utf-8') as f:
                f.write(request.latex_text)
            
            pdf_filename = "output.pdf"
            pdf_path = temp_path / pdf_filename
            
            # Add BasicTeX to PATH for compilation
            env = os.environ.copy()
            if os.path.exists('/Library/TeX/texbin'):
                env['PATH'] = f"/Library/TeX/texbin:{env.get('PATH', '')}"
            
            # Full LaTeX compilation sequence for bibliography support
            # 1. First pdflatex pass - generates .aux file with citations
            try:
                result = subprocess.run(
                    ['pdflatex', '-interaction=nonstopmode', '-output-directory', str(temp_path), str(tex_path)],
                    cwd=str(temp_path),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                if result.returncode != 0:
                    logger.warning(f"pdflatex first pass returned code {result.returncode}")
                    logger.debug(f"pdflatex stdout: {result.stdout}")
            except subprocess.TimeoutExpired:
                raise HTTPException(status_code=500, detail="LaTeX compilation timed out (first pass)")
            
            # 2. Run bibtex to process bibliography (if .aux file exists)
            aux_path = temp_path / "output.aux"
            if aux_path.exists():
                try:
                    bibtex_result = subprocess.run(
                        ['bibtex', 'output'],
                        cwd=str(temp_path),
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    # BibTeX warnings are common and acceptable
                    if bibtex_result.returncode != 0:
                        logger.warning(f"bibtex returned code {bibtex_result.returncode}")
                        logger.debug(f"bibtex stdout: {bibtex_result.stdout}")
                except subprocess.TimeoutExpired:
                    logger.warning("BibTeX timed out, continuing without bibliography")
                except FileNotFoundError:
                    logger.warning("bibtex not found, skipping bibliography processing")
            
            # 3. Second pdflatex pass - includes bibliography from .bbl
            try:
                result = subprocess.run(
                    ['pdflatex', '-interaction=nonstopmode', '-output-directory', str(temp_path), str(tex_path)],
                    cwd=str(temp_path),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                if result.returncode != 0:
                    logger.warning(f"pdflatex second pass returned code {result.returncode}")
                    logger.debug(f"pdflatex stdout: {result.stdout}")
            except subprocess.TimeoutExpired:
                raise HTTPException(status_code=500, detail="LaTeX compilation timed out (second pass)")
            
            # 4. Third pdflatex pass - resolves all cross-references
            try:
                result = subprocess.run(
                    ['pdflatex', '-interaction=nonstopmode', '-output-directory', str(temp_path), str(tex_path)],
                    cwd=str(temp_path),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                if result.returncode != 0:
                    logger.warning(f"pdflatex final pass returned code {result.returncode}")
                    logger.debug(f"pdflatex stdout: {result.stdout}")
                    logger.debug(f"pdflatex stderr: {result.stderr}")
            except subprocess.TimeoutExpired:
                raise HTTPException(status_code=500, detail="LaTeX compilation timed out (final pass)")
            
            # Check if PDF was generated (even with warnings/errors)
            if not pdf_path.exists():
                error_msg = "PDF generation failed"
                if result.returncode != 0:
                    # Try to extract meaningful error from log
                    log_path = temp_path / "output.log"
                    if log_path.exists():
                        with open(log_path, 'r', encoding='utf-8', errors='ignore') as log_file:
                            log_content = log_file.read()
                            # Find critical errors
                            if "! Emergency stop" in log_content:
                                error_msg += ": Emergency stop in LaTeX compilation"
                            elif "Fatal error" in log_content:
                                error_msg += ": Fatal error in LaTeX compilation"
                raise HTTPException(status_code=500, detail=error_msg)
            
            # Read the PDF file
            pdf_content = pdf_path.read_bytes()
            
            # Save to a temporary file that will persist for the response
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
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error compiling LaTeX: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to compile LaTeX: {str(e)}")


@router.get("/graph/{project_id}/")
async def get_graph_endpoint(project_id: str):
    """
    Endpoint to retrieve the reference graph for a given project ID.
    Returns nodes and edges as stored in the graph (including authors).
    """
    try:
        reference_graph = ReferenceGraph(project_id=project_id)
        graph_data = {}

        processed_nodes = []
        processed_edges = []

        nodes = reference_graph.graph.get("nodes") or {}
        edges = reference_graph.graph.get("edges") or []
        if not nodes:
            raise HTTPException(
                status_code=404,
                detail=f"Graph not found for project {project_id}",
            )

        # Process all nodes (papers and authors)
        for node in nodes.values():
            node_id = node["paper_id"]
            node_data = node["data"]
            is_processed = node.get("processed", False)
            
            # Build node data
            data = {
                "id": node_id,
                "title": node_data.get("title", ""),
                "authors": node_data.get("authors", []),
                "published": node_data.get("published", ""),
                "is_processed": is_processed,
                "refs_to": node.get("refs_to", []),
                "refs_from": node.get("refs_from", []),
                "node_type": node_data.get("node_type", "paper"),
                "label": node_data.get("label", node_data.get("title", "")),
            }

            processed_nodes.append({
                "data": data,
            })

        # Process all edges (citations and authorships)
        for edge in edges:
            edge_data = {
                **edge,
                "edge_type": edge.get("edge_type", "citation"),
            }
            processed_edges.append({
                "data": edge_data,
            })

        graph_data["nodes"] = processed_nodes
        graph_data["edges"] = processed_edges

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