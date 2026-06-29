from atria.core.blackboard.models import Note
from atria.core.blackboard.render import render_digest


def _n(t, c, thread=0, ts=0.0):
    return Note(type=t, content=c, thread_id=thread, ts=ts)


def test_empty_returns_empty_string():
    assert render_digest([], viewer_id=0, window_tokens=2000) == ""


def test_dedup_and_format():
    out = render_digest([_n("FACT", "a"), _n("FACT", "a")], viewer_id=0, window_tokens=2000)
    assert out.count("[t0/FACT] a") == 1


def test_priority_orders_patch_summary_first():
    notes = [_n("TRIED", "did x", ts=2.0), _n("PATCH_SUMMARY", "files=a | idea=b | evidence=ran t PASSED | risk=n", ts=1.0)]
    out = render_digest(notes, viewer_id=0, window_tokens=2000)
    assert out.index("PATCH_SUMMARY") < out.index("TRIED")


def test_token_budget_truncates():
    notes = [_n("FACT", "x" * 80, thread=i, ts=float(i)) for i in range(50)]
    out = render_digest(notes, viewer_id=0, window_tokens=50)  # ~200 chars budget
    assert len(out) <= 50 * 4
    assert out  # non-empty
