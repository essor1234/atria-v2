#!/usr/bin/env python3
"""topic_briefings — per-topic executive briefings that fan out, then merge.

Each topic's briefing is produced by a 9-stage pipeline (research → outline →
keypoints → tags → sources → score → render → assemble → verify). The final
``merge`` aggregates every verified briefing into a ranked digest.

Dispatch-shaped: a multi-topic request splits into 9 chained subtasks per
topic (each depends on the previous) plus a single ``merge`` that depends on
every ``verify_<topic>`` — the exact DAG the ``solve`` tool (strategy=divide)
fans out across background subagents. For N topics the DAG has 9N+1 tasks,
so the Dispatch tab shows sustained progress instead of two-shot flashes.

``gen`` remains as a backward-compatible shortcut that runs every stage for
one topic in order — useful for manual testing, not for dispatch.

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
import urllib.error
import urllib.request
from pathlib import Path

_MODULE_ROOT = Path(__file__).resolve().parent.parent
_DATA = Path(os.environ.get("ATRIA_TOPIC_BRIEFINGS_DIR", str(_MODULE_ROOT / "data")))
_BRIEFINGS = _DATA / "briefings"
_STAGES = _DATA / "stages"

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

# Ordered pipeline — used by `gen` shortcut and by SKILL decomposition.
PIPELINE = (
    "research",
    "outline",
    "keypoints",
    "tags",
    "sources",
    "score",
    "render",
    "assemble",
    "verify",
)


def _briefings_dir() -> Path:
    _BRIEFINGS.mkdir(parents=True, exist_ok=True)
    return _BRIEFINGS


def _stage_dir(topic: str) -> Path:
    d = _STAGES / _slug(topic)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(topic: str) -> str:
    return topic.strip().lower().replace("/", "_")


def _pick(seq: tuple, idx: int):
    return seq[idx % len(seq)]


def _topic_hash(topic: str) -> int:
    return int(hashlib.sha256(topic.strip().lower().encode()).hexdigest(), 16)


def _write_stage(topic: str, stage: str, payload: dict) -> Path:
    path = _stage_dir(topic) / f"{stage}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return path


def _read_stage(topic: str, stage: str) -> dict:
    path = _stage_dir(topic) / f"{stage}.json"
    if not path.exists():
        raise FileNotFoundError(f"missing stage '{stage}' for topic '{topic}' (expected {path})")
    return json.loads(path.read_text())


def _serper_search(topic: str, timeout: float = 15.0) -> dict | None:
    """Real web research via Serper. Returns None if unavailable/failed."""
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key:
        return None
    query = f"{topic} latest developments industry analysis"
    body = json.dumps({"q": query, "num": 10}).encode("utf-8")
    req = urllib.request.Request(
        "https://google.serper.dev/search",
        data=body,
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        print(f"[serper] error: {e}", file=sys.stderr)
        return None
    organic = payload.get("organic") or []
    if not organic:
        return None
    return {
        "source": "serper",
        "organic": [
            {"title": o.get("title"), "link": o.get("link"), "snippet": o.get("snippet", "")}
            for o in organic[:10]
        ],
        "knowledgeGraph": payload.get("knowledgeGraph") or {},
        "peopleAlsoAsk": bool(payload.get("peopleAlsoAsk")),
    }


def _emit(obj: dict, as_json: bool, human: str) -> None:
    print(json.dumps(obj, ensure_ascii=False) if as_json else human)


# --------------------------------------------------------------------------- #
# Pipeline stages — each is one dispatchable subtask.
# --------------------------------------------------------------------------- #

def cmd_research(args: argparse.Namespace) -> int:
    topic = args.topic.strip()
    if args.sleep > 0:
        time.sleep(args.sleep)
    real = _serper_search(topic)
    if real is not None:
        payload = {"topic": topic, "mode": "serper", **real}
    else:
        h = _topic_hash(topic)
        payload = {
            "topic": topic,
            "mode": "synthetic",
            "seed": h & 0xFFFFFFFF,
            "note": "SERPER_API_KEY unset or search failed — synthetic seed derived from topic name.",
        }
    _write_stage(topic, "research", payload)
    _emit(
        {"ok": True, "stage": "research", "topic": topic, "mode": payload["mode"]},
        args.json,
        f"[research] {topic}: mode={payload['mode']}",
    )
    return 0


def cmd_outline(args: argparse.Namespace) -> int:
    topic = args.topic.strip()
    if args.sleep > 0:
        time.sleep(args.sleep)
    research = _read_stage(topic, "research")
    if research["mode"] == "serper" and research.get("organic"):
        headline = research["organic"][0].get("title") or f"{topic.upper()} briefing"
    else:
        h = _topic_hash(topic)
        headline = _pick(_HEADLINES, h).format(T=topic.upper())
    outline = {"topic": topic, "headline": headline}
    _write_stage(topic, "outline", outline)
    _emit(
        {"ok": True, "stage": "outline", "topic": topic, "headline": headline},
        args.json,
        f"[outline] {topic}: {headline}",
    )
    return 0


def cmd_keypoints(args: argparse.Namespace) -> int:
    topic = args.topic.strip()
    if args.sleep > 0:
        time.sleep(args.sleep)
    research = _read_stage(topic, "research")
    if research["mode"] == "serper":
        key_points = [
            o.get("snippet", "").strip()
            for o in research.get("organic", [])[:3]
            if o.get("snippet")
        ] or ["(no snippets returned)"]
    else:
        h = _topic_hash(topic)
        idxs = ((h >> 8) & 0xFF, (h >> 16) & 0xFF, (h >> 24) & 0xFF)
        key_points = [_pick(_POINTS, i) for i in idxs]
    _write_stage(topic, "keypoints", {"topic": topic, "key_points": key_points})
    _emit(
        {"ok": True, "stage": "keypoints", "topic": topic, "count": len(key_points)},
        args.json,
        f"[keypoints] {topic}: {len(key_points)} point(s)",
    )
    return 0


def cmd_tags(args: argparse.Namespace) -> int:
    topic = args.topic.strip()
    if args.sleep > 0:
        time.sleep(args.sleep)
    research = _read_stage(topic, "research")
    if research["mode"] == "serper":
        tags = []
        kg = research.get("knowledgeGraph") or {}
        if kg.get("type"):
            tags.append(kg["type"].lower())
        if research.get("peopleAlsoAsk"):
            tags.append("paa")
        tags.append("serper")
        tags = sorted(set(tags))
    else:
        h = _topic_hash(topic)
        tags = sorted({_pick(_TAGS, h >> s) for s in (44, 48, 52)})
    _write_stage(topic, "tags", {"topic": topic, "tags": tags})
    _emit(
        {"ok": True, "stage": "tags", "topic": topic, "tags": tags},
        args.json,
        f"[tags] {topic}: {','.join(tags)}",
    )
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    topic = args.topic.strip()
    if args.sleep > 0:
        time.sleep(args.sleep)
    research = _read_stage(topic, "research")
    if research["mode"] == "serper":
        sources = [
            {"title": o.get("title"), "link": o.get("link")}
            for o in research.get("organic", [])[:5]
        ]
    else:
        sources = []
    _write_stage(topic, "sources", {"topic": topic, "sources": sources})
    _emit(
        {"ok": True, "stage": "sources", "topic": topic, "count": len(sources)},
        args.json,
        f"[sources] {topic}: {len(sources)} source(s)",
    )
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    topic = args.topic.strip()
    if args.sleep > 0:
        time.sleep(args.sleep)
    research = _read_stage(topic, "research")
    keypoints = _read_stage(topic, "keypoints")
    n_points = len(keypoints.get("key_points", []))
    if research["mode"] == "serper":
        organic_ct = len(research.get("organic", []))
        reading_time_min = max(3, min(9, organic_ct // 2 + 2))
        confidence = round(min(0.95, 0.6 + n_points * 0.1), 2)
    else:
        h = _topic_hash(topic)
        reading_time_min = 3 + (h >> 32) % 6
        confidence = round(0.55 + ((h >> 40) % 40) / 100, 2)
    _write_stage(
        topic,
        "score",
        {
            "topic": topic,
            "reading_time_min": reading_time_min,
            "confidence": confidence,
        },
    )
    _emit(
        {
            "ok": True,
            "stage": "score",
            "topic": topic,
            "reading_time_min": reading_time_min,
            "confidence": confidence,
        },
        args.json,
        f"[score] {topic}: conf={confidence}, read={reading_time_min}min",
    )
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    """Assemble in-memory content dict from prior stages (no persist yet)."""
    topic = args.topic.strip()
    if args.sleep > 0:
        time.sleep(args.sleep)
    research = _read_stage(topic, "research")
    outline = _read_stage(topic, "outline")
    keypoints = _read_stage(topic, "keypoints")
    tags = _read_stage(topic, "tags")
    sources = _read_stage(topic, "sources")
    score = _read_stage(topic, "score")
    content = {
        "headline": outline["headline"],
        "key_points": keypoints["key_points"],
        "reading_time_min": score["reading_time_min"],
        "confidence": score["confidence"],
        "tags": tags["tags"],
        "source": "serper" if research["mode"] == "serper" else "synthetic",
    }
    if sources.get("sources"):
        content["sources"] = sources["sources"]
    _write_stage(topic, "render", content)
    _emit(
        {"ok": True, "stage": "render", "topic": topic, "fields": sorted(content.keys())},
        args.json,
        f"[render] {topic}: {len(content)} field(s)",
    )
    return 0


def cmd_assemble(args: argparse.Namespace) -> int:
    """Write the final `briefings/<topic>.json` from the render stage."""
    topic = args.topic.strip()
    if args.sleep > 0:
        time.sleep(args.sleep)
    content = _read_stage(topic, "render")
    briefing = {"topic": topic, "generated_at": int(time.time()), **content}
    path = _briefings_dir() / f"{_slug(topic)}.json"
    path.write_text(json.dumps(briefing, ensure_ascii=False, indent=2))
    _emit(
        {"ok": True, "stage": "assemble", "topic": topic, "path": str(path)},
        args.json,
        f"[assemble] {topic} -> {path}",
    )
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    topic = args.topic.strip()
    if args.sleep > 0:
        time.sleep(args.sleep)
    path = _briefings_dir() / f"{_slug(topic)}.json"
    if not path.exists():
        _emit(
            {"ok": False, "stage": "verify", "error": f"briefing missing: {path}"},
            args.json,
            f"[verify] {topic}: MISSING {path}",
        )
        return 1
    briefing = json.loads(path.read_text())
    required = ("headline", "key_points", "reading_time_min", "confidence", "tags")
    missing = [k for k in required if k not in briefing]
    if missing:
        _emit(
            {"ok": False, "stage": "verify", "topic": topic, "missing": missing},
            args.json,
            f"[verify] {topic}: MISSING FIELDS {missing}",
        )
        return 1
    _write_stage(topic, "verify", {"topic": topic, "path": str(path), "ok": True})
    _emit(
        {"ok": True, "stage": "verify", "topic": topic, "path": str(path)},
        args.json,
        f"[verify] {topic}: ok",
    )
    return 0


# Map stage name → handler for the `gen` shortcut.
_STAGE_HANDLERS = {
    "research": cmd_research,
    "outline": cmd_outline,
    "keypoints": cmd_keypoints,
    "tags": cmd_tags,
    "sources": cmd_sources,
    "score": cmd_score,
    "render": cmd_render,
    "assemble": cmd_assemble,
    "verify": cmd_verify,
}


def cmd_gen(args: argparse.Namespace) -> int:
    """Backward-compat: run the full pipeline for ONE topic in order."""
    topic = args.topic.strip()
    if not topic:
        _emit({"ok": False, "error": "topic is required"}, args.json, "error: topic is required")
        return 2
    per_stage_sleep = args.sleep / len(PIPELINE) if args.sleep > 0 else 0.0
    stage_args = argparse.Namespace(topic=topic, sleep=per_stage_sleep, json=args.json)
    for stage in PIPELINE:
        rc = _STAGE_HANDLERS[stage](stage_args)
        if rc != 0:
            return rc
    path = _briefings_dir() / f"{_slug(topic)}.json"
    briefing = json.loads(path.read_text())
    _emit(
        {"ok": True, "topic": topic, "path": str(path), **{k: briefing[k] for k in briefing if k not in ("topic", "generated_at")}},
        args.json,
        f"[gen] {topic}: {briefing['headline']} (conf={briefing['confidence']}, "
        f"read={briefing['reading_time_min']}min) -> {path}",
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
    path = _briefings_dir() / f"{_slug(args.topic)}.json"
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
    if _STAGES.exists():
        for topic_dir in _STAGES.iterdir():
            if topic_dir.is_dir():
                for p in topic_dir.glob("*.json"):
                    p.unlink()
                topic_dir.rmdir()
    digest = _DATA / "digest.json"
    if digest.exists():
        digest.unlink()
    _emit({"ok": True, "removed": n}, args.json, f"[reset] removed {n} briefing(s) + stage cache")
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable output")

    p = argparse.ArgumentParser(
        prog="briefing.py",
        description="Per-topic executive briefings + weekly digest (9-stage pipeline).",
        parents=[common],
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # Per-stage subcommands — each is one dispatchable subtask.
    for stage in PIPELINE:
        sp = sub.add_parser(
            stage,
            parents=[common],
            help=f"pipeline stage '{stage}' for one topic",
        )
        sp.add_argument("--topic", required=True)
        sp.add_argument(
            "--sleep",
            type=float,
            default=1.0,
            help="simulated work seconds for this stage (default 1.0)",
        )
        sp.set_defaults(func=_STAGE_HANDLERS[stage])

    # Backward-compat: run every stage in order for one topic.
    g = sub.add_parser(
        "gen",
        parents=[common],
        help="run the full 9-stage pipeline for ONE topic (backward-compat shortcut)",
    )
    g.add_argument("--topic", required=True)
    g.add_argument(
        "--sleep",
        type=float,
        default=2.0,
        help="TOTAL simulated work seconds, divided across the 9 stages (default 2.0)",
    )
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
        "reset", parents=[common], help="delete all generated briefings + stage cache + digest"
    ).set_defaults(func=cmd_reset)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
