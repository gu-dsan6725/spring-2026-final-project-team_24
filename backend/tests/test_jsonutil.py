# Adapted from: vendor/yubo/tests/test_karpathy_jsonutil.py
"""Tests for app.ai.jsonutil — LLM JSON extraction utilities."""

from __future__ import annotations

from app.ai.jsonutil import extract_first_json_object, load_llm_json, strip_code_fence


def test_strip_code_fence_json():
    assert strip_code_fence('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_strip_code_fence_no_fence():
    assert strip_code_fence('{"a": 1}') == '{"a": 1}'


def test_strip_code_fence_with_language_tag():
    assert strip_code_fence("```python\nprint('hi')\n```") == "print('hi')"


def test_extract_first_json_object_with_preamble():
    raw = 'Sure, here is the result:\n{"x": 1, "y": {"z": 2}}\nDone.'
    s = extract_first_json_object(raw)
    assert s is not None
    assert '"x": 1' in s
    assert s.startswith("{") and s.endswith("}")


def test_extract_first_json_object_nested():
    raw = '{"outer": {"inner": "val"}}'
    s = extract_first_json_object(raw)
    assert s == raw


def test_extract_first_json_object_no_json():
    assert extract_first_json_object("no json here") is None


def test_extract_first_json_object_with_strings_containing_braces():
    raw = '{"msg": "hello {world}"}'
    s = extract_first_json_object(raw)
    assert s == raw


def test_load_llm_json_strips_fence():
    d = load_llm_json('```json\n{"ok": true}\n```')
    assert d == {"ok": True}


def test_load_llm_json_with_preamble():
    d = load_llm_json('Here is the JSON:\n{"result": 42}')
    assert d == {"result": 42}


def test_load_llm_json_empty():
    assert load_llm_json("") is None
    assert load_llm_json("   ") is None


def test_load_llm_json_non_object():
    assert load_llm_json("[1, 2, 3]") is None


def test_load_llm_json_invalid():
    assert load_llm_json("{broken json") is None
