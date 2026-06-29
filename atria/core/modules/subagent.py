"""Derive dedicated subagent specs from agent-backed modules (the "gateway").

A module opts in via the ``subagent`` block in ``manifest.json``. For each
opted-in module we build one ``SubAgentSpec`` whose system prompt is a base
worker prompt plus a per-module *gateway block* — the same lazy summary +
sub-skill index the main agent sees, scoped to one module. The spec is named
after the module so it surfaces by name in the ``spawn_subagent`` enum.
"""
from __future__ import annotations

import logging
from pathlib import Path

from atria.core.agents.prompts.loader import load_prompt
from atria.core.agents.subagents.specs import SubAgentSpec
from atria.core.modules.prompt import _format_root, render_module_section
from atria.core.modules.registry import ModuleRegistry
from atria.core.modules.store import Module

logger = logging.getLogger(__name__)

DEFAULT_MODULE_SUBAGENT_TOOLS = ["run_command", "invoke_skill", "read_file", "write_file"]

_WORKER_FALLBACK = (
    "You are a dedicated worker subagent for a single installed module. Use "
    "invoke_skill to load sub-skill guides before guessing flags, run scripts "
    "with absolute paths, and return a concise structured summary. The module "
    "you operate follows."
)


def build_module_gateway_block(module: Module, root: Path) -> str:
    """Build the per-module context block injected into its subagent's prompt.

    Reuses ``render_module_section`` so the subagent sees the same summary +
    sub-skill index as the main agent, prefixed with the modules root and the
    absolute-path rule for running this module's scripts.
    """
    r = _format_root(root)
    intro = (
        f"## Your module: {module.name}\n\n"
        f"You are the dedicated worker for the **{module.name}** module, installed "
        f"under ``{r}/{module.name}/``. Load a sub-skill's full guide on demand "
        f"with ``invoke_skill`` before guessing flags. Run its scripts with "
        f"``python {r}/{module.name}/scripts/<file>.py`` — always absolute paths "
        f"(your bash CWD is the chat workspace, not the modules root)."
    )
    section = "\n".join(render_module_section(module))
    return f"{intro}\n\n{section}"


def module_subagent_specs(registry: ModuleRegistry) -> list[SubAgentSpec]:
    """Return one ``SubAgentSpec`` per module whose subagent block is enabled."""
    specs: list[SubAgentSpec] = []
    try:
        modules = registry.all()
    except Exception as exc:  # registry is lazy/watcher-refreshed; never hard-fail
        logger.warning("module_subagent_specs: registry read failed: %s", exc)
        return specs

    worker_base = load_prompt("subagents/subagent-module-worker", fallback=_WORKER_FALLBACK)
    for m in modules:
        sub = m.manifest.subagent if m.manifest else None
        if not (sub and sub.enabled):
            continue
        gateway = build_module_gateway_block(m, registry.root)
        spec: SubAgentSpec = {
            "name": m.name,
            "description": (m.description or f"Dedicated worker for the {m.name} module.").strip(),
            "system_prompt": f"{worker_base}\n\n{gateway}",
            "tools": list(sub.tools) if sub.tools else list(DEFAULT_MODULE_SUBAGENT_TOOLS),
        }
        if sub.model:
            spec["model"] = sub.model
        specs.append(spec)
    return specs
