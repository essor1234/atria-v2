"""Tests for the maintenance_copilot document parser + sample corpus."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_MOD_ROOT = Path(__file__).resolve().parent.parent / "modules" / "maintenance_copilot"
_CORPUS_PY = _MOD_ROOT / "scripts" / "corpus.py"
_SAMPLES = _MOD_ROOT / "sample_manuals"


def _load():
    spec = importlib.util.spec_from_file_location("mc_corpus_uut", _CORPUS_PY)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.modules["mc_corpus_uut"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_parse_document_reads_frontmatter_and_body():
    mod = _load()
    doc = mod.parse_document(str(_SAMPLES / "amm_ata32.md"))
    assert doc.doc_type == "AMM"
    assert doc.revision == "Rev-42"
    assert doc.ata_chapter == "32"
    assert "Main Landing Gear" in doc.text
    # Body must exclude the front-matter delimiters.
    assert "doc_type:" not in doc.text


def test_parse_document_missing_key_raises():
    mod = _load()
    tmp = _SAMPLES.parent / "data" / "_bad.md"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text("---\ndoc_type: AMM\n---\nbody", encoding="utf-8")
    try:
        with pytest.raises(ValueError) as exc:
            mod.parse_document(str(tmp))
        assert "title" in str(exc.value)
    finally:
        tmp.unlink()
        try:
            tmp.parent.rmdir()
        except OSError:
            pass


def test_load_corpus_returns_all_four_sorted():
    mod = _load()
    docs = mod.load_corpus(str(_SAMPLES))
    assert [d.doc_type for d in docs] == ["AMM", "CDL", "MEL", "TSM"]  # sorted by filename
    assert {d.ata_chapter for d in docs} == {"32", "52"}
