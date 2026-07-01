"""Advisory gating for heavy DeLM orchestration (parallel solve / divide work).

The DeLM paper (Table 1) shows the coordination machinery yields large gains on cheap base
models (Gemini-3-Flash: +9.3 Avg@1) but little on strong ones (Opus 4.6: +1-3). This helper
flags when the heavy multi-agent path is likely low-ROI for the configured base model so the
tool layer can advise the user. It is advisory only — it never hard-blocks a dispatch the
user explicitly invoked. The lightweight always-on path (shared blackboard + admission
verification) is unaffected.
"""
from __future__ import annotations

from typing import Any

# Substrings of model ids strong enough that extra coordination buys little (paper Table 1).
STRONG_MODEL_MARKERS = (
    "opus", "gpt-5", "sonnet-4", "gemini-3-pro", "deepseek-v4-pro", "o3", "o4-",
)


def model_is_strong(model: str | None) -> bool:
    """True when the model id looks like a frontier model where DeLM gains are marginal."""
    m = (model or "").lower()
    return any(marker in m for marker in STRONG_MODEL_MARKERS)


def assess_heavy_path(config: Any) -> str:
    """Return a short advisory when the heavy path is low-ROI for the base model, else ''."""
    model = getattr(config, "model", None)
    if model_is_strong(model):
        return (
            f"advisory: base model '{model}' is already strong — DeLM-style multi-agent "
            "coordination adds little here (paper Table 1); the single-agent path is likely "
            "as good and cheaper."
        )
    return ""
