"""Skill-tool primitives: ToolSpec and SkillToolContext.

Skill folders that ship executable tools export a `register(ctx)` function from
`tools.py` returning a list of ToolSpec. The tool registry constructs a single
mutable SkillToolContext at init and passes it to register(). Session layers
mutate `ctx.broadcaster`, `ctx.review_callback`, and `ctx.clarify_callback` after the session is set up;
handlers read these fields at call time so the mutation propagates without
re-registration.
"""

from __future__ import annotations

import importlib.util
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable


@dataclass
class ToolSpec:
    """A single tool exposed by a skill."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., dict[str, Any]]
    card_path: Path | None = None


@dataclass
class SkillToolContext:
    """Cross-cutting services available to skill tools.

    `broadcaster`, `review_callback`, `clarify_callback`, and `on_clarify_message`
    are deliberately mutable — the web session layer assigns them after the
    session starts. Handlers read these attributes at call time, not at register
    time.
    """

    working_dir: str | None = None
    web_search: Any | None = None
    broadcaster: Callable[[dict[str, Any]], None] | None = None
    # (job_id, request_id, event_payload) -> result. The callback must
    # register pending state BEFORE emitting `event_payload` over the
    # broadcaster, then block on the user's response. Putting register +
    # emit in one place closes the race where the user could respond
    # before the pending entry exists.
    review_callback: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None
    # Clarification Q&A callback. Mirrors review_callback signature:
    # (job_id, request_id, payload) -> result with {"answers": [...]}.
    clarify_callback: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None
    # Per-message persistence hook for clarification round-trip. Receives a payload
    # like {"role": "assistant"|"user", "content": str, "metadata": dict}; the bridge
    # converts it into a ChatMessage and persists to the session store.
    on_clarify_message: Callable[[dict[str, Any]], None] | None = None
    subagent_dispatcher: Callable[..., Any] | None = None
    on_artifact: Callable[[dict[str, Any]], None] | None = None
    on_analyze_done: Callable[[dict[str, Any]], None] | None = None
    # Text-LLM call: (system, user) -> str. Wired from AppConfig so skills
    # reuse atria's configured api_key/api_base_url/model.
    llm_chat: Callable[[str, str], str] | None = None
    # Vision LLM call: (system, user, image_b64) -> str. Optional.
    llm_vision: Callable[[str, str, str], str] | None = None
    # Model identifier (for display/logging).
    llm_model: str | None = None
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("atria.skill_tools"))


# ─── append to atria/core/skill_tools.py ─────────────────────────────────────

_FRONTMATTER_TOOLS_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


class SkillToolError(RuntimeError):
    """Raised when a skill tools.py module cannot be loaded or registered."""


class SkillToolLoader:
    """Finds SKILL.md files declaring `tools: tools.py` and registers their tools."""

    def __init__(self, skill_dirs: Iterable[Path]) -> None:
        self._dirs = [Path(d) for d in skill_dirs]

    def discover_and_register(self, ctx: SkillToolContext) -> list[ToolSpec]:
        """Discover all code-bearing skills and return merged ToolSpecs.

        Raises SkillToolError on duplicate tool names across skills.
        """
        specs: list[ToolSpec] = []
        seen: dict[str, Path] = {}

        for skill_md in self._iter_skill_files():
            tools_file = self._tools_file_for(skill_md)
            if tools_file is None:
                continue
            module = self._import_tools_module(skill_md.parent, tools_file)
            register_fn = getattr(module, "register", None)
            if register_fn is None:
                raise SkillToolError(f"{tools_file}: missing required `register(ctx)` function")
            produced = register_fn(ctx)
            if not isinstance(produced, list):
                raise SkillToolError(f"{tools_file}: register() must return list[ToolSpec]")
            for spec in produced:
                if not isinstance(spec, ToolSpec):
                    raise SkillToolError(
                        f"{tools_file}: register() returned non-ToolSpec item: {spec!r}"
                    )
                if spec.name in seen:
                    raise SkillToolError(
                        f"Duplicate tool name {spec.name!r}: " f"{seen[spec.name]} and {tools_file}"
                    )
                seen[spec.name] = tools_file
                specs.append(spec)

        return specs

    def _iter_skill_files(self) -> Iterable[Path]:
        for d in self._dirs:
            if not d.exists():
                continue
            yield from d.glob("**/SKILL.md")

    def _tools_file_for(self, skill_md: Path) -> Path | None:
        """Return absolute path to tools.py if frontmatter declares it."""
        try:
            text = skill_md.read_text(encoding="utf-8")
        except OSError:
            return None
        m = _FRONTMATTER_TOOLS_RE.match(text)
        if not m:
            return None
        block = m.group(1)
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("tools:"):
                value = line.split(":", 1)[1].strip().strip("'\"")
                if not value:
                    return None
                p = (skill_md.parent / value).resolve()
                if p.exists():
                    return p
                raise SkillToolError(f"{skill_md}: declared tools file {value!r} not found")
        return None

    @staticmethod
    def _import_tools_module(skill_dir: Path, tools_file: Path) -> Any:
        """Import a skill's tools.py as `atria_skills.<dir>.tools`.

        Uses submodule_search_locations so sibling modules in the skill folder
        resolve via package-relative imports without leaking onto sys.path.
        """
        pkg_name = f"atria_skills.{skill_dir.name.replace('-', '_')}"
        import sys

        # Ensure the top-level `atria_skills` namespace package exists so that
        # relative imports inside sibling modules (e.g. engine.py → search.py)
        # can resolve their grandparent package correctly.
        root_pkg = "atria_skills"
        if root_pkg not in sys.modules:
            root_spec = importlib.util.spec_from_loader(root_pkg, loader=None)
            assert root_spec is not None
            root_mod = importlib.util.module_from_spec(root_spec)
            root_mod.__path__ = [str(skill_dir.parent)]  # type: ignore[attr-defined]
            sys.modules[root_pkg] = root_mod

        if pkg_name not in sys.modules:
            parent_spec = importlib.util.spec_from_loader(pkg_name, loader=None)
            assert parent_spec is not None
            parent_mod = importlib.util.module_from_spec(parent_spec)
            parent_mod.__path__ = [str(skill_dir)]  # type: ignore[attr-defined]
            sys.modules[pkg_name] = parent_mod

        mod_name = f"{pkg_name}.tools"
        spec = importlib.util.spec_from_file_location(
            mod_name,
            tools_file,
            submodule_search_locations=[str(skill_dir)],
        )
        if spec is None or spec.loader is None:
            raise SkillToolError(f"could not build import spec for {tools_file}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
        return module
