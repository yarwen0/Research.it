"""
arXiv API client for fetching research papers and extracting text.

This module provides functionality to:
1. Generate related topics for a user prompt via LLM
2. Search for papers on arXiv based on topics
3. Download PDF files from arXiv
4. Extract text from PDF files using PyMuPDF
"""

import os
import time
import random
import logging
import json
from typing import List, Dict, Optional, Any, Callable
import arxiv  # type: ignore
import fitz  # type: ignore  # PyMuPDF
import numpy as np

from core import OpenRouterClient, ReferenceParameterExtractorFallback

from utils.regex import extract_references_from_string

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# arXiv export API often returns 502/503 when overloaded. The official client
# retries internally; we add another layer with backoff for any remaining errors.
ARXIV_SEARCH_MAX_ATTEMPTS = 8


def _arxiv_transient_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if "429" in msg or "rate limit" in msg or "too many requests" in msg:
        return True
    # Service unavailable / gateway / timeout (arXiv or fronting CDN)
    if any(code in msg for code in ("503", "502", "504")):
        return True
    if "http 500" in msg or "500 (" in msg:
        return True
    if "timed out" in msg or "timeout" in msg:
        return True
    return False


def fetch_arxiv_search_results(
    search: arxiv.Search,
    *,
    client: Optional[Any] = None,
) -> List[Any]:
    """
    Run an arxiv.Search with the same retry/backoff policy as ArxivClient.search_papers.

    Use this anywhere we call ``arxiv.Client().results(...)`` so transient 503s
    from export.arxiv.org do not abort the whole pipeline.
    """
    c = client or arxiv.Client(page_size=20, delay_seconds=4.0, num_retries=5)
    last_err: Optional[BaseException] = None
    for attempt in range(ARXIV_SEARCH_MAX_ATTEMPTS):
        try:
            return list(c.results(search))
        except Exception as e:
            last_err = e
            if not _arxiv_transient_error(e):
                raise
            backoff = min(120.0, (2 ** attempt) * 6 + random.uniform(2, 8))
            logger.warning(
                f"arXiv transient error ({e!s}), retry {attempt + 1}/{ARXIV_SEARCH_MAX_ATTEMPTS} "
                f"after {backoff:.1f}s"
            )
            time.sleep(backoff)
            continue
    raise last_err if last_err else RuntimeError("arXiv search failed")


USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/119.0",
]


class ArxivClient:
    """Client for interacting with arXiv API and processing papers."""
    
    def __init__(self, max_results_per_topic: int = 5, *, reference_extractor_fallback: ReferenceParameterExtractorFallback, openrouter_client: OpenRouterClient):
        """
        Initialize the arXiv client.
        
        Args:
            max_results_per_topic: Maximum number of papers to fetch per topic
        """
        self.max_results_per_topic = max_results_per_topic
        # Slightly slower pacing + extra internal retries to reduce 429/503 bursts.
        self.client = arxiv.Client(page_size=20, delay_seconds=4.0, num_retries=5)
        self.reference_extractor_fallback = reference_extractor_fallback
        self.openrouter_client = openrouter_client
    
    def _get_random_user_agent(self) -> str:
        """Get a random user agent from the pool."""
        return random.choice(USER_AGENTS)
    
    def _extract_references(self, text: str) -> List[Dict[str, Any]]:
        """
        Extract references from paper text using LLM fallback.
        
        Since extract_references_from_string() is a stub that returns empty list,
        we directly use the LLM-based extractor to parse references from the full text.
        """
        try:
            # Pass the full text to the LLM extractor
            # It will identify and parse the references section
            responses = self.reference_extractor_fallback.extract([text])
            processed_refs = []
            for response in responses.refs:
                processed_refs.append(json.loads(response.model_dump_json()))
            logger.info(f"LLM extracted {len(processed_refs)} references from text")
            return processed_refs
        except Exception as e:
            logger.error(f"Failed to extract references using LLM: {str(e)}")
            return []

        processed_refs = []
        invalid_refs = []

        for i, r in enumerate(ref):
            if "title" not in r:
                invalid_refs.append(r)
            else:
                processed_refs.append(r)

        processed_refs.extend(json.loads(response).get("references", []))

        # # Batch process invalid refs
        # REF_BATCH_SIZE = 5
        # for i in range(0, len(invalid_refs), REF_BATCH_SIZE):
        #     batch = invalid_refs[i:i+REF_BATCH_SIZE]
        #     inputs = [
        #         r.get("raw_ref") or r.get("raw") or json.dumps(r, ensure_ascii=False)
        #         for r in batch
        #     ]
        #     responses = self.reference_extractor_fallback.extract(inputs)
        #     for j, response in enumerate(responses.refs):
        #         processed_refs.append(json.loads(response.model_dump_json()))

        return processed_refs

    def search_papers(self, query: str, max_results: Optional[int] = None) -> List[Any]:
        """
        Search for papers on arXiv.
        
        Args:
            query: Search query string
            max_results: Maximum number of results to return (defaults to self.max_results_per_topic)
        
        Returns:
            List of arxiv.Result objects
        """
        if max_results is None:
            max_results = self.max_results_per_topic
        
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance,
            sort_order=arxiv.SortOrder.Descending
        )

        return fetch_arxiv_search_results(search, client=self.client)
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """
        Calculate cosine similarity between two vectors.
        
        Args:
            vec1: First embedding vector
            vec2: Second embedding vector
        
        Returns:
            Cosine similarity score (0 to 1)
        """
        vec1_np = np.array(vec1)
        vec2_np = np.array(vec2)
        
        dot_product = np.dot(vec1_np, vec2_np)
        norm1 = np.linalg.norm(vec1_np)
        norm2 = np.linalg.norm(vec2_np)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return float(dot_product / (norm1 * norm2))
    
    def search_and_rerank_papers(
        self,
        user_query: str,
        desired_count: int,
        broad_search_multiplier: int = 10,
        embedding_model: str = "sentence-transformers/all-minilm-l12-v2"
    ) -> List[Any]:
        """
        Search arXiv broadly and rerank papers based on semantic similarity to user query.
        
        This method addresses the poor quality of arXiv's default search by:
        1. Searching for more papers than needed (broad approach)
        2. Using LLM embeddings to compute semantic similarity
        3. Reranking based on vector similarity to user's original query
        4. Returning only the top-k most relevant papers
        
        Args:
            user_query: The original user query/topic
            desired_count: Number of papers actually wanted
            broad_search_multiplier: How many times more papers to search (default: 10)
                                    e.g., if desired_count=5, will search for 50 papers
            embedding_model: Model to use for embeddings (default: sentence-transformers/all-minilm-l12-v2)
        
        Returns:
            List of top-k reranked arxiv.Result objects
        """
        # Calculate broad search count
        broad_search_count = desired_count * broad_search_multiplier
        
        logger.info(
            f"Searching broadly for {broad_search_count} papers, will rerank and return top {desired_count}"
        )
        
        # Step 1: Search broadly
        papers = self.search_papers(user_query, max_results=broad_search_count)
        
        if len(papers) == 0:
            logger.warning(f"No papers found for query: {user_query}")
            return []
        
        if len(papers) <= desired_count:
            logger.info(f"Found {len(papers)} papers, less than desired {desired_count}, returning all")
            return papers
        
        logger.info(f"Found {len(papers)} papers, computing embeddings for reranking...")
        
        # Step 2: Prepare texts for embedding
        # Combine title + abstract for better semantic matching
        paper_texts = []
        for paper in papers:
            text = f"{paper.title} {paper.summary}"
            paper_texts.append(text)
        
        # Step 3: Get embeddings for all papers and the query
        try:
            # Batch all texts including the query
            all_texts = [user_query] + paper_texts
            embeddings = self.openrouter_client.get_embeddings(all_texts, model=embedding_model)
            
            query_embedding = embeddings[0]
            paper_embeddings = embeddings[1:]
            
            logger.info(f"Successfully computed {len(paper_embeddings)} paper embeddings")
            
        except Exception as e:
            logger.error(f"Failed to compute embeddings: {e}, falling back to original order")
            return papers[:desired_count]
        
        # Step 4: Calculate similarity scores
        similarities = []
        for i, paper_embedding in enumerate(paper_embeddings):
            similarity = self._cosine_similarity(query_embedding, paper_embedding)
            similarities.append((i, similarity, papers[i]))
        
        # Step 5: Sort by similarity (descending)
        similarities.sort(key=lambda x: x[1], reverse=True)
        
        # Log top similarities for debugging
        logger.info("Top 5 reranked papers by similarity:")
        for i, (idx, sim, paper) in enumerate(similarities[:5]):
            logger.info(f"  {i+1}. [{sim:.4f}] {paper.title[:80]}")
        
        # Step 6: Return top-k papers
        reranked_papers = [item[2] for item in similarities[:desired_count]]
        
        logger.info(f"Reranked and returning top {len(reranked_papers)} papers")
        return reranked_papers
    
    def download_pdf(self, paper: Any, download_dir: Optional[str] = None) -> str:
        """
        Download a paper's PDF file.
        
        Args:
            paper: arxiv.Result object
            download_dir: Directory to save the PDF (defaults to data/tmp)
        
        Returns:
            Path to the downloaded PDF file
        """
        if download_dir is None:
            # Get the directory where this script is located
            script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            download_dir = os.path.join(script_dir, "data", "tmp")
        
        os.makedirs(download_dir, exist_ok=True)
        
        # Create a safe filename from the paper ID
        filename = f"{paper.get_short_id()}.pdf"
        filepath = os.path.join(download_dir, filename)
        
        # Check if file already exists
        if os.path.exists(filepath):
            logger.info(f"PDF already exists locally, skipping arXiv download (rate limit friendly): {filename}")
            return filepath
        
        logger.info(f"PDF not found locally, downloading from arXiv: {paper.title} (ID: {paper.get_short_id()})")
        logger.debug(f"Download URL: {paper.pdf_url}")
        
        try:
            # Download the PDF
            paper.download_pdf(dirpath=download_dir, filename=filename)
            logger.info(f"Successfully downloaded PDF: {filename} to {download_dir}")
        except Exception as e:
            logger.error(f"Failed to download PDF {filename}: {str(e)}")
            raise
        
        return filepath
    
    def extract_text_from_pdf(self, pdf_path: str, max_pages: Optional[int] = None) -> str:
        """
        Extract text from a PDF file using PyMuPDF.
        
        Args:
            pdf_path: Path to the PDF file
            max_pages: Maximum number of pages to extract (None for all pages)
        
        Returns:
            Extracted text as a string
        """
        logger.info(f"Starting text extraction from: {pdf_path}")
        
        try:
            doc = fitz.open(pdf_path)
            text_parts = []
            
            # Treat max_pages=0 or None as "extract all pages"
            num_pages = len(doc) if (max_pages is None or max_pages == 0) else min(len(doc), max_pages)
            logger.debug(f"Extracting text from {num_pages} pages (total: {len(doc)} pages)")
            
            for page_num in range(num_pages):
                page = doc[page_num]
                text = page.get_text()  # type: ignore[attr-defined]
                text_parts.append(text)
            
            doc.close()
            
            total_chars = sum(len(part) for part in text_parts)
            logger.info(f"Successfully extracted {total_chars} characters from {num_pages} pages")
            
            return "\n\n".join(text_parts)
        except Exception as e:
            logger.error(f"Failed to extract text from PDF {pdf_path}: {str(e)}")
            raise
    
    def extract_text_with_sections(self, pdf_path: str, first_pages: int = 2, last_pages: int = 2) -> Dict[str, str]:
        """
        Extract text from PDF with separate sections for first pages, last pages (excluding references), and full text.
        
        Args:
            pdf_path: Path to the PDF file
            first_pages: Number of first pages to extract separately (default: 2)
            last_pages: Number of last pages to extract separately (default: 2)
        
        Returns:
            Dictionary with 'full_text', 'first_pages_text', and 'last_pages_text'
        """
        logger.info(f"Starting sectioned text extraction from: {pdf_path}")
        
        try:
            doc = fitz.open(pdf_path)
            total_pages = len(doc)
            
            # Extract all pages
            all_page_texts = []
            for page_num in range(total_pages):
                page = doc[page_num]
                text = page.get_text()  # type: ignore[attr-defined]
                all_page_texts.append(text)
            
            doc.close()
            
            # Join all text
            full_text = "\n\n".join(all_page_texts)
            
            # Extract first pages
            first_pages_text = "\n\n".join(all_page_texts[:first_pages]) if first_pages > 0 else ""
            
            # Find references section by searching for common reference keywords
            references_start_page = None
            reference_keywords = [
                'references',
                'bibliography', 
                'works cited',
                'literature cited'
            ]
            
            for page_num in range(max(0, total_pages - 5), total_pages):  # Search last 5 pages
                page_text_lower = all_page_texts[page_num].lower()
                
                # Check if this page starts with a reference header
                first_100_chars = page_text_lower[:100]
                for keyword in reference_keywords:
                    if keyword in first_100_chars:
                        references_start_page = page_num
                        logger.info(f"Found references section starting at page {page_num + 1}")
                        break
                
                if references_start_page is not None:
                    break
            
            # Extract last pages, excluding references
            if references_start_page is not None:
                # Get last_pages worth of content BEFORE the references section
                last_page_end = references_start_page
                last_page_start = max(0, last_page_end - last_pages)
                last_pages_text = "\n\n".join(all_page_texts[last_page_start:last_page_end])
                logger.info(f"Extracted last {last_pages} pages (pages {last_page_start + 1}-{last_page_end}) before references")
            else:
                # No references section found, use the last pages as-is
                last_page_start = max(0, total_pages - last_pages)
                last_pages_text = "\n\n".join(all_page_texts[last_page_start:])
                logger.warning(f"References section not found, using last {last_pages} pages as-is")
            
            logger.info(f"Extracted text: full={len(full_text)} chars, first_pages={len(first_pages_text)} chars, last_pages={len(last_pages_text)} chars")
            
            return {
                "full_text": full_text,
                "first_pages_text": first_pages_text,
                "last_pages_text": last_pages_text
            }
            
        except Exception as e:
            logger.error(f"Failed to extract sectioned text from PDF {pdf_path}: {str(e)}")
            raise
    
    def fetch_and_extract_paper(
        self, 
        paper: Any, 
        download_dir: Optional[str] = None,
        max_pages: Optional[int] = None,
        cleanup: bool = False
    ) -> Dict[str, Any]:
        """
        Download a paper and extract its text.
        
        Args:
            paper: arxiv.Result object
            download_dir: Directory to save the PDF
            max_pages: Maximum number of pages to extract
            cleanup: Whether to delete the PDF after extraction
        
        Returns:
            Dictionary with paper metadata and extracted text
        """
        paper_id = paper.get_short_id()
        logger.info(f"Processing paper: {paper.title} (ID: {paper_id})")
        
        # Download PDF
        pdf_path = self.download_pdf(paper, download_dir)
        
        # Extract text
        text = self.extract_text_from_pdf(pdf_path, max_pages)
        
        # Extract references
        references = self._extract_references(text)
        logger.info(f"Extracted {len(references)} references from paper {paper_id}")
        
        # Cleanup if requested
        if cleanup and os.path.exists(pdf_path):
            os.remove(pdf_path)
            logger.debug(f"Cleaned up PDF file: {pdf_path}")
        
        logger.info(f"Successfully processed paper {paper_id}")
        
        return {
            "paper_id": paper_id,
            "title": paper.title,
            "authors": [author.name for author in paper.authors],
            "published": paper.published.isoformat() if paper.published else None,
            "summary": paper.summary,
            "pdf_url": paper.pdf_url,
            "references": references,
            "text": text
        }
    
    def search_and_extract_papers(
        self, 
        query: str, 
        max_results: Optional[int] = None,
        download_dir: Optional[str] = None,
        max_pages: Optional[int] = None,
        cleanup: bool = False,
        delay_between_downloads: float = 3.0,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        use_reranking: bool = True,
        broad_search_multiplier: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search for papers and extract text from all results.
        
        Args:
            query: Search query string
            max_results: Maximum number of papers to fetch
            download_dir: Directory to save PDFs
            max_pages: Maximum number of pages to extract per paper
            cleanup: Whether to delete PDFs after extraction
            delay_between_downloads: Delay in seconds between downloads (default 3s per arXiv guidance)
            progress_callback: Optional callback function(completed, total) for progress updates
            use_reranking: Whether to use vector-based reranking (default: True)
            broad_search_multiplier: Multiplier for broad search when reranking (default: 10)
        
        Returns:
            List of dictionaries with paper metadata and extracted text
        """
        logger.info(f"Searching arXiv for query: '{query}' (max_results: {max_results or self.max_results_per_topic})")
        
        # Use reranking if enabled
        if use_reranking:
            desired_count = max_results or self.max_results_per_topic
            papers = self.search_and_rerank_papers(
                user_query=query,
                desired_count=desired_count,
                broad_search_multiplier=broad_search_multiplier
            )
        else:
            papers = self.search_papers(query, max_results)
        
        logger.info(f"Found {len(papers)} papers for query: '{query}'")
        
        extracted_papers = []
        
        logger.info("Processing papers sequentially (threading disabled to respect arXiv rate limits)")
        for i, paper in enumerate(papers):
            try:
                if i > 0:
                    time.sleep(delay_between_downloads)

                logger.info(f"Processing paper {i+1}/{len(papers)}")
                extracted_data = self.fetch_and_extract_paper(
                    paper,
                    download_dir=download_dir,
                    max_pages=max_pages,
                    cleanup=cleanup
                )
                extracted_papers.append(extracted_data)

                if progress_callback:
                    progress_callback(len(extracted_papers), len(papers))
            except Exception as e:
                logger.error(f"Error processing paper {paper.get_short_id()}: {str(e)}")
                continue
        
        logger.info(f"Completed processing: {len(extracted_papers)}/{len(papers)} papers successfully extracted")
        return extracted_papers


class TopicGenerator:
    """Generate related research topics using an LLM client."""

    def __init__(self, llm_client: OpenRouterClient):
        self.client = llm_client

    def generate_related_topics(self, user_prompt: str, num_topics: int = 10) -> List[str]:
        """Return a list of related research topics for the supplied prompt."""

        system_prompt = """You are a research topic generator for arXiv paper searches. Your task is to generate search queries that will find relevant papers on arXiv.

CRITICAL Guidelines:
1. ALWAYS include the core domain from the user's prompt in EVERY topic (e.g., if they ask about "plastic recycling", ALL topics must include "plastic" or "polymer")
2. Keep queries SHORT and BROAD - arXiv search works better with 2-5 word phrases
3. Focus on combining the core domain with different research approaches or subtopics
4. Use common scientific terminology that appears in paper titles and abstracts
5. Avoid overly specific or narrow queries that won't return results

EXAMPLES:
User prompt: "plastic recycling"
GOOD topics: ["plastic recycling machine learning", "polymer degradation", "plastic waste management", "chemical recycling polymers"]
BAD topics: ["Machine learning techniques for automated sorting of mixed plastic waste streams"] (too specific, loses "plastic")

Output format: Return ONLY a JSON object with a "topics" key containing an array of SHORT topic strings.
Example: {"topics": ["topic 1", "topic 2", "topic 3"]}
"""

        user_message = f"""Generate {num_topics} SHORT arXiv search queries for the following research area:

"{user_prompt}"

Remember: 
- Keep each query to 2-5 words maximum
- ALWAYS include the core domain from the prompt
- Make them broad enough to find papers but specific enough to be relevant
Return only the JSON object with the topics array."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "topics_response",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "topics": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": f"Array of {num_topics} related research topics",
                        }
                    },
                    "required": ["topics"],
                    "additionalProperties": False,
                },
            },
        }

        response = self.client.chat_completion(messages, response_format=response_format)
        logger.info(f"Topic gen raw response (first 500): {response[:500]!r}")
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                data = json.loads(cleaned[start:end+1])
            else:
                logger.error(f"Could not parse topic response: {response!r}")
                raise
        topics_raw = list(data.get("topics", []) or [])
        topics = topics_raw[:num_topics]
        if len(topics_raw) != num_topics:
            logger.warning(
                f"Topic generator returned {len(topics_raw)} topics; truncated/padded to {num_topics}"
            )
        while len(topics) < num_topics:
            topics.append(user_prompt.strip()[:200])
        return topics[:num_topics]

    def generate_paper_suggestions(self, gaps: List[Dict], user_prompt: str, num_papers: int = 10) -> List[Dict]:
        """Generate paper suggestions from research gaps."""
        
        system_prompt = """You are a research paper idea generator. Given research gaps identified from analyzing existing papers, generate concrete, innovative paper proposals.

For each gap, create a realistic research paper proposal with:
- A compelling, specific title
- 5 relevant keywords
- A detailed abstract (150-250 words) that describes the problem, approach, methods, and expected results

Make the proposals:
1. Technically sound and feasible
2. Address the identified gap directly
3. Use concrete methods and datasets where applicable
4. Include specific performance metrics or evaluation criteria
5. Sound like real academic abstracts

Return ONLY a JSON object with a "papers" key containing an array of paper objects."""

        gaps_description = []
        for i, gap in enumerate(gaps):
            gap_desc = f"Gap {i+1}: {gap.get('gap_type', 'Unknown')}\n"
            gap_desc += f"Problem Domain: {gap.get('problem', 'N/A')}\n"
            if gap.get('method'):
                gap_desc += f"Method: {gap['method']}\n"
            if gap.get('dataset'):
                gap_desc += f"Dataset: {gap['dataset']}\n"
            if gap.get('limitation'):
                gap_desc += f"Limitation to Address: {gap['limitation']}\n"
            if gap.get('future_work'):
                gap_desc += f"Future Work: {gap['future_work']}\n"
            gap_desc += f"Importance Score: {gap.get('score', 0)}\n"
            gaps_description.append(gap_desc)
        
        user_message = f"""Based on the analysis of papers in "{user_prompt}", here are the top research gaps identified:

{chr(10).join(gaps_description)}

Generate {num_papers} innovative research paper proposals that address these gaps. Each paper should be realistic and academically sound."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]

        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "paper_suggestions",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "papers": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "keywords": {
                                        "type": "array",
                                        "items": {"type": "string"}
                                    },
                                    "abstract": {"type": "string"}
                                },
                                "required": ["title", "keywords", "abstract"],
                                "additionalProperties": False
                            }
                        }
                    },
                    "required": ["papers"],
                    "additionalProperties": False
                }
            }
        }

        response = self.client.chat_completion(messages, response_format=response_format)
        data = json.loads(response)
        return data.get("papers", [])
