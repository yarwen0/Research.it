"""Retrieval over a project's papers.

`chunking` splits a paper into passages, `embedder` embeds them with the right
task hint, `store` keeps them next to the papers they came from and searches
them, and `indexer` ties the three together for the pipeline.
"""
