"""LLM-powered summarization of old messages (the final compaction stage)."""

from __future__ import annotations

import logging
from typing import Any

from atria.core.agents.components.api.configuration import build_temperature_param
from atria.core.agents.prompts.loader import load_prompt

from .stages import STAGE_COMPACT

logger = logging.getLogger(__name__)


class SummaryMixin:
    """Full compaction: summarize middle messages via the configured LLM."""

    def compact(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        *,
        trigger: str = "auto",
    ) -> list[dict[str, Any]]:
        """Compact older messages into a summary, preserving recent context.

        Strategy:
            1. Archive full history to scratch file for post-compaction grep.
            2. Keep system prompt message (index 0).
            3. Keep last N messages intact.
            4. Summarize everything between into a single user message.
            5. Inject artifact index into the summary.

        Args:
            messages: Current conversation messages.
            system_prompt: System prompt string.
            trigger: What triggered compaction ("auto" or "manual").
        """
        # Fire PreCompact hook
        if self._hook_manager:
            from atria.core.hooks.models import HookEvent

            if self._hook_manager.has_hooks_for(HookEvent.PRE_COMPACT):
                self._hook_manager.run_hooks(
                    HookEvent.PRE_COMPACT,
                    match_value=trigger,
                )

        if len(messages) <= 4:
            return messages

        # Step 1: Archive history before compaction
        archive_path = self.archive_history(messages)

        # Determine how many recent messages to preserve
        keep_recent = min(5, max(2, len(messages) // 3))

        head = messages[:1]
        middle = messages[1:-keep_recent]
        tail = messages[-keep_recent:]

        if not middle:
            return messages

        summary_text = self._summarize(middle)
        if not summary_text:
            summary_text = "[Previous conversation context was compacted.]"

        # Inject artifact index so file awareness survives compaction
        artifact_summary = self.artifact_index.as_summary()
        if artifact_summary:
            summary_text = f"{summary_text}\n\n{artifact_summary}"

        # Add archive reference so agent knows where to find full history
        if archive_path:
            summary_text += (
                f"\n\n**Note:** Full conversation history archived at "
                f"`{archive_path}`. Use read_file to recover details if needed."
            )

        summary_msg: dict[str, Any] = {
            "role": "user",
            "content": f"[CONVERSATION SUMMARY]\n{summary_text}",
        }

        compacted = head + [summary_msg] + tail

        logger.info(
            "Compacted %d messages → %d (removed %d, kept %d recent)",
            len(messages),
            len(compacted),
            len(middle),
            keep_recent,
        )

        # Invalidate API calibration (message list changed)
        self._api_prompt_tokens = 0
        self._msg_count_at_calibration = 0

        # Reset stage warnings so they fire again if context grows back
        self._warned_70 = False
        self._warned_80 = False
        self._warned_90 = False

        return compacted

    # ------------------------------------------------------------------
    # Public: compact with retry (replay from last user message)
    # ------------------------------------------------------------------
    def compact_with_retry(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        *,
        trigger: str = "auto",
        max_retries: int = 2,
    ) -> list[dict[str, Any]]:
        """Compact with retry logic — if still over limit after first pass,
        replay from last user message.

        Args:
            messages: Current conversation messages.
            system_prompt: System prompt string.
            trigger: What triggered compaction.
            max_retries: Maximum compaction attempts.
        """
        result = self.compact(messages, system_prompt, trigger=trigger)

        for attempt in range(max_retries):
            # Re-check usage after compaction
            self._update_token_count(result, system_prompt)
            pct = self.usage_pct / 100.0

            if pct < STAGE_COMPACT:
                break  # Under the limit, we're good

            logger.warning(
                "Post-compaction still at %.1f%% (attempt %d/%d), "
                "replaying from last user message",
                pct * 100,
                attempt + 1,
                max_retries,
            )

            # Find the last user message (skip conversation summaries)
            last_user_idx = None
            for i in range(len(result) - 1, -1, -1):
                if result[i].get("role") == "user" and not result[i].get("content", "").startswith(
                    "[CONVERSATION SUMMARY]"
                ):
                    last_user_idx = i
                    break

            if last_user_idx is None or last_user_idx <= 1:
                break  # Nothing more we can do

            # Keep: head[0] + compact summary + last user message + any responses after
            head = result[:1]  # System/first message

            # Summarize everything between head and last user message
            middle = result[1:last_user_idx]
            if middle:
                summary_text = self._fallback_summary(middle)
                artifact_summary = self.artifact_index.as_summary()
                if artifact_summary:
                    summary_text = f"{summary_text}\n\n{artifact_summary}"

                summary_msg: dict[str, Any] = {
                    "role": "user",
                    "content": (f"[CONVERSATION SUMMARY — compact replay]\n{summary_text}"),
                }
                tail = result[last_user_idx:]
                result = head + [summary_msg] + tail
            else:
                break  # Already minimal

            logger.info(
                "Replay compaction: %d messages remaining (attempt %d)",
                len(result),
                attempt + 1,
            )

        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _update_token_count(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
    ) -> None:
        """Update _last_token_count using API calibration or tiktoken."""
        if self._api_prompt_tokens > 0:
            new_msg_count = len(messages) - self._msg_count_at_calibration
            if new_msg_count > 0:
                delta = self._count_message_tokens(messages[-new_msg_count:], "")
                total = self._api_prompt_tokens + delta
            else:
                total = self._api_prompt_tokens
        else:
            total = self._count_message_tokens(messages, system_prompt)
        self._last_token_count = total

    def _sanitize_for_summarization(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Replace full tool results with summaries before sending to LLM.

        Prevents sensitive data from leaking into the summarization LLM calls.
        """
        sanitized = []
        for msg in messages:
            msg_copy = msg.copy()

            if "tool_calls" in msg_copy and msg_copy["tool_calls"]:
                sanitized_tool_calls = []
                for tc in msg_copy["tool_calls"]:
                    tc_copy = tc.copy()

                    if "result" in tc_copy:
                        if tc_copy.get("result_summary"):
                            tc_copy["result"] = tc_copy["result_summary"]
                        else:
                            result_str = str(tc_copy["result"])
                            if result_str:
                                tc_copy["result"] = result_str[:200] + (
                                    "..." if len(result_str) > 200 else ""
                                )
                            else:
                                tc_copy["result"] = "[result omitted]"

                    sanitized_tool_calls.append(tc_copy)

                msg_copy["tool_calls"] = sanitized_tool_calls

            sanitized.append(msg_copy)

        return sanitized

    def _summarize(self, messages: list[dict[str, Any]]) -> str:
        """Use the configured LLM to summarize a block of messages."""
        sanitized = self._sanitize_for_summarization(messages)

        parts: list[str] = []
        for msg in sanitized:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if content:
                parts.append(f"[{role}] {content[:500]}")

        conversation_text = "\n".join(parts)

        compact_info = (
            self._config.get_compact_model_info()
            if hasattr(self._config, "get_compact_model_info")
            else None
        )
        if compact_info:
            _, model_id, _ = compact_info
        else:
            model_id = getattr(self._config, "model", "gpt-4o-mini")

        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": load_prompt("system/compaction")},
                {"role": "user", "content": conversation_text},
            ],
            "max_tokens": 1024,
            **build_temperature_param(model_id, 0.2),
        }

        try:
            result = self._http_client.post_json(payload)
            if result.success and result.response is not None:
                data = result.response.json()
                return data["choices"][0]["message"]["content"]
        except Exception:
            logger.warning("LLM summarization failed, using fallback", exc_info=True)

        return self._fallback_summary(messages)

    @staticmethod
    def _fallback_summary(messages: list[dict[str, Any]]) -> str:
        """Create a basic summary without an LLM call."""
        parts: list[str] = []
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            role = msg.get("role", "")
            if content and role in ("user", "assistant"):
                snippet = content[:200]
                parts.append(f"- [{role}] {snippet}")
                total += len(snippet)
                if total > 2000:
                    parts.append(f"... ({len(messages) - len(parts)} more messages)")
                    break
        return "\n".join(parts)

    def _count_message_tokens(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
    ) -> int:
        """Estimate total tokens across all messages and system prompt."""
        total = self._token_monitor.count_tokens(system_prompt)
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        total += self._token_monitor.count_tokens(block.get("text", ""))
            elif content:
                total += self._token_monitor.count_tokens(content)
            for tc in msg.get("tool_calls", []):
                func = tc.get("function", {})
                total += self._token_monitor.count_tokens(func.get("name", ""))
                total += self._token_monitor.count_tokens(func.get("arguments", ""))
        total += len(messages) * 4
        return total
