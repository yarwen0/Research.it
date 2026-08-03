"""
Trend analysis and graph data generation for research visualization.

This module provides functions to analyze processed research papers and generate
trend data suitable for visualization with MUI X Charts in React frontend.
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Literal
from collections import Counter, defaultdict
from datetime import datetime
import logging
import re

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from sklearn.metrics.pairwise import cosine_similarity

from utils.charts import ChartType, LayoutType, create_chart_response
from utils.datasets import DatasetValidator

logger = logging.getLogger(__name__)


class TrendsCreator:
    """
    Creates trend analyses from processed research papers.
    
    Generates various chart-ready data structures for MUI X Charts including:
    - Time series trends (publications over time)
    - Method frequency distributions
    - Dataset usage patterns
    - Research topic coverage
    - Assumption and limitation patterns
    """
    
    def __init__(self, processed_papers_data: Dict[str, Any], ontology_data: Optional[Dict[str, Any]] = None, llm_client=None):
        """
        Initialize trends creator with processed papers data.
        
        Args:
            processed_papers_data: Dictionary containing processed papers (from JSON file)
            ontology_data: Optional ontology data for enriched analysis
            llm_client: Optional LLM client for dataset validation
        """
        self.data = processed_papers_data
        self.papers = processed_papers_data.get('papers', [])
        self.user_prompt = processed_papers_data.get('user_prompt', 'Unknown Research Area')
        self.ontology = ontology_data or {}
        self.llm_client = llm_client
        self.dataset_validator = DatasetValidator(llm_client) if llm_client else None
        
    @classmethod
    def from_file(cls, filepath: str, ontology_filepath: Optional[str] = None, llm_client=None):
        """
        Create TrendsCreator from a processed papers JSON file.
        
        Args:
            filepath: Path to processed papers JSON file
            ontology_filepath: Optional path to ontology JSON file
            llm_client: Optional LLM client for dataset validation
            
        Returns:
            TrendsCreator instance
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        ontology = None
        if ontology_filepath:
            with open(ontology_filepath, 'r', encoding='utf-8') as f:
                ontology = json.load(f)
        
        return cls(data, ontology, llm_client)
    
    @classmethod
    def from_latest_file(cls, data_dir: str = "data", ontology_filepath: Optional[str] = None, llm_client=None):
        """
        Create TrendsCreator from the most recent processed papers file.
        
        Args:
            data_dir: Directory containing processed papers JSON files
            ontology_filepath: Optional path to ontology JSON file
            llm_client: Optional LLM client for dataset validation
            
        Returns:
            TrendsCreator instance
        """
        data_path = Path(data_dir)
        json_files = list(data_path.glob("processed_papers_*.json"))
        
        if not json_files:
            raise FileNotFoundError(f"No processed papers files found in {data_dir}")
        
        # Get most recent file by modification time
        latest_file = max(json_files, key=lambda p: p.stat().st_mtime)
        logger.info(f"Loading latest processed papers file: {latest_file}")
        
        return cls.from_file(str(latest_file), ontology_filepath, llm_client)
    
    def create_all_trends(self) -> Dict[str, Any]:
        """
        Generate all available trend analyses.
        
        Returns:
            Dictionary containing all trend data for frontend visualization
        """
        trends = {
            "metadata": self._get_metadata(),
        }
        
        # Only add charts with meaningful data
        # Publication timeline - needs at least 2 years for trend
        pub_timeline = self.get_publication_timeline()
        if len(pub_timeline.get("dataPoints", [])) >= 2:
            trends["publication_timeline"] = pub_timeline
        
        # Method frequency - needs at least 3 methods
        method_freq = self.get_method_frequency(top_n=15)
        if len(method_freq.get("dataPoints", [])) >= 3:
            trends["method_frequency"] = method_freq
        
        # Sankey: Research Flow (Topics → Methods → Future Work) - 3rd in order
        research_flow = self.get_research_flow_sankey()
        if len(research_flow.get("dataPoints", [])) >= 3:
            trends["research_flow_sankey"] = research_flow
        
        
        # Research evolution - needs at least 2 years
        research_evol = self.get_research_evolution()
        if len(research_evol.get("dataPoints", [])) >= 2:
            trends["research_evolution"] = research_evol
        
        # Future work - needs at least 3 themes
        future_work = self.get_future_work_themes(top_n=10)
        if len(future_work.get("dataPoints", [])) >= 3:
            trends["future_work_themes"] = future_work
        
        # Wordcloud: Assumptions - needs at least 5 assumptions
        assumptions_cloud = self.get_assumptions_wordcloud(top_n=50)
        if len(assumptions_cloud.get("dataPoints", [])) >= 5:
            trends["assumptions_wordcloud"] = assumptions_cloud
        
        # Wordcloud: Limitations - needs at least 5 limitations
        limitations_cloud = self.get_limitations_wordcloud(top_n=50)
        if len(limitations_cloud.get("dataPoints", [])) >= 5:
            trends["limitations_wordcloud"] = limitations_cloud
        
        # Topics summary - always include for frontend navigation
        trends["topics_summary"] = self.get_topics_summary()
        
        return trends
    
    def _get_metadata(self) -> Dict[str, Any]:
        """Get metadata about the dataset."""
        return {
            "user_prompt": self.user_prompt,
            "total_papers": len(self.papers),
            "timestamp": self.data.get('timestamp'),
            "unique_topics": len(set(p.get('topic', '') for p in self.papers)),
            "unique_authors": len(self._get_all_authors()),
            "date_range": self._get_date_range()
        }
    
    def get_publication_timeline(self) -> Dict[str, Any]:
        """
        Create time series data of publications over time.
        
        Returns MUI X Charts line/bar chart compatible data.
        """
        # Extract publication years
        year_counts = Counter()
        year_papers = defaultdict(list)
        
        for paper in self.papers:
            pub_date = paper.get('published', '')
            if pub_date:
                try:
                    year = datetime.fromisoformat(pub_date.replace('+00:00', '')).year
                    year_counts[year] += 1
                    year_papers[year].append(paper.get('title', 'Untitled'))
                except (ValueError, AttributeError):
                    continue
        
        # Sort by year
        sorted_years = sorted(year_counts.keys()) if year_counts else []
        
        data_points = [
            {
                "id": f"year_{year}",
                "label": str(year),
                "value": year_counts[year],
                "year": year,
                "papers": year_papers[year]
            }
            for year in sorted_years
        ]
        
        series = [
            {
                "id": "publications",
                "label": "Publications",
                "color": "#1976d2",
                "valueKey": "value"
            }
        ]
        
        return create_chart_response(
            chart_type="line",
            title="Publication Timeline",
            description=f"Number of papers published per year in '{self.user_prompt}' research",
            data_points=data_points,
            series=series,
            x_axis_label="Year",
            y_axis_label="Number of Publications"
        )
    
    def _categorize_methods_with_nlp(self, methods_list: List[str], n_categories: int = 6) -> Dict[str, List[str]]:
        """
        Use NLP to categorize methods into topic clusters.
        
        Args:
            methods_list: List of method names
            n_categories: Number of categories to create
            
        Returns:
            Dictionary mapping category name to list of methods
        """
        if len(methods_list) < n_categories:
            # Not enough methods to categorize, return as single category
            return {"Methods": methods_list}
        
        try:
            # Vectorize method names using TF-IDF
            vectorizer = TfidfVectorizer(
                max_features=100,
                ngram_range=(1, 3),
                stop_words='english'
            )
            method_vectors = vectorizer.fit_transform(methods_list)
            
            # Cluster methods using K-Means
            n_clusters = min(n_categories, len(methods_list))
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
            clusters = kmeans.fit_predict(method_vectors)
            
            # Group methods by cluster
            clustered_methods = defaultdict(list)
            for method, cluster_id in zip(methods_list, clusters):
                clustered_methods[cluster_id].append(method)
            
            # Name each cluster based on common terms
            category_names = {}
            feature_names = vectorizer.get_feature_names_out()
            
            for cluster_id, cluster_center in enumerate(kmeans.cluster_centers_):
                # Get top terms for this cluster
                top_indices = cluster_center.argsort()[-3:][::-1]
                top_terms = [str(feature_names[i]) for i in top_indices if i < len(feature_names)]
                
                # Create a meaningful category name
                if top_terms:
                    category_name = " & ".join([term.title() for term in top_terms[:2]])
                else:
                    category_name = f"Category {cluster_id + 1}"
                
                category_names[cluster_id] = category_name
            
            # Return categorized methods with named categories
            categorized = {}
            for cluster_id, methods in clustered_methods.items():
                category_name = category_names.get(cluster_id, f"Category {cluster_id + 1}")
                categorized[category_name] = methods
            
            return categorized
            
        except Exception as e:
            logger.warning(f"NLP categorization failed: {e}. Falling back to simple grouping.")
            # Fallback: group by first word
            categorized = defaultdict(list)
            for method in methods_list:
                first_word = method.split()[0] if method else "Other"
                categorized[first_word].append(method)
            return dict(categorized)
    
    def get_method_frequency(self, top_n: int = 15) -> Dict[str, Any]:
        """
        Analyze frequency of methods used across papers with NLP categorization.
        Returns radar chart format showing method categories by research topic.
        
        Args:
            top_n: Number of top methods to include per topic (kept for backward compatibility but not used in radar chart)
            
        Returns MUI X Charts radar chart compatible data.
        """
        method_counts = Counter()
        method_papers = defaultdict(list)
        
        for paper in self.papers:
            normalized = paper.get('normalized', {})
            methods = normalized.get('methods', [])
            
            for method in methods:
                if isinstance(method, list) and len(method) >= 2:
                    method_key = method[0]
                    method_name = method[1]
                else:
                    method_key = str(method)
                    method_name = str(method)
                
                if method_name and method_name.strip():
                    method_counts[method_name] += 1
                    method_papers[method_name].append(paper.get('title', 'Untitled'))
        
        if not method_counts:
            return {
                "config": {
                    "type": "radar",
                    "title": "Method Categories by Research Topic",
                    "description": "No methods data available",
                },
                "dataPoints": [],
                "series": [],
                "radar": {
                    "metrics": [],
                    "max": 10
                }
            }
        
        # Get all unique methods
        all_methods = list(method_counts.keys())
        
        # Categorize methods using NLP
        method_categories = self._categorize_methods_with_nlp(all_methods, n_categories=6)
        
        # Build topic-category counts
        topic_category_counts = defaultdict(lambda: defaultdict(int))
        
        for paper in self.papers:
            topic = paper.get('topic', 'Uncategorized')
            normalized = paper.get('normalized', {})
            methods = normalized.get('methods', [])
            
            for method in methods:
                if isinstance(method, list) and len(method) >= 2:
                    method_name = method[1]
                else:
                    method_name = str(method)
                
                if method_name and method_name.strip():
                    # Find which category this method belongs to
                    for category, category_methods in method_categories.items():
                        if method_name in category_methods:
                            topic_category_counts[topic][category] += 1
                            break
        
        # Prepare metrics (categories)
        category_names = list(method_categories.keys())
        
        # Find max value for normalization
        max_value = 0
        for topic_counts in topic_category_counts.values():
            max_value = max(max_value, max(topic_counts.values()) if topic_counts else 0)
        
        # Create series for each topic
        series = []
        for idx, (topic, category_counts) in enumerate(topic_category_counts.items()):
            topic_short = topic[:40] + "..." if len(topic) > 40 else topic
            series.append({
                "id": f"topic_{idx}",
                "label": topic_short,
                "data": [category_counts.get(cat, 0) for cat in category_names],
                "fullTopic": topic
            })
        
        data_points = [
            {
                "id": f"category_{idx}",
                "label": category[:50] + "..." if len(category) > 50 else category,
                "fullName": category,
                "methods": method_categories[category][:5],  # First 5 methods as examples
                "totalMethods": len(method_categories[category])
            }
            for idx, category in enumerate(category_names)
        ]
        
        return {
            "config": {
                "type": "radar",
                "title": "Method Categories by Research Topic",
                "description": f"NLP-categorized methods across topics in '{self.user_prompt}' research",
            },
            "dataPoints": data_points,
            "series": series,
            "radar": {
                "metrics": category_names,
                "max": max_value if max_value > 0 else 10
            }
        }
    
    def get_research_evolution(self) -> Dict[str, Any]:
        """
        Analyze how research has evolved over time (methods adoption trends).
        
        Returns MUI X Charts line chart compatible data.
        """
        # Group papers by year and count unique methods
        year_method_diversity = defaultdict(set)
        year_paper_count = Counter()
        
        for paper in self.papers:
            pub_date = paper.get('published', '')
            if pub_date:
                try:
                    year = datetime.fromisoformat(pub_date.replace('+00:00', '')).year
                    year_paper_count[year] += 1
                    
                    normalized = paper.get('normalized', {})
                    methods = normalized.get('methods', [])
                    
                    for method in methods:
                        if isinstance(method, list) and len(method) >= 2:
                            method_key = method[0]
                            year_method_diversity[year].add(method_key)
                except (ValueError, AttributeError):
                    continue
        
        sorted_years = sorted(year_method_diversity.keys()) if year_method_diversity else []
        
        data_points = [
            {
                "id": f"year_{year}",
                "label": str(year),
                "value": len(year_method_diversity[year]),
                "year": year,
                "uniqueMethods": len(year_method_diversity[year]),
                "paperCount": year_paper_count[year],
                "methodsPerPaper": round(len(year_method_diversity[year]) / year_paper_count[year], 2) if year_paper_count[year] > 0 else 0
            }
            for year in sorted_years
        ]
        
        # Create multi-line series
        series = [
            {
                "id": "unique_methods",
                "label": "Unique Methods",
                "color": "#1976d2",
                "valueKey": "uniqueMethods"
            },
            {
                "id": "paper_count",
                "label": "Paper Count",
                "color": "#2e7d32",
                "valueKey": "paperCount"
            }
        ]
        
        return create_chart_response(
            chart_type="line",
            title="Research Evolution Over Time",
            description="Method diversity and publication volume trends",
            data_points=data_points,
            series=series,
            x_axis_label="Year",
            y_axis_label="Count"
        )
    
    def get_future_work_themes(self, top_n: int = 10) -> Dict[str, Any]:
        """
        Analyze common themes in future work suggestions across topics using radar chart.
        
        Args:
            top_n: Number of top themes to include
            
        Returns MUI X Charts radar chart compatible data.
        """
        future_work_counts = Counter()
        future_work_papers = defaultdict(list)
        topic_future_work_counts = defaultdict(lambda: defaultdict(int))
        
        for paper in self.papers:
            topic = paper.get('topic', 'Uncategorized')
            topic_short = topic[:40] + "..." if len(topic) > 40 else topic
            normalized = paper.get('normalized', {})
            future_work = normalized.get('future_work', [])
            
            for work in future_work:
                if isinstance(work, list) and len(work) >= 2:
                    work_text = work[1]
                else:
                    work_text = str(work)
                
                if work_text and work_text.strip():
                    # Truncate for cleaner display
                    work_short = work_text[:60] + "..." if len(work_text) > 60 else work_text
                    future_work_counts[work_short] += 1
                    future_work_papers[work_short].append(paper.get('title', 'Untitled'))
                    topic_future_work_counts[topic_short][work_short] += 1
        
        if not future_work_counts:
            return {
                "config": {
                    "type": "radar",
                    "title": "Future Research Directions by Topic",
                    "description": "No future work data available",
                },
                "dataPoints": [],
                "series": [],
                "radar": {
                    "metrics": [],
                    "max": 10
                }
            }
        
        # Get top future work themes overall
        top_themes = [theme for theme, _ in future_work_counts.most_common(top_n)]
        
        # Find max value for normalization
        max_value = 0
        for topic_counts in topic_future_work_counts.values():
            max_value = max(max_value, max(topic_counts.values()) if topic_counts else 0)
        
        # Create series for each topic
        series = []
        for idx, (topic, theme_counts) in enumerate(topic_future_work_counts.items()):
            series.append({
                "id": f"topic_{idx}",
                "label": topic,
                "data": [theme_counts.get(theme, 0) for theme in top_themes],
                "fullTopic": topic
            })
        
        # Create data points for themes
        data_points = [
            {
                "id": f"theme_{idx}",
                "label": theme[:50] + "..." if len(theme) > 50 else theme,
                "fullText": theme,
                "papers": future_work_papers[theme][:3],
                "totalPapers": len(future_work_papers[theme]),
                "totalMentions": future_work_counts[theme]
            }
            for idx, theme in enumerate(top_themes)
        ]
        
        return {
            "config": {
                "type": "radar",
                "title": "Future Research Directions by Topic",
                "description": f"Top {len(top_themes)} future work themes across research topics",
            },
            "dataPoints": data_points,
            "series": series,
            "radar": {
                "metrics": top_themes,
                "max": max_value if max_value > 0 else 10
            }
        }
    
    def _extract_meaningful_words(self, texts: List[str], top_n: int = 50, min_word_length: int = 3) -> List[tuple]:
        """
        Extract the most meaningful words from a collection of texts using TF-IDF.
        
        Args:
            texts: List of text strings to analyze
            top_n: Number of top words to extract
            min_word_length: Minimum length for words to be considered
            
        Returns:
            List of (word, score) tuples, sorted by importance
        """
        if not texts:
            return []
        
        # Combine all texts
        combined_text = " ".join(texts)
        
        # Extended stopwords list (common English words that don't add meaning)
        custom_stopwords = [
            'the', 'be', 'to', 'of', 'and', 'a', 'in', 'that', 'have', 'i',
            'it', 'for', 'not', 'on', 'with', 'he', 'as', 'you', 'do', 'at',
            'this', 'but', 'his', 'by', 'from', 'they', 'we', 'say', 'her', 'she',
            'or', 'an', 'will', 'my', 'one', 'all', 'would', 'there', 'their',
            'what', 'so', 'up', 'out', 'if', 'about', 'who', 'get', 'which', 'go',
            'me', 'when', 'make', 'can', 'like', 'time', 'no', 'just', 'him', 'know',
            'take', 'people', 'into', 'year', 'your', 'good', 'some', 'could', 'them',
            'see', 'other', 'than', 'then', 'now', 'look', 'only', 'come', 'its', 'over',
            'think', 'also', 'back', 'after', 'use', 'two', 'how', 'our', 'work', 'first',
            'well', 'way', 'even', 'new', 'want', 'because', 'any', 'these', 'give', 'day',
            'most', 'us', 'is', 'was', 'are', 'been', 'has', 'had', 'were', 'said', 'did',
            'having', 'may', 'such', 'being', 'does', 'done', 'each', 'both', 'few', 'more',
            'many', 'much', 'such', 'own', 'same', 'than', 'too', 'very', 'can', 'should',
            'might', 'must', 'shall', 'could', 'would', 'ought', 'need', 'used', 'using',
            'based', 'however', 'although', 'though', 'yet', 'still', 'therefore', 'thus',
            'hence', 'since', 'while', 'whereas', 'whether', 'where', 'here', 'there',
            'present', 'study', 'paper', 'research', 'work', 'approach', 'method', 'result'
        ]
        
        try:
            # Use TF-IDF to extract meaningful terms
            # Token pattern to extract words and technical terms (including hyphens, underscores)
            vectorizer = TfidfVectorizer(
                max_features=top_n * 3,  # Get more than needed to filter
                stop_words=custom_stopwords,
                token_pattern=r'\b[a-zA-Z][a-zA-Z\-_]{' + str(min_word_length-1) + r',}\b',
                lowercase=True,
                ngram_range=(1, 2),  # Include bigrams for better context
                max_df=0.8,  # Ignore terms that appear in >80% of docs (too common)
                min_df=2  # Must appear at least twice
            )
            
            # Fit on individual texts to get better TF-IDF scores
            tfidf_matrix = vectorizer.fit_transform(texts)
            
            # Get feature names and their average TF-IDF scores
            feature_names = vectorizer.get_feature_names_out()
            
            # Calculate mean TF-IDF score for each term across all documents
            mean_tfidf = np.asarray(tfidf_matrix.mean(axis=0)).ravel()  # type: ignore
            
            # Create word-score pairs
            word_scores = list(zip(feature_names, mean_tfidf))
            
            # Sort by score descending
            word_scores.sort(key=lambda x: x[1], reverse=True)
            
            # Filter out very short words and take top_n
            filtered_words = [
                (word, score) for word, score in word_scores 
                if len(word) >= min_word_length and score > 0
            ][:top_n]
            
            return filtered_words
            
        except Exception as e:
            logger.error(f"Error extracting meaningful words: {e}")
            
            # Fallback: simple word frequency
            words = re.findall(r'\b[a-zA-Z][a-zA-Z\-_]{' + str(min_word_length-1) + r',}\b', combined_text.lower())
            word_counts = Counter(
                w for w in words 
                if w not in custom_stopwords and len(w) >= min_word_length
            )
            return word_counts.most_common(top_n)
    
    def get_assumptions_wordcloud(self, top_n: int = 50) -> Dict[str, Any]:
        """
        Generate wordcloud-friendly data for assumptions using NLP to extract meaningful words.
        Combines all assumption texts and uses TF-IDF to find the most significant terms.
        
        Args:
            top_n: Number of top words to include
            
        Returns wordcloud compatible data format.
        """
        all_assumption_texts = []
        assumption_by_paper = defaultdict(list)
        
        for paper in self.papers:
            normalized = paper.get('normalized', {})
            explicit = normalized.get('assumptions_explicit', [])
            implicit = normalized.get('assumptions_implicit', [])
            all_assumptions = explicit + implicit
            
            paper_title = paper.get('title', 'Untitled')
            
            for assumption in all_assumptions:
                if isinstance(assumption, list) and len(assumption) >= 2:
                    assumption_text = assumption[1]
                else:
                    assumption_text = str(assumption)
                
                if assumption_text and assumption_text.strip():
                    all_assumption_texts.append(assumption_text)
                    assumption_by_paper[assumption_text].append(paper_title)
        
        if not all_assumption_texts:
            return {
                "config": {
                    "type": "wordcloud",
                    "title": "Research Assumptions Cloud",
                    "description": "No assumptions found",
                },
                "dataPoints": [],
                "series": [],
                "wordcloud": {
                    "minFontSize": 12,
                    "maxFontSize": 60,
                    "rotationAngles": [0, 90]
                }
            }
        
        # Extract meaningful words using NLP
        word_scores = self._extract_meaningful_words(all_assumption_texts, top_n=top_n)
        
        if not word_scores:
            return {
                "config": {
                    "type": "wordcloud",
                    "title": "Research Assumptions Cloud",
                    "description": "Could not extract meaningful words",
                },
                "dataPoints": [],
                "series": [],
                "wordcloud": {
                    "minFontSize": 12,
                    "maxFontSize": 60,
                    "rotationAngles": [0, 90]
                }
            }
        
        # Normalize scores to reasonable range for wordcloud (1-100)
        max_score = word_scores[0][1] if word_scores else 1
        min_score = word_scores[-1][1] if word_scores else 0
        score_range = max_score - min_score if max_score > min_score else 1
        
        word_papers = defaultdict(set)
        for word, _ in word_scores:
            word_lower = word.lower()
            for assumption_text, papers in assumption_by_paper.items():
                if word_lower in assumption_text.lower():
                    word_papers[word].update(papers)
        
        wordcloud_data = [
            {
                "text": word,
                "value": int(10 + ((score - min_score) / score_range) * 90),  # Scale to 10-100
                "rawScore": float(score),
                "papers": list(word_papers[word])[:3],
                "totalPapers": len(word_papers[word])
            }
            for word, score in word_scores
        ]
        
        return {
            "config": {
                "type": "wordcloud",
                "title": "Research Assumptions Cloud",
                "description": f"Top {len(wordcloud_data)} most significant terms from {len(all_assumption_texts)} assumptions",
            },
            "dataPoints": wordcloud_data,
            "series": [],
            "wordcloud": {
                "minFontSize": 12,
                "maxFontSize": 60,
                "rotationAngles": [0, 90]
            }
        }
    
    def get_limitations_wordcloud(self, top_n: int = 50) -> Dict[str, Any]:
        """
        Generate wordcloud-friendly data for limitations using NLP to extract meaningful words.
        Combines all limitation texts and uses TF-IDF to find the most significant terms.
        
        Args:
            top_n: Number of top words to include
            
        Returns wordcloud compatible data format.
        """
        all_limitation_texts = []
        limitation_by_paper = defaultdict(list)
        
        for paper in self.papers:
            normalized = paper.get('normalized', {})
            explicit = normalized.get('limitations_explicit', [])
            implicit = normalized.get('limitations_implied', [])
            all_limitations = explicit + implicit
            
            paper_title = paper.get('title', 'Untitled')
            
            for limitation in all_limitations:
                if isinstance(limitation, list) and len(limitation) >= 2:
                    limitation_text = limitation[1]
                else:
                    limitation_text = str(limitation)
                
                if limitation_text and limitation_text.strip():
                    all_limitation_texts.append(limitation_text)
                    limitation_by_paper[limitation_text].append(paper_title)
        
        if not all_limitation_texts:
            return {
                "config": {
                    "type": "wordcloud",
                    "title": "Research Limitations Cloud",
                    "description": "No limitations found",
                },
                "dataPoints": [],
                "series": [],
                "wordcloud": {
                    "minFontSize": 12,
                    "maxFontSize": 60,
                    "rotationAngles": [0, 90]
                }
            }
        
        # Extract meaningful words using NLP
        word_scores = self._extract_meaningful_words(all_limitation_texts, top_n=top_n)
        
        if not word_scores:
            return {
                "config": {
                    "type": "wordcloud",
                    "title": "Research Limitations Cloud",
                    "description": "Could not extract meaningful words",
                },
                "dataPoints": [],
                "series": [],
                "wordcloud": {
                    "minFontSize": 12,
                    "maxFontSize": 60,
                    "rotationAngles": [0, 90]
                }
            }
        
        # Normalize scores to reasonable range for wordcloud (1-100)
        max_score = word_scores[0][1] if word_scores else 1
        min_score = word_scores[-1][1] if word_scores else 0
        score_range = max_score - min_score if max_score > min_score else 1
        
        # Find which papers contain each word
        word_papers = defaultdict(set)
        for word, _ in word_scores:
            word_lower = word.lower()
            for limitation_text, papers in limitation_by_paper.items():
                if word_lower in limitation_text.lower():
                    word_papers[word].update(papers)
        
        wordcloud_data = [
            {
                "text": word,
                "value": int(10 + ((score - min_score) / score_range) * 90),  # Scale to 10-100
                "rawScore": float(score),
                "papers": list(word_papers[word])[:3],
                "totalPapers": len(word_papers[word])
            }
            for word, score in word_scores
        ]
        
        return {
            "config": {
                "type": "wordcloud",
                "title": "Research Limitations Cloud",
                "description": f"Top {len(wordcloud_data)} most significant terms from {len(all_limitation_texts)} limitations",
            },
            "dataPoints": wordcloud_data,
            "series": [],
            "wordcloud": {
                "minFontSize": 12,
                "maxFontSize": 60,
                "rotationAngles": [0, 90]
            }
        }
    
    def get_research_flow_sankey(self) -> Dict[str, Any]:
        """
        Create a Sankey diagram showing research methodology flow:
        Topics → Methods → Future Work Directions
        
        Shows how different research topics use specific methods and lead to future directions.
        Uses AG Grid Charts format (simpler than MUI X).
        
        Returns AG Grid Sankey compatible data.
        """
        # Collect top methods and future work themes
        method_counts = Counter()
        future_work_counts = Counter()
        
        # Track which topics use which methods/future work
        topic_methods = defaultdict(lambda: defaultdict(int))
        method_future_work = defaultdict(lambda: defaultdict(int))
        
        for paper in self.papers:
            topic = paper.get('topic', 'Uncategorized')
            # Truncate topic name for cleaner display
            topic_short = topic[:45] + "..." if len(topic) > 45 else topic
            
            normalized = paper.get('normalized', {})
            
            # Process methods
            methods = normalized.get('methods', [])
            paper_methods = []
            
            for method in methods:
                if isinstance(method, list) and len(method) >= 2:
                    method_name = method[1]
                else:
                    method_name = str(method)
                
                if method_name and method_name.strip():
                    # Truncate for display
                    method_short = method_name[:45] + "..." if len(method_name) > 45 else method_name
                    method_counts[method_short] += 1
                    topic_methods[topic_short][method_short] += 1
                    paper_methods.append(method_short)
            
            # Process future work
            future_work = normalized.get('future_work', [])
            
            for work in future_work:
                if isinstance(work, list) and len(work) >= 2:
                    work_text = work[1]
                else:
                    work_text = str(work)
                
                if work_text and work_text.strip():
                    # Truncate for display
                    work_short = work_text[:45] + "..." if len(work_text) > 45 else work_text
                    future_work_counts[work_short] += 1
                    
                    # Connect methods to future work within same paper
                    for method_short in paper_methods:
                        method_future_work[method_short][work_short] += 1
        
        # Get top methods and future work (at least 2 papers)
        top_methods = [m for m, count in method_counts.most_common(10) if count >= 1]
        top_future_work = [f for f, count in future_work_counts.most_common(10) if count >= 1]
        
        if not top_methods or not top_future_work:
            return {
                "config": {
                    "type": "sankey",
                    "title": "Research Flow: Topics → Methods → Future Work",
                    "description": "Not enough data to generate flow diagram",
                },
                "dataPoints": [],
                "series": []
            }
        
        sankey_data = []
        
        # Link 1: Topics → Methods
        for topic, methods_dict in topic_methods.items():
            for method, count in methods_dict.items():
                if method in top_methods and count >= 1:
                    sankey_data.append({
                        "from": topic,
                        "to": method,
                        "size": count,
                        "type": "topic_to_method"
                    })
        
        for method, future_dict in method_future_work.items():
            if method in top_methods:
                for future, count in future_dict.items():
                    if future in top_future_work and count >= 1:
                        sankey_data.append({
                            "from": method,
                            "to": future,
                            "size": count,
                            "type": "method_to_future_work"
                        })
        
        connected_nodes = set()
        for item in sankey_data:
            connected_nodes.add(item["from"])
            connected_nodes.add(item["to"])
        
        # Only keep data with connected nodes
        sankey_data = [item for item in sankey_data if item["from"] in connected_nodes and item["to"] in connected_nodes]
        
        if len(sankey_data) < 3:
            return {
                "config": {
                    "type": "sankey",
                    "title": "Research Flow: Topics → Methods → Future Work",
                    "description": "Not enough connections to generate flow diagram",
                },
                "dataPoints": [],
                "series": []
            }
        
        return {
            "config": {
                "type": "sankey",
                "title": "Research Flow: Topics → Methods → Future Work",
                "description": "How research topics use specific methods and lead to future research directions",
                "fromKey": "from",
                "toKey": "to",
                "sizeKey": "size"
            },
            "dataPoints": sankey_data,
            "series": [{
                "type": "sankey",
                "fromKey": "from",
                "toKey": "to",
                "sizeKey": "size"
            }],
            "sankey": {
                "totalLinks": len(sankey_data),
                "nodeAlignment": "justify",
                "uniqueNodes": len(connected_nodes)
            }
        }
    
    def _get_all_authors(self) -> set:
        """Get set of all unique authors."""
        authors = set()
        for paper in self.papers:
            for author in paper.get('authors', []):
                authors.add(author)
        return authors
    
    def _get_date_range(self) -> Dict[str, str]:
        """Get earliest and latest publication dates."""
        dates = []
        for paper in self.papers:
            pub_date = paper.get('published', '')
            if pub_date:
                try:
                    dates.append(datetime.fromisoformat(pub_date.replace('+00:00', '')))
                except (ValueError, AttributeError):
                    continue
        
        if dates:
            return {
                "earliest": min(dates).isoformat(),
                "latest": max(dates).isoformat()
            }
        return {"earliest": "", "latest": ""}
    
    def get_topics_summary(self) -> Dict[str, Any]:
        """
        Create a structured summary of topics with associated paper IDs.
        
        Frontend can use these paper IDs to lookup full paper data from processed_papers.
        
        Returns:
            Dictionary with topic names and their associated paper IDs
        """
        topics_data = {}
        
        for paper in self.papers:
            topic = paper.get('topic', 'Uncategorized')
            paper_id = paper.get('paper_id', '')
            
            if topic not in topics_data:
                topics_data[topic] = {
                    "topic": topic,
                    "paper_ids": []
                }
            
            topics_data[topic]["paper_ids"].append(paper_id)
        
        # Convert to list and sort by topic name
        topics_list = list(topics_data.values())
        topics_list.sort(key=lambda x: x["topic"])
        
        return {
            "total_topics": len(topics_list),
            "topics": topics_list
        }
    
    def get_dataset_summary(self) -> Dict[str, Any]:
        """
        Create a comprehensive dataset summary with detailed information.
        
        This aggregates all dataset information across papers and provides:
        - Validated dataset identifiers (filtered with LLM if available)
        - Normalized dataset identifiers and their original names
        - Count of papers using each dataset
        - List of papers using each dataset
        - Pie chart data for visualization
        - Dataset metadata and descriptions
        
        Returns:
            Dictionary with organized dataset information for frontend display
        """
        dataset_info = {}
        
        for paper in self.papers:
            normalized = paper.get('normalized', {})
            datasets = normalized.get('datasets', [])
            paper_id = paper.get('paper_id', '')
            paper_title = paper.get('title', 'Untitled')
            
            for dataset in datasets:
                if isinstance(dataset, list) and len(dataset) >= 2:
                    dataset_key = dataset[0]  # Normalized identifier
                    dataset_original = dataset[1]  # Original text from paper
                else:
                    continue
                
                if not dataset_key or not dataset_key.strip():
                    continue
                
                # Initialize dataset entry if not exists
                if dataset_key not in dataset_info:
                    dataset_info[dataset_key] = {
                        "normalized_id": dataset_key,
                        "original_names": set(),
                        "paper_count": 0,
                        "papers": []
                    }
                
                # Add original name variant
                if dataset_original and dataset_original.strip():
                    dataset_info[dataset_key]["original_names"].add(dataset_original)
                
                # Add paper info (avoid duplicates)
                if not any(p["paper_id"] == paper_id for p in dataset_info[dataset_key]["papers"]):
                    dataset_info[dataset_key]["papers"].append({
                        "paper_id": paper_id,
                        "title": paper_title,
                        "original_name_used": dataset_original
                    })
                    dataset_info[dataset_key]["paper_count"] += 1
        
        # Validate datasets if LLM client is available
        validated_datasets = {}
        if self.dataset_validator:
            logger.info(f"Validating {len(dataset_info)} datasets with LLM...")
            
            # Collect all unique original names for validation
            all_original_names = set()
            for info in dataset_info.values():
                all_original_names.update(info["original_names"])
            
            # Validate in batches
            validation_results = self.dataset_validator.batch_validate_datasets(list(all_original_names))
            
            # Filter out invalid datasets (where ALL original names are invalid)
            for dataset_key, info in dataset_info.items():
                # Check if at least one original name is valid
                has_valid_name = any(
                    validation_results.get(name, False) 
                    for name in info["original_names"]
                )
                
                if has_valid_name:
                    validated_datasets[dataset_key] = info
                else:
                    logger.info(f"Filtered out invalid dataset: {dataset_key} (names: {info['original_names']})")
            
            logger.info(f"Validation complete: {len(validated_datasets)}/{len(dataset_info)} datasets are valid")
        else:
            logger.info("No LLM client available, skipping dataset validation")
            validated_datasets = dataset_info
        
        # Convert sets to lists for JSON serialization and sort by paper count
        dataset_summary = []
        for dataset_key, info in validated_datasets.items():
            dataset_summary.append({
                "normalized_id": info["normalized_id"],
                "original_names": sorted(list(info["original_names"])),
                "paper_count": info["paper_count"],
                "papers": info["papers"]
            })
        
        # Sort by paper count (descending)
        dataset_summary.sort(key=lambda x: x["paper_count"], reverse=True)
        
        # Generate pie chart data
        pie_chart_data = self._create_dataset_pie_chart(dataset_summary)
        
        return {
            "total_unique_datasets": len(dataset_summary),
            "datasets": dataset_summary,
            "pie_chart": pie_chart_data
        }
    
    def _create_dataset_pie_chart(self, dataset_summary: List[Dict[str, Any]], top_n: int = 10) -> Dict[str, Any]:
        """
        Create pie chart data for dataset distribution.
        
        Args:
            dataset_summary: List of dataset info dictionaries
            top_n: Number of top datasets to show individually (rest grouped as "Others")
            
        Returns:
            Pie chart compatible data structure
        """
        if not dataset_summary:
            return create_chart_response(
                chart_type="pie",
                title="Dataset Distribution",
                description="No datasets found",
                data_points=[],
                series=[]
            )
        
        # Take top N datasets
        top_datasets = dataset_summary[:top_n]
        
        # Calculate "Others" if there are more datasets
        others_count = sum(d["paper_count"] for d in dataset_summary[top_n:])
        
        # Create data points
        data_points = []
        for idx, dataset in enumerate(top_datasets):
            # Use the most common original name or normalized_id
            display_name = dataset["original_names"][0] if dataset["original_names"] else dataset["normalized_id"]
            
            # Truncate long names
            if len(display_name) > 40:
                display_name = display_name[:37] + "..."
            
            data_points.append({
                "id": dataset["normalized_id"],
                "label": display_name,
                "value": dataset["paper_count"],
                "normalized_id": dataset["normalized_id"],
                "all_names": dataset["original_names"],
                "papers": dataset["papers"]
            })
        
        # Add "Others" category if applicable
        if others_count > 0:
            data_points.append({
                "id": "others",
                "label": "Others",
                "value": others_count,
                "normalized_id": "others",
                "all_names": [],
                "papers": []
            })
        
        series = [
            {
                "id": "dataset_usage",
                "label": "Papers Using Dataset",
                "valueKey": "value"
            }
        ]
        
        total_papers = sum(d["value"] for d in data_points)
        
        return create_chart_response(
            chart_type="pie",
            title="Dataset Distribution",
            description=f"Distribution of {len(dataset_summary)} unique datasets across {total_papers} paper-dataset associations",
            data_points=data_points,
            series=series
        )


def create_trends_from_file(filepath: str, ontology_filepath: Optional[str] = None, llm_client=None) -> Dict[str, Any]:
    """
    Convenience function to create all trends from a file.
    
    Args:
        filepath: Path to processed papers JSON file
        ontology_filepath: Optional path to ontology JSON file
        llm_client: Optional LLM client for dataset validation
        
    Returns:
        Dictionary of all trend data ready for frontend
    """
    creator = TrendsCreator.from_file(filepath, ontology_filepath, llm_client)
    return creator.create_all_trends()


def create_trends_from_latest(data_dir: str = "data", ontology_filepath: Optional[str] = None, llm_client=None) -> Dict[str, Any]:
    """
    Convenience function to create all trends from the latest file.
    
    Args:
        data_dir: Directory containing processed papers JSON files
        ontology_filepath: Optional path to ontology JSON file
        llm_client: Optional LLM client for dataset validation
        
    Returns:
        Dictionary of all trend data ready for frontend
    """
    creator = TrendsCreator.from_latest_file(data_dir, ontology_filepath, llm_client)
    return creator.create_all_trends()