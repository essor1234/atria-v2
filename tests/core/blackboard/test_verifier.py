from atria.core.blackboard.verifier import verify_notes


def test_normalizes_type_and_drops_invalid():
    clean, status = verify_notes([{"type": "fact", "content": "a"}, {"type": "BOGUS", "content": "b"}])
    assert clean == [{"type": "FACT", "content": "a"}]
    assert status == "ok:1/2"


def test_drops_empty_and_caps_length():
    long = "x" * 250
    clean, _ = verify_notes([{"type": "FACT", "content": long}, {"type": "FACT", "content": "  "}])
    assert len(clean) == 1
    assert len(clean[0]["content"]) == 100  # MAX_CONTENT_CHARS


def test_patch_summary_keeps_300_and_rejects_placeholder_evidence():
    good = "files=a.py | idea=fix | evidence=ran test_x and it PASSED | risk=none"
    bad = "files=a.py | idea=fix | evidence=TBD | risk=none"
    clean, status = verify_notes([{"type": "PATCH_SUMMARY", "content": good},
                                  {"type": "PATCH_SUMMARY", "content": bad}])
    assert clean == [{"type": "PATCH_SUMMARY", "content": good}]
    assert "ps_invalid_ev=1" in status


def test_collapses_exact_duplicates():
    clean, status = verify_notes([{"type": "FACT", "content": "a"}, {"type": "FACT", "content": "a"}])
    assert clean == [{"type": "FACT", "content": "a"}]
    assert status == "ok:1/2"
