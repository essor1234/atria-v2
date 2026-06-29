"""Docker preparation for SubAgentManager: availability, file copy-in, task rewriting."""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from atria.core.agents.prompts import get_reminder

if TYPE_CHECKING:
    from atria.models.config import AppConfig

    from atria.core.agents.subagents.specs import CompiledSubAgent, SubAgentSpec

logger = logging.getLogger(__name__)


class DockerPrepMixin:
    """Docker availability, input-file handling, task rewriting and path sanitizing."""

    # Declared for type checking — set by SubAgentManager.__init__
    _config: AppConfig
    _tool_registry: Any
    _mode_manager: Any
    _working_dir: Any
    _env_context: Any
    _hook_manager: Any
    _agents: dict[str, CompiledSubAgent]
    _all_tool_names: list[str]

    def _is_docker_available(self) -> bool:
        """Check if Docker is available on the system."""
        return shutil.which("docker") is not None

    def _get_spec_for_subagent(self, name: str) -> SubAgentSpec | None:
        """Get the SubAgentSpec for a registered subagent."""
        from atria.core.agents.subagents.agents import ALL_SUBAGENTS

        return next((s for s in ALL_SUBAGENTS if s["name"] == name), None)

    def _extract_input_files(self, task: str, local_working_dir: Path) -> list[Path]:
        """Extract DOCUMENT file paths referenced in the task.

        Only extracts PDF, DOC, DOCX - formats that can contain research papers.
        Images (PNG, JPEG, SVG) and data files (CSV) are NOT extracted.

        Looks for:
        - @filename patterns (e.g., @paper.pdf)
        - Quoted file paths (e.g., "paper.pdf")
        - Unquoted document filenames (e.g., PDF paper.pdf)

        Args:
            task: The task description string
            local_working_dir: Local working directory to resolve relative paths

        Returns:
            List of existing document file paths to copy into Docker
        """
        files: list[Path] = []
        seen: set[str] = set()  # Track by resolved filename to avoid duplicates

        # Only document formats (PDF, DOC, DOCX)
        doc_pattern = r"pdf|docx?"

        # Pattern 1: @filename (e.g., @paper.pdf)
        at_mentions = re.findall(rf"@([\w\-\.]+\.(?:{doc_pattern}))\b", task, re.I)
        for filename in at_mentions:
            path = local_working_dir / filename
            if path.exists() and path.is_file() and path.name not in seen:
                files.append(path)
                seen.add(path.name)

        # Pattern 2: Quoted file paths (e.g., "paper.pdf", 'paper.pdf', `paper.pdf`)
        quoted_paths = re.findall(rf'["\'\`]([^"\'\`]+\.(?:{doc_pattern}))["\'\`]', task, re.I)
        for p in quoted_paths:
            path = Path(p) if Path(p).is_absolute() else local_working_dir / p
            if path.exists() and path.is_file() and path.name not in seen:
                files.append(path)
                seen.add(path.name)

        # Pattern 3: Unquoted document filenames (e.g., "PDF paper.pdf")
        unquoted_docs = re.findall(rf'(?:^|[\s(,])([^\s"\'()<>]+\.(?:{doc_pattern}))\b', task, re.I)
        for filename in unquoted_docs:
            path = Path(filename) if Path(filename).is_absolute() else local_working_dir / filename
            if path.exists() and path.is_file() and path.name not in seen:
                files.append(path)
                seen.add(path.name)

        # Pattern 4: Stems without extension (e.g., "paper 2303.11366v4" without .pdf)
        # Match alphanumeric+dots patterns that could be paper IDs (e.g., arXiv IDs)
        # Then check if a corresponding .pdf/.doc/.docx exists
        stem_pattern = r"(?:^|[\s(,])(\d[\w\.\-]+v\d+|\d{4}\.\d+(?:v\d+)?)\b"
        stems = re.findall(stem_pattern, task, re.I)
        for stem in stems:
            # Try adding document extensions
            for ext in ["pdf", "PDF", "docx", "DOCX", "doc", "DOC"]:
                candidate = local_working_dir / f"{stem}.{ext}"
                if candidate.exists() and candidate.is_file():
                    # Check if this file was already found (use resolved name)
                    if candidate.name not in seen:
                        files.append(candidate)
                        seen.add(candidate.name)
                    break

        return files

    def _extract_github_info(self, task: str) -> tuple[str, str, str] | None:
        """Extract GitHub repo URL and issue number from task.

        Looks for GitHub issue URLs in the format:
        https://github.com/owner/repo/issues/123

        Args:
            task: The task description string

        Returns:
            Tuple of (repo_url, owner_repo, issue_number) or None if not found
        """
        match = re.search(r"https://github\.com/([^/]+/[^/]+)/issues/(\d+)", task)
        if match:
            owner_repo = match.group(1)
            issue_number = match.group(2)
            repo_url = f"https://github.com/{owner_repo}.git"
            return (repo_url, owner_repo, issue_number)
        return None

    def _copy_files_to_docker(
        self,
        container_name: str,
        files: list[Path],
        workspace_dir: str,
        ui_callback: Any = None,
    ) -> dict[str, str]:
        """Copy local files into Docker container using docker cp.

        Args:
            container_name: Docker container name or ID
            files: List of local file paths to copy
            workspace_dir: Target directory in Docker container
            ui_callback: Optional UI callback for progress display

        Returns:
            Mapping of Docker paths to local paths (for local-only tool remapping)
        """
        import subprocess

        path_mapping: dict[str, str] = {}

        for local_file in files:
            # Show copy progress - use on_nested_tool_call for proper display
            if ui_callback:
                if hasattr(ui_callback, "on_nested_tool_call"):
                    # Direct nested callback - use proper method
                    ui_callback.on_nested_tool_call(
                        "docker_copy",
                        {"file": local_file.name},
                        depth=getattr(ui_callback, "_depth", 1),
                        parent=getattr(ui_callback, "_context", "Docker"),
                    )
                elif hasattr(ui_callback, "on_tool_call"):
                    ui_callback.on_tool_call("docker_copy", {"file": local_file.name})

            try:
                docker_target = f"{workspace_dir}/{local_file.name}"
                docker_path = f"{container_name}:{docker_target}"

                # Use docker cp for reliable file transfer (handles any size/binary)
                result = subprocess.run(
                    ["docker", "cp", str(local_file), docker_path],
                    capture_output=True,
                    text=True,
                    timeout=60.0,
                )

                if result.returncode != 0:
                    raise RuntimeError(f"docker cp failed: {result.stderr}")

                # Store mapping: Docker path -> local path
                path_mapping[docker_target] = str(local_file)

                # Show completion - use on_nested_tool_result for proper display
                if ui_callback:
                    result_data = {"success": True, "output": f"Copied to {docker_target}"}
                    if hasattr(ui_callback, "on_nested_tool_result"):
                        ui_callback.on_nested_tool_result(
                            "docker_copy",
                            {"file": local_file.name},
                            result_data,
                            depth=getattr(ui_callback, "_depth", 1),
                            parent=getattr(ui_callback, "_context", "Docker"),
                        )
                    elif hasattr(ui_callback, "on_tool_result"):
                        ui_callback.on_tool_result(
                            "docker_copy", {"file": local_file.name}, result_data
                        )

            except Exception as e:
                if ui_callback:
                    result_data = {"success": False, "error": str(e)}
                    if hasattr(ui_callback, "on_nested_tool_result"):
                        ui_callback.on_nested_tool_result(
                            "docker_copy",
                            {"file": local_file.name},
                            result_data,
                            depth=getattr(ui_callback, "_depth", 1),
                            parent=getattr(ui_callback, "_context", "Docker"),
                        )
                    elif hasattr(ui_callback, "on_tool_result"):
                        ui_callback.on_tool_result(
                            "docker_copy", {"file": local_file.name}, result_data
                        )

        return path_mapping

    def _rewrite_task_for_docker(
        self,
        task: str,
        input_files: list[Path],
        workspace_dir: str,
    ) -> str:
        """Rewrite task to reference Docker paths instead of local paths.

        Args:
            task: Original task description
            input_files: List of files that were copied to Docker
            workspace_dir: Docker workspace directory

        Returns:
            Task with paths rewritten to Docker paths, including Docker context
        """
        new_task = task

        # Remove phrases that hint at local filesystem
        new_task = re.sub(r"\blocal\s+", "", new_task, flags=re.IGNORECASE)
        new_task = re.sub(r"\bin this repo\b", f"in {workspace_dir}", new_task, flags=re.IGNORECASE)
        new_task = re.sub(r"\bthis repo\b", workspace_dir, new_task, flags=re.IGNORECASE)

        # Replace any reference to the local working directory with workspace
        local_working_dir = self._working_dir
        if local_working_dir:
            local_dir_str = str(local_working_dir)
            # Replace the local directory path with workspace
            new_task = new_task.replace(local_dir_str, workspace_dir)
            # Also try without trailing slash
            new_task = new_task.replace(local_dir_str.rstrip("/"), workspace_dir)

        for local_file in input_files:
            docker_path = f"{workspace_dir}/{local_file.name}"
            # Replace @filename with Docker path
            new_task = new_task.replace(f"@{local_file.name}", docker_path)
            # Also replace any absolute local paths
            new_task = new_task.replace(str(local_file), docker_path)
            # Replace plain filename references (be careful to avoid partial matches)
            # Use word boundary matching by checking surrounding chars
            new_task = re.sub(rf"\b{re.escape(local_file.name)}\b", docker_path, new_task)

        # Prepend Docker context with strong emphasis
        docker_context = get_reminder("docker/docker_context", workspace_dir=workspace_dir)
        return docker_context + "\n\n" + new_task

    def _create_docker_path_sanitizer(
        self,
        workspace_dir: str,
        local_dir: str,
        image_name: str,
        container_id: str,
    ):
        """Create a path sanitizer for Docker mode UI display.

        Converts local paths to Docker workspace paths with container prefix:
        - /Users/.../test_opencli/src/file.py -> [uv:a1b2c3d4]:/workspace/src/file.py
        - README.md -> [uv:a1b2c3d4]:/workspace/README.md

        Args:
            workspace_dir: The Docker workspace directory (e.g., /workspace)
            local_dir: The local working directory (e.g., /Users/.../test_opencli)
            image_name: Full Docker image name (e.g., ghcr.io/astral-sh/uv:python3.11)
            container_id: Short container ID (e.g., a1b2c3d4)

        Returns:
            A callable that sanitizes paths for display
        """
        # Extract short image name: "ghcr.io/astral-sh/uv:python3.11-bookworm" -> "uv"
        short_image = image_name.split("/")[-1].split(":")[0]
        prefix = f"[{short_image}:{container_id}]:"

        def sanitize(path: str) -> str:
            # If path starts with local_dir, replace with workspace_dir
            if path.startswith(local_dir):
                relative = path[len(local_dir) :].lstrip("/")
                docker_path = f"{workspace_dir}/{relative}" if relative else workspace_dir
                return f"{prefix}{docker_path}"

            # Handle Docker-internal absolute paths (e.g., /workspace/..., /testbed/...)
            # These are paths the LLM outputs when running inside Docker
            if path.startswith(workspace_dir):
                return f"{prefix}{path}"

            # Fallback: extract filename from other absolute paths
            match = re.match(r"^(/Users/|/home/|/var/|/tmp/).+/([^/]+)$", path)
            if match:
                return f"{prefix}{workspace_dir}/{match.group(2)}"

            # Convert relative paths to full Docker paths
            # e.g., "README.md" -> "[uv:a1b2c3d4]:/workspace/README.md"
            # e.g., "." -> "[uv:a1b2c3d4]:/workspace"
            # e.g., "src/model.py" -> "[uv:a1b2c3d4]:/workspace/src/model.py"
            if not path.startswith("/"):
                clean_path = path.lstrip("./")
                if not clean_path:
                    return f"{prefix}{workspace_dir}"
                return f"{prefix}{workspace_dir}/{clean_path}"

            return path

        return sanitize

    def create_docker_nested_callback(
        self,
        ui_callback: Any,
        subagent_name: str,
        workspace_dir: str,
        image_name: str,
        container_id: str,
        local_dir: str | None = None,
    ) -> Any:
        """Create NestedUICallback with Docker path sanitizer for consistent display.

        This is the STANDARD INTERFACE for Docker subagent UI context.
        Use this method whenever executing a subagent inside Docker.

        Args:
            ui_callback: Parent UI callback to wrap
            subagent_name: Name of the subagent (e.g., "Code-Explorer", "Web-clone")
            workspace_dir: Docker workspace path (e.g., "/workspace", "/testbed")
            image_name: Full Docker image name (e.g., "ghcr.io/astral-sh/uv:python3.11")
            container_id: Short container ID (e.g., "a1b2c3d4")
            local_dir: Local directory for path remapping (optional)

        Returns:
            NestedUICallback wrapped with Docker path sanitizer, or None if ui_callback is None

        Usage:
            nested_callback = manager.create_docker_nested_callback(
                ui_callback=self.ui_callback,
                subagent_name="Web-clone",
                workspace_dir="/workspace",
                image_name=docker_image,
                container_id=container_id,
            )
            result = manager.execute_subagent(..., ui_callback=nested_callback)
        """
        if ui_callback is None:
            return None

        from atria.ui_textual.nested_callback import NestedUICallback

        # Use existing _create_docker_path_sanitizer
        path_sanitizer = self._create_docker_path_sanitizer(
            workspace_dir=workspace_dir,
            local_dir=local_dir or str(self._working_dir or Path.cwd()),
            image_name=image_name,
            container_id=container_id,
        )

        return NestedUICallback(
            parent_callback=ui_callback,
            parent_context=subagent_name,
            depth=1,
            path_sanitizer=path_sanitizer,
        )
