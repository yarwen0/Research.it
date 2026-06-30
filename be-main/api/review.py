"""
Review module for handling paper review creation and management.

This module implements a comprehensive review generation pipeline:
1. Load base papers from saved file
2. Search arXiv for additional papers (different sorting methods)
3. Process papers into chunks with embeddings
4. Use semantic search to find relevant content
5. Generate LaTeX review using LLM
"""
import logging
import json
import random
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
import arxiv

from api.arxiv import fetch_arxiv_search_results
from core import OpenRouterClient
from utils.embeddings import EmbeddingManager
from constants.prompts.review_system_prompt import REVIEW_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class ReviewManager:
    """Manages paper review creation and storage."""
    
    def __init__(
        self, 
        openrouter_client: OpenRouterClient,
        arxiv_client=None
    ):
        """
        Initialize the review manager.
        
        Args:
            openrouter_client: OpenRouterClient for LLM and embeddings
            arxiv_client: ArxivClient for searching papers and extracting PDFs
        """
        self.openrouter_client = openrouter_client
        self.arxiv_client = arxiv_client
        self.embedding_manager = EmbeddingManager(openrouter_client)
        
        self.reviews_dir = Path("data/reviews")
        self.reviews_dir.mkdir(parents=True, exist_ok=True)
        
        self.pdfs_dir = Path("data/pdfs")
        self.pdfs_dir.mkdir(parents=True, exist_ok=True)
    
    def _load_saved_papers(self, saved_filepath: str) -> Dict[str, Any]:
        """
        Load papers from saved processed file.
        
        Args:
            saved_filepath: Path to the processed papers JSON file
        
        Returns:
            Dictionary containing paper data
        """
        logger.info(f"Loading papers from {saved_filepath}")
        
        with open(saved_filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        logger.info(f"Loaded {data.get('total_papers', 0)} papers")
        return data
    
    def _select_base_papers(
        self, 
        papers: List[Dict[str, Any]], 
        target_keywords: List[str],
        num_papers: int = 2
    ) -> List[Dict[str, Any]]:
        """
        Select the most relevant papers from saved dataset as base papers.
        
        Args:
            papers: List of processed papers
            target_keywords: Keywords to match against
            num_papers: Number of papers to select
        
        Returns:
            List of selected paper dictionaries
        """
        logger.info(f"Selecting {num_papers} base papers from {len(papers)} available")
        
        scored_papers = []
        keywords_lower = [k.lower() for k in target_keywords]
        
        for paper in papers:
            score = 0
            
            # Check title
            title = paper.get("title", "").lower()
            for keyword in keywords_lower:
                if keyword in title:
                    score += 3  # Title matches are high priority
            
            abstract = paper.get("abstract", "").lower()
            for keyword in keywords_lower:
                if keyword in abstract:
                    score += 2
            
            paper_keywords = [k.lower() for k in paper.get("keywords", [])]
            for keyword in keywords_lower:
                if any(keyword in pk for pk in paper_keywords):
                    score += 5  # Exact keyword matches are highest priority
            
            scored_papers.append((score, paper))
        
        # Sort by score and take top N
        scored_papers.sort(key=lambda x: x[0], reverse=True)
        selected = [paper for score, paper in scored_papers[:num_papers]]
        
        logger.info(f"Selected {len(selected)} base papers")
        for i, paper in enumerate(selected):
            logger.info(f"  {i+1}. {paper.get('title', 'Unknown')}")
        
        return selected
    
    def _search_arxiv_diverse(
        self,
        keywords: List[str],
        topic: str,
        papers_per_variant: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search arXiv with diverse strategies to get varied papers.
        
        Strategy:
        - Use different keyword combinations
        - Use different sort criteria (relevance, date, popularity)
        - Deduplicate results
        
        Args:
            keywords: List of keywords to search with
            topic: Main topic string
            papers_per_variant: Number of papers per search variant
        
        Returns:
            List of paper metadata dictionaries
        """
        logger.info(f"Searching arXiv with diverse strategies")
        
        all_papers = {}  # Use dict to deduplicate by arxiv_id
        
        sort_criteria = [
            (arxiv.SortCriterion.Relevance, "relevance"),
            (arxiv.SortCriterion.SubmittedDate, "date"),
            (arxiv.SortCriterion.LastUpdatedDate, "updated"),
        ]
        
        # Generate query variations
        queries = []
        
        # Main topic
        queries.append(topic)
        
        # Individual keywords
        for keyword in keywords[:3]:  # Limit to avoid too many queries
            queries.append(keyword)
        
        # Combined keywords
        if len(keywords) >= 2:
            queries.append(f"{keywords[0]} {keywords[1]}")
        
        logger.info(f"Will search with {len(queries)} query variations and {len(sort_criteria)} sort methods")

        arxiv_http = arxiv.Client(page_size=20, delay_seconds=4.0, num_retries=5)

        for query in queries:
            for sort_criterion, sort_name in sort_criteria:
                try:
                    search = arxiv.Search(
                        query=query,
                        max_results=papers_per_variant,
                        sort_by=sort_criterion,
                        sort_order=arxiv.SortOrder.Descending
                    )

                    results = fetch_arxiv_search_results(search, client=arxiv_http)
                    
                    for result in results:
                        arxiv_id = result.entry_id.split('/')[-1]
                        
                        if arxiv_id not in all_papers:
                            all_papers[arxiv_id] = {
                                "arxiv_id": arxiv_id,
                                "title": result.title,
                                "authors": [author.name for author in result.authors],
                                "abstract": result.summary,
                                "published": result.published.isoformat() if result.published else None,
                                "pdf_url": result.pdf_url,
                                "categories": result.categories,
                                "search_query": query,
                                "sort_method": sort_name
                            }
                    
                    logger.info(f"Found {len(results)} papers for query='{query}', sort={sort_name}")
                    
                except Exception as e:
                    logger.error(f"Error searching arXiv with query='{query}', sort={sort_name}: {e}")
        
        papers_list = list(all_papers.values())
        logger.info(f"Total unique papers found: {len(papers_list)}")
        
        return papers_list
    
    def _download_and_extract_pdf(self, pdf_url: str, arxiv_id: str) -> Optional[Dict[str, str]]:
        """
        Download PDF and extract text content using ArxivClient with smart sectioning.
        
        Args:
            pdf_url: URL to the PDF
            arxiv_id: arXiv ID for naming
        
        Returns:
            Dictionary with 'full_text', 'first_pages_text', and 'last_pages_text', or None if failed
        """
        try:
            import urllib.request
            
            pdf_path = self.pdfs_dir / f"{arxiv_id}.pdf"
            
            # Download PDF if not exists
            if pdf_path.exists():
                logger.info(f"PDF already exists: {pdf_path}")
            else:
                logger.info(f"Downloading PDF from {pdf_url}")
                urllib.request.urlretrieve(pdf_url, pdf_path)
                logger.info(f"Saved PDF to {pdf_path}")
            
            # Extract text with sections (first 2 pages, last 2 pages excluding references, full text)
            text_data = self.arxiv_client.extract_text_with_sections(str(pdf_path), first_pages=2, last_pages=2)
            logger.info(f"Extracted text from {arxiv_id}: full={len(text_data['full_text'])} chars, "
                       f"first_pages={len(text_data['first_pages_text'])} chars, "
                       f"last_pages={len(text_data['last_pages_text'])} chars")
            return text_data
            
        except Exception as e:
            logger.error(f"Error processing PDF {arxiv_id}: {e}")
            return None
    
    def _create_chunks_from_papers(
        self,
        papers: List[Dict[str, Any]],
        chunk_size: int = 1000,
        overlap: int = 200,
        prioritize_key_sections: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Create text chunks from papers with metadata.
        Uses smart chunking that prioritizes first and last pages.
        
        Args:
            papers: List of paper dictionaries with 'text' field
            chunk_size: Size of each chunk
            overlap: Overlap between chunks
            prioritize_key_sections: If True, chunks from first/last pages get higher priority weights
        
        Returns:
            List of chunk dictionaries with text, metadata, and priority weights
        """
        all_chunks = []
        
        for paper in papers:
            # Get different text sections
            full_text = paper.get("text", {})
            
            # Handle both string and dict formats
            if isinstance(full_text, str):
                main_text = full_text
                first_pages = None
                last_pages = None
            else:
                main_text = full_text.get("full_text", "")
                first_pages = full_text.get("first_pages_text")
                last_pages = full_text.get("last_pages_text")
            
            if not main_text:
                # If no full text, use abstract
                main_text = paper.get("abstract", "")
            
            if not main_text:
                logger.warning(f"No text available for paper {paper.get('arxiv_id', 'unknown')}")
                continue
            
            # Strategy 1: Create chunks from first pages (high priority)
            if first_pages and prioritize_key_sections:
                first_chunks = self.embedding_manager.chunk_text(first_pages, chunk_size, overlap)
                for i, chunk_text in enumerate(first_chunks):
                    chunk = {
                        "text": chunk_text,
                        "paper_id": paper.get("arxiv_id", "unknown"),
                        "paper_title": paper.get("title", "Unknown"),
                        "paper_authors": paper.get("authors", []),
                        "paper_year": paper.get("published", "")[:4] if paper.get("published") else "",
                        "chunk_index": i,
                        "section": "first_pages",
                        "priority_weight": 1.5  # Higher weight for first pages
                    }
                    all_chunks.append(chunk)
            
            # Strategy 2: Create chunks from last pages (high priority)
            if last_pages and prioritize_key_sections:
                last_chunks = self.embedding_manager.chunk_text(last_pages, chunk_size, overlap)
                for i, chunk_text in enumerate(last_chunks):
                    chunk = {
                        "text": chunk_text,
                        "paper_id": paper.get("arxiv_id", "unknown"),
                        "paper_title": paper.get("title", "Unknown"),
                        "paper_authors": paper.get("authors", []),
                        "paper_year": paper.get("published", "")[:4] if paper.get("published") else "",
                        "chunk_index": i,
                        "section": "last_pages",
                        "priority_weight": 1.5  # Higher weight for last pages
                    }
                    all_chunks.append(chunk)
            
            # Strategy 3: Sample from middle sections (lower priority)
            # Extract chunks from the full text, but with lower weight
            full_chunks = self.embedding_manager.chunk_text(main_text, chunk_size, overlap)
            
            # If we're prioritizing, only sample from middle sections
            if prioritize_key_sections and first_pages and last_pages:
                # Take every 3rd chunk from middle to reduce redundancy
                total_chunks = len(full_chunks)
                for i in range(0, total_chunks, 3):
                    chunk_text = full_chunks[i]
                    chunk = {
                        "text": chunk_text,
                        "paper_id": paper.get("arxiv_id", "unknown"),
                        "paper_title": paper.get("title", "Unknown"),
                        "paper_authors": paper.get("authors", []),
                        "paper_year": paper.get("published", "")[:4] if paper.get("published") else "",
                        "chunk_index": i,
                        "section": "middle",
                        "priority_weight": 1.0  # Normal weight for middle sections
                    }
                    all_chunks.append(chunk)
            else:
                # No prioritization, use all chunks normally
                for i, chunk_text in enumerate(full_chunks):
                    chunk = {
                        "text": chunk_text,
                        "paper_id": paper.get("arxiv_id", "unknown"),
                        "paper_title": paper.get("title", "Unknown"),
                        "paper_authors": paper.get("authors", []),
                        "paper_year": paper.get("published", "")[:4] if paper.get("published") else "",
                        "chunk_index": i,
                        "section": "all",
                        "priority_weight": 1.0
                    }
                    all_chunks.append(chunk)
        
        logger.debug(f"Created {len(all_chunks)} chunks from {len(papers)} papers")
        
        # Log priority distribution
        high_priority = sum(1 for c in all_chunks if c.get("priority_weight", 1.0) > 1.0)
        logger.debug(f"  High priority chunks (first/last pages): {high_priority}")
        logger.debug(f"  Normal priority chunks: {len(all_chunks) - high_priority}")
        
        return all_chunks
    
    def _select_relevant_chunks(
        self,
        chunks: List[Dict[str, Any]],
        query: str,
        top_k: Optional[int] = 50,
        use_priority_weighting: bool = True,
        max_chunks_to_rank: int = 500
    ) -> List[Dict[str, Any]]:
        """
        Select most relevant chunks using semantic similarity with priority weighting.
        Chunks from first/last pages get boosted scores.
        
        Args:
            chunks: List of chunk dictionaries with optional 'priority_weight' field
            query: Query string to match against
            top_k: Number of top chunks to select (None = return all)
            use_priority_weighting: If True, apply priority weights to similarity scores
            max_chunks_to_rank: Maximum number of chunks to rank (to avoid oversized API requests)
        
        Returns:
            List of selected chunks with similarity scores
        """
        logger.info(f"Selecting top {top_k} relevant chunks from {len(chunks)} total")
        
        # OPTIMIZATION: If we have too many chunks, pre-filter to high-priority ones first
        chunks_to_rank = chunks
        if len(chunks) > max_chunks_to_rank:
            logger.info(f"Too many chunks ({len(chunks)}), pre-filtering to {max_chunks_to_rank} before ranking")
            
            # Strategy: Prioritize high-priority chunks (first/last pages)
            high_priority = [c for c in chunks if c.get("priority_weight", 1.0) > 1.0]
            normal_priority = [c for c in chunks if c.get("priority_weight", 1.0) == 1.0]
            
            logger.info(f"  High priority chunks: {len(high_priority)}")
            logger.info(f"  Normal priority chunks: {len(normal_priority)}")
            
            # Take all high-priority chunks + sample from normal
            remaining_slots = max_chunks_to_rank - len(high_priority)
            if remaining_slots > 0:
                # Sample evenly from normal priority chunks
                if len(normal_priority) > remaining_slots:
                    normal_sample = random.sample(normal_priority, remaining_slots)
                else:
                    normal_sample = normal_priority
                
                chunks_to_rank = high_priority + normal_sample
                logger.info(f"  Pre-filtered to {len(chunks_to_rank)} chunks (all {len(high_priority)} high-priority + {len(normal_sample)} sampled)")
            else:
                # Too many high-priority chunks, sample from them
                chunks_to_rank = random.sample(high_priority, max_chunks_to_rank)
                logger.info(f"  Pre-filtered to {len(chunks_to_rank)} sampled high-priority chunks")
        
        # Rank by relevance (gets similarity scores)
        ranked_chunks = self.embedding_manager.rank_chunks_by_relevance(
            query=query,
            chunks=chunks_to_rank,
            top_k=None  # Don't limit yet, we need to apply priority weights first
        )
        
        # Apply priority weighting to similarity scores
        if use_priority_weighting:
            for chunk in ranked_chunks:
                original_score = chunk.get("similarity_score", 0.0)
                priority_weight = chunk.get("priority_weight", 1.0)
                
                # Boost score based on priority (first/last pages get 1.5x)
                weighted_score = original_score * priority_weight
                
                chunk["original_similarity_score"] = original_score
                chunk["similarity_score"] = weighted_score
            
            # Re-sort by weighted scores
            ranked_chunks.sort(key=lambda x: x["similarity_score"], reverse=True)
            
            logger.debug("Applied priority weighting to similarity scores")
            
            # Log some stats
            if ranked_chunks:
                high_priority_in_top = sum(
                    1 for c in ranked_chunks[:top_k] 
                    if c.get("priority_weight", 1.0) > 1.0
                )
                logger.debug(
                    f"  Top {top_k} chunks include {high_priority_in_top} "
                    f"high-priority chunks (first/last pages)"
                )
        
        # Take top k after weighting
        top_chunks = ranked_chunks[:top_k] if top_k else ranked_chunks
        
        # Deduplicate similar chunks
        deduplicated_chunks = self.embedding_manager.deduplicate_chunks(
            top_chunks,
            similarity_threshold=0.95
        )
        
        logger.debug(f"Selected {len(deduplicated_chunks)} unique relevant chunks")
        
        return deduplicated_chunks
    
    def _generate_latex_review(
        self,
        chunks: List[Dict[str, Any]],
        topic: str,
        keywords: List[str]
    ) -> str:
        """
        Generate LaTeX review using LLM.
        
        Args:
            chunks: List of relevant text chunks with metadata
            topic: Main topic of the review
            keywords: Keywords for the review
        
        Returns:
            LaTeX formatted review text
        """
        logger.info("Generating LaTeX review using LLM")
        
        # Prepare context from chunks
        context_parts = []
        for i, chunk in enumerate(chunks[:40]):  # Limit to avoid token limits
            context_parts.append(
                f"[Source {i+1}] Paper: {chunk['paper_title']} ({chunk['paper_year']})\n"
                f"Authors: {', '.join(chunk['paper_authors'][:3])}\n"
                f"Content: {chunk['text']}\n"
                f"Citation Key: {chunk['paper_id']}\n"
            )
        
        context = "\n---\n".join(context_parts)
        
        # Create prompt
        user_prompt = f"""Create a comprehensive literature review in LaTeX format on the topic: "{topic}"

Keywords: {', '.join(keywords)}

Use the following research paper excerpts as your sources. Synthesize the information, identify themes and patterns, and create a well-structured academic review.

SOURCES:
{context}

Requirements:
1. Create a complete LaTeX document with sections and subsections
2. Synthesize information across sources (don't just summarize each paper)
3. Use proper citations with \\cite{{arxiv_id}} format
4. Include a bibliography section at the end with BibTeX entries
5. Organize by themes or methodologies, not by individual papers
6. Identify trends, patterns, and research gaps
7. Write in formal academic style
8. Ensure all citations have corresponding bibliography entries

Generate the complete LaTeX review now:"""
        
        # Call LLM
        response = self.openrouter_client.chat_completion(
            messages=[
                {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            response_format=None  # Free-form text for LaTeX
        )
        
        logger.debug(f"Generated review with {len(response)} characters")
        return response
    
    def _create_bibliography_metadata(
        self,
        chunks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Create bibliography metadata from chunks.
        
        Args:
            chunks: List of chunks with paper metadata
        
        Returns:
            List of paper metadata for bibliography
        """
        papers_dict = {}
        
        for chunk in chunks:
            paper_id = chunk.get("paper_id")
            if paper_id and paper_id not in papers_dict:
                papers_dict[paper_id] = {
                    "arxiv_id": paper_id,
                    "title": chunk.get("paper_title", ""),
                    "authors": chunk.get("paper_authors", []),
                    "year": chunk.get("paper_year", ""),
                }
        
        return list(papers_dict.values())
    
    def create_review_with_progress(
        self,
        saved_filepath: str,
        paper_index: int,
        paper_info: Dict[str, Any],
        num_base_papers: int = 2,
        num_arxiv_papers_per_variant: int = 5,
        num_relevant_chunks: int = 50,
        progress_callback: Optional[Any] = None
    ):
        """
        Create a comprehensive review with progress callbacks for SSE streaming.
        Generator that yields progress events in real-time.
        
        Args:
            saved_filepath: Path to the processed papers JSON file
            paper_index: Index of the paper in the processed dataset
            paper_info: Dictionary containing paper metadata (title, keywords, abstract)
            num_base_papers: Number of base papers to select from saved file
            num_arxiv_papers_per_variant: Number of papers per arXiv search variant
            num_relevant_chunks: Number of relevant chunks to use for review
            progress_callback: Optional callback function for progress updates
        
        Yields:
            Dictionary containing progress events with status, message, and optional result
            
        Returns:
            Final dictionary containing review data and metadata
        """
        def emit_progress(status: str, message: str, result: Optional[Dict[str, Any]] = None):
            """
            Emit progress event following SSE format.
            
            Status types:
            - "processing": Initial start, reading, initializing, extracting, normalizing, mapping
            - "progress": Intermediate progress updates with results
            - "success": Completed successfully
            - "error": Error occurred
            - "completed": Final completion with all results
            """
            event = {"status": status, "message": message, "result": result or {}}
            if progress_callback:
                progress_callback(status, message, result)
            logger.info(f"[{status}] {message}")
            return event
        
        yield emit_progress("processing", "Starting literature review generation...")
        
        # Extract metadata
        title = paper_info.get("title", "Unknown Title")
        keywords = paper_info.get("keywords", [])
        topic = paper_info.get("topic", title)
        
        # Step 1: Load and select base papers
        saved_data = self._load_saved_papers(saved_filepath)
        total_saved = len(saved_data.get("papers", []))
        
        yield emit_progress("processing", f"Analyzing {total_saved} papers from your dataset...")
        
        base_papers = self._select_base_papers(
            saved_data.get("papers", []),
            keywords,
            num_base_papers
        )
        
        # Step 2: Search arXiv for additional papers
        yield emit_progress("processing", "Searching for related papers on arXiv...")
        
        arxiv_papers = self._search_arxiv_diverse(
            keywords=keywords,
            topic=topic,
            papers_per_variant=num_arxiv_papers_per_variant
        )
        
        # Step 3: Download PDFs and extract text
        yield emit_progress("processing", f"Extracting content from {len(arxiv_papers) + len(base_papers)} papers...")
        
        all_papers = []
        processed_count = 0
        
        # Process base papers (silently, no individual updates)
        for idx, paper in enumerate(base_papers):
            paper_copy = paper.copy()
            if "pdf_url" in paper and paper["pdf_url"]:
                text_data = self._download_and_extract_pdf(
                    paper["pdf_url"],
                    paper.get("arxiv_id", f"base_{hash(paper['title'])}")
                )
                if text_data:
                    paper_copy["text"] = text_data
                    processed_count += 1
            all_papers.append(paper_copy)
        
        # Process arXiv papers (silently, no individual updates)
        for idx, paper in enumerate(arxiv_papers):
            text_data = self._download_and_extract_pdf(
                paper["pdf_url"],
                paper["arxiv_id"]
            )
            if text_data:
                paper["text"] = text_data
                all_papers.append(paper)
                processed_count += 1
        
        yield emit_progress("progress", f"Processing {processed_count} papers...")
        
        # Step 4: Create chunks (internal, no update)
        chunks = self._create_chunks_from_papers(
            all_papers,
            prioritize_key_sections=True
        )
        
        high_priority_count = sum(1 for c in chunks if c.get("priority_weight", 1.0) > 1.0)
        
        # Step 5: Select relevant chunks (internal, no update)
        query = f"{topic} {' '.join(keywords)}"
        relevant_chunks = self._select_relevant_chunks(
            chunks=chunks,
            query=query,
            top_k=num_relevant_chunks,
            use_priority_weighting=True
        )
        
        high_priority_selected = sum(
            1 for c in relevant_chunks 
            if c.get("priority_weight", 1.0) > 1.0
        )
        
        # Step 6: Generate LaTeX review
        yield emit_progress("processing", "Generating comprehensive literature review...")
        
        latex_review = self._generate_latex_review(
            chunks=relevant_chunks,
            topic=topic,
            keywords=keywords
        )
        
        # Step 7: Save review
        yield emit_progress("processing", "Finalizing review...")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        review_filename = f"review_{timestamp}.tex"
        review_filepath = self.reviews_dir / review_filename
        
        with open(review_filepath, 'w', encoding='utf-8') as f:
            f.write(latex_review)
        
        bibliography = self._create_bibliography_metadata(relevant_chunks)
        
        metadata_filepath = self.reviews_dir / f"review_{timestamp}_metadata.json"
        metadata = {
            "topic": topic,
            "keywords": keywords,
            "timestamp": datetime.now().isoformat(),
            "saved_filepath": saved_filepath,
            "paper_index": paper_index,
            "num_base_papers": len(base_papers),
            "num_arxiv_papers": len(arxiv_papers),
            "num_processed_papers": len(all_papers),
            "num_chunks": len(chunks),
            "num_relevant_chunks": len(relevant_chunks),
            "review_filepath": str(review_filepath),
            "bibliography": bibliography,
            "papers_used": [
                {
                    "arxiv_id": p.get("arxiv_id", ""),
                    "title": p.get("title", ""),
                    "authors": p.get("authors", []),
                    "year": p.get("published", "")[:4] if p.get("published") else "",
                    "url": p.get("pdf_url", "")
                }
                for p in all_papers
            ]
        }
        
        with open(metadata_filepath, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
                
        review_data = {
            "id": timestamp,  # Use timestamp as unique ID
            "paperTitle": paper_info.get("title", ""),
            "paperIndex": paper_index,
            "savedFilepath": saved_filepath,
            "latexContent": latex_review,
            "bibliography": bibliography,
            "papersUsed": [
                {
                    "arxiv_id": p.get("arxiv_id", ""),
                    "title": p.get("title", ""),
                    "authors": p.get("authors", []),
                    "published": p.get("published", ""),
                    "year": p.get("published", "")[:4] if p.get("published") else "",
                    "pdf_url": p.get("pdf_url", ""),
                    "summary": p.get("abstract", "")
                }
                for p in all_papers
            ],
            "statistics": {
                "base_papers": len(base_papers),
                "arxiv_papers": len(arxiv_papers),
                "processed_papers": len(all_papers),
                "total_chunks": len(chunks),
                "relevant_chunks": len(relevant_chunks),
                "high_priority_chunks": high_priority_count,
                "high_priority_selected": high_priority_selected
            },
            "reviewFilepath": str(review_filepath),
            "createdAt": int(datetime.now().timestamp() * 1000),  # Milliseconds since epoch
            "updatedAt": int(datetime.now().timestamp() * 1000),
            "status": "completed"
        }
        
        return {
            "status": "success",
            "message": "Literature review generation completed successfully!",
            "result": review_data
        }
    
    def create_review(
        self,
        saved_filepath: str,
        paper_index: int,
        paper_info: Dict[str, Any],
        num_base_papers: int = 2,
        num_arxiv_papers_per_variant: int = 5,
        num_relevant_chunks: int = 50
    ) -> Dict[str, Any]:
        """
        Create a comprehensive review using the full pipeline (non-streaming version).
        
        For SSE streaming support, use create_review_with_progress instead.
        """
        # Consume the generator and return the final result
        result = None
        for event in self.create_review_with_progress(
            saved_filepath=saved_filepath,
            paper_index=paper_index,
            paper_info=paper_info,
            num_base_papers=num_base_papers,
            num_arxiv_papers_per_variant=num_arxiv_papers_per_variant,
            num_relevant_chunks=num_relevant_chunks,
            progress_callback=None
        ):
            # The generator yields progress events and returns the final result
            result = event
        
        if result is None:
            raise ValueError("Review generation failed to produce a result")
        return result
    
    def get_review(self, review_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a specific review by ID.
        
        Args:
            review_id: Unique identifier for the review (timestamp)
        
        Returns:
            Review data if found, None otherwise
        """
        logger.info(f"Retrieving review with ID: {review_id}")
        
        review_filepath = self.reviews_dir / f"review_{review_id}.tex"
        metadata_filepath = self.reviews_dir / f"review_{review_id}_metadata.json"
        
        if not review_filepath.exists():
            logger.warning(f"Review not found: {review_filepath}")
            return None
        
        with open(review_filepath, 'r', encoding='utf-8') as f:
            latex_content = f.read()
        
        metadata = {}
        if metadata_filepath.exists():
            with open(metadata_filepath, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
        
        return {
            "review_id": review_id,
            "latex_content": latex_content,
            "metadata": metadata
        }
    
    def list_reviews(self, saved_filepath: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List all reviews, optionally filtered by source dataset.
        
        Args:
            saved_filepath: Optional filter by source dataset filepath
        
        Returns:
            List of review metadata dictionaries
        """
        logger.info(f"Listing reviews for filepath: {saved_filepath or 'all'}")
        
        reviews = []
        
        for metadata_file in self.reviews_dir.glob("review_*_metadata.json"):
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                
                # Filter by saved_filepath if provided
                if saved_filepath and metadata.get("saved_filepath") != saved_filepath:
                    continue
                
                review_id = metadata_file.stem.replace("review_", "").replace("_metadata", "")
                
                reviews.append({
                    "review_id": review_id,
                    "topic": metadata.get("topic", ""),
                    "keywords": metadata.get("keywords", []),
                    "timestamp": metadata.get("timestamp", ""),
                    "num_papers": metadata.get("num_processed_papers", 0),
                    "review_filepath": metadata.get("review_filepath", "")
                })
                
            except Exception as e:
                logger.error(f"Error reading metadata file {metadata_file}: {e}")
        
        reviews.sort(key=lambda x: x["timestamp"], reverse=True)
        
        logger.info(f"Found {len(reviews)} reviews")
        return reviews
