"""Small tool handlers implemented directly on the tool registry."""

from __future__ import annotations

from typing import Any


class InlineToolsMixin:
    """Browser, image, PDF, todo, plan, batch, skill and patch tool handlers."""

    def _open_browser(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute the open_browser tool."""
        if not self.open_browser_tool:
            return {
                "success": False,
                "error": "open_browser tool not available",
                "output": None,
            }
        return self.open_browser_tool.execute(**arguments)

    def _analyze_image(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute the analyze_image tool (VLM)."""
        if not self.vlm_tool:
            return {
                "success": False,
                "error": "VLM tool not available",
                "output": None,
            }
        # Handle max_completion_tokens -> max_tokens conversion (OpenAI models use different param)
        if "max_completion_tokens" in arguments:
            arguments["max_tokens"] = arguments.pop("max_completion_tokens")
        result = self.vlm_tool.analyze_image(**arguments)
        # Format output for consistency with other tools
        if result.get("success"):
            return {
                "success": True,
                "output": result.get("content", ""),
                "model": result.get("model"),
                "provider": result.get("provider"),
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
                "output": None,
            }

    def _capture_web_screenshot(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute the capture_web_screenshot tool."""
        if not self.web_screenshot_tool:
            return {
                "success": False,
                "error": "Web screenshot tool not available",
                "output": None,
            }
        result = self.web_screenshot_tool.capture_web_screenshot(**arguments)
        # Format output for consistency
        if result.get("success"):
            output_lines = [
                f"Screenshot captured: {result.get('screenshot_path')}",
                f"URL: {result.get('url')}",
            ]
            if result.get("pdf_path"):
                output_lines.append(f"PDF captured: {result.get('pdf_path')}")
            if result.get("warning"):
                output_lines.append(f"Warning: {result['warning']}")
            if result.get("pdf_warning"):
                output_lines.append(f"PDF Warning: {result['pdf_warning']}")

            response = {
                "success": True,
                "output": "\n".join(output_lines),
                "screenshot_path": result.get("screenshot_path"),
            }
            if result.get("pdf_path"):
                response["pdf_path"] = result.get("pdf_path")
            return response
        else:
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
                "output": None,
            }

    def _write_todos(self, arguments: dict[str, Any], context: Any = None) -> dict[str, Any]:
        """Execute the write_todos tool."""
        return self.todo_handler.write_todos(arguments.get("todos", []))

    def _update_todo(self, arguments: dict[str, Any], context: Any = None) -> dict[str, Any]:
        """Execute the update_todo tool."""
        return self.todo_handler.update_todo(
            id=arguments.get("id"),
            status=arguments.get("status"),
            title=arguments.get("title"),
        )

    def _complete_todo(self, arguments: dict[str, Any], context: Any = None) -> dict[str, Any]:
        """Execute the complete_todo tool."""
        return self.todo_handler.complete_todo(id=arguments.get("id"))

    def _read_pdf(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute the read_pdf tool to extract text from a PDF file.

        Args:
            arguments: Dict with 'file_path' key

        Returns:
            Result with extracted text content and metadata
        """
        file_path = arguments.get("file_path", "")
        if not file_path:
            return {
                "success": False,
                "error": "file_path is required for read_pdf",
                "output": None,
            }

        result = self._pdf_tool.extract_text(file_path)

        if result.get("success"):
            # Format output for display
            content = result.get("content", "")
            metadata = result.get("metadata", {})
            page_count = result.get("page_count", 0)
            sections = result.get("sections", [])

            output_parts = []
            if metadata:
                if metadata.get("title"):
                    output_parts.append(f"Title: {metadata['title']}")
                if metadata.get("author"):
                    output_parts.append(f"Author: {metadata['author']}")
            output_parts.append(f"Pages: {page_count}")
            if sections:
                output_parts.append(f"Detected sections: {len(sections)}")
                section_titles = [s.get("title", "") for s in sections[:10]]
                output_parts.append(f"  {', '.join(section_titles)}")

            output_parts.append("\n--- Content ---\n")
            output_parts.append(content)

            return {
                "success": True,
                "output": "\n".join(output_parts),
                "metadata": metadata,
                "page_count": page_count,
                "sections": sections,
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
                "output": None,
            }

    def _execute_task_complete(
        self, arguments: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        """Execute the task_complete tool to signal explicit task completion.

        Args:
            arguments: Dict with 'summary' (required) and 'status' keys
            context: Tool execution context (unused)

        Returns:
            Result with _completion flag for loop termination
        """
        summary = arguments.get("summary", "")
        status = arguments.get("status", "success")

        return self._task_complete_tool.execute(summary=summary, status=status)

    def _execute_present_plan(
        self, arguments: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        """Execute the present_plan tool to present plan for approval.

        Args:
            arguments: Dict with 'plan_file_path' key.
            context: Tool execution context.

        Returns:
            Result indicating approval status.
        """
        kwargs: dict[str, Any] = {
            "plan_file_path": arguments.get("plan_file_path", ""),
        }
        if context:
            kwargs["ui_callback"] = getattr(context, "ui_callback", None)
            kwargs["session_manager"] = getattr(context, "session_manager", None)

        result = self._present_plan_tool.execute(**kwargs)

        # Set autonomy to AUTO if user chose "Start implementation (auto-approve)"
        if result.get("auto_approve") and context:
            approval_manager = getattr(context, "approval_manager", None)
            if approval_manager and hasattr(approval_manager, "set_autonomy_level"):
                approval_manager.set_autonomy_level("Auto")

        # Auto-create todos from plan steps
        if result.get("plan_approved"):
            plan_content = result.get("plan_content", "")
            if plan_content:
                self._create_todos_from_plan(plan_content, result)

        return result

    def _create_todos_from_plan(self, plan_content: str, result: dict[str, Any]) -> None:
        """Parse plan and create todos from implementation steps.

        Args:
            plan_content: Raw plan text.
            result: The present_plan result dict to augment with todo count.
        """
        from atria.core.agents.components.response.plan_parser import parse_plan

        # Ensure content has delimiters (safety net)
        if "---BEGIN PLAN---" not in plan_content:
            plan_content = f"---BEGIN PLAN---\n{plan_content}\n---END PLAN---"

        parsed = parse_plan(plan_content)
        if parsed and parsed.steps:
            todos = parsed.get_todo_items()
            todo_result = self.todo_handler.write_todos(todos)
            if todo_result.get("success"):
                count = todo_result.get("created_count", len(todos))
                result["todos_created"] = count
                result["output"] += f"\n\nCreated {count} implementation todos."

    def _execute_batch_tool(self, arguments: dict[str, Any], context: Any = None) -> dict[str, Any]:
        """Execute the batch_tool for parallel/serial multi-tool invocations.

        Args:
            arguments: Dict with 'invocations' list and optional 'mode'
            context: Tool execution context

        Returns:
            Result with list of tool outputs
        """
        if not self._batch_handler:
            return {"success": False, "error": "Batch handler not initialized", "results": []}

        # Pass context-related kwargs for tool execution
        kwargs: dict[str, Any] = {}
        if context:
            kwargs["mode_manager"] = getattr(context, "mode_manager", None)
            kwargs["approval_manager"] = getattr(context, "approval_manager", None)
            kwargs["undo_manager"] = getattr(context, "undo_manager", None)
            kwargs["task_monitor"] = getattr(context, "task_monitor", None)
            kwargs["session_manager"] = getattr(context, "session_manager", None)
            kwargs["ui_callback"] = getattr(context, "ui_callback", None)

        return self._batch_handler.handle(arguments, **kwargs)

    def _handle_invoke_skill(
        self, arguments: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        """Execute the invoke_skill tool to load skill content into context.

        Args:
            arguments: Dict with 'skill_name' key
            context: Tool execution context (unused)

        Returns:
            Result with skill content or error
        """
        if not self._skill_loader:
            return {
                "success": False,
                "error": "Skills system not configured. invoke_skill tool unavailable.",
                "output": None,
            }

        skill_name = arguments.get("skill_name", "")
        if not skill_name:
            # List available skills if no name provided
            available = self._skill_loader.get_skill_names()
            return {
                "success": True,
                "output": f"Available skills: {', '.join(available) if available else 'None'}",
            }

        skill = self._skill_loader.load_skill(skill_name)
        if not skill:
            available = self._skill_loader.get_skill_names()
            return {
                "success": False,
                "error": f"Skill not found: '{skill_name}'. Available: {', '.join(available) if available else 'None'}",
                "output": None,
            }

        # Dedup: if already invoked this session, return a short reminder
        if skill_name in self._invoked_skills:
            return {
                "success": True,
                "output": (
                    f"Skill '{skill.metadata.name}' is already loaded in this conversation. "
                    "Refer to the skill content above and proceed with the next action step — "
                    "do not invoke this skill again."
                ),
                "skill_name": skill.metadata.name,
                "skill_namespace": skill.metadata.namespace,
            }

        self._invoked_skills.add(skill_name)
        return {
            "success": True,
            "output": f"Loaded skill: {skill.metadata.name}\n\n{skill.content}",
            "skill_name": skill.metadata.name,
            "skill_namespace": skill.metadata.namespace,
        }

    def _handle_list_agents(self, arguments: dict[str, Any], context: Any = None) -> dict[str, Any]:
        """List available subagent types."""
        return self._agents_tool.list_agents(subagent_manager=self._subagent_manager)

    def _handle_apply_patch(self, arguments: dict[str, Any], context: Any = None) -> dict[str, Any]:
        """Apply a unified diff patch."""
        return self._patch_tool.apply_patch(
            patch=arguments.get("patch", ""),
            dry_run=arguments.get("dry_run", False),
        )
