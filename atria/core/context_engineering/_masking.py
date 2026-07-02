"""Observation masking, tool-output pruning and history archival for the compactor."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from atria.core.paths import atria_dir

from .stages import PRUNE_PROTECTED_TOKENS, PROTECTED_TOOL_TYPES, OptimizationLevel

logger = logging.getLogger(__name__)


class MaskingMixin:
    """Staged context reduction that runs before full LLM compaction."""

    @staticmethod
    def _build_tool_call_map(messages: list[dict[str, Any]]) -> dict[str, str]:
        """Build a mapping from tool_call_id to tool function name.

        Scans assistant messages for tool_calls and extracts the id → name mapping
        so callers can determine whether a tool result belongs to a protected tool.

        Args:
            messages: API-format message list.

        Returns:
            Dict mapping tool_call_id to function name.
        """
        tc_map: dict[str, str] = {}
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            for tc in msg.get("tool_calls", []):
                tc_id = tc.get("id", "")
                func_name = tc.get("function", {}).get("name", "")
                if tc_id and func_name:
                    tc_map[tc_id] = func_name
        return tc_map

    # ------------------------------------------------------------------
    # Public: observation masking
    # ------------------------------------------------------------------
    def mask_old_observations(
        self,
        messages: list[dict[str, Any]],
        level: str,
    ) -> list[dict[str, Any]]:
        """Replace old tool result messages with compact references.

        Tool outputs are ~80% of context tokens. This replaces tool result
        messages that are N+ turns old with minimal placeholders, dramatically
        reducing token usage without losing the tool call structure.

        Args:
            messages: Current API-format messages (mutated in-place).
            level: OptimizationLevel.MASK or AGGRESSIVE.

        Returns:
            The messages list (same reference, mutated).
        """
        if level == OptimizationLevel.MASK:
            # Keep recent 6 tool results intact, mask older ones
            recent_threshold = 6
        elif level == OptimizationLevel.AGGRESSIVE:
            # Keep only last 3 tool results intact
            recent_threshold = 3
        else:
            return messages

        # Find all tool result message indices (walk backwards)
        tool_indices: list[int] = []
        for i, msg in enumerate(messages):
            if msg.get("role") == "tool":
                tool_indices.append(i)

        if len(tool_indices) <= recent_threshold:
            return messages

        # Build tool_call_id → tool name map for protected-tool detection
        tc_map = self._build_tool_call_map(messages)

        # Mask old tool results (all except the last `recent_threshold`)
        old_indices = set(tool_indices[:-recent_threshold])
        masked_count = 0
        for i in old_indices:
            msg = messages[i]
            content = msg.get("content", "")
            # Skip already-masked messages
            if content.startswith("[ref:"):
                continue
            # Skip protected tool types (skills, plans, read_file)
            tool_call_id = msg.get("tool_call_id", "?")
            tool_name = tc_map.get(tool_call_id, "")
            if tool_name in PROTECTED_TOOL_TYPES:
                continue
            # Replace with compact reference
            msg["content"] = f"[ref: tool result {tool_call_id} — see history]"
            masked_count += 1

        if masked_count > 0:
            logger.info(
                "Masked %d old tool results (level=%s, kept recent %d)",
                masked_count,
                level,
                recent_threshold,
            )

        return messages

    # ------------------------------------------------------------------
    # Public: fast pruning (cheaper than LLM compaction)
    # ------------------------------------------------------------------
    def prune_old_tool_outputs(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Strip old tool outputs while protecting the most recent ones.

        This is a fast, zero-cost alternative to LLM compaction. Walks
        backwards through messages, protects the last ~40K tokens worth
        of tool results, and replaces older ones with a `[pruned]` marker.

        Much cheaper than LLM summarization and often sufficient to stay
        under the context limit.

        Args:
            messages: Current API-format messages (mutated in-place).

        Returns:
            The messages list (same reference, mutated).
        """
        # Collect all tool result message indices (in reverse order)
        tool_indices: list[int] = []
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "tool":
                tool_indices.append(i)

        if not tool_indices:
            return messages

        # Build tool_call_id → tool name map for protected-tool detection
        tc_map = self._build_tool_call_map(messages)

        # Walk backwards, protecting recent tokens up to the budget
        protected_tokens = 0
        protected_indices: set[int] = set()
        for idx in tool_indices:
            content = messages[idx].get("content", "")
            # Skip already-pruned/masked messages
            if content.startswith("[ref:") or content == "[pruned]":
                continue
            # Always protect outputs from protected tool types
            tool_call_id = messages[idx].get("tool_call_id", "")
            tool_name = tc_map.get(tool_call_id, "")
            if tool_name in PROTECTED_TOOL_TYPES:
                protected_indices.add(idx)
                continue
            # Rough token estimate: ~4 chars per token
            token_estimate = len(content) // 4
            if protected_tokens + token_estimate <= PRUNE_PROTECTED_TOKENS:
                protected_tokens += token_estimate
                protected_indices.add(idx)
            # Once budget exhausted, remaining are candidates for pruning

        # Prune unprotected tool results
        pruned_count = 0
        for idx in tool_indices:
            if idx in protected_indices:
                continue
            content = messages[idx].get("content", "")
            if content.startswith("[ref:") or content == "[pruned]":
                continue
            messages[idx]["content"] = "[pruned]"
            pruned_count += 1

        if pruned_count > 0:
            logger.info(
                "Pruned %d old tool outputs (protected %d, ~%dK tokens kept)",
                pruned_count,
                len(protected_indices),
                protected_tokens // 1000,
            )

        return messages

    # ------------------------------------------------------------------
    # Public: history archival
    # ------------------------------------------------------------------
    def archive_history(
        self,
        messages: list[dict[str, Any]],
        session_id: str | None = None,
    ) -> str | None:
        """Write full conversation to a file before compaction.

        The agent can grep this file to recover details lost in compaction.

        Args:
            messages: Messages about to be compacted.
            session_id: Session ID for file path scoping.

        Returns:
            Path to the archive file, or None if archival failed.
        """
        sid = session_id or self._session_id or "unknown"
        scratch_dir = atria_dir() / "scratch" / sid
        try:
            scratch_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("Failed to create scratch dir: %s", scratch_dir)
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_path = scratch_dir / f"history_archive_{timestamp}.md"

        try:
            lines: list[str] = [
                f"# Conversation Archive — {timestamp}",
                f"Session: {sid}",
                f"Messages: {len(messages)}",
                "",
            ]
            for i, msg in enumerate(messages):
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                lines.append(f"## Message {i} [{role}]")
                if content:
                    lines.append(content[:2000])
                # Include tool call info
                for tc in msg.get("tool_calls", []):
                    func = tc.get("function", {})
                    name = func.get("name", "?")
                    args_str = func.get("arguments", "")
                    lines.append(f"  Tool: {name}")
                    if args_str:
                        lines.append(f"  Args: {args_str[:500]}")
                lines.append("")

            archive_path.write_text("\n".join(lines), encoding="utf-8")
            logger.info("Archived %d messages to %s", len(messages), archive_path)
            return str(archive_path)
        except OSError:
            logger.warning("Failed to write history archive", exc_info=True)
            return None
