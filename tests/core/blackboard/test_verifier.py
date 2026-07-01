from atria.core.blackboard.verifier import verify_notes


def test_normalizes_type_and_drops_invalid():
    clean, status = verify_notes([{"type": "fact", "content": "a"}, {"type": "BOGUS", "content": "b"}])
    assert clean == [{"type": "FACT", "content": "a"}]
    assert status == "ok:1/2"


def test_drops_empty_and_caps_length():
    long = "x" * 500
    clean, _ = verify_notes([{"type": "FACT", "content": long}, {"type": "FACT", "content": "  "}])
    assert len(clean) == 1
    assert len(clean[0]["content"]) == 300  # MAX_NOTE_CHARS (single budget)


def test_placeholder_evidence_now_passes_hygiene():
    # S1: the deterministic placeholder blocklist is removed — semantic grounding is
    # now the LLM admission verifier's job (see test_blackboard_admission.py).
    bad = "files=a.py | idea=fix | evidence=TBD | risk=none"
    clean, status = verify_notes([{"type": "PATCH_SUMMARY", "content": bad}])
    assert clean == [{"type": "PATCH_SUMMARY", "content": bad}]
    assert status == "ok:1/1"


def test_collapses_exact_duplicates():
    clean, status = verify_notes([{"type": "FACT", "content": "a"}, {"type": "FACT", "content": "a"}])
    assert clean == [{"type": "FACT", "content": "a"}]
    assert status == "ok:1/2"
