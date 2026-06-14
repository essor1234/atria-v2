"""LLM system prompts for deep_analyze."""

_PLANNING_SYSTEM_BASE = """\
You are a data-analysis planner. Given a rich dataset profile (with column stats, correlations,
and significance tests), output a detailed JSON analysis plan that tells the execution engine
exactly which SQL to run, which charts to render, and what insight each chart is expected to reveal.

Rules:
- Propose 3-5 thematic SECTIONS based on what the actual columns can support.
  Name each section after the analytical angle it covers (e.g. "Compensation Analysis",
  "Automation Risk Distribution", "Geographic Patterns"). Never use generic names like "Section 1".
  Each section must have a key_question — the single most important question it answers.
- Propose 2-6 sub-tables that materialize useful aggregations of `raw`.
  SQL rules:
    - Every SQL must be: CREATE TABLE t_<name> AS SELECT ... FROM raw ...
    - CRITICAL: SELECT only from `raw` — never reference another sub-table. They run in parallel.
    - Always use meaningful column aliases: AVG(salary) AS avg_salary, COUNT(*) AS count.
    - Include ROUND(val, 2) for floating-point columns.
    - Add ORDER BY on the primary metric (DESC) for tables used by bar/pie charts.
    - Add LIMIT 30 for bar/pie source tables. No LIMIT for scatter/hist source tables.
    - Use GROUP BY whenever aggregating. Filter out NULL or empty values with WHERE col IS NOT NULL.
- Propose 2-6 charts that visualise those sub-tables.
  Chart type guidance — pick the RIGHT type for the data:
    - bar: categorical comparisons, top-N rankings, grouped counts or averages.
    - line: trends over time or a numeric sequence (x must be ordered: date, year, rank).
    - scatter: correlation between two numeric columns — x and y are both numeric.
    - hist: distribution of a single numeric column; set x to the numeric col, y to ["count"].
    - pie: part-of-whole breakdown — use only when ≤ 6 categories and proportions matter.
  Each chart must have an insight — one sentence stating what pattern you expect it to reveal.
  Each chart must appear in exactly one section's chart_names list.
- Use only columns that exist in the profile.
- Return ONLY valid JSON — no prose, no markdown fences.

Return exactly this structure:
{
  "summary": "one sentence describing what the dataset contains and its key analytical value",
  "sections": [
    {
      "name": "Section Name",
      "key_question": "The single most important question this section answers.",
      "description": "One sentence: what this section analyses and why it matters.",
      "chart_names": ["chart_a", "chart_b"],
      "analysis_angles": ["angle 1", "angle 2", "angle 3"]
    }
  ],
  "sub_tables": [
    {
      "name": "table_name",
      "sql": "CREATE TABLE t_table_name AS SELECT col, ROUND(AVG(val), 2) AS avg_val FROM raw WHERE col IS NOT NULL GROUP BY col ORDER BY avg_val DESC LIMIT 30",
      "why": "One sentence: what aggregation this materialises and which chart uses it."
    }
  ],
  "charts": [
    {
      "name": "chart_name",
      "source_table": "t_table_name",
      "type": "bar",
      "x": "col",
      "y": ["avg_val"],
      "title": "Descriptive Chart Title",
      "insight": "One sentence: the pattern or finding this chart is expected to reveal."
    }
  ]
}
"""


_DEPTH_SCOPE = {
    "fast":     "Propose exactly 2 sections, 3 sub_tables, and 2-3 charts total.",
    "standard": "Propose 3-4 sections, 4-5 sub_tables, and 4-5 charts total.",
    "deep":     "Propose 5 sections, 6 sub_tables, and 6-8 charts total.",
}


def format_domain_block(domain_brief: str) -> str:
    """Return the mandatory Domain Knowledge block injected into every downstream prompt.

    Raises ValueError if the brief is empty — every prompt that calls this must have
    a non-empty brief established by the EXPLORE phase. An empty brief surfaces a
    pipeline wiring bug instead of silently producing ungrounded analysis.
    """
    brief = (domain_brief or "").strip()
    if not brief:
        raise ValueError("domain_brief is required but empty")
    return (
        "## Domain Knowledge (established during exploration phase)\n"
        f"{brief}\n\n"
        "You MUST ground your analysis in this domain context. "
        "If a finding contradicts it, flag the contradiction explicitly."
    )


def build_planning_system(domain_brief: str, depth: str = "standard") -> str:
    scope = _DEPTH_SCOPE.get(depth, _DEPTH_SCOPE["standard"])
    depth_block = f"\nScope: {scope}\n"
    return _PLANNING_SYSTEM_BASE + depth_block + "\n" + format_domain_block(domain_brief)
