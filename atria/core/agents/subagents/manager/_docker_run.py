"""Docker execution for SubAgentManager: handler wiring and the run loop."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from atria.models.config import AppConfig

    from atria.core.agents.subagents.specs import CompiledSubAgent, SubAgentSpec

logger = logging.getLogger(__name__)


class DockerRunMixin:
    """Docker handler wiring, nested-callback bridging and the execution run loop."""

    # Declared for type checking — set by SubAgentManager.__init__
    _config: AppConfig
    _tool_registry: Any
    _mode_manager: Any
    _working_dir: Any
    _env_context: Any
    _hook_manager: Any
    _agents: dict[str, CompiledSubAgent]
    _all_tool_names: list[str]

    def execute_with_docker_handler(
        self,
        name: str,
        task: str,
        deps: Any,
        docker_handler: Any,
        ui_callback: Any = None,
        container_id: str = "",
        image_name: str = "",
        workspace_dir: str = "/workspace",
        description: str | None = None,
    ) -> dict[str, Any]:
        """Execute subagent with pre-configured Docker handler.

        Use this when you need custom Docker setup (e.g., clone repo, install deps)
        before subagent execution, but still want standardized UI display.

        This provides:
        - Spawn header: Spawn[name](description)
        - Nested callback with Docker path prefix: [image:containerid]:/workspace/...
        - Consistent result display

        Args:
            name: Subagent name (e.g., "Code-Explorer", "Web-clone")
            task: Task prompt for subagent
            deps: SubAgentDeps with mode_manager, approval_manager, undo_manager
            docker_handler: Pre-configured DockerToolHandler
            ui_callback: UI callback for display
            container_id: Docker container ID (last 8 chars) for path prefix
            image_name: Docker image name for path prefix
            workspace_dir: Workspace directory inside container
            description: Description for Spawn header (defaults to task excerpt)

        Returns:
            Result dict with success, content, etc.
        """
        compiled = self._agents.get(name)
        if not compiled:
            return {"success": False, "error": f"Unknown subagent: {name}"}

        # Extract description from task if not provided
        if description is None:
            description = self._extract_task_description(task)

        # Show Spawn header
        spawn_args = {
            "subagent_type": name,
            "description": description,
        }
        if ui_callback and hasattr(ui_callback, "on_tool_call"):
            ui_callback.on_tool_call("spawn_subagent", spawn_args)

        # Create nested callback with Docker context
        nested_callback = self.create_docker_nested_callback(
            ui_callback=ui_callback,
            subagent_name=name,
            workspace_dir=workspace_dir,
            image_name=image_name,
            container_id=container_id,
        )

        try:
            # Execute subagent with nested callback and docker handler
            result = self.execute_subagent(
                name=name,
                task=task,
                deps=deps,
                ui_callback=nested_callback,
                docker_handler=docker_handler,
                show_spawn_header=False,  # Already shown
            )

            # Show Spawn result
            if ui_callback and hasattr(ui_callback, "on_tool_result"):
                success = isinstance(result, str) or result.get("success", True)
                ui_callback.on_tool_result(
                    "spawn_subagent",
                    spawn_args,
                    {
                        "success": success,
                        "output": (
                            result.get("content", "") if isinstance(result, dict) else str(result)
                        ),
                    },
                )

            return result

        except Exception as e:
            if ui_callback and hasattr(ui_callback, "on_tool_result"):
                ui_callback.on_tool_result(
                    "spawn_subagent",
                    spawn_args,
                    {
                        "success": False,
                        "error": str(e),
                    },
                )
            return {"success": False, "error": str(e)}

    def _extract_task_description(self, task: str) -> str:
        """Extract a short description from the task for Spawn header display.

        Args:
            task: The full task description

        Returns:
            A short description suitable for display
        """
        # Look for PDF filename in task
        if ".pdf" in task.lower():
            match = re.search(r"([^\s/]+\.pdf)", task, re.IGNORECASE)
            if match:
                return f"Implement {match.group(1)}"
        # Default: first line, truncated
        first_line = task.split("\n")[0][:50]
        if len(task.split("\n")[0]) > 50:
            return first_line + "..."
        return first_line

    def _get_agent_display_type(self, name: str) -> str:
        """Get the display type for an agent.

        Args:
            name: The subagent name

        Returns:
            The display type (e.g., "Explore" for "Explore" agent)
        """
        # Map internal agent names to display types
        # For now, just return the name as-is
        # Could add special handling for specific agents
        return name

    def _execute_with_docker(
        self,
        name: str,
        task: str,
        deps: Any,
        spec: SubAgentSpec,
        ui_callback: Any = None,
        task_monitor: Any = None,
        show_spawn_header: bool = True,
        local_output_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Execute a subagent inside Docker with automatic container lifecycle.

        This method:
        1. Starts a Docker container with the spec's docker_config
        2. Executes the subagent with all tools routed through Docker
        3. Copies generated files from container to local working directory
        4. Stops the container

        Args:
            name: The subagent type name
            task: The task description
            deps: Dependencies for tool execution
            spec: The subagent specification with docker_config
            ui_callback: Optional UI callback
            task_monitor: Optional task monitor
            show_spawn_header: Whether to show the Spawn[] header. Set to False when
                called via tool_registry (react_executor already showed it).
            local_output_dir: Local directory where files should be copied after Docker
                execution. If None, uses self._working_dir or cwd.

        Returns:
            Result dict with content, success, and messages
        """
        import asyncio

        from atria.core.docker.deployment import DockerDeployment
        from atria.core.docker.tool_handler import DockerToolHandler

        docker_config = spec.get("docker_config")
        if docker_config is None:
            return {
                "success": False,
                "error": "No docker_config in subagent spec",
                "content": "",
            }

        # Workspace inside Docker container
        workspace_dir = "/workspace"
        local_working_dir = local_output_dir or (
            Path(self._working_dir) if self._working_dir else Path.cwd()
        )

        deployment = None
        loop = None
        nested_callback = None

        # Show Spawn header only for direct invocations (e.g., /paper2code)
        # When called via tool_registry, react_executor already showed the header
        spawn_args = None
        if show_spawn_header:
            spawn_args = {
                "subagent_type": name,
                "description": self._extract_task_description(task),
            }
            if ui_callback and hasattr(ui_callback, "on_tool_call"):
                ui_callback.on_tool_call("spawn_subagent", spawn_args)

        try:
            # Create Docker deployment first to get container name
            # (container name is generated in __init__, before start())
            deployment = DockerDeployment(config=docker_config)

            # Extract container ID (last 8 chars of container name)
            # Container name format: "swecli-runtime-a1b2c3d4"
            container_id = deployment._container_name.split("-")[-1]

            # Create nested callback wrapper with container info using standardized interface
            # This ensures docker_start, docker_copy, and all subagent tool calls
            # appear properly nested under the Spawn[subagent_name] parent
            nested_callback = self.create_docker_nested_callback(
                ui_callback=ui_callback,
                subagent_name=name,
                workspace_dir=workspace_dir,
                image_name=docker_config.image,
                container_id=container_id,
                local_dir=str(local_working_dir),
            )

            # Show Docker start as a tool call with spinner (using nested callback)
            if nested_callback and hasattr(nested_callback, "on_tool_call"):
                nested_callback.on_tool_call("docker_start", {"image": docker_config.image})

            # Run async start in sync context - use a single event loop for the whole operation
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(deployment.start())

            # Show Docker start completion (using nested callback)
            if nested_callback and hasattr(nested_callback, "on_tool_result"):
                nested_callback.on_tool_result(
                    "docker_start",
                    {"image": docker_config.image},
                    {
                        "success": True,
                        "output": docker_config.image,
                    },
                )

            # Create workspace directory in Docker container
            # (some images like uv don't have /workspace by default)
            loop.run_until_complete(deployment.runtime.run(f"mkdir -p {workspace_dir}"))

            # Create Docker tool handler with local registry fallback for tools like read_pdf
            runtime = deployment.runtime
            shell_init = docker_config.shell_init if hasattr(docker_config, "shell_init") else ""
            docker_handler = DockerToolHandler(
                runtime,
                workspace_dir=workspace_dir,
                shell_init=shell_init,
            )

            # Extract input files from task (PDFs, images, etc.)
            input_files = self._extract_input_files(task, local_working_dir)

            # Copy input files into Docker container using docker cp
            # Returns mapping of Docker paths to local paths for local-only tools
            # Note: Individual docker_copy calls will show progress for each file
            path_mapping: dict[str, str] = {}
            if input_files:
                path_mapping = self._copy_files_to_docker(
                    deployment._container_name,
                    input_files,
                    workspace_dir,
                    nested_callback,  # Use nested callback for proper nesting
                )

            # Rewrite task to use Docker paths
            docker_task = self._rewrite_task_for_docker(task, input_files, workspace_dir)

            # Execute subagent with Docker tools (local_registry passed for fallback)
            # Pass nested_callback - execute_subagent will detect it's already nested
            result = self.execute_subagent(
                name=name,
                task=docker_task,  # Use rewritten task with Docker paths
                deps=deps,
                ui_callback=nested_callback,  # Already nested, will be used directly
                task_monitor=task_monitor,
                working_dir=workspace_dir,
                docker_handler=docker_handler,
                path_mapping=path_mapping,  # For local-only tool path remapping
            )

            # Copy generated files from Docker to local working directory
            if result.get("success"):
                self._copy_files_from_docker(
                    container_name=deployment._container_name,
                    workspace_dir=workspace_dir,
                    local_dir=local_working_dir,
                    spec=spec,
                    ui_callback=nested_callback,
                )

            # Show Spawn completion only if we showed the header
            if spawn_args and ui_callback and hasattr(ui_callback, "on_tool_result"):
                ui_callback.on_tool_result(
                    "spawn_subagent",
                    spawn_args,
                    {
                        "success": result.get("success", True),
                    },
                )

            return result

        except Exception as e:
            import traceback

            # Stop the docker_start spinner by reporting failure
            if nested_callback and hasattr(nested_callback, "on_tool_result"):
                nested_callback.on_tool_result(
                    "docker_start",
                    {"image": docker_config.image},
                    {
                        "success": False,
                        "error": str(e),
                    },
                )
            # Show Spawn failure only if we showed the header
            if spawn_args and ui_callback and hasattr(ui_callback, "on_tool_result"):
                ui_callback.on_tool_result(
                    "spawn_subagent",
                    spawn_args,
                    {
                        "success": False,
                        "error": str(e),
                    },
                )
            return {
                "success": False,
                "error": f"Docker execution failed: {str(e)}\n{traceback.format_exc()}",
                "content": "",
            }
        finally:
            # Show Docker stop as a tool call (matching docker_start pattern)
            if (
                deployment is not None
                and nested_callback
                and hasattr(nested_callback, "on_tool_call")
            ):
                nested_callback.on_tool_call(
                    "docker_stop", {"container": deployment._container_name[:12]}
                )

            # Always stop the container
            if deployment is not None and loop is not None:
                try:
                    loop.run_until_complete(deployment.stop())
                except Exception:
                    pass  # Ignore cleanup errors

                # Show Docker stop completion with container ID
                if nested_callback and hasattr(nested_callback, "on_tool_result"):
                    container_id = deployment._container_name
                    nested_callback.on_tool_result(
                        "docker_stop",
                        {"container": container_id},
                        {"success": True, "output": container_id},
                    )

            # Close the loop after all async operations
            if loop is not None:
                try:
                    loop.close()
                except Exception:
                    pass

    def _copy_files_from_docker(
        self,
        container_name: str,
        workspace_dir: str,
        local_dir: Path,
        spec: SubAgentSpec | None = None,
        ui_callback: Any = None,
    ) -> None:
        """Copy generated files from Docker container to local directory using docker cp.

        Uses docker cp for recursive directory copy, which is more reliable and
        handles nested directories properly (e.g., reflexion_minimal/*.py).

        Args:
            container_name: Docker container name/ID
            workspace_dir: Path inside container (e.g., /workspace)
            local_dir: Local directory to copy files to
            spec: SubAgentSpec for copy configuration
            ui_callback: UI callback for progress display
        """
        import subprocess

        recursive = spec.get("copy_back_recursive", True) if spec else True

        if not recursive:
            return  # Skip copy if not configured

        try:
            # Show copy operation in UI
            if ui_callback and hasattr(ui_callback, "on_tool_call"):
                ui_callback.on_tool_call(
                    "docker_copy_back",
                    {
                        "from": f"{container_name}:{workspace_dir}",
                        "to": str(local_dir),
                    },
                )

            # Use docker cp to copy entire workspace recursively
            # The "/." at the end copies contents without creating workspace folder
            result = subprocess.run(
                ["docker", "cp", f"{container_name}:{workspace_dir}/.", str(local_dir)],
                capture_output=True,
                text=True,
                timeout=120.0,
            )

            if result.returncode == 0:
                logger.info(f"Copied workspace from Docker to {local_dir}")
                if ui_callback and hasattr(ui_callback, "on_tool_result"):
                    ui_callback.on_tool_result(
                        "docker_copy_back",
                        {},
                        {
                            "success": True,
                            "output": f"Copied to {local_dir}",
                        },
                    )
            else:
                logger.warning(f"docker cp failed: {result.stderr}")
                if ui_callback and hasattr(ui_callback, "on_tool_result"):
                    ui_callback.on_tool_result(
                        "docker_copy_back",
                        {},
                        {
                            "success": False,
                            "error": result.stderr,
                        },
                    )

        except subprocess.TimeoutExpired:
            logger.error("docker cp timed out after 120 seconds")
        except Exception as e:
            logger.error(f"Failed to copy from Docker: {e}")
