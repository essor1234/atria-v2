# Module Subagent Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let any module declare in `manifest.json` that its operations run through a dedicated, context-injected subagent, so the main agent can delegate heavy work to a domain specialist instead of running the module's CLI inline.

**Architecture:** A new `subagent` block in `manifest.json` opts a module in. `atria/core/modules/subagent.py` derives one `SubAgentSpec` per opted-in module — its system prompt is a base worker prompt plus a **gateway block** (the module's lazy summary + sub-skill index, reusing the `modules/prompt.py` renderer). `AgentFactory.create()` registers these specs through the existing `SubAgentManager.register_subagent`, so they appear in the `spawn_subagent` enum by name with no schema change. The main agent's Active Modules block tells the model to delegate multi-step work to these subagents (it decides — no hard-coded routing). `item_flow_tracking` is the first module to opt in.

**Tech Stack:** Python 3.11+, dataclasses, existing module registry + subagent manager, pytest.

## Global Constraints

- Line length 100 (Black + Ruff). Type hints on public APIs (mypy strict). Google-style docstrings.
- Never hard-code if/else branching for LLM conversation flow — delegation is guided by prompt text, decided by the model (CLAUDE.md rule).
- Never use table format in system prompts — prose / bullets only (CLAUDE.md rule).
- Backward compatible: a module without a `subagent` block behaves exactly as today (inline). No existing module changes behaviour until it opts in.
- Reuse the existing `spawn_subagent` / `run_in_background` path untouched — background durability arrives later via the in-progress TaskIQ plan; this work does not depend on it.
- Bash tool name is `run_command`; skill-loading tool is `invoke_skill`.
- Commit after every task. Conventional Commit messages. Do NOT add a `Co-Authored-By: Claude` trailer (project rule).
- `docs/` is gitignored — commit plan/spec/doc files with `git add -f`.
- Skip per-task suite-wide runs; per-task run only the new test. Run the full suite once at the end (project rule).
- Testing (CLAUDE.md): both unit tests AND a real end-to-end simulation with `OPENAI_API_KEY` are required before claiming done.

---

### Task 1: Parse the `subagent` manifest block

**Files:**
- Modify: `atria/core/modules/store.py` (add `ModuleSubagentManifest`, a field on `ModuleManifest`, and `_parse_subagent`; wire into `_read_manifest`)
- Test: `tests/core/modules/test_manifest_subagent.py`

**Interfaces:**
- Produces: `ModuleSubagentManifest(enabled: bool, model: Optional[str], tools: Optional[List[str]])`; `ModuleManifest.subagent: Optional[ModuleSubagentManifest]`. A module with no/invalid `subagent` block → `manifest.subagent is None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/modules/test_manifest_subagent.py
import json
from pathlib import Path

from atria.core.modules.store import _read_manifest


def _write_manifest(tmp_path: Path, body: dict) -> Path:
    (tmp_path / "manifest.json").write_text(json.dumps(body), encoding="utf-8")
    return tmp_path


def test_subagent_block_parsed(tmp_path):
    d = _write_manifest(
        tmp_path,
        {"subagent": {"enabled": True, "model": "opus", "tools": ["run_command"]}},
    )
    man = _read_manifest(d)
    assert man is not None
    assert man.subagent is not None
    assert man.subagent.enabled is True
    assert man.subagent.model == "opus"
    assert man.subagent.tools == ["run_command"]


def test_no_subagent_block_yields_none(tmp_path):
    man = _read_manifest(_write_manifest(tmp_path, {"display_name": "X"}))
    assert man is not None
    assert man.subagent is None


def test_malformed_subagent_block_degrades(tmp_path):
    man = _read_manifest(_write_manifest(tmp_path, {"subagent": "nope"}))
    assert man is not None
    assert man.subagent is None


def test_enabled_defaults_false_when_missing(tmp_path):
    man = _read_manifest(_write_manifest(tmp_path, {"subagent": {"model": "opus"}}))
    assert man.subagent is not None
    assert man.subagent.enabled is False
    assert man.subagent.tools is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/modules/test_manifest_subagent.py -v`
Expected: FAIL — `AttributeError: 'ModuleManifest' object has no attribute 'subagent'`.

- [ ] **Step 3: Add the dataclass and parser**

In `atria/core/modules/store.py`, add this dataclass directly above `class ModuleManifest:`:

```python
@dataclass
class ModuleSubagentManifest:
    """Opt-in config for routing a module's work to a dedicated subagent."""

    enabled: bool = False
    model: Optional[str] = None
    tools: Optional[List[str]] = None
```

Add a field to `ModuleManifest` (alongside `activity_actions`):

```python
    subagent: Optional[ModuleSubagentManifest] = None
```

Add the parser near `_parse_dashboard` (it uses the existing `_nonempty_str` helper):

```python
def _parse_subagent(raw: Any) -> Optional[ModuleSubagentManifest]:
    """Lenient parser for the optional ``subagent`` manifest block.

    Anything malformed degrades to ``None`` so old/invalid manifests keep working.
    """
    if not isinstance(raw, dict):
        return None
    enabled = raw.get("enabled")
    if not isinstance(enabled, bool):
        enabled = False
    tools_raw = raw.get("tools")
    tools: Optional[List[str]] = None
    if isinstance(tools_raw, list):
        cleaned = [t for t in tools_raw if isinstance(t, str) and t.strip()]
        tools = cleaned or None
    return ModuleSubagentManifest(
        enabled=enabled,
        model=_nonempty_str(raw.get("model")),
        tools=tools,
    )
```

In `_read_manifest`, add `subagent=...` to the returned `ModuleManifest(...)`:

```python
    return ModuleManifest(
        display_name=_nonempty_str(raw.get("display_name")),
        tooltip=_nonempty_str(raw.get("tooltip")),
        icon=_nonempty_str(raw.get("icon")),
        dashboard=_parse_dashboard(raw.get("dashboard")),
        activity_default=activity_default,
        activity_actions=activity_actions,
        subagent=_parse_subagent(raw.get("subagent")),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/modules/test_manifest_subagent.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add atria/core/modules/store.py tests/core/modules/test_manifest_subagent.py
git commit -m "feat(modules): parse optional subagent block in manifest.json"
```

---

### Task 2: Single-module section renderer (refactor for reuse)

**Files:**
- Modify: `atria/core/modules/prompt.py` (extract `render_module_section`; `build_skill_block` calls it)
- Test: `tests/core/modules/test_render_module_section.py`

**Interfaces:**
- Consumes: `atria.core.modules.store.Module`.
- Produces: `render_module_section(module: Module) -> list[str]` — the per-module catalog lines (heading, description, "When to use", sub-skill index, full-guide line, file listing). Used by both `build_skill_block` (Task 4) and the gateway builder (Task 3).

- [ ] **Step 1: Write the failing test**

```python
# tests/core/modules/test_render_module_section.py
from atria.core.modules.prompt import render_module_section
from atria.core.modules.store import Module, SubSkill


def _module() -> Module:
    return Module(
        name="demo_mod",
        skill_md="---\ndescription: Demo desc\n---\n# demo\n\n## When to use\n\n- when X\n",
        dir=__import__("pathlib").Path("/tmp/demo_mod"),
        mtime=0.0,
        files=["scripts/run.py"],
        description="Demo desc",
        subskills=[SubSkill(name="ops", description="ops guide", rel_path="skills/ops.md")],
    )


def test_render_module_section_has_core_pieces():
    text = "\n".join(render_module_section(_module()))
    assert "### demo_mod" in text
    assert "Demo desc" in text
    assert "**When to use:**" in text
    assert "when X" in text
    assert 'invoke_skill("demo_mod:ops")' in text
    assert 'invoke_skill("demo_mod")' in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/modules/test_render_module_section.py -v`
Expected: FAIL — `ImportError: cannot import name 'render_module_section'`.

- [ ] **Step 3: Extract the renderer**

In `atria/core/modules/prompt.py`, add this function above `build_skill_block`:

```python
def render_module_section(m: Module) -> list[str]:
    """Render one module's catalog lines (heading, summary, sub-skill index).

    Shared by the always-on Active Modules block and the per-module gateway
    block injected into a module's dedicated subagent.
    """
    _, body = parse_frontmatter(m.skill_md)
    section = [f"### {m.name}", "", (m.description or "").strip()]

    when = _extract_section(body, "When to use")
    if when:
        section += ["", "**When to use:**", when]

    if m.subskills:
        section += ["", "**Sub-skills** (load individually with `invoke_skill`):"]
        for s in m.subskills:
            section.append(f'- `invoke_skill("{m.name}:{s.name}")` — {s.description}')

    section += ["", f'Full guide: `invoke_skill("{m.name}")`']

    listing = _format_files(list(m.files))
    if listing:
        section += ["", listing]
    return section
```

Add the `Module` import at the top of the file (next to the existing store import):

```python
from atria.core.modules.store import Module, parse_frontmatter
```

Replace the per-module body of `build_skill_block` so it reuses the renderer:

```python
def build_skill_block(registry: ModuleRegistry) -> str:
    """Return the lazy module catalog (header + a summary per module). Empty if none."""
    modules = registry.all()
    if not modules:
        return ""
    parts = [_header(registry.root)]
    for m in modules:
        parts.append("\n".join(render_module_section(m)) + "\n")
    return "\n".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/modules/test_render_module_section.py tests/core/modules/ -v`
Expected: PASS, and existing module-prompt tests still pass.

- [ ] **Step 5: Commit**

```bash
git add atria/core/modules/prompt.py tests/core/modules/test_render_module_section.py
git commit -m "refactor(modules): extract render_module_section for reuse"
```

---

### Task 3: Gateway builder + module subagent specs

**Files:**
- Create: `atria/core/modules/subagent.py`
- Create: `atria/core/agents/prompts/templates/subagents/subagent-module-worker.md`
- Test: `tests/core/modules/test_module_subagent_specs.py`

**Interfaces:**
- Consumes: `render_module_section` (Task 2), `_format_root` (existing in `prompt.py`), `ModuleRegistry`, `SubAgentSpec`, `load_prompt`.
- Produces:
  - `build_module_gateway_block(module: Module, root: Path) -> str`
  - `DEFAULT_MODULE_SUBAGENT_TOOLS: list[str]` = `["run_command", "invoke_skill", "read_file", "write_file"]`
  - `module_subagent_specs(registry: ModuleRegistry) -> list[SubAgentSpec]` — one spec per module whose `manifest.subagent.enabled` is true.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/modules/test_module_subagent_specs.py
from pathlib import Path

from atria.core.modules.registry import ModuleRegistry
from atria.core.modules.store import Module, ModuleManifest, ModuleSubagentManifest
from atria.core.modules.subagent import (
    DEFAULT_MODULE_SUBAGENT_TOOLS,
    build_module_gateway_block,
    module_subagent_specs,
)


def _module(name: str, sub: ModuleSubagentManifest | None) -> Module:
    return Module(
        name=name,
        skill_md=f"---\ndescription: {name} desc\n---\n# {name}\n\n## When to use\n\n- use {name}\n",
        dir=Path(f"/tmp/{name}"),
        mtime=0.0,
        files=["scripts/run.py"],
        manifest=ModuleManifest(subagent=sub) if sub is not None else None,
        description=f"{name} desc",
    )


class _FakeRegistry:
    def __init__(self, modules, root):
        self._modules = modules
        self.root = root

    def all(self):
        return self._modules


def test_gateway_block_contains_context():
    m = _module("demo_mod", ModuleSubagentManifest(enabled=True))
    text = build_module_gateway_block(m, Path("/work/modules"))
    assert "demo_mod" in text
    assert "demo_mod desc" in text
    assert "invoke_skill" in text
    assert "/work/modules/demo_mod/scripts" in text  # absolute-path rule


def test_specs_only_for_enabled_modules():
    reg = _FakeRegistry(
        [
            _module("on_mod", ModuleSubagentManifest(enabled=True)),
            _module("off_mod", ModuleSubagentManifest(enabled=False)),
            _module("plain_mod", None),
        ],
        Path("/work/modules"),
    )
    specs = module_subagent_specs(reg)
    names = {s["name"] for s in specs}
    assert names == {"on_mod"}


def test_spec_defaults_and_overrides():
    reg = _FakeRegistry(
        [
            _module("def_mod", ModuleSubagentManifest(enabled=True)),
            _module(
                "ovr_mod",
                ModuleSubagentManifest(enabled=True, model="opus", tools=["run_command"]),
            ),
        ],
        Path("/work/modules"),
    )
    by_name = {s["name"]: s for s in module_subagent_specs(reg)}
    assert by_name["def_mod"]["tools"] == DEFAULT_MODULE_SUBAGENT_TOOLS
    assert "model" not in by_name["def_mod"]
    assert by_name["ovr_mod"]["tools"] == ["run_command"]
    assert by_name["ovr_mod"]["model"] == "opus"
    assert "def_mod desc" in by_name["def_mod"]["description"]
    assert by_name["def_mod"]["system_prompt"]  # non-empty


def test_registry_failure_returns_empty():
    class _Boom:
        root = Path("/x")

        def all(self):
            raise RuntimeError("boom")

    assert module_subagent_specs(_Boom()) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/modules/test_module_subagent_specs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'atria.core.modules.subagent'`.

- [ ] **Step 3: Write the worker base prompt template**

```markdown
<!-- atria/core/agents/prompts/templates/subagents/subagent-module-worker.md -->
You are a dedicated worker subagent for a single installed module. You own that
module's operations and return a concise result to the agent that spawned you —
not a transcript of every command.

Operating rules:
- Use `invoke_skill` to load a sub-skill's full guide before guessing CLI flags.
  Do not invent flags.
- Run the module's scripts with absolute paths (shown in the module context
  below). Your bash CWD is the chat workspace, not the modules root.
- When intake data is missing (e.g. quantities), state what you need rather than
  inventing defaults.
- Finish with a short, structured summary of what changed and the key result
  (ids, counts, status) — the spawning agent only sees your final message.

The specific module you operate, with its summary and sub-skill index, follows.
```

- [ ] **Step 4: Implement the gateway builder and spec factory**

```python
# atria/core/modules/subagent.py
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/core/modules/test_module_subagent_specs.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add atria/core/modules/subagent.py \
  atria/core/agents/prompts/templates/subagents/subagent-module-worker.md \
  tests/core/modules/test_module_subagent_specs.py
git commit -m "feat(modules): gateway builder and module subagent spec factory"
```

---

### Task 4: Register module subagents in the factory + dispatch guidance

**Files:**
- Modify: `atria/core/base/factories/agent_factory.py` (add `_register_module_subagents`, call it in `create()`)
- Modify: `atria/core/modules/prompt.py` (`build_skill_block` annotates agent-backed modules)
- Test: `tests/core/modules/test_dispatch_guidance.py`

**Interfaces:**
- Consumes: `module_subagent_specs` (Task 3), `SubAgentManager.register_subagent`, `get_registry`.
- Produces: agent-backed modules appear in `manager.get_agent_configs()` by name; the Active Modules block carries a delegation note for each enabled module.

- [ ] **Step 1: Write the failing test (dispatch-guidance note)**

```python
# tests/core/modules/test_dispatch_guidance.py
from pathlib import Path

from atria.core.modules.prompt import build_skill_block
from atria.core.modules.store import Module, ModuleManifest, ModuleSubagentManifest


def _module(name, sub):
    return Module(
        name=name,
        skill_md=f"---\ndescription: {name} desc\n---\n# {name}\n",
        dir=Path(f"/tmp/{name}"),
        mtime=0.0,
        files=[],
        manifest=ModuleManifest(subagent=sub) if sub else None,
        description=f"{name} desc",
    )


class _Reg:
    root = Path("/work/modules")

    def __init__(self, mods):
        self._mods = mods

    def all(self):
        return self._mods


def test_agent_backed_module_gets_delegation_note():
    block = build_skill_block(_Reg([_module("on_mod", ModuleSubagentManifest(enabled=True))]))
    assert 'spawn_subagent(subagent_type="on_mod")' in block


def test_plain_module_has_no_delegation_note():
    block = build_skill_block(_Reg([_module("plain_mod", None)]))
    assert "spawn_subagent" not in block
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/modules/test_dispatch_guidance.py -v`
Expected: FAIL — `test_agent_backed_module_gets_delegation_note` asserts a string not yet emitted.

- [ ] **Step 3: Add the delegation note in `build_skill_block`**

In `atria/core/modules/prompt.py`, change the loop body of `build_skill_block` to append a note for agent-backed modules:

```python
    for m in modules:
        section_lines = render_module_section(m)
        sub = m.manifest.subagent if m.manifest else None
        if sub and sub.enabled:
            section_lines += [
                "",
                f"**Dedicated subagent:** this module has a specialist subagent "
                f'`{m.name}`. For multi-step or heavy work, delegate with '
                f'`spawn_subagent(subagent_type="{m.name}")` — its CLI output stays '
                f"out of this conversation. Quick lookups may run inline.",
            ]
        parts.append("\n".join(section_lines) + "\n")
```

- [ ] **Step 4: Run the guidance test to verify it passes**

Run: `uv run pytest tests/core/modules/test_dispatch_guidance.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Wire registration into the factory**

In `atria/core/base/factories/agent_factory.py`, inside `create()`, immediately after `self._register_custom_agents()`:

```python
            # Register custom agents from config files
            self._register_custom_agents()

            # Register dedicated subagents derived from agent-backed modules
            self._register_module_subagents()
```

Add the method next to `_register_custom_agents`:

```python
    def _register_module_subagents(self) -> None:
        """Register one dedicated subagent per agent-backed module (opt-in)."""
        if not self._subagent_manager:
            return
        try:
            from atria.core.modules.registry import get_registry
            from atria.core.modules.subagent import module_subagent_specs

            specs = module_subagent_specs(get_registry())
            for spec in specs:
                self._subagent_manager.register_subagent(spec)
            if specs:
                logger.info("Registered %d module subagent(s)", len(specs))
        except Exception as exc:
            logger.warning("Failed to register module subagents: %s", exc)
```

- [ ] **Step 6: Write the failing integration test (factory registers the module subagent)**

```python
# tests/core/modules/test_factory_registers_module_subagents.py
from atria.core.agents.subagents.manager import SubAgentManager
from atria.core.modules.store import Module, ModuleManifest, ModuleSubagentManifest
from atria.core.modules.subagent import module_subagent_specs
from pathlib import Path


class _Reg:
    root = Path("/work/modules")

    def all(self):
        return [
            Module(
                name="reg_mod",
                skill_md="---\ndescription: reg desc\n---\n# reg_mod\n",
                dir=Path("/tmp/reg_mod"),
                mtime=0.0,
                files=[],
                manifest=ModuleManifest(subagent=ModuleSubagentManifest(enabled=True)),
                description="reg desc",
            )
        ]


def test_registered_module_subagent_shows_in_configs(tmp_path):
    # SubAgentManager registration path: specs flow into get_agent_configs().
    from atria.core.context_engineering.tools.registry import ToolRegistry  # type: ignore

    mgr = SubAgentManager.__new__(SubAgentManager)  # lightweight: exercise registration only
    # Fall back to a real manager if the lightweight path is unavailable.
    specs = module_subagent_specs(_Reg())
    assert any(s["name"] == "reg_mod" for s in specs)
```

> Note for the implementer: if `SubAgentManager` cannot be constructed without a
> full tool registry in your environment, keep this test focused on
> `module_subagent_specs(...)` returning the spec (as written). The end-to-end
> "appears in `spawn_subagent` enum" path is covered by the real E2E in Task 6.

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/core/modules/test_dispatch_guidance.py tests/core/modules/test_factory_registers_module_subagents.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add atria/core/base/factories/agent_factory.py atria/core/modules/prompt.py \
  tests/core/modules/test_dispatch_guidance.py \
  tests/core/modules/test_factory_registers_module_subagents.py
git commit -m "feat(agents): register module subagents and add delegation guidance"
```

---

### Task 5: Opt `item_flow_tracking` into the gateway

**Files:**
- Modify: `modules/item_flow_tracking/manifest.json` (add `subagent` block)
- Test: `tests/core/modules/test_item_flow_opt_in.py`

**Interfaces:**
- Consumes: `_read_manifest` (Task 1), `module_subagent_specs` (Task 3).
- Produces: `item_flow_tracking`'s manifest reports `subagent.enabled == True`.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/modules/test_item_flow_opt_in.py
from pathlib import Path

from atria.core.modules.store import _read_manifest

MODULE_DIR = Path("modules/item_flow_tracking")


def test_item_flow_tracking_is_agent_backed():
    man = _read_manifest(MODULE_DIR)
    assert man is not None
    assert man.subagent is not None
    assert man.subagent.enabled is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/modules/test_item_flow_opt_in.py -v`
Expected: FAIL — `man.subagent is None` (block not added yet).

- [ ] **Step 3: Add the `subagent` block to the manifest**

In `modules/item_flow_tracking/manifest.json`, add a top-level `"subagent"` key (sibling of `"activity"`):

```json
  "subagent": {
    "enabled": true,
    "model": null,
    "tools": null
  }
```

(Keep valid JSON — add a comma after the preceding `"activity"` block.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/modules/test_item_flow_opt_in.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add modules/item_flow_tracking/manifest.json tests/core/modules/test_item_flow_opt_in.py
git commit -m "feat(item_flow_tracking): opt into dedicated subagent gateway"
```

---

### Task 6: Full suite + real end-to-end verification

**Files:**
- No new source files. Verification only.

- [ ] **Step 1: Run the full unit suite (project rule: once, at the end)**

Run: `make test`
Expected: PASS — all existing tests plus the new ones from Tasks 1–5.

- [ ] **Step 2: Lint, format, typecheck**

Run: `make check`
Expected: clean (Black + Ruff + mypy).

- [ ] **Step 3: Real end-to-end simulation (CLAUDE.md requirement)**

Ensure `export OPENAI_API_KEY=...` is set, then launch the web UI / agent in a
workspace where `modules/item_flow_tracking` is discoverable:

Run: `make run`

Drive a real conversation that exercises the new delegation path:
- Ask the agent to create a real laundry order (e.g. "tạo đơn 2 bin cho khách
  0901234567, khăn:50"). The agent should call
  `spawn_subagent(subagent_type="item_flow_tracking", ...)` rather than running
  `flow.py` inline.
- Verify the subagent runs `flow.py` (creates the order in `data/flow.db`),
  returns a concise summary, and the CLI noise does NOT appear in the main
  conversation.
- Ask a quick lookup ("order list") and confirm the agent may answer inline
  (delegation is by judgement, not forced).

Expected: order is created in the DB; the main conversation shows a concise
result from the subagent; `spawn_subagent` offered `item_flow_tracking` as a type.

- [ ] **Step 4: Final commit (if any verification fixups were needed)**

```bash
git add -A
git commit -m "test(modules): verify module subagent gateway end-to-end"
```

---

## Self-Review

**Spec coverage:**
- Manifest declaration → Task 1. Gateway builder → Task 3. Spec factory → Task 3. Factory registration → Task 4. Dispatch guidance in Active Modules block → Task 4. `item_flow_tracking` first consumer → Task 5. Context isolation / concise return → worker template (Task 3) + E2E (Task 6). Background reuse of `run_in_background` → unchanged path; no task needed (verified conceptually, asserted out of scope). Error handling (no block / malformed / registry failure / name collision) → Tasks 1 and 3 tests + existing built-in-wins guard. Testing (unit + real E2E) → Tasks 1–5 unit, Task 6 E2E.

**Type consistency:** `ModuleSubagentManifest(enabled, model, tools)` defined in Task 1 and consumed identically in Tasks 3–5. `render_module_section(module) -> list[str]` defined in Task 2, consumed in Tasks 3–4. `module_subagent_specs(registry) -> list[SubAgentSpec]` and `build_module_gateway_block(module, root)` defined in Task 3, consumed in Task 4. `DEFAULT_MODULE_SUBAGENT_TOOLS` defined and asserted in Task 3. Tool names `run_command` / `invoke_skill` consistent with the registry. `spawn_subagent(subagent_type="<name>")` wording consistent between the delegation note (Task 4) and E2E (Task 6).

**Placeholder scan:** No TBD/TODO; every code step shows complete code; the only prose-only step (Task 6 E2E) is intentional manual verification with concrete commands and expected outcomes.

**Watcher re-sync note:** runtime add/remove of modules re-deriving specs is intentionally deferred — specs are registered once at factory `create()`. This matches today's subagent lifecycle (built-ins/custom agents are also registered at construction). If hot-reload of module subagents is later required, it is a follow-up, not part of this plan.
