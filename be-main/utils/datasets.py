"""LLM-backed validation of extracted dataset names.

Extraction pulls plenty of noise out of papers -- section headings, table
captions, stray capitalised phrases. This asks the model which of the
candidates are real, named datasets before any of them reach a chart.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class DatasetValidator:
    """Validates dataset names using an LLM to filter out invalid entries."""
    
    def __init__(self, llm_client):
        """
        Initialize validator with LLM client.
        
        Args:
            llm_client: OpenRouterClient instance for validation
        """
        self.llm_client = llm_client
    
    def validate_datasets(self, dataset_names: List[str]) -> Dict[str, bool]:
        """
        Validate a batch of dataset names using LLM.
        
        Args:
            dataset_names: List of dataset names to validate
            
        Returns:
            Dictionary mapping dataset name to validity (True/False)
        """
        if not dataset_names:
            return {}
        
        system_prompt = """You are a research dataset validator. Your task is to identify whether each given name represents an actual research dataset or not.

A valid dataset is:
- A named collection of data used in research (e.g., "ImageNet", "COCO", "MNIST")
- A publicly available or well-known dataset in academic research
- A specific database or corpus used for experiments

NOT a valid dataset:
- Generic descriptions (e.g., "Real data", "Custom dataset", "Our data")
- Vague references (e.g., "GitHub repository", "User data", "Places")
- Method names, tool names, or software (e.g., "OpenStreetMap" is a service, not a dataset)
- Generic locations or sources

Return ONLY a JSON object with dataset names as keys and boolean values (true for valid, false for invalid)."""

        user_message = f"""Validate these dataset names and return true/false for each:

{json.dumps(dataset_names, indent=2)}

Return format:
{{
  "dataset_name_1": true,
  "dataset_name_2": false,
  ...
}}"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]

        try:
            response = self.llm_client.chat_completion(messages, response_format={"type": "json_object"})
            validation_results = json.loads(response)
            
            # Ensure all datasets have a result, default to False if missing
            result = {}
            for name in dataset_names:
                result[name] = validation_results.get(name, False)
            
            return result
        except Exception as e:
            logger.error(f"Failed to validate datasets with LLM: {e}")
            # In case of error, assume all are valid to not lose data
            return {name: True for name in dataset_names}
    
    def batch_validate_datasets(self, dataset_names: List[str], batch_size: int = 20) -> Dict[str, bool]:
        """
        Validate datasets in batches to avoid token limits.
        
        Args:
            dataset_names: List of dataset names to validate
            batch_size: Number of datasets per batch
            
        Returns:
            Dictionary mapping dataset name to validity
        """
        all_results = {}
        
        for i in range(0, len(dataset_names), batch_size):
            batch = dataset_names[i:i + batch_size]
            logger.info(f"Validating dataset batch {i//batch_size + 1} ({len(batch)} datasets)")
            results = self.validate_datasets(batch)
            all_results.update(results)
        
        return all_results
