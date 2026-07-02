"""Tests for maintenance_copilot chunking + citation anchors."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MOD = Path(__file__).resolve().parent.parent / "modules" / "maintenance_copilot" / "scripts"


def _load(name: str, sentinel: str):
    spec = importlib.util.spec_from_file_location(sentinel, _MOD / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[sentinel] = mod
    spec.loader.exec_module(mod)
    return mod


class _FakeChunk:
    def __init__(self, text, start_index, end_index, token_count):
        self.text = text
        self.start_index = start_index
        self.end_index = end_index
        self.token_count = token_count


class _FakeChunker:
    """Splits on blank lines so tests are deterministic and offline."""

    def chunk(self, text):
        chunks = []
        cursor = 0
        for para in text.split("\n\n"):
            start = text.index(para, cursor)
            end = start + len(para)
            cursor = end
            chunks.append(_FakeChunk(para, start, end, len(para.split())))
        return chunks


def _sample_doc(corpus):
    return corpus.Document(
        doc_type="AMM", title="Landing Gear", revision="Rev-42",
        effective_date="2026-05-01", ata_chapter="32",
        path="/x/amm_ata32.md", text="Para one text.\n\nPara two text here.",
    )


def test_chunk_document_builds_records_with_citation_and_offsets():
    corpus = _load("corpus", "mc_corpus_for_chunk")
    chunking = _load("chunking", "mc_chunking_uut")
    recs = chunking.chunk_document(_sample_doc(corpus), chunker=_FakeChunker())
    assert len(recs) == 2
    assert recs[0].chunk_id == "amm_ata32#0"
    assert recs[0].citation == "AMM Landing Gear (Rev-42) · amm_ata32#0"
    # Offsets index back into the original text.
    assert _sample_doc(corpus).text[recs[1].start_index:recs[1].end_index] == recs[1].text
    assert recs[0].ata_chapter == "32" and recs[0].revision == "Rev-42"


def test_chunk_document_carries_metadata_to_every_record():
    corpus = _load("corpus", "mc_corpus_for_chunk2")
    chunking = _load("chunking", "mc_chunking_uut2")
    recs = chunking.chunk_document(_sample_doc(corpus), chunker=_FakeChunker())
    assert all(r.doc_type == "AMM" and r.source_path.endswith("amm_ata32.md") for r in recs)
