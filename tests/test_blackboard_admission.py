"""Unit tests for blackboard admission-time verification (DeLM §A.3) + hygiene (S1)."""
from __future__ import annotations

import asyncio

import pytest

from atria.core.blackboard.admission import _parse, admit_notes
from atria.core.blackboard.blackboard import Blackboard
from atria.core.blackboard.models import MAX_NOTE_CHARS, VALID_TYPES
from atria.core.blackboard.verifier import verify_notes
from atria.core.blackboard.verify_llm import build_verify_llm, resolve_verify_model


# --------------------------------------------------------------------------- #
# S1 — deterministic hygiene: single cap, no placeholder blocklist
# --------------------------------------------------------------------------- #
def test_hygiene_single_cap_applies_to_all_types():
    clean, status = verify_notes(
        [
            {"type": "fact", "content": "x" * 500},
            {"type": "PATCH_SUMMARY", "content": "y" * 500},
        ]
    )
    assert status == "ok:2/2"
    assert all(len(c["content"]) == MAX_NOTE_CHARS for c in clean)


def test_hygiene_drops_unknown_type_and_empty_and_dupes():
    clean, status = verify_notes(
        [
            {"type": "BOGUS", "content": "z"},
            {"type": "FACT", "content": ""},
            {"type": "FACT", "content": "dup"},
            {"type": "FACT", "content": "dup"},
        ]
    )
    assert [c["content"] for c in clean] == ["dup"]
    assert status == "ok:1/4"


def test_hygiene_no_longer_blocks_placeholder_evidence():
    # The old _INVALID_EVIDENCE_PHRASES blocklist is gone — the LLM verifier owns this.
    clean, _ = verify_notes(
        [{"type": "PATCH_SUMMARY", "content": "files=a | idea=b | evidence=tbd"}]
    )
    assert len(clean) == 1
    assert "evidence=tbd" in clean[0]["content"]


def test_valid_types_unchanged():
    assert "FACT" in VALID_TYPES and "PATCH_SUMMARY" in VALID_TYPES


# --------------------------------------------------------------------------- #
# W1 — admission parse + concurrency + fail-open
# --------------------------------------------------------------------------- #
def test_parse_extracts_json_verdict():
    assert _parse('{"ok": true, "reason": ""}') == (True, "")
    assert _parse('prefix {"ok": false, "reason": "speculative"} suffix') == (
        False,
        "speculative",
    )


def test_parse_fails_open_on_garbage():
    ok, reason = _parse("not json at all")
    assert ok is True and reason == ""


def test_admit_rejects_unsupported_admits_grounded():
    def fake(system: str, user: str) -> str:
        if "SPECULATE" in user:
            return '{"ok": false, "reason": "speculative"}'
        return '{"ok": true, "reason": ""}'

    admitted, reasons = asyncio.run(
        admit_notes(
            [
                {"type": "FACT", "content": "grounded finding"},
                {"type": "CLAIM", "content": "SPECULATE this will work"},
            ],
            fake,
        )
    )
    assert [a["content"] for a in admitted] == ["grounded finding"]
    assert reasons == ["CLAIM: speculative"]


def test_admit_fails_open_on_llm_error():
    def boom(system: str, user: str) -> str:
        raise RuntimeError("verifier down")

    admitted, reasons = asyncio.run(
        admit_notes([{"type": "FACT", "content": "keep me"}], boom)
    )
    assert [a["content"] for a in admitted] == ["keep me"]
    assert reasons == []


def test_admit_empty_is_noop():
    assert asyncio.run(admit_notes([], lambda s, u: "{}")) == ([], [])


def test_admit_runs_concurrently():
    # If calls were serialized, 8 x 50ms sleeps would take >=0.4s; concurrently ~<0.2s.
    import time

    def slow(system: str, user: str) -> str:
        time.sleep(0.05)
        return '{"ok": true, "reason": ""}'

    notes = [{"type": "FACT", "content": f"n{i}"} for i in range(8)]
    start = time.monotonic()
    admitted, _ = asyncio.run(admit_notes(notes, slow, concurrency_limit=8))
    elapsed = time.monotonic() - start
    assert len(admitted) == 8
    assert elapsed < 0.2, f"expected concurrent execution, took {elapsed:.3f}s"


# --------------------------------------------------------------------------- #
# W1 — cheap-model resolution + disabled/unavailable -> None
# --------------------------------------------------------------------------- #
class _BB:
    def __init__(self, verify=True, verify_model=None):
        self.verify = verify
        self.verify_model = verify_model


class _Cfg:
    def __init__(self, *, verify=True, verify_model=None, api_key="k", **models):
        self.blackboard = _BB(verify=verify, verify_model=verify_model)
        self.model = models.get("model", "gpt-4o")
        self.model_critique = models.get("model_critique")
        self.model_compact = models.get("model_compact")
        self.api_base_url = None
        self._api_key = api_key

    def get_api_key(self):
        return self._api_key


def test_resolve_prefers_critique_then_compact_then_main():
    assert resolve_verify_model(_Cfg(model_critique="c", model_compact="d")) == "c"
    assert resolve_verify_model(_Cfg(model_compact="d")) == "d"
    assert resolve_verify_model(_Cfg(model="m")) == "m"
    assert resolve_verify_model(_Cfg(verify_model="explicit", model_critique="c")) == "explicit"


def test_build_verify_llm_none_when_disabled_or_no_key():
    assert build_verify_llm(_Cfg(verify=False)) is None
    assert build_verify_llm(_Cfg(api_key="")) is None
    assert callable(build_verify_llm(_Cfg()))


# --------------------------------------------------------------------------- #
# W1 — Blackboard.write integrates both gates; rejected notes not stored
# --------------------------------------------------------------------------- #
class _FakeStore:
    _key = "atria:bb:task123"

    def __init__(self):
        self.appended: list = []

    async def append(self, notes):
        self.appended.extend(notes)

    async def read_all(self):
        return list(self.appended)


def test_write_rejected_note_not_stored_status_reports_count():
    store = _FakeStore()

    def verifier(system: str, user: str) -> str:
        return '{"ok": false, "reason": "no evidence"}' if "bad" in user else '{"ok": true}'

    bb = Blackboard(store, verify_llm=verifier)
    status = asyncio.run(
        bb.write(
            [
                {"type": "FACT", "content": "good grounded"},
                {"type": "CLAIM", "content": "bad speculative"},
            ]
        )
    )
    assert "rejected=1" in status
    assert [n.content for n in store.appended] == ["good grounded"]


def test_write_without_verifier_skips_admission():
    store = _FakeStore()
    bb = Blackboard(store, verify_llm=None)
    status = asyncio.run(bb.write([{"type": "FACT", "content": "anything"}]))
    assert status == "ok:1/1"
    assert [n.content for n in store.appended] == ["anything"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
