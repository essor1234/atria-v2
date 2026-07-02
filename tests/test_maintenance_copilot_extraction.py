"""Tests for LLM graph extraction → validated GraphExtraction with provenance."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_MOD = Path(__file__).resolve().parent.parent / "modules" / "maintenance_copilot" / "scripts"


def _load(name, sentinel):
    spec = importlib.util.spec_from_file_location(sentinel, _MOD / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[sentinel] = mod
    spec.loader.exec_module(mod)
    return mod


_PROV = {"source_doc": "mel_ata32.md", "revision": "Rev-18", "page": "mel_ata32#0",
         "extracted_by": "Qwen2.5-1.5B"}

_GOOD = """```json
{"entities": [
   {"type": "MELItem", "key": "32-30-01", "props": {"category": "C"}},
   {"type": "ATAChapter", "key": "32", "props": {}},
   {"type": "Alien", "key": "x", "props": {}}],
 "relationships": [
   {"type": "IN_CHAPTER", "src": "32-30-01", "dst": "32", "props": {}, "confidence": 0.9},
   {"type": "BOGUS", "src": "a", "dst": "b", "props": {}}]}
```"""


def test_parse_extraction_validates_types_and_stamps_provenance():
    ex = _load("extraction", "mc_extraction_uut")
    out = ex.parse_extraction(_GOOD, _PROV)
    # Unknown 'Alien' entity and 'BOGUS' edge dropped.
    assert [e.type for e in out.entities] == ["MELItem", "ATAChapter"]
    assert [e.type for e in out.edges] == ["IN_CHAPTER"]
    mel = out.entities[0]
    assert mel.props["source_doc"] == "mel_ata32.md"
    assert mel.props["revision"] == "Rev-18"
    assert mel.props["status"] == "unverified"
    assert mel.props["confidence"] == 0.5           # entity had no confidence → default
    assert out.edges[0].props["confidence"] == 0.9  # edge-supplied confidence preserved
    assert out.edges[0].props["status"] == "unverified"


def test_parse_extraction_raises_on_non_json():
    ex = _load("extraction", "mc_extraction_uut2")
    with pytest.raises(ValueError):
        ex.parse_extraction("the model refused to answer", _PROV)


def test_extract_graph_calls_chat_fn_with_messages():
    ex = _load("extraction", "mc_extraction_uut3")
    seen = {}

    def fake_chat(messages):
        seen["messages"] = messages
        return _GOOD

    out = ex.extract_graph("MEL 32-30-01 ...", fake_chat, _PROV)
    assert seen["messages"][-1]["role"] == "user"
    assert "MEL 32-30-01" in seen["messages"][-1]["content"]
    assert len(out.entities) == 2
