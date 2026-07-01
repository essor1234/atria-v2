"""Integration tests for ReAct loop completion with task_complete tool."""

import json
from unittest.mock import MagicMock, patch


class TestMainAgentTaskComplete:
    """Test task_complete handling in MainAgent.run_sync()."""

    def test_loop_ends_on_task_complete(self):
        """Loop should end when task_complete is called."""
        from atria.core.agents.main_agent import MainAgent
        from atria.models.config import AppConfig

        # Create agent with mocked dependencies
        config = AppConfig()
        tool_registry = MagicMock()
        mode_manager = MagicMock()

        with (
            patch.object(MainAgent, "build_system_prompt", return_value="Test prompt"),
            patch.object(MainAgent, "build_tool_schemas", return_value=[]),
        ):
            agent = MainAgent(config, tool_registry, mode_manager)

        # Mock HTTP client to return task_complete tool call
        mock_response = MagicMock()
        mock_response.success = True
        mock_response.response = MagicMock()
        mock_response.response.status_code = 200
        mock_response.response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "I'll complete the task now.",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "task_complete",
                                    "arguments": json.dumps(
                                        {
                                            "summary": "Task completed successfully",
                                            "status": "success",
                                        }
                                    ),
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"total_tokens": 100},
        }

        with patch.object(agent, "_priv_http_client") as mock_client:
            mock_client.post_json.return_value = mock_response

            deps = MagicMock()
            deps.mode_manager = mode_manager
            deps.approval_manager = None
            deps.undo_manager = None

            result = agent.run_sync("Do something", deps)

        assert result["success"] is True
        assert result["content"] == "Task completed successfully"
        assert result.get("completion_status") == "success"

    def test_loop_ends_on_task_complete_failed(self):
        """Loop should end with success=False when task_complete status is failed."""
        from atria.core.agents.main_agent import MainAgent
        from atria.models.config import AppConfig

        config = AppConfig()
        tool_registry = MagicMock()
        mode_manager = MagicMock()

        with (
            patch.object(MainAgent, "build_system_prompt", return_value="Test prompt"),
            patch.object(MainAgent, "build_tool_schemas", return_value=[]),
        ):
            agent = MainAgent(config, tool_registry, mode_manager)

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.response = MagicMock()
        mock_response.response.status_code = 200
        mock_response.response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "Could not complete.",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "task_complete",
                                    "arguments": json.dumps(
                                        {"summary": "Failed to complete", "status": "failed"}
                                    ),
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"total_tokens": 100},
        }

        with patch.object(agent, "_priv_http_client") as mock_client:
            mock_client.post_json.return_value = mock_response

            deps = MagicMock()
            deps.mode_manager = mode_manager
            deps.approval_manager = None
            deps.undo_manager = None

            result = agent.run_sync("Do something", deps)

        assert result["success"] is False
        assert result["completion_status"] == "failed"

    def test_loop_accepts_implicit_completion_on_success(self):
        """Loop should accept implicit completion when last tool succeeded."""
        from atria.core.agents.main_agent import MainAgent
        from atria.models.config import AppConfig

        config = AppConfig()
        tool_registry = MagicMock()
        tool_registry.execute_tool.return_value = {
            "success": True,
            "output": "Command executed successfully",
        }
        mode_manager = MagicMock()

        with (
            patch.object(MainAgent, "build_system_prompt", return_value="Test prompt"),
            patch.object(MainAgent, "build_tool_schemas", return_value=[]),
        ):
            agent = MainAgent(config, tool_registry, mode_manager)

        responses = [
            # First call - run_command tool call
            MagicMock(
                success=True,
                response=MagicMock(
                    status_code=200,
                    json=MagicMock(
                        return_value={
                            "choices": [
                                {
                                    "message": {
                                        "content": "Running command...",
                                        "tool_calls": [
                                            {
                                                "id": "call_1",
                                                "function": {
                                                    "name": "run_command",
                                                    "arguments": json.dumps(
                                                        {"command": "echo hello"}
                                                    ),
                                                },
                                            }
                                        ],
                                    }
                                }
                            ],
                            "usage": {"total_tokens": 50},
                        }
                    ),
                ),
            ),
            # Second call - no tool calls (implicit completion). Because a tool was
            # used, the loop injects one completion nudge and continues.
            MagicMock(
                success=True,
                response=MagicMock(
                    status_code=200,
                    json=MagicMock(
                        return_value={
                            "choices": [{"message": {"content": "Done!", "tool_calls": None}}],
                            "usage": {"total_tokens": 50},
                        }
                    ),
                ),
            ),
            # Third call - post-nudge confirmation, accepted as final answer.
            MagicMock(
                success=True,
                response=MagicMock(
                    status_code=200,
                    json=MagicMock(
                        return_value={
                            "choices": [{"message": {"content": "Done!", "tool_calls": None}}],
                            "usage": {"total_tokens": 50},
                        }
                    ),
                ),
            ),
        ]

        with (
            patch.object(agent, "_priv_http_client") as mock_client,
            patch.object(agent, "_check_todo_completion", return_value=(True, "")),
        ):
            mock_client.post_json.side_effect = responses

            deps = MagicMock()
            deps.mode_manager = mode_manager
            deps.approval_manager = None
            deps.undo_manager = None

            result = agent.run_sync("Do something", deps)

        # Implicit completion triggers one completion nudge, then the loop accepts
        # the post-nudge answer (3 LLM calls total).
        assert mock_client.post_json.call_count == 3
        assert result["success"] is True
        assert result["content"] == "Done!"

    def test_loop_nudges_on_tool_failure(self):
        """Loop should nudge agent when last tool failed and no tool calls returned."""
        from atria.core.agents.main_agent import MainAgent
        from atria.models.config import AppConfig

        config = AppConfig()
        tool_registry = MagicMock()
        # First call fails, second succeeds
        tool_registry.execute_tool.side_effect = [
            {"success": False, "error": "Command not found"},
            {"success": True, "output": "Fixed and worked"},
        ]
        mode_manager = MagicMock()

        with (
            patch.object(MainAgent, "build_system_prompt", return_value="Test prompt"),
            patch.object(MainAgent, "build_tool_schemas", return_value=[]),
        ):
            agent = MainAgent(config, tool_registry, mode_manager)

        responses = [
            # First call - run_command (will fail)
            MagicMock(
                success=True,
                response=MagicMock(
                    status_code=200,
                    json=MagicMock(
                        return_value={
                            "choices": [
                                {
                                    "message": {
                                        "content": "Running...",
                                        "tool_calls": [
                                            {
                                                "id": "call_1",
                                                "function": {
                                                    "name": "run_command",
                                                    "arguments": json.dumps({"command": "bad_cmd"}),
                                                },
                                            }
                                        ],
                                    }
                                }
                            ],
                            "usage": {"total_tokens": 50},
                        }
                    ),
                ),
            ),
            # Second call - no tool calls (agent suggests fix but doesn't act)
            MagicMock(
                success=True,
                response=MagicMock(
                    status_code=200,
                    json=MagicMock(
                        return_value={
                            "choices": [
                                {"message": {"content": "I see the error...", "tool_calls": None}}
                            ],
                            "usage": {"total_tokens": 50},
                        }
                    ),
                ),
            ),
            # Third call (after nudge) - fixes and runs again
            MagicMock(
                success=True,
                response=MagicMock(
                    status_code=200,
                    json=MagicMock(
                        return_value={
                            "choices": [
                                {
                                    "message": {
                                        "content": "Fixed!",
                                        "tool_calls": [
                                            {
                                                "id": "call_2",
                                                "function": {
                                                    "name": "run_command",
                                                    "arguments": json.dumps(
                                                        {"command": "good_cmd"}
                                                    ),
                                                },
                                            }
                                        ],
                                    }
                                }
                            ],
                            "usage": {"total_tokens": 50},
                        }
                    ),
                ),
            ),
            # Fourth call - implicit completion (triggers one completion nudge).
            MagicMock(
                success=True,
                response=MagicMock(
                    status_code=200,
                    json=MagicMock(
                        return_value={
                            "choices": [{"message": {"content": "All done!", "tool_calls": None}}],
                            "usage": {"total_tokens": 50},
                        }
                    ),
                ),
            ),
            # Fifth call - post-nudge confirmation, accepted as final answer.
            MagicMock(
                success=True,
                response=MagicMock(
                    status_code=200,
                    json=MagicMock(
                        return_value={
                            "choices": [{"message": {"content": "All done!", "tool_calls": None}}],
                            "usage": {"total_tokens": 50},
                        }
                    ),
                ),
            ),
        ]

        with (
            patch.object(agent, "_priv_http_client") as mock_client,
            patch.object(agent, "_check_todo_completion", return_value=(True, "")),
        ):
            mock_client.post_json.side_effect = responses

            deps = MagicMock()
            deps.mode_manager = mode_manager
            deps.approval_manager = None
            deps.undo_manager = None

            result = agent.run_sync("Do something", deps)

        # Failure nudge (call 2), fix + re-run (call 3), implicit completion (call 4),
        # completion nudge, then accepted post-nudge answer (call 5).
        assert mock_client.post_json.call_count == 5
        assert result["success"] is True
        assert result["content"] == "All done!"


class TestTaskCompleteToolSchema:
    """Test that task_complete tool schema is correctly defined."""

    def test_schema_in_builtin_schemas(self):
        """Verify task_complete schema is in builtin schemas."""
        from atria.core.agents.components.schemas import _BUILTIN_TOOL_SCHEMAS

        task_complete_schema = None
        for schema in _BUILTIN_TOOL_SCHEMAS:
            if schema["function"]["name"] == "task_complete":
                task_complete_schema = schema
                break

        assert task_complete_schema is not None
        assert task_complete_schema["type"] == "function"

        params = task_complete_schema["function"]["parameters"]
        assert "summary" in params["properties"]
        assert "status" in params["properties"]
        assert "summary" in params["required"]
        assert "status" in params["required"]

    def test_schema_has_enum_for_status(self):
        """Verify status has valid enum values."""
        from atria.core.agents.components.schemas import _BUILTIN_TOOL_SCHEMAS

        for schema in _BUILTIN_TOOL_SCHEMAS:
            if schema["function"]["name"] == "task_complete":
                status_schema = schema["function"]["parameters"]["properties"]["status"]
                assert "enum" in status_schema
                assert set(status_schema["enum"]) == {"success", "partial", "failed"}
                break
