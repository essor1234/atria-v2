#!/usr/bin/env python3
"""topic_briefings — per-topic executive briefings that fan out, then merge.

Each ``gen --topic <name>`` is a fully independent unit of work: it derives
deterministic synthetic content from the topic name and writes one JSON
briefing. ``merge`` aggregates every generated briefing into a ranked digest.

Dispatch-shaped: a multi-topic request splits into one independent ``gen``
subtask per topic plus a single ``merge`` that depends on all of them — the
exact DAG the ``solve`` tool (strategy=divide) fans out across background
subagents. Non-coding scenario: pure content generation, no LLM.

Stdlib only. Output dir defaults to ``<module>/data`` and can be overridden
with ``ATRIA_TOPIC_BRIEFINGS_DIR``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

_MODULE_ROOT = Path(__file__).resolve().parent.parent
_DATA = Path(os.environ.get("ATRIA_TOPIC_BRIEFINGS_DIR", str(_MODULE_ROOT / "data")))
_BRIEFINGS = _DATA / "briefings"

_HEADLINES = (
    "{T} adoption accelerates in enterprise",
    "Regulators sharpen focus on {T}",
    "New research reshapes the {T} landscape",
    "{T} talent shortage tightens further",
    "Capital rotation lifts {T} valuations",
    "Standards body drafts baseline for {T}",
    "Open-source push disrupts {T} incumbents",
    "Cross-border pilots stress-test {T}",
)

_POINTS = (
    "Consolidation among top-3 vendors continues; expect one more merger by Q3.",
    "New benchmark shows a 22% quality lift vs the last-gen baseline.",
    "Deployment cost per unit fell ~14% year-over-year on reference workloads.",
    "Compliance overhead is the single biggest blocker cited by adopters.",
    "Two regional standards proposals are diverging; watch APAC lead.",
    "Enterprise pilots are converting to production at roughly 1-in-3.",
    "Open datasets released this quarter unlocked a new class of experiments.",
    "Talent flows from research labs to startups; retention costs are up ~18%.",
    "Latency guarantees are the next competitive frontier, not raw accuracy.",
    "Independent audits are becoming a de-facto requirement in RFPs.",
)

_TAGS = ("frontier", "enterprise", "policy", "capital", "research", "infra", "ecosystem")


def _briefings_dir() -> Path:
    _BRIEFINGS.mkdir(parents=True, exist_ok=True)
    return _BRIEFINGS


def _pick(seq: tuple, idx: int):
    return seq[idx % len(seq)]


def _content(topic: str) -> dict:
    """Deterministic synthetic briefing derived from the topic name."""
    key = topic.strip().lower()
    h = int(hashlib.sha256(key.encode()).hexdigest(), 16)
    T = key.upper()
    headline = _pick(_HEADLINES, h).format(T=T)
    idxs = ((h >> 8) & 0xFF, (h >> 16) & 0xFF, (h >> 24) & 0xFF)
    key_points = [_pick(_POINTS, i) for i in idxs]
    reading_time_min = 3 + (h >> 32) % 6
    confidence = round(0.55 + ((h >> 40) % 40) / 100, 2)
    tags = sorted({_pick(_TAGS, h >> s) for s in (44, 48, 52)})
    return {
        "headline": headline,
        "key_points": key_points,
        "reading_time_min": reading_time_min,
        "confidence": confidence,
        "tags": tags,
    }


def _emit(obj: dict, as_json: bool, human: str) -> None:
    print(json.dumps(obj, ensure_ascii=False) if as_json else human)


def cmd_gen(args: argparse.Namespace) -> int:
    topic = args.topic.strip()
    if not topic:
        _emit({"ok": False, "error": "topic is required"}, args.json, "error: topic is required")
        return 2
    if args.sleep > 0:
        time.sleep(args.sleep)
    content = _content(topic)
    briefing = {"topic": topic, "generated_at": int(time.time()), **content}
    path = _briefings_dir() / f"{topic.lower().replace('/', '_')}.json"
    path.write_text(json.dumps(briefing, ensure_ascii=False, indent=2))
    _emit(
        {"ok": True, "topic": topic, "path": str(path), **content},
        args.json,
        f"[gen] {topic}: {content['headline']} (conf={content['confidence']}, "
        f"read={content['reading_time_min']}min) -> {path}",
    )
    return 0


def _load_briefings() -> list[dict]:
    out = []
    for p in sorted(_briefings_dir().glob("*.json")):
        try:
            out.append(json.loads(p.read_text()))
        except Exception:  # noqa: BLE001 — skip unreadable/partial files
            continue
    return out


def _score(b: dict) -> float:
    return float(b.get("confidence", 0)) * float(b.get("reading_time_min", 0))


def cmd_merge(args: argparse.Namespace) -> int:
    briefings = _load_briefings()
    if not briefings:
        _emit({"ok": False, "error": "no briefings to merge"}, args.json, "error: no briefings yet")
        return 1
    ranked = sorted(briefings, key=_score, reverse=True)
    digest = {
        "topics": len(ranked),
        "avg_confidence": round(
            sum(b.get("confidence", 0) for b in ranked) / len(ranked), 3
        ),
        "total_reading_time_min": sum(b.get("reading_time_min", 0) for b in ranked),
        "top_topic": ranked[0]["topic"],
        "ranking": [
            {"topic": b["topic"], "headline": b["headline"], "score": round(_score(b), 3)}
            for b in ranked
        ],
    }
    out = Path(args.out) if args.out else _DATA / "digest.json"
    out.write_text(json.dumps(digest, ensure_ascii=False, indent=2))
    _emit(
        {"ok": True, "path": str(out), **digest},
        args.json,
        f"[merge] {digest['topics']} topics, avg_conf={digest['avg_confidence']}, "
        f"top={digest['top_topic']} -> {out}",
    )
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    briefings = _load_briefings()
    _emit(
        {"ok": True, "count": len(briefings), "topics": [b["topic"] for b in briefings]},
        args.json,
        "\n".join(f"{b['topic']}: {b['headline']}" for b in briefings) or "(no briefings yet)",
    )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    path = _briefings_dir() / f"{args.topic.strip().lower().replace('/', '_')}.json"
    if not path.exists():
        _emit({"ok": False, "error": "not found"}, args.json, f"error: no briefing for {args.topic}")
        return 1
    briefing = json.loads(path.read_text())
    _emit(briefing, args.json, json.dumps(briefing, ensure_ascii=False, indent=2))
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Emit the full dashboard payload (topics ranked + digest if merged)."""
    briefings = sorted(_load_briefings(), key=_score, reverse=True)
    digest = None
    dp = _DATA / "digest.json"
    if dp.exists():
        try:
            digest = json.loads(dp.read_text())
        except Exception:  # noqa: BLE001
            digest = None
    payload = {
        "ok": True,
        "count": len(briefings),
        "topics": briefings,
        "digest": digest,
        "avg_confidence": (
            round(sum(b.get("confidence", 0) for b in briefings) / len(briefings), 3)
            if briefings
            else 0
        ),
        "total_reading_time_min": sum(b.get("reading_time_min", 0) for b in briefings),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    n = 0
    if _BRIEFINGS.exists():
        for p in _BRIEFINGS.glob("*.json"):
            p.unlink()
            n += 1
    digest = _DATA / "digest.json"
    if digest.exists():
        digest.unlink()
    _emit({"ok": True, "removed": n}, args.json, f"[reset] removed {n} briefing(s)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable output")

    p = argparse.ArgumentParser(
        prog="briefing.py",
        description="Per-topic executive briefings + weekly digest.",
        parents=[common],
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser(
        "gen",
        parents=[common],
        help="generate the briefing for ONE topic (independent unit)",
    )
    g.add_argument("--topic", required=True)
    g.add_argument("--sleep", type=float, default=2.0, help="simulated work seconds (default 2.0)")
    g.set_defaults(func=cmd_gen)

    m = sub.add_parser(
        "merge",
        parents=[common],
        help="aggregate all briefings into a ranked weekly digest",
    )
    m.add_argument("--out", default="", help="output path (default <module>/data/digest.json)")
    m.set_defaults(func=cmd_merge)

    sub.add_parser("list", parents=[common], help="list generated briefings").set_defaults(
        func=cmd_list
    )

    s = sub.add_parser("show", parents=[common], help="print one topic's briefing")
    s.add_argument("--topic", required=True)
    s.set_defaults(func=cmd_show)

    sub.add_parser(
        "dashboard", parents=[common], help="emit the dashboard JSON payload"
    ).set_defaults(func=cmd_dashboard)

    sub.add_parser(
        "reset", parents=[common], help="delete all generated briefings + digest"
    ).set_defaults(func=cmd_reset)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
