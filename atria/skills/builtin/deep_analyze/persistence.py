"""Structured markdown + PDF report builder for deep_analyze."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .jobs import AnalyzeJob


def _escape_md(val: Any) -> str:
    return str(val).replace("|", "\\|")


def _profile_table(columns: List[Dict[str, Any]]) -> List[str]:
    lines = [
        "| Column | Type | Mean / Top Value | Nulls | Outliers | Skew |",
        "|--------|------|-----------------|-------|----------|------|",
    ]
    for col in columns:
        dtype = col.get("dtype", "?")
        null_pct = f"{col.get('null_pct', 0):.1%}"
        if dtype in {"int", "float"}:
            mean = col.get("mean")
            mean_str = f"{mean:.2f}" if mean is not None else "—"
            outliers = str(col.get("outlier_count", "—"))
            skew = col.get("skewness")
            skew_str = f"{skew:.2f}" if skew is not None else "—"
            lines.append(
                f"| {_escape_md(col['name'])} | {dtype} | {mean_str} | {null_pct} | {outliers} | {skew_str} |"
            )
        else:
            tvs = col.get("top_values", [])
            top = tvs[0]["value"] if tvs else "—"
            lines.append(
                f"| {_escape_md(col['name'])} | {dtype} | {_escape_md(top)} | {null_pct} | — | — |"
            )
    return lines


def default_reporter(job: AnalyzeJob) -> str:
    from atria.core.context_engineering.tools.implementations.md_to_pdf_tool import (  # noqa: PLC0415
        MdToPdfTool,
    )

    filename = Path(job.file_path).name
    profile = job.profile_rich if job.profile_rich else job.profile
    cols = profile.get("columns", [])

    md: List[str] = []

    # ── title + summary ───────────────────────────────────────────────────────
    md.append(f"# Deep Analyze Report — {filename}\n")
    if job.plan.get("summary"):
        md.append(f"_{job.plan['summary']}_\n")

    # ── domain context ────────────────────────────────────────────────────────
    if job.domain_brief:
        md.append("## Domain Context\n")
        md.append(f"{job.domain_brief}\n")
        if job.clarification_qa:
            md.append("**Clarifications gathered during exploration:**\n")
            for rec in job.clarification_qa:
                ans = (rec.get("answer") or "").strip()
                if not ans:
                    continue
                md.append(f"- _{rec['text']}_ → {ans}")
            md.append("")

    # ── data profile ──────────────────────────────────────────────────────────
    md.append("## Data Profile\n")
    row_count = profile.get("row_count", "?")
    null_pcts = [c.get("null_pct", 0) for c in cols]
    avg_null = sum(null_pcts) / len(null_pcts) if null_pcts else 0.0
    md.append(f"_{row_count} rows · {len(cols)} columns · {avg_null:.1%} avg nulls_\n")
    md.extend(_profile_table(cols))
    md.append("")

    notable_corrs = [c for c in profile.get("correlations", []) if c.get("notable")]
    if notable_corrs:
        parts = [f"{c['col_a']} ↔ {c['col_b']} (r={c['r']})" for c in notable_corrs]
        md.append(f"**Notable correlations:** {', '.join(parts)}\n")

    sig_tests = [t for t in profile.get("significance_tests", []) if t.get("significant")]
    if sig_tests:
        parts = [f"{t['categorical']} → {t['numeric']} (p={t['p_value']})" for t in sig_tests]
        md.append(f"**Significant group differences:** {', '.join(parts)}\n")

    md.append("")

    # ── executive summary ─────────────────────────────────────────────────────
    if job.exec_summary:
        md.append("## Executive Summary\n")
        md.append(job.exec_summary + "\n")

    # ── thematic sections ─────────────────────────────────────────────────────
    chart_lookup: Dict[str, Dict[str, Any]] = {c["name"]: c for c in job.charts}
    for i, section in enumerate(job.sections, 1):
        md.append(f"## {i}. {section['name']}\n")
        if section.get("content"):
            md.append(section["content"] + "\n")
        for chart_name in section.get("chart_names", []):
            chart = chart_lookup.get(chart_name)
            if chart and chart.get("status") == "done" and chart.get("png_path"):
                rel = f"charts/{chart_name}.png"
                md.append(f"![{chart_name}]({rel})\n")
                if chart.get("insight_md"):
                    md.append(f"> {chart['insight_md']}\n")
        md.append("")

    # ── key findings ──────────────────────────────────────────────────────────
    if job.key_findings:
        md.append("## Key Findings & Recommendations\n")
        md.append(job.key_findings + "\n")

    # ── write markdown ────────────────────────────────────────────────────────
    md_path = job.dir / "report.md"
    md_path.write_text("\n".join(md), encoding="utf-8")

    # ── render PDF ────────────────────────────────────────────────────────────
    pdf_path = str(job.dir / "report.pdf")
    res = MdToPdfTool().render(str(md_path), pdf_path)
    if not res["success"]:
        raise RuntimeError(res["error"])
    return pdf_path
