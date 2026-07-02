"""Tests for grounded answer synthesis + citation post-validation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MOD = Path(__file__).resolve().parent.parent / "modules" / "maintenance_copilot" / "scripts"


def _load(name, sentinel):
    spec = importlib.util.spec_from_file_location(sentinel, _MOD / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[sentinel] = mod
    spec.loader.exec_module(mod)
    return mod


_HITS = [
    {"chunk_id": "amm_ata32#1", "text": "Torque the pivot pin nut to 1200 in-lb.",
     "citation": "AMM ... · amm_ata32#1", "score": 0.9},
    {"chunk_id": "mel_ata32#0", "text": "MEL 32-30-01 Category C.",
     "citation": "MEL ... · mel_ata32#0", "score": 0.8},
]


def test_synthesize_keeps_cited_drops_uncited():
    syn = _load("synthesis", "mc_synth_uut")

    def fake_chat(messages):
        return ("Torque is 1200 in-lb [amm_ata32#1]. "
                "You may always dispatch with the gear removed.")

    out = syn.synthesize("gear torque?", _HITS, fake_chat)
    assert "1200 in-lb" in out["answer"]
    assert "always dispatch" not in out["answer"]
    assert out["dropped"] and "always dispatch" in out["dropped"][0]
    assert out["citations"] == ["amm_ata32#1"]
    assert out["needs_review"] is False
    assert "ADVISORY ONLY" in out["disclaimer"]


def test_synthesize_low_confidence_flags_review():
    syn = _load("synthesis", "mc_synth_uut2")
    low = [{"chunk_id": "amm_ata32#1", "text": "x", "citation": "c", "score": 0.05}]

    def fake_chat(messages):
        return "Torque is 1200 in-lb [amm_ata32#1]."

    out = syn.synthesize("q", low, fake_chat)
    assert out["needs_review"] is True
    assert "review" in out["answer"].lower()


def test_synthesize_all_uncited_flags_review():
    syn = _load("synthesis", "mc_synth_uut3")

    def fake_chat(messages):
        return "Unicorns fix landing gear."

    out = syn.synthesize("q", _HITS, fake_chat)
    assert out["needs_review"] is True
    assert out["citations"] == []
