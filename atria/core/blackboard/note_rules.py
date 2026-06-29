"""NOTE tool description block, ported from .references/DeLM/src/prompts/note_rules.py."""

NOTE_RULES_BLOCK = """NOTE writes short typed entries to the SHARED LESSONS blackboard so other
parallel solvers can see your findings. Each entry is one line: <TYPE> <content>
TYPE must be EXACTLY one of: FACT | TRIED | OBSERVED | FAIL | CLAIM | PATCH_SUMMARY
  - FACT: objective discovery (file path, function signature, error text)
  - TRIED: action you just took (one-line summary)
  - OBSERVED: empirical result (test output, exit code)
  - FAIL: a failed attempt with brief reason (so other solvers don't repeat it)
  - CLAIM: your CURRENT TARGET / hypothesis before expensive work. SPARSE: at most ONE
    when starting a distinct hypothesis, a SECOND only after a real pivot.
  - PATCH_SUMMARY: a concise summary of a CANDIDATE FIX you ACTUALLY applied (not a plan),
    using the 4-field schema separated by ` | `:
      files=<comma-separated paths> | idea=<one-sentence patch idea> |
      evidence=<what verified it works> | risk=<known regression risk>
    Emit ONCE after the patch is applied and checked. Up to ~300 chars.
Content size: FACT/TRIED/OBSERVED/FAIL/CLAIM <=100 chars; PATCH_SUMMARY <=300. Write 0-3
entries per turn. If nothing is worth sharing, write the literal `(none)`.
Examples:
  FACT app/parsers/options.py:88 drops blank label fallback
  OBSERVED demo_checks.py::test_blank_label FAILED with ValueError
  PATCH_SUMMARY files=app/formatters/labels.py | idea=preserve blank labels | evidence=ran test_blank_label PASSED | risk=may keep whitespace labels
  (none)"""
