"""
Embedding and semantic similarity utilities for review generation.
"""
import logging
from typing import List, Dict, Any, Tuple, Optional
import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingManager:
    """Manages text embeddings and similarity computations."""
    
    def __init__(self, openrouter_client):
        """
        Initialize the embedding manager.
        
        Args:
            openrouter_client: OpenRouterClient instance for generating embeddings
        """
        self.openrouter_client = openrouter_client
    
    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
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
    
    def get_embeddings(
        self, 
        texts: List[str], 
        model: str = "sentence-transformers/all-minilm-l12-v2"
    ) -> List[List[float]]:
        """
        Get embeddings for a list of texts.
        
        Args:
            texts: List of text strings to embed
            model: Embedding model to use (default: sentence-transformers/all-minilm-l12-v2)
        
        Returns:
            List of embedding vectors
        """
        return self.openrouter_client.get_embeddings(texts, model=model)
    
    def chunk_text(
        self, 
        text: str, 
        chunk_size: int = 1000, 
        overlap: int = 200,
        max_chunk_size: int = 8000
    ) -> List[str]:
        """
        Split text into overlapping chunks for embedding.
        
        Args:
            text: Text to chunk
            chunk_size: Size of each chunk in characters
            overlap: Overlap between chunks in characters
            max_chunk_size: Maximum allowed chunk size (hard limit to prevent API errors)
        
        Returns:
            List of text chunks
        """
        if len(text) <= chunk_size:
            # Truncate if it exceeds max size
            if len(text) > max_chunk_size:
                logger.warning(f"Single text chunk ({len(text)} chars) exceeds max size, truncating to {max_chunk_size}")
                return [text[:max_chunk_size]]
            return [text]
        
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            
            # Try to break at sentence boundary
            if end < len(text):
                # Look for sentence ending punctuation
                last_period = chunk.rfind('.')
                last_question = chunk.rfind('?')
                last_exclaim = chunk.rfind('!')
                
                break_point = max(last_period, last_question, last_exclaim)
                
                if break_point > chunk_size * 0.5:  # Only break if we're past halfway
                    chunk = chunk[:break_point + 1]
                    end = start + break_point + 1
            
            # Safety check: enforce max chunk size
            if len(chunk) > max_chunk_size:
                logger.warning(f"Chunk ({len(chunk)} chars) exceeds max size, truncating to {max_chunk_size}")
                chunk = chunk[:max_chunk_size]

            # Skip empty/whitespace-only chunks so we never embed a blank string.
            stripped = chunk.strip()
            if stripped:
                chunks.append(stripped)
            start = end - overlap

        return chunks
    
    def rank_chunks_by_relevance(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        top_k: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Rank text chunks by semantic similarity to a query.
        
        Args:
            query: Query text to compare against
            chunks: List of chunk dictionaries with 'text' and 'metadata' keys
            top_k: Number of top chunks to return (None = return all, sorted)
        
        Returns:
            List of chunks sorted by relevance (highest first), with similarity scores
        """
        if not chunks:
            return []
        
        # Log chunk statistics
        logger.debug(f"Ranking {len(chunks)} chunks by relevance")
        chunk_lengths = [len(chunk["text"]) for chunk in chunks]
        logger.debug(f"Chunk size stats - Min: {min(chunk_lengths)}, Max: {max(chunk_lengths)}, Avg: {sum(chunk_lengths)/len(chunk_lengths):.0f}")
        logger.debug(f"Query length: {len(query)} characters")
        
        # Check for oversized chunks
        oversized = [i for i, length in enumerate(chunk_lengths) if length > 8000]
        if oversized:
            logger.warning(f"Found {len(oversized)} oversized chunks (>8000 chars): indices {oversized[:10]}")
        
        # Get embeddings for query and all chunks
        texts = [query] + [chunk["text"] for chunk in chunks]
        total_chars = sum(len(t) for t in texts)
        logger.debug(f"Preparing to embed {len(texts)} texts (total {total_chars} chars)")
        
        embeddings = self.get_embeddings(texts)
        
        query_embedding = embeddings[0]
        chunk_embeddings = embeddings[1:]
        
        # Calculate similarity scores
        for i, chunk in enumerate(chunks):
            similarity = self.cosine_similarity(query_embedding, chunk_embeddings[i])
            chunk["similarity_score"] = similarity
        
        # Sort by similarity (descending)
        sorted_chunks = sorted(chunks, key=lambda x: x["similarity_score"], reverse=True)
        
        if top_k is not None:
            return sorted_chunks[:top_k]
        
        return sorted_chunks
    
    def deduplicate_chunks(
        self,
        chunks: List[Dict[str, Any]],
        similarity_threshold: float = 0.95
    ) -> List[Dict[str, Any]]:
        """
        Remove highly similar chunks to reduce redundancy.
        
        Args:
            chunks: List of chunk dictionaries with 'text' key
            similarity_threshold: Similarity threshold for deduplication
        
        Returns:
            List of deduplicated chunks
        """
        if not chunks:
            return []
        
        # Get embeddings for all chunks
        texts = [chunk["text"] for chunk in chunks]
        embeddings = self.get_embeddings(texts)
        
        # Track which chunks to keep
        keep_indices = []
        
        for i in range(len(chunks)):
            is_duplicate = False
            
            # Check against all previously kept chunks
            for kept_idx in keep_indices:
                similarity = self.cosine_similarity(embeddings[i], embeddings[kept_idx])
                
                if similarity >= similarity_threshold:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                keep_indices.append(i)
        
        deduplicated = [chunks[i] for i in keep_indices]
        
        logger.debug(
            f"Deduplicated {len(chunks)} chunks to {len(deduplicated)} "
            f"(removed {len(chunks) - len(deduplicated)} duplicates)"
        )
        
        return deduplicated
