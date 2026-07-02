"""Tests for the guardrails: citation enforcement, confidence, review routing."""

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


def test_enforce_citations_drops_uncited_sentences():
    g = _load("guardrails", "mc_guardrails_uut")
    answer = (
        "The main gear pivot pin torque is 1200 in-lb [amm_ata32#1]. "
        "The aircraft can always be dispatched with the gear removed. "
        "MEL 32-30-01 is Category C [mel_ata32#0]."
    )
    out = g.enforce_citations(answer, {"amm_ata32#1", "mel_ata32#0"})
    assert len(out["grounded"]) == 2
    assert len(out["dropped"]) == 1
    assert "always be dispatched" in out["dropped"][0]
    assert "[amm_ata32#1]" in out["answer"]


def test_enforce_citations_marker_not_in_allowed_is_dropped():
    g = _load("guardrails", "mc_guardrails_uut2")
    out = g.enforce_citations("Fabricated claim [ghost#9].", {"amm_ata32#1"})
    assert out["grounded"] == []
    assert len(out["dropped"]) == 1


def test_confidence_and_review_routing():
    g = _load("guardrails", "mc_guardrails_uut3")
    assert g.answer_confidence([{"score": 0.8}, {"score": 0.2}]) == 0.8
    assert g.answer_confidence([]) == 0.0
    # Below default threshold OR nothing grounded → needs review.
    assert g.needs_manual_review(0.1, grounded_count=3) is True
    assert g.needs_manual_review(0.9, grounded_count=0) is True
    assert g.needs_manual_review(0.9, grounded_count=2) is False


def test_min_confidence_env_override(monkeypatch):
    g = _load("guardrails", "mc_guardrails_uut4")
    monkeypatch.setenv("MC_MIN_CONFIDENCE", "0.7")
    assert g.default_min_confidence() == 0.7
    assert g.needs_manual_review(0.6, grounded_count=5) is True
