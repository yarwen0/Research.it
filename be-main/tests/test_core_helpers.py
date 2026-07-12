"""Tests for pure helper functions in core (schema conversion, reasoning strip).

No network or LLM calls — these are the format adapters used before dispatching
to Gemini/Ollama/OpenRouter.
"""

from __future__ import annotations

from core import (
    _strip_reasoning,
    _strip_unsupported_schema_keys,
    _to_gemini_response_schema,
    _to_ollama_format,
)


class TestStripUnsupportedSchemaKeys:
    def test_drops_incompatible_keys(self):
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "additionalProperties": False,
            "strict": True,
            "name": "Foo",
            "properties": {"a": {"type": "string"}},
        }
        cleaned = _strip_unsupported_schema_keys(schema)
        assert cleaned == {"type": "object", "properties": {"a": {"type": "string"}}}

    def test_collapses_union_type_to_first_non_null(self):
        assert _strip_unsupported_schema_keys({"type": ["string", "null"]}) == {"type": "string"}

    def test_union_type_all_null_falls_back_to_string(self):
        assert _strip_unsupported_schema_keys({"type": ["null"]}) == {"type": "string"}

    def test_recurses_into_nested_lists(self):
        schema = {"items": [{"additionalProperties": True, "type": "string"}]}
        assert _strip_unsupported_schema_keys(schema) == {"items": [{"type": "string"}]}

    def test_scalars_pass_through(self):
        assert _strip_unsupported_schema_keys("plain") == "plain"


class TestToGeminiResponseSchema:
    def test_none_returns_none(self):
        assert _to_gemini_response_schema(None) is None

    def test_unwraps_openai_json_schema_wrapper(self):
        rf = {
            "type": "json_schema",
            "json_schema": {"schema": {"type": "object", "additionalProperties": False}},
        }
        assert _to_gemini_response_schema(rf) == {"type": "object"}

    def test_raw_schema_is_stripped(self):
        assert _to_gemini_response_schema({"type": "object", "$schema": "x"}) == {"type": "object"}

    def test_missing_inner_schema_returns_none(self):
        assert _to_gemini_response_schema({"type": "json_schema", "json_schema": {}}) is None


class TestToOllamaFormat:
    def test_none_returns_none(self):
        assert _to_ollama_format(None) is None

    def test_unwraps_json_schema_wrapper(self):
        rf = {"type": "json_schema", "json_schema": {"schema": {"type": "object"}}}
        assert _to_ollama_format(rf) == {"type": "object"}

    def test_empty_inner_schema_falls_back_to_json(self):
        assert _to_ollama_format({"type": "json_schema", "json_schema": {}}) == "json"

    def test_plain_dict_passes_through(self):
        assert _to_ollama_format({"type": "object"}) == {"type": "object"}

    def test_non_dict_truthy_returns_json(self):
        assert _to_ollama_format("whatever") == "json"


class TestStripReasoning:
    def test_removes_single_think_block(self):
        assert _strip_reasoning("<think>reasoning</think>answer") == "answer"

    def test_removes_multiline_think_block(self):
        assert _strip_reasoning("a<think>x\ny</think>b") == "ab"

    def test_removes_multiple_blocks(self):
        assert _strip_reasoning("<think>1</think>mid<think>2</think>end") == "midend"

    def test_text_without_tags_is_unchanged(self):
        assert _strip_reasoning("no tags here") == "no tags here"
