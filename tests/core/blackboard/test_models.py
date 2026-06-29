from atria.core.blackboard.models import (
    MAX_CONTENT_CHARS,
    MAX_PATCH_SUMMARY_CHARS,
    VALID_TYPES,
    Note,
)


def test_valid_types_and_caps():
    assert VALID_TYPES == ("FACT", "TRIED", "OBSERVED", "FAIL", "CLAIM", "PATCH_SUMMARY")
    assert MAX_CONTENT_CHARS == 100
    assert MAX_PATCH_SUMMARY_CHARS == 300


def test_note_roundtrips_dict():
    n = Note(type="FACT", content="x.py:1 does y", thread_id=0, ts=123.0)
    d = n.to_dict()
    assert d == {"type": "FACT", "content": "x.py:1 does y", "thread_id": 0, "ts": 123.0}
    assert Note.from_dict(d) == n
