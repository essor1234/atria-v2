"""Staged-compaction thresholds and optimization levels.

Extracted from ``compaction`` so the thresholds can be shared by the compactor
mixins without import cycles.
"""

from __future__ import annotations

# Staged compaction thresholds (fraction of context window)
STAGE_WARNING = 0.70
STAGE_MASK = 0.80
STAGE_PRUNE = 0.85  # Fast pruning: strip old tool outputs before LLM compaction
STAGE_AGGRESSIVE = 0.90
STAGE_COMPACT = 0.99

# Token budget to protect from pruning (recent tool outputs)
PRUNE_PROTECTED_TOKENS = 40_000

# Tool types whose outputs survive compaction pruning
PROTECTED_TOOL_TYPES = {"skill", "present_plan", "read_file"}


class OptimizationLevel:
    """Optimization level returned by check_usage."""

    NONE = "none"
    WARNING = "warning"  # 70%: log warning
    MASK = "mask"  # 80%: progressive observation masking
    PRUNE = "prune"  # 85%: fast pruning of old tool outputs
    AGGRESSIVE = "aggressive"  # 90%: aggressive masking
    COMPACT = "compact"  # 99%: full compaction
