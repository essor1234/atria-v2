"""Auto-compaction of conversation history when approaching context limits.

Implements staged context optimization with proactive reduction:
- 70%: Warning logged, tracking begins
- 80%: Progressive observation masking (old tool results → compact refs)
- 90%: Aggressive masking + trimming of old tool outputs
- 99%: Full LLM-powered compaction (summarize middle messages)

Also provides:
- History archival: writes full messages to file before compacting
- Artifact index: tracks files touched, survives compaction
"""

from __future__ import annotations

import logging
from typing import Any

from atria.core.context_engineering.retrieval.token_monitor import ContextTokenMonitor
from atria.models.config import AppConfig

from ._masking import MaskingMixin
from ._summary import SummaryMixin
from .artifact_index import ArtifactIndex
from .stages import (
    PROTECTED_TOOL_TYPES,
    PRUNE_PROTECTED_TOKENS,
    STAGE_AGGRESSIVE,
    STAGE_COMPACT,
    STAGE_MASK,
    STAGE_PRUNE,
    STAGE_WARNING,
    OptimizationLevel,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ContextCompactor",
    "ArtifactIndex",
    "OptimizationLevel",
    "STAGE_WARNING",
    "STAGE_MASK",
    "STAGE_PRUNE",
    "STAGE_AGGRESSIVE",
    "STAGE_COMPACT",
    "PROTECTED_TOOL_TYPES",
    "PRUNE_PROTECTED_TOKENS",
]


class ContextCompactor(MaskingMixin, SummaryMixin):
    """Auto-compacts conversation history when approaching context limits.

    Implements staged optimization that activates progressively as context fills:
    1. Warning at 70% — logs and starts tracking
    2. Observation masking at 80% — replaces old tool results with compact refs
    3. Aggressive masking at 90% — minimal refs for all but recent tool results
    4. Full compaction at 99% — LLM-powered summarization of old messages
    """

    def __init__(
        self,
        config: AppConfig,
        http_client: Any,
    ) -> None:
        self._config = config
        self._http_client = http_client
        self._token_monitor = ContextTokenMonitor()
        self._last_token_count = 0
        self._api_prompt_tokens: int = 0
        self._msg_count_at_calibration: int = 0

        self._max_context = getattr(config, "max_context_tokens", 100_000)
        logger.info(
            "ContextCompactor: max_context=%d tokens (model=%s)",
            self._max_context,
            getattr(config, "model", "unknown"),
        )

        # Artifact index survives compaction
        self.artifact_index = ArtifactIndex()

        # Track whether we've already warned at each stage (avoid log spam)
        self._warned_70 = False
        self._warned_80 = False
        self._warned_90 = False

        # Session ID for scratch file paths (set by react executor)
        self._session_id: str | None = None

        # Hook manager for PreCompact event
        self._hook_manager = None

    def set_hook_manager(self, hook_manager: Any) -> None:
        """Set the hook manager for PreCompact hooks.

        Args:
            hook_manager: HookManager instance
        """
        self._hook_manager = hook_manager

    # ------------------------------------------------------------------
    # Public: staged usage check
    # ------------------------------------------------------------------
    def check_usage(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
    ) -> str:
        """Check context usage and return the appropriate optimization level.

        Returns:
            One of OptimizationLevel constants.
        """
        self._update_token_count(messages, system_prompt)
        pct = self.usage_pct / 100.0  # Convert to 0-1 range

        if pct >= STAGE_COMPACT:
            return OptimizationLevel.COMPACT
        if pct >= STAGE_AGGRESSIVE:
            if not self._warned_90:
                logger.warning("Context at %.1f%% — aggressive optimization active", pct * 100)
                self._warned_90 = True
            return OptimizationLevel.AGGRESSIVE
        if pct >= STAGE_PRUNE:
            return OptimizationLevel.PRUNE
        if pct >= STAGE_MASK:
            if not self._warned_80:
                logger.warning("Context at %.1f%% — observation masking active", pct * 100)
                self._warned_80 = True
            return OptimizationLevel.MASK
        if pct >= STAGE_WARNING:
            if not self._warned_70:
                logger.info("Context at %.1f%% — approaching limits", pct * 100)
                self._warned_70 = True
            return OptimizationLevel.WARNING
        return OptimizationLevel.NONE

    def should_compact(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
    ) -> bool:
        """Check if conversation exceeds the compaction threshold.

        Backwards-compatible: returns True only when full compaction is needed.
        """
        self._update_token_count(messages, system_prompt)
        return self._last_token_count > int(self._max_context * STAGE_COMPACT)

    @property
    def usage_pct(self) -> float:
        """Context usage as percentage of the model's full context window (0-100+)."""
        if self._max_context <= 0:
            return 0.0
        if self._last_token_count == 0:
            return 0.0
        return (self._last_token_count / self._max_context) * 100

    def update_from_api_usage(self, prompt_tokens: int, message_count: int = 0) -> None:
        """Calibrate with real API token count."""
        if prompt_tokens > 0:
            self._api_prompt_tokens = prompt_tokens
            self._msg_count_at_calibration = message_count
            self._last_token_count = prompt_tokens
        else:
            logger.debug(
                "update_from_api_usage: prompt_tokens=0, skipping calibration "
                "(max_context=%d, last_token_count=%d)",
                self._max_context,
                self._last_token_count,
            )

    @property
    def pct_until_compact(self) -> float:
        """Percentage points remaining before full compaction triggers."""
        threshold_pct = STAGE_COMPACT * 100
        return max(0.0, threshold_pct - self.usage_pct)
