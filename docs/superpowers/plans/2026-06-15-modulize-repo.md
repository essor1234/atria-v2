# Modulize Repo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the "skill" concept into a first-class **Module** abstraction (Skill markdown + Python Tools + composable Tasks) that is fully configurable through the Web UI.

**Architecture:** New `atria/core/modules/` package owns runtime (ToolRegistry, ModuleLoader, TaskExecutor). Five new PostgreSQL tables persist modules/skills/tools/tasks/task_runs via SQLAlchemy ORM. FastAPI routes under `/api/modules` expose CRUD + test-run. Web UI gets a Modules page with Skill / Tools / Tasks tabs, plus a linear-list Task editor. The agent layer surfaces a flat list of "callables" (Tools and Tasks share one interface) and injects `skill_md` into the system prompt.

**Tech Stack:** Python 3 + SQLAlchemy 2.0 (async) + FastAPI + PostgreSQL + Pydantic + Jinja2 (sandbox) + React/Vite + Zustand + CodeMirror. Tests: pytest (async).

**Project memory:** Per `MEMORY.md` ([[feedback_skip_per_task_tests]]) we **do not** run pytest per task. Each implementation task writes test code alongside source. A single final task runs `make test` and `make check` once.

---

## File Structure

```
atria/
  db/
    models.py                            # MODIFY: add Module, ModuleSkill, ModuleTool, ModuleTask, TaskRun; add Conversation.active_module_id
    repositories/
      modules_repo.py                    # NEW: async CRUD repository
  core/
    modules/                             # NEW package
      __init__.py                        # imports builtins so @register_tool runs
      registry.py                        # @register_tool decorator + ToolRegistry
      models.py                          # Module, ToolCallable, TaskCallable, ToolSpec dataclasses
      loader.py                          # ModuleLoader (DB rows -> runtime Module, cached)
      seed.py                            # idempotent built-in seeding
      executor/
        __init__.py
        templating.py                    # Jinja2 sandbox render
        validation.py                    # graph validation (cycles, dangling, unknown node)
        task_executor.py                 # walks the Task graph, writes task_runs
        nodes/
          __init__.py
          llm_node.py
          tool_node.py
      builtins/
        __init__.py
        deep_analyze/
          __init__.py
          tools.py                       # registered Python tools
          seed/
            skill.md                     # copied verbatim from old SKILL.md
            tasks/
              extract_and_lookup.json    # one seeded task example
    agents/
      main_agent.py                      # MODIFY: ask loader for callables, append skill_md prompt
      prompts/
        composition.py                   # MODIFY: register 'module_skill' section
  web/
    routes/
      modules.py                         # NEW: REST endpoints
    __init__.py (or main router file)    # MODIFY: include modules.router
  serve.py                               # MODIFY: call seed() on startup

web-ui/src/pages/modules/
  ModulesListPage.tsx                    # NEW
  ModuleDetailPage.tsx                   # NEW (tabs)
  TaskEditorPage.tsx                     # NEW (linear list editor)
  api.ts                                 # NEW (typed fetch helpers)
  types.ts                               # NEW (shared TS types)

tests/core/modules/
  test_registry.py
  test_templating.py
  test_validation.py
  test_task_executor.py
  test_loader.py
  test_seed.py
  test_modules_repo.py
  test_modules_api.py
  test_agent_integration.py
```

---

## Task 1: Add ORM models for modules schema

**Files:**
- Modify: `atria/db/models.py` (append at end of file)

- [ ] **Step 1: Append new ORM models**

Add to the bottom of `atria/db/models.py`:

```python
class Module(Base):
    __tablename__ = "modules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    skill: Mapped[Optional["ModuleSkill"]] = relationship(
        "ModuleSkill", back_populates="module", uselist=False, cascade="all, delete-orphan"
    )
    tools: Mapped[list["ModuleTool"]] = relationship(
        "ModuleTool", back_populates="module", cascade="all, delete-orphan"
    )
    tasks: Mapped[list["ModuleTask"]] = relationship(
        "ModuleTask", back_populates="module", cascade="all, delete-orphan"
    )


class ModuleSkill(Base):
    __tablename__ = "module_skills"

    module_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("modules.id", ondelete="CASCADE"), primary_key=True
    )
    content_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    module: Mapped["Module"] = relationship("Module", back_populates="skill")


class ModuleTool(Base):
    __tablename__ = "module_tools"
    __table_args__ = (
        Index("uq_module_tool_registry", "module_id", "registry_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("modules.id", ondelete="CASCADE"), nullable=False
    )
    registry_id: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    module: Mapped["Module"] = relationship("Module", back_populates="tools")


class ModuleTask(Base):
    __tablename__ = "module_tasks"
    __table_args__ = (
        Index("uq_module_task_name", "module_id", "name", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("modules.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    graph_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    module: Mapped["Module"] = relationship("Module", back_populates="tasks")


class TaskRun(Base):
    __tablename__ = "task_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("module_tasks.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(10), nullable=False)  # 'ok' | 'error'
    inputs_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    outputs_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
```

- [ ] **Step 2: Add `active_module_id` to the existing `Conversation` model**

Locate `class Conversation(Base):` in the same file. Add this column alongside the existing ones:

```python
    active_module_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("modules.id", ondelete="SET NULL"), nullable=True
    )
```

- [ ] **Step 3: Commit**

```bash
git add atria/db/models.py
git commit -m "feat(modules): add ORM models for modules, skill, tools, tasks, runs"
```

---

## Task 2: ToolRegistry with decorator-based registration

**Files:**
- Create: `atria/core/modules/__init__.py`
- Create: `atria/core/modules/registry.py`
- Create: `tests/core/modules/__init__.py`
- Create: `tests/core/modules/test_registry.py`

- [ ] **Step 1: Create `atria/core/modules/__init__.py`**

```python
"""Modules subsystem: registry, loader, task executor, builtins.

Importing this package triggers built-in tool registration as a side effect
of importing `atria.core.modules.builtins`.
"""

from atria.core.modules import builtins  # noqa: F401  (side-effect: register tools)
from atria.core.modules.registry import ToolRegistry, register_tool

__all__ = ["ToolRegistry", "register_tool"]
```

- [ ] **Step 2: Create `atria/core/modules/registry.py`**

```python
"""Process-wide registry of Python-implemented tools available to modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional


ToolFn = Callable[..., Any]
AsyncToolFn = Callable[..., Awaitable[Any]]


@dataclass
class ToolSpec:
    """Metadata + callable for a registered tool."""

    id: str
    description: str
    fn: ToolFn
    input_schema: Dict[str, Any] = field(default_factory=dict)
    display_name: Optional[str] = None
    is_async: bool = False


class ToolRegistry:
    """Singleton registry; populated by @register_tool at import time."""

    _instance: Optional["ToolRegistry"] = None

    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    @classmethod
    def instance(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, spec: ToolSpec) -> None:
        if spec.id in self._tools:
            raise ValueError(f"Tool already registered: {spec.id}")
        self._tools[spec.id] = spec

    def get(self, tool_id: str) -> ToolSpec:
        if tool_id not in self._tools:
            raise KeyError(f"Tool not registered: {tool_id}")
        return self._tools[tool_id]

    def has(self, tool_id: str) -> bool:
        return tool_id in self._tools

    def list(self) -> List[ToolSpec]:
        return list(self._tools.values())

    def clear(self) -> None:
        """Test-only helper."""
        self._tools.clear()


def register_tool(
    *,
    id: str,
    description: str,
    input_schema: Optional[Dict[str, Any]] = None,
    display_name: Optional[str] = None,
) -> Callable[[ToolFn], ToolFn]:
    """Decorator to register a Python function as a module tool."""

    import inspect

    def decorator(fn: ToolFn) -> ToolFn:
        spec = ToolSpec(
            id=id,
            description=description,
            fn=fn,
            input_schema=input_schema or {},
            display_name=display_name or id,
            is_async=inspect.iscoroutinefunction(fn),
        )
        ToolRegistry.instance().register(spec)
        return fn

    return decorator
```

- [ ] **Step 3: Create `tests/core/modules/__init__.py`** (empty file)

```python
```

- [ ] **Step 4: Create `tests/core/modules/test_registry.py`**

```python
import pytest

from atria.core.modules.registry import ToolRegistry, register_tool


@pytest.fixture(autouse=True)
def _clean_registry():
    ToolRegistry.instance().clear()
    yield
    ToolRegistry.instance().clear()


def test_register_tool_adds_spec():
    @register_tool(id="t.echo", description="echoes")
    def echo(text: str) -> str:
        return text

    spec = ToolRegistry.instance().get("t.echo")
    assert spec.id == "t.echo"
    assert spec.description == "echoes"
    assert spec.fn("hi") == "hi"
    assert spec.is_async is False


def test_duplicate_registration_raises():
    @register_tool(id="t.dup", description="x")
    def a() -> None: ...

    with pytest.raises(ValueError):
        @register_tool(id="t.dup", description="y")
        def b() -> None: ...


def test_async_tool_detected():
    @register_tool(id="t.async", description="x")
    async def a() -> int:
        return 1

    assert ToolRegistry.instance().get("t.async").is_async is True


def test_has_and_list():
    @register_tool(id="t.a", description="x")
    def a() -> None: ...

    assert ToolRegistry.instance().has("t.a") is True
    assert ToolRegistry.instance().has("t.z") is False
    ids = [s.id for s in ToolRegistry.instance().list()]
    assert "t.a" in ids
```

- [ ] **Step 5: Commit**

```bash
git add atria/core/modules/__init__.py atria/core/modules/registry.py tests/core/modules/__init__.py tests/core/modules/test_registry.py
git commit -m "feat(modules): ToolRegistry with @register_tool decorator"
```

---

## Task 3: Jinja2 sandbox templating helper

**Files:**
- Create: `atria/core/modules/executor/__init__.py`
- Create: `atria/core/modules/executor/templating.py`
- Create: `tests/core/modules/test_templating.py`

- [ ] **Step 1: Create `atria/core/modules/executor/__init__.py`** (empty)

```python
```

- [ ] **Step 2: Create `atria/core/modules/executor/templating.py`**

```python
"""Sandboxed Jinja2 templating used by Task graphs."""

from __future__ import annotations

from typing import Any, Mapping

from jinja2.sandbox import SandboxedEnvironment


_env = SandboxedEnvironment(
    autoescape=False,
    keep_trailing_newline=True,
)


class TemplateError(Exception):
    """Raised when a template fails to render."""


def render(template: str, ctx: Mapping[str, Any]) -> str:
    """Render `template` against `ctx` using a sandboxed Jinja2 env."""
    try:
        return _env.from_string(template).render(**ctx)
    except Exception as exc:  # pragma: no cover - re-raised as TemplateError
        raise TemplateError(str(exc)) from exc


def render_value(value: Any, ctx: Mapping[str, Any]) -> Any:
    """Render `value` if it is a string template; otherwise pass through.

    Recurses into dict and list so callers can map node inputs declaratively.
    """
    if isinstance(value, str):
        if "{{" in value or "{%" in value:
            return render(value, ctx)
        return value
    if isinstance(value, dict):
        return {k: render_value(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [render_value(v, ctx) for v in value]
    return value
```

- [ ] **Step 3: Create `tests/core/modules/test_templating.py`**

```python
from atria.core.modules.executor.templating import render, render_value


def test_render_simple_variable():
    assert render("hello {{name}}", {"name": "ada"}) == "hello ada"


def test_render_value_passes_through_non_template_string():
    assert render_value("plain", {"x": 1}) == "plain"


def test_render_value_dict_and_list_recursion():
    ctx = {"x": "v"}
    out = render_value(
        {"a": "{{x}}", "b": ["{{x}}", "y"]},
        ctx,
    )
    assert out == {"a": "v", "b": ["v", "y"]}


def test_render_value_pass_through_non_strings():
    assert render_value(42, {}) == 42
    assert render_value(None, {}) is None
```

- [ ] **Step 4: Commit**

```bash
git add atria/core/modules/executor/__init__.py atria/core/modules/executor/templating.py tests/core/modules/test_templating.py
git commit -m "feat(modules): Jinja2 sandbox templating helper"
```

---

## Task 4: Task graph validation

**Files:**
- Create: `atria/core/modules/executor/validation.py`
- Create: `tests/core/modules/test_validation.py`

- [ ] **Step 1: Create `atria/core/modules/executor/validation.py`**

```python
"""Validate Task `graph_json` shape: known node types, no cycles, edges resolved."""

from __future__ import annotations

from typing import Any, Dict, List, Set


SUPPORTED_NODE_TYPES = {"llm", "tool"}


class TaskValidationError(Exception):
    """Raised when a Task graph is structurally invalid."""

    def __init__(self, message: str, *, node_id: str | None = None) -> None:
        super().__init__(message)
        self.node_id = node_id


def validate(graph: Dict[str, Any]) -> None:
    """Raise TaskValidationError if `graph` cannot be safely executed."""

    nodes = graph.get("nodes")
    edges = graph.get("edges", [])
    if not isinstance(nodes, list) or not nodes:
        raise TaskValidationError("graph.nodes must be a non-empty list")
    if not isinstance(edges, list):
        raise TaskValidationError("graph.edges must be a list")

    node_ids: Set[str] = set()
    for node in nodes:
        nid = node.get("id")
        if not nid or not isinstance(nid, str):
            raise TaskValidationError("each node must have a string `id`")
        if nid in node_ids:
            raise TaskValidationError(f"duplicate node id: {nid}", node_id=nid)
        node_ids.add(nid)
        ntype = node.get("type")
        if ntype not in SUPPORTED_NODE_TYPES:
            raise TaskValidationError(
                f"unsupported node type: {ntype!r}", node_id=nid
            )
        if ntype == "llm" and not node.get("prompt"):
            raise TaskValidationError("llm node missing `prompt`", node_id=nid)
        if ntype == "tool" and not node.get("registry_id"):
            raise TaskValidationError("tool node missing `registry_id`", node_id=nid)

    adj: Dict[str, List[str]] = {nid: [] for nid in node_ids}
    for edge in edges:
        f, t = edge.get("from"), edge.get("to")
        if f not in node_ids or t not in node_ids:
            raise TaskValidationError(f"edge references unknown node: {edge}")
        adj[f].append(t)

    _ensure_acyclic(adj)


def _ensure_acyclic(adj: Dict[str, List[str]]) -> None:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in adj}

    def visit(n: str) -> None:
        if color[n] == GRAY:
            raise TaskValidationError(f"cycle detected at node {n}", node_id=n)
        if color[n] == BLACK:
            return
        color[n] = GRAY
        for m in adj[n]:
            visit(m)
        color[n] = BLACK

    for n in adj:
        visit(n)


def topological_order(graph: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return nodes in dependency order. Assumes `validate(graph)` already passed."""

    nodes_by_id = {n["id"]: n for n in graph["nodes"]}
    indeg = {nid: 0 for nid in nodes_by_id}
    succ: Dict[str, List[str]] = {nid: [] for nid in nodes_by_id}
    for edge in graph.get("edges", []):
        indeg[edge["to"]] += 1
        succ[edge["from"]].append(edge["to"])

    ready = [nid for nid, d in indeg.items() if d == 0]
    order: List[str] = []
    while ready:
        nid = ready.pop(0)
        order.append(nid)
        for m in succ[nid]:
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)

    return [nodes_by_id[nid] for nid in order]
```

- [ ] **Step 2: Create `tests/core/modules/test_validation.py`**

```python
import pytest

from atria.core.modules.executor.validation import (
    TaskValidationError,
    topological_order,
    validate,
)


def _graph(nodes, edges=None):
    return {"nodes": nodes, "edges": edges or [], "output": ""}


def test_valid_linear_graph_passes():
    g = _graph(
        [
            {"id": "a", "type": "llm", "prompt": "x"},
            {"id": "b", "type": "tool", "registry_id": "t.x"},
        ],
        [{"from": "a", "to": "b"}],
    )
    validate(g)
    assert [n["id"] for n in topological_order(g)] == ["a", "b"]


def test_empty_nodes_rejected():
    with pytest.raises(TaskValidationError):
        validate(_graph([]))


def test_duplicate_node_id_rejected():
    with pytest.raises(TaskValidationError):
        validate(_graph([
            {"id": "a", "type": "llm", "prompt": "x"},
            {"id": "a", "type": "llm", "prompt": "y"},
        ]))


def test_unknown_node_type_rejected():
    with pytest.raises(TaskValidationError):
        validate(_graph([{"id": "a", "type": "branch"}]))


def test_llm_node_requires_prompt():
    with pytest.raises(TaskValidationError):
        validate(_graph([{"id": "a", "type": "llm"}]))


def test_tool_node_requires_registry_id():
    with pytest.raises(TaskValidationError):
        validate(_graph([{"id": "a", "type": "tool"}]))


def test_edge_to_unknown_node_rejected():
    with pytest.raises(TaskValidationError):
        validate(_graph(
            [{"id": "a", "type": "llm", "prompt": "x"}],
            [{"from": "a", "to": "zzz"}],
        ))


def test_cycle_detected():
    g = _graph(
        [
            {"id": "a", "type": "llm", "prompt": "x"},
            {"id": "b", "type": "llm", "prompt": "y"},
        ],
        [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}],
    )
    with pytest.raises(TaskValidationError, match="cycle"):
        validate(g)
```

- [ ] **Step 3: Commit**

```bash
git add atria/core/modules/executor/validation.py tests/core/modules/test_validation.py
git commit -m "feat(modules): graph validation and topological order"
```

---

## Task 5: Node runners (LLM + Tool) and base-model client abstraction

**Files:**
- Create: `atria/core/modules/executor/nodes/__init__.py`
- Create: `atria/core/modules/executor/nodes/llm_node.py`
- Create: `atria/core/modules/executor/nodes/tool_node.py`
- Create: `tests/core/modules/test_nodes.py`

- [ ] **Step 1: Create `atria/core/modules/executor/nodes/__init__.py`**

```python
from atria.core.modules.executor.nodes.llm_node import LlmNode
from atria.core.modules.executor.nodes.tool_node import ToolNode

NODE_TYPES = {
    "llm": LlmNode,
    "tool": ToolNode,
}

__all__ = ["LlmNode", "ToolNode", "NODE_TYPES"]
```

- [ ] **Step 2: Create `atria/core/modules/executor/nodes/llm_node.py`**

```python
"""LLM node runner. Calls the global base-model client with a rendered prompt."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Mapping

from atria.core.modules.executor.templating import render


# Type for the injected base-model client. Returns the model's text completion.
LlmClient = Callable[[str], Awaitable[str]]


class LlmNode:
    """Runner for `type: "llm"` nodes."""

    @staticmethod
    async def run(
        node: Dict[str, Any],
        ctx: Mapping[str, Any],
        *,
        llm_client: LlmClient,
    ) -> str:
        prompt = render(node["prompt"], ctx)
        return await llm_client(prompt)
```

- [ ] **Step 3: Create `atria/core/modules/executor/nodes/tool_node.py`**

```python
"""Tool node runner. Looks up a registered Python tool and invokes it."""

from __future__ import annotations

import inspect
from typing import Any, Dict, Mapping

from atria.core.modules.executor.templating import render_value
from atria.core.modules.registry import ToolRegistry


class ToolNode:
    """Runner for `type: "tool"` nodes."""

    @staticmethod
    async def run(
        node: Dict[str, Any],
        ctx: Mapping[str, Any],
        *,
        llm_client: Any = None,  # unused; signature parity with LlmNode
    ) -> Any:
        spec = ToolRegistry.instance().get(node["registry_id"])
        inputs = render_value(node.get("inputs", {}), ctx)
        if not isinstance(inputs, dict):
            raise TypeError(
                f"tool node {node['id']!r} inputs must render to a dict, got {type(inputs)}"
            )
        result = spec.fn(**inputs)
        if inspect.isawaitable(result):
            result = await result
        return result
```

- [ ] **Step 4: Create `tests/core/modules/test_nodes.py`**

```python
import pytest

from atria.core.modules.executor.nodes import LlmNode, ToolNode
from atria.core.modules.registry import ToolRegistry, register_tool


@pytest.fixture(autouse=True)
def _clean_registry():
    ToolRegistry.instance().clear()
    yield
    ToolRegistry.instance().clear()


@pytest.mark.asyncio
async def test_llm_node_renders_prompt_and_calls_client():
    seen = {}

    async def client(prompt: str) -> str:
        seen["prompt"] = prompt
        return "RESPONSE"

    out = await LlmNode.run(
        {"id": "n1", "type": "llm", "prompt": "hello {{name}}"},
        {"name": "ada"},
        llm_client=client,
    )
    assert out == "RESPONSE"
    assert seen["prompt"] == "hello ada"


@pytest.mark.asyncio
async def test_tool_node_invokes_sync_tool_with_rendered_inputs():
    @register_tool(id="t.concat", description="concat")
    def concat(a: str, b: str) -> str:
        return a + b

    out = await ToolNode.run(
        {"id": "n1", "type": "tool", "registry_id": "t.concat",
         "inputs": {"a": "{{x}}", "b": "{{y}}"}},
        {"x": "hi-", "y": "there"},
    )
    assert out == "hi-there"


@pytest.mark.asyncio
async def test_tool_node_invokes_async_tool():
    @register_tool(id="t.aecho", description="aecho")
    async def aecho(text: str) -> str:
        return text + "!"

    out = await ToolNode.run(
        {"id": "n1", "type": "tool", "registry_id": "t.aecho", "inputs": {"text": "hi"}},
        {},
    )
    assert out == "hi!"


@pytest.mark.asyncio
async def test_tool_node_rejects_non_dict_inputs():
    @register_tool(id="t.noop", description="noop")
    def noop() -> int:
        return 0

    with pytest.raises(TypeError):
        await ToolNode.run(
            {"id": "n1", "type": "tool", "registry_id": "t.noop", "inputs": "not-a-dict"},
            {},
        )
```

- [ ] **Step 5: Commit**

```bash
git add atria/core/modules/executor/nodes/ tests/core/modules/test_nodes.py
git commit -m "feat(modules): LLM and Tool node runners"
```

---

## Task 6: TaskExecutor

**Files:**
- Create: `atria/core/modules/executor/task_executor.py`
- Create: `tests/core/modules/test_task_executor.py`

- [ ] **Step 1: Create `atria/core/modules/executor/task_executor.py`**

```python
"""Walks a Task graph and produces a final output."""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from atria.core.modules.executor.nodes import NODE_TYPES
from atria.core.modules.executor.templating import render_value
from atria.core.modules.executor.validation import (
    TaskValidationError,
    topological_order,
    validate,
)
from atria.db.models import TaskRun


LlmClient = Callable[[str], Awaitable[str]]


class TaskExecutor:
    """Executes a Task graph and records a `task_runs` row."""

    def __init__(
        self,
        *,
        llm_client: LlmClient,
        sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None,
    ) -> None:
        self._llm = llm_client
        self._sessionmaker = sessionmaker

    async def execute(
        self,
        graph: Dict[str, Any],
        inputs: Mapping[str, Any],
        *,
        task_id: Optional[int] = None,
    ) -> Any:
        validate(graph)
        ctx: Dict[str, Any] = {"input": dict(inputs)}
        start = time.monotonic()
        error: Optional[str] = None
        output: Any = None
        try:
            for node in topological_order(graph):
                runner = NODE_TYPES[node["type"]]
                result = await runner.run(node, ctx, llm_client=self._llm)
                out_var = node.get("output_var")
                if out_var:
                    ctx[node["id"]] = {out_var: result}
                else:
                    ctx[node["id"]] = result
            output_template = graph.get("output", "")
            output = render_value(output_template, ctx) if output_template else ctx
            return output
        except TaskValidationError as exc:
            error = f"validation: {exc}"
            raise
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            if task_id is not None and self._sessionmaker is not None:
                await self._record_run(
                    task_id=task_id,
                    inputs=dict(inputs),
                    output=output,
                    error=error,
                    duration_ms=int((time.monotonic() - start) * 1000),
                )

    async def _record_run(
        self,
        *,
        task_id: int,
        inputs: Dict[str, Any],
        output: Any,
        error: Optional[str],
        duration_ms: int,
    ) -> None:
        async with self._sessionmaker() as session:
            run = TaskRun(
                task_id=task_id,
                status="error" if error else "ok",
                inputs_json=inputs,
                outputs_json={"value": output} if output is not None else None,
                error=error,
                duration_ms=duration_ms,
            )
            session.add(run)
            await session.commit()
```

- [ ] **Step 2: Create `tests/core/modules/test_task_executor.py`**

```python
import pytest

from atria.core.modules.executor.task_executor import TaskExecutor
from atria.core.modules.registry import ToolRegistry, register_tool


@pytest.fixture(autouse=True)
def _clean_registry():
    ToolRegistry.instance().clear()
    yield
    ToolRegistry.instance().clear()


@pytest.mark.asyncio
async def test_executor_runs_two_node_chain():
    @register_tool(id="t.upper", description="upper")
    def upper(text: str) -> str:
        return text.upper()

    async def llm(prompt: str) -> str:
        return f"echo:{prompt}"

    graph = {
        "nodes": [
            {"id": "n1", "type": "llm", "prompt": "hi {{input.name}}", "output_var": "v"},
            {"id": "n2", "type": "tool", "registry_id": "t.upper",
             "inputs": {"text": "{{n1.v}}"}, "output_var": "v"},
        ],
        "edges": [{"from": "n1", "to": "n2"}],
        "output": "{{n2.v}}",
    }
    executor = TaskExecutor(llm_client=llm)
    result = await executor.execute(graph, {"name": "ada"})
    assert result == "ECHO:HI ADA"


@pytest.mark.asyncio
async def test_executor_propagates_validation_error():
    async def llm(prompt: str) -> str:
        return ""

    graph = {"nodes": [], "edges": [], "output": ""}
    executor = TaskExecutor(llm_client=llm)
    with pytest.raises(Exception):
        await executor.execute(graph, {})
```

- [ ] **Step 3: Commit**

```bash
git add atria/core/modules/executor/task_executor.py tests/core/modules/test_task_executor.py
git commit -m "feat(modules): TaskExecutor with task_runs recording"
```

---

## Task 7: Module dataclasses + ModuleLoader

**Files:**
- Create: `atria/core/modules/models.py`
- Create: `atria/core/modules/loader.py`
- Create: `tests/core/modules/test_loader.py`

- [ ] **Step 1: Create `atria/core/modules/models.py`**

```python
"""Runtime dataclasses for loaded modules (distinct from ORM models)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional


InvokeFn = Callable[[Dict[str, Any]], Awaitable[Any]]


@dataclass
class Callable_:  # underscore avoids shadowing typing.Callable
    """Shared shape for both Tool-backed and Task-backed callables."""

    name: str
    description: str
    input_schema: Dict[str, Any]
    invoke: InvokeFn
    kind: str  # 'tool' | 'task'
    source_id: int = 0  # ModuleTool.id or ModuleTask.id


@dataclass
class LoadedModule:
    """Runtime view of a Module row + its skill + callables."""

    id: int
    name: str
    skill_md: str
    callables: List[Callable_] = field(default_factory=list)
    missing_tool_ids: List[str] = field(default_factory=list)
```

- [ ] **Step 2: Create `atria/core/modules/loader.py`**

```python
"""Reads a Module from the DB and returns a runtime LoadedModule."""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from sqlalchemy.orm import selectinload

from atria.core.modules.executor.task_executor import TaskExecutor
from atria.core.modules.models import Callable_, LoadedModule
from atria.core.modules.registry import ToolRegistry
from atria.db.models import Module


LlmClient = Callable[[str], Awaitable[str]]


class ModuleLoader:
    """Loads modules lazily and caches them until invalidated."""

    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        llm_client: LlmClient,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._llm = llm_client
        self._cache: Dict[int, LoadedModule] = {}

    def invalidate(self, module_id: int) -> None:
        self._cache.pop(module_id, None)

    def invalidate_all(self) -> None:
        self._cache.clear()

    async def load(self, module_id: int) -> LoadedModule:
        if module_id in self._cache:
            return self._cache[module_id]

        async with self._sessionmaker() as session:
            stmt = (
                select(Module)
                .options(
                    selectinload(Module.skill),
                    selectinload(Module.tools),
                    selectinload(Module.tasks),
                )
                .where(Module.id == module_id, Module.enabled.is_(True))
            )
            row = (await session.execute(stmt)).scalar_one_or_none()

        if row is None:
            raise KeyError(f"Module not found or disabled: {module_id}")

        return self._build(row)

    def _build(self, row: Module) -> LoadedModule:
        callables: list[Callable_] = []
        missing: list[str] = []
        registry = ToolRegistry.instance()

        for tb in row.tools:
            if not tb.enabled:
                continue
            if not registry.has(tb.registry_id):
                missing.append(tb.registry_id)
                continue
            spec = registry.get(tb.registry_id)
            callables.append(
                Callable_(
                    name=tb.display_name or spec.id,
                    description=spec.description,
                    input_schema=spec.input_schema,
                    invoke=_tool_invoker(spec),
                    kind="tool",
                    source_id=tb.id,
                )
            )

        executor = TaskExecutor(llm_client=self._llm, sessionmaker=self._sessionmaker)
        for tk in row.tasks:
            if not tk.enabled:
                continue
            callables.append(
                Callable_(
                    name=tk.name,
                    description=tk.description,
                    input_schema=tk.input_schema or {},
                    invoke=_task_invoker(executor, tk.id, tk.graph_json),
                    kind="task",
                    source_id=tk.id,
                )
            )

        loaded = LoadedModule(
            id=row.id,
            name=row.name,
            skill_md=(row.skill.content_md if row.skill else ""),
            callables=callables,
            missing_tool_ids=missing,
        )
        self._cache[row.id] = loaded
        return loaded


def _tool_invoker(spec: Any) -> Callable[[Dict[str, Any]], Awaitable[Any]]:
    async def invoke(inputs: Dict[str, Any]) -> Any:
        result = spec.fn(**inputs)
        if inspect.isawaitable(result):
            result = await result
        return result

    return invoke


def _task_invoker(
    executor: TaskExecutor, task_id: int, graph: Dict[str, Any]
) -> Callable[[Dict[str, Any]], Awaitable[Any]]:
    async def invoke(inputs: Dict[str, Any]) -> Any:
        return await executor.execute(graph, inputs, task_id=task_id)

    return invoke
```

- [ ] **Step 3: Create `tests/core/modules/test_loader.py`**

```python
"""Loader tests that don't need a real DB — exercise _build via crafted ORM stand-ins."""

from types import SimpleNamespace

import pytest

from atria.core.modules.loader import ModuleLoader
from atria.core.modules.registry import ToolRegistry, register_tool


@pytest.fixture(autouse=True)
def _clean_registry():
    ToolRegistry.instance().clear()
    yield
    ToolRegistry.instance().clear()


def _row(*, tools=None, tasks=None, skill_md=""):
    return SimpleNamespace(
        id=1,
        name="m",
        skill=SimpleNamespace(content_md=skill_md) if skill_md else None,
        tools=tools or [],
        tasks=tasks or [],
    )


def test_build_skips_missing_registry_tools():
    @register_tool(id="t.ok", description="ok")
    def ok() -> int:
        return 1

    tb_ok = SimpleNamespace(id=10, registry_id="t.ok", display_name="OK",
                            enabled=True, config_json={})
    tb_missing = SimpleNamespace(id=11, registry_id="t.gone", display_name="Gone",
                                 enabled=True, config_json={})

    async def llm(p: str) -> str:
        return ""

    loader = ModuleLoader(sessionmaker=None, llm_client=llm)  # type: ignore[arg-type]
    loaded = loader._build(_row(tools=[tb_ok, tb_missing]))

    assert [c.name for c in loaded.callables] == ["OK"]
    assert loaded.missing_tool_ids == ["t.gone"]


def test_build_includes_tasks_as_callables():
    tk = SimpleNamespace(
        id=20, name="my_task", description="d",
        input_schema={}, enabled=True,
        graph_json={
            "nodes": [{"id": "n", "type": "llm", "prompt": "hi"}],
            "edges": [],
            "output": "",
        },
    )

    async def llm(p: str) -> str:
        return "ok"

    loader = ModuleLoader(sessionmaker=None, llm_client=llm)  # type: ignore[arg-type]
    loaded = loader._build(_row(tasks=[tk]))
    assert [c.kind for c in loaded.callables] == ["task"]
    assert loaded.callables[0].name == "my_task"
```

- [ ] **Step 4: Commit**

```bash
git add atria/core/modules/models.py atria/core/modules/loader.py tests/core/modules/test_loader.py
git commit -m "feat(modules): ModuleLoader produces runtime callables from DB rows"
```

---

## Task 8: Async repository for module CRUD

**Files:**
- Create: `atria/db/repositories/modules_repo.py`
- Create: `tests/core/modules/test_modules_repo.py`

- [ ] **Step 1: Create `atria/db/repositories/modules_repo.py`**

```python
"""Async CRUD for modules, skill, tool bindings, tasks, task runs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from atria.db.models import (
    Module,
    ModuleSkill,
    ModuleTool,
    ModuleTask,
    TaskRun,
)
from atria.db.repositories.base import BaseRepository


class ModulesRepository(BaseRepository):
    # ------------------- Modules -------------------

    async def list_modules(self) -> List[Module]:
        async with self._sessionmaker() as s:
            stmt = select(Module).order_by(Module.id)
            return list((await s.execute(stmt)).scalars().all())

    async def get_module(self, module_id: int) -> Optional[Module]:
        async with self._sessionmaker() as s:
            stmt = (
                select(Module)
                .options(
                    selectinload(Module.skill),
                    selectinload(Module.tools),
                    selectinload(Module.tasks),
                )
                .where(Module.id == module_id)
            )
            return (await s.execute(stmt)).scalar_one_or_none()

    async def get_module_by_name(self, name: str) -> Optional[Module]:
        async with self._sessionmaker() as s:
            stmt = select(Module).where(Module.name == name)
            return (await s.execute(stmt)).scalar_one_or_none()

    async def create_module(
        self, *, name: str, display_name: str, description: Optional[str] = None,
        is_builtin: bool = False,
    ) -> Module:
        async with self._sessionmaker() as s:
            m = Module(
                name=name, display_name=display_name,
                description=description, is_builtin=is_builtin,
            )
            s.add(m)
            await s.flush()
            s.add(ModuleSkill(module_id=m.id, content_md=""))
            await s.commit()
            await s.refresh(m)
            return m

    async def patch_module(
        self, module_id: int, **fields: Any
    ) -> Optional[Module]:
        if not fields:
            return await self.get_module(module_id)
        fields["updated_at"] = datetime.utcnow()
        async with self._sessionmaker() as s:
            await s.execute(
                update(Module).where(Module.id == module_id).values(**fields)
            )
            await s.commit()
        return await self.get_module(module_id)

    async def delete_module(self, module_id: int) -> bool:
        async with self._sessionmaker() as s:
            result = await s.execute(
                delete(Module).where(
                    Module.id == module_id, Module.is_builtin.is_(False)
                )
            )
            await s.commit()
            return result.rowcount > 0

    # ------------------- Skill -------------------

    async def upsert_skill(self, module_id: int, content_md: str) -> ModuleSkill:
        async with self._sessionmaker() as s:
            existing = (
                await s.execute(
                    select(ModuleSkill).where(ModuleSkill.module_id == module_id)
                )
            ).scalar_one_or_none()
            if existing is None:
                existing = ModuleSkill(module_id=module_id, content_md=content_md)
                s.add(existing)
            else:
                existing.content_md = content_md
                existing.updated_at = datetime.utcnow()
            await s.commit()
            await s.refresh(existing)
            return existing

    # ------------------- Tool bindings -------------------

    async def list_tools(self, module_id: int) -> List[ModuleTool]:
        async with self._sessionmaker() as s:
            stmt = select(ModuleTool).where(ModuleTool.module_id == module_id)
            return list((await s.execute(stmt)).scalars().all())

    async def add_tool(
        self, *, module_id: int, registry_id: str, display_name: str,
        config_json: Optional[Dict[str, Any]] = None,
    ) -> ModuleTool:
        async with self._sessionmaker() as s:
            tb = ModuleTool(
                module_id=module_id, registry_id=registry_id,
                display_name=display_name, config_json=config_json or {},
            )
            s.add(tb)
            await s.commit()
            await s.refresh(tb)
            return tb

    async def patch_tool(self, tool_binding_id: int, **fields: Any) -> Optional[ModuleTool]:
        async with self._sessionmaker() as s:
            await s.execute(
                update(ModuleTool).where(ModuleTool.id == tool_binding_id).values(**fields)
            )
            await s.commit()
            return (
                await s.execute(
                    select(ModuleTool).where(ModuleTool.id == tool_binding_id)
                )
            ).scalar_one_or_none()

    async def remove_tool(self, tool_binding_id: int) -> bool:
        async with self._sessionmaker() as s:
            result = await s.execute(
                delete(ModuleTool).where(ModuleTool.id == tool_binding_id)
            )
            await s.commit()
            return result.rowcount > 0

    # ------------------- Tasks -------------------

    async def list_tasks(self, module_id: int) -> List[ModuleTask]:
        async with self._sessionmaker() as s:
            stmt = select(ModuleTask).where(ModuleTask.module_id == module_id)
            return list((await s.execute(stmt)).scalars().all())

    async def get_task(self, task_id: int) -> Optional[ModuleTask]:
        async with self._sessionmaker() as s:
            return (
                await s.execute(select(ModuleTask).where(ModuleTask.id == task_id))
            ).scalar_one_or_none()

    async def create_task(
        self, *, module_id: int, name: str, description: str,
        input_schema: Dict[str, Any], graph_json: Dict[str, Any],
    ) -> ModuleTask:
        async with self._sessionmaker() as s:
            t = ModuleTask(
                module_id=module_id, name=name, description=description,
                input_schema=input_schema, graph_json=graph_json,
            )
            s.add(t)
            await s.commit()
            await s.refresh(t)
            return t

    async def update_task(self, task_id: int, **fields: Any) -> Optional[ModuleTask]:
        fields["updated_at"] = datetime.utcnow()
        async with self._sessionmaker() as s:
            await s.execute(
                update(ModuleTask).where(ModuleTask.id == task_id).values(**fields)
            )
            await s.commit()
            return await self.get_task(task_id)

    async def delete_task(self, task_id: int) -> bool:
        async with self._sessionmaker() as s:
            result = await s.execute(
                delete(ModuleTask).where(ModuleTask.id == task_id)
            )
            await s.commit()
            return result.rowcount > 0

    async def recent_runs(self, task_id: int, limit: int = 20) -> List[TaskRun]:
        async with self._sessionmaker() as s:
            stmt = (
                select(TaskRun)
                .where(TaskRun.task_id == task_id)
                .order_by(TaskRun.created_at.desc())
                .limit(limit)
            )
            return list((await s.execute(stmt)).scalars().all())
```

- [ ] **Step 2: Create `tests/core/modules/test_modules_repo.py`**

```python
"""Integration-style tests against an in-memory async SQLite engine.

These exercise the ORM/repository roundtrip without touching PostgreSQL.
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atria.db.models import Base
from atria.db.repositories.modules_repo import ModulesRepository


@pytest_asyncio.fixture
async def sessionmaker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def repo(sessionmaker):
    return ModulesRepository(sessionmaker)


@pytest.mark.asyncio
async def test_create_then_get_module(repo):
    m = await repo.create_module(name="m1", display_name="M1", is_builtin=True)
    assert m.id is not None
    fetched = await repo.get_module(m.id)
    assert fetched is not None
    assert fetched.skill is not None
    assert fetched.skill.content_md == ""


@pytest.mark.asyncio
async def test_upsert_skill(repo):
    m = await repo.create_module(name="m2", display_name="M2")
    await repo.upsert_skill(m.id, "## hello")
    fetched = await repo.get_module(m.id)
    assert fetched.skill.content_md == "## hello"


@pytest.mark.asyncio
async def test_tool_lifecycle(repo):
    m = await repo.create_module(name="m3", display_name="M3")
    tb = await repo.add_tool(module_id=m.id, registry_id="x.y", display_name="X")
    assert (await repo.list_tools(m.id))[0].registry_id == "x.y"
    await repo.patch_tool(tb.id, enabled=False)
    assert (await repo.list_tools(m.id))[0].enabled is False
    await repo.remove_tool(tb.id)
    assert await repo.list_tools(m.id) == []


@pytest.mark.asyncio
async def test_task_create_update_delete(repo):
    m = await repo.create_module(name="m4", display_name="M4")
    t = await repo.create_task(
        module_id=m.id, name="task1", description="d",
        input_schema={}, graph_json={"nodes": [], "edges": [], "output": ""},
    )
    assert (await repo.get_task(t.id)).name == "task1"
    await repo.update_task(t.id, description="d2")
    assert (await repo.get_task(t.id)).description == "d2"
    await repo.delete_task(t.id)
    assert await repo.get_task(t.id) is None


@pytest.mark.asyncio
async def test_delete_builtin_module_blocked(repo):
    m = await repo.create_module(name="bi", display_name="BI", is_builtin=True)
    assert await repo.delete_module(m.id) is False
    m2 = await repo.create_module(name="usr", display_name="USR", is_builtin=False)
    assert await repo.delete_module(m2.id) is True
```

- [ ] **Step 3: Add aiosqlite test dep if missing**

In `pyproject.toml`, under the dev dependency group (usually `[project.optional-dependencies] dev`), ensure `aiosqlite` and `pytest-asyncio` are present. If they are not, add them. Confirm the test config also has `asyncio_mode = "auto"` under `[tool.pytest.ini_options]` (add if absent).

- [ ] **Step 4: Commit**

```bash
git add atria/db/repositories/modules_repo.py tests/core/modules/test_modules_repo.py pyproject.toml
git commit -m "feat(modules): async ModulesRepository + integration tests"
```

---

## Task 9: Seeding system + deep_analyze builtin

**Files:**
- Create: `atria/core/modules/seed.py`
- Create: `atria/core/modules/builtins/__init__.py`
- Create: `atria/core/modules/builtins/deep_analyze/__init__.py`
- Create: `atria/core/modules/builtins/deep_analyze/tools.py`
- Create: `atria/core/modules/builtins/deep_analyze/seed/skill.md`
- Create: `atria/core/modules/builtins/deep_analyze/seed/tasks/extract_and_summarize.json`
- Create: `tests/core/modules/test_seed.py`

- [ ] **Step 1: Create `atria/core/modules/builtins/__init__.py`**

```python
"""Importing this package registers all built-in tools."""

from atria.core.modules.builtins import deep_analyze  # noqa: F401

__all__ = ["deep_analyze"]
```

- [ ] **Step 2: Create `atria/core/modules/builtins/deep_analyze/__init__.py`**

```python
"""Built-in deep_analyze module: registers tools at import time."""

from atria.core.modules.builtins.deep_analyze import tools  # noqa: F401
```

- [ ] **Step 3: Create `atria/core/modules/builtins/deep_analyze/tools.py`**

Migrate the simplest atomic functions from the old `atria/skills/builtin/deep_analyze/`. Start with two minimal but real registrations to prove the pattern; the full migration of every function happens in Task 14.

```python
"""Registered Python tools for the built-in deep_analyze module."""

from __future__ import annotations

from atria.core.modules.registry import register_tool


@register_tool(
    id="deep_analyze.extract_entities",
    description="Extract a flat list of named entities from the given text.",
    input_schema={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
    display_name="Extract entities",
)
def extract_entities(text: str) -> list[str]:
    # Minimal placeholder: real implementation calls existing extractor.
    # See Task 14 for the migration.
    return [tok.strip(".,;:!?") for tok in text.split() if tok.istitle()]


@register_tool(
    id="deep_analyze.summarize",
    description="Return a short prose summary of the given text.",
    input_schema={
        "type": "object",
        "properties": {"text": {"type": "string"}, "max_chars": {"type": "integer"}},
        "required": ["text"],
    },
    display_name="Summarize text",
)
def summarize(text: str, max_chars: int = 280) -> str:
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"
```

- [ ] **Step 4: Create `atria/core/modules/builtins/deep_analyze/seed/skill.md`**

```markdown
# Deep Analyze

Use this module when the user wants you to break down a document, transcript, or
dataset into structured findings. Prefer running the `extract_and_summarize`
task first for any new input; then drill into entities of interest using the
`extract_entities` tool. Never invent data — every claim must be traceable to
the input.
```

- [ ] **Step 5: Create `atria/core/modules/builtins/deep_analyze/seed/tasks/extract_and_summarize.json`**

```json
{
  "name": "extract_and_summarize",
  "description": "Extract entities from input.text and produce a short summary.",
  "input_schema": {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"]
  },
  "graph_json": {
    "nodes": [
      {
        "id": "n1",
        "type": "tool",
        "registry_id": "deep_analyze.extract_entities",
        "inputs": {"text": "{{input.text}}"},
        "output_var": "entities"
      },
      {
        "id": "n2",
        "type": "tool",
        "registry_id": "deep_analyze.summarize",
        "inputs": {"text": "{{input.text}}", "max_chars": 200},
        "output_var": "summary"
      },
      {
        "id": "n3",
        "type": "llm",
        "prompt": "Combine entities {{n1.entities}} with summary '{{n2.summary}}' into a one-paragraph report.",
        "output_var": "report"
      }
    ],
    "edges": [
      {"from": "n1", "to": "n3"},
      {"from": "n2", "to": "n3"}
    ],
    "output": "{{n3.report}}"
  }
}
```

- [ ] **Step 6: Create `atria/core/modules/seed.py`**

```python
"""Idempotently seed built-in modules into the DB on startup."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from atria.core.modules.registry import ToolRegistry
from atria.db.repositories.modules_repo import ModulesRepository


BUILTINS_DIR = Path(__file__).parent / "builtins"


async def seed(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    """Create rows for each builtin directory if not already present.

    Idempotent: existing modules are NOT overwritten (per design — user edits
    survive restarts). The `reset_module` endpoint re-applies the seed.
    """
    repo = ModulesRepository(sessionmaker)
    for module_dir in sorted(_module_dirs()):
        await _seed_module(repo, module_dir)


async def reset_module(
    sessionmaker: async_sessionmaker[AsyncSession], name: str
) -> None:
    """Re-apply the seed for a single builtin module, overwriting user edits."""
    repo = ModulesRepository(sessionmaker)
    module_dir = BUILTINS_DIR / name
    if not module_dir.is_dir():
        raise FileNotFoundError(f"No builtin named {name!r}")
    await _seed_module(repo, module_dir, force=True)


def _module_dirs() -> list[Path]:
    return [p for p in BUILTINS_DIR.iterdir() if p.is_dir() and not p.name.startswith("_")]


async def _seed_module(repo: ModulesRepository, module_dir: Path, *, force: bool = False) -> None:
    name = module_dir.name
    existing = await repo.get_module_by_name(name)

    if existing is None:
        module = await repo.create_module(
            name=name,
            display_name=name.replace("_", " ").title(),
            description=None,
            is_builtin=True,
        )
    else:
        module = existing
        if not force:
            return

    skill_path = module_dir / "seed" / "skill.md"
    if skill_path.exists():
        await repo.upsert_skill(module.id, skill_path.read_text(encoding="utf-8"))

    # Auto-bind every tool registered under this module's id namespace.
    prefix = f"{name}."
    registry = ToolRegistry.instance()
    existing_bindings = {tb.registry_id for tb in await repo.list_tools(module.id)}
    for spec in registry.list():
        if spec.id.startswith(prefix) and spec.id not in existing_bindings:
            await repo.add_tool(
                module_id=module.id,
                registry_id=spec.id,
                display_name=spec.display_name or spec.id,
            )

    tasks_dir = module_dir / "seed" / "tasks"
    if tasks_dir.is_dir():
        existing_task_names = {t.name for t in await repo.list_tasks(module.id)}
        for task_file in sorted(tasks_dir.glob("*.json")):
            blob: Dict[str, Any] = json.loads(task_file.read_text(encoding="utf-8"))
            if blob["name"] in existing_task_names and not force:
                continue
            if force and blob["name"] in existing_task_names:
                # Replace by delete+create for simplicity.
                tasks_by_name = {t.name: t for t in await repo.list_tasks(module.id)}
                await repo.delete_task(tasks_by_name[blob["name"]].id)
            await repo.create_task(
                module_id=module.id,
                name=blob["name"],
                description=blob.get("description", ""),
                input_schema=blob.get("input_schema", {}),
                graph_json=blob["graph_json"],
            )
```

- [ ] **Step 7: Create `tests/core/modules/test_seed.py`**

```python
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atria.core.modules import seed as seed_mod
from atria.core.modules.registry import ToolRegistry
from atria.db.models import Base
from atria.db.repositories.modules_repo import ModulesRepository


@pytest_asyncio.fixture
async def sm():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_seed_creates_deep_analyze_idempotently(sm):
    # Builtins were already imported at package import; registry is populated.
    assert ToolRegistry.instance().has("deep_analyze.extract_entities")

    await seed_mod.seed(sm)
    repo = ModulesRepository(sm)
    m1 = await repo.get_module_by_name("deep_analyze")
    assert m1 is not None
    assert m1.is_builtin is True

    # Second seed must not duplicate rows
    await seed_mod.seed(sm)
    tools = await repo.list_tools(m1.id)
    assert len({t.registry_id for t in tools}) == len(tools)


@pytest.mark.asyncio
async def test_reset_module_force_replaces_task(sm):
    await seed_mod.seed(sm)
    repo = ModulesRepository(sm)
    m = await repo.get_module_by_name("deep_analyze")
    task = (await repo.list_tasks(m.id))[0]
    await repo.update_task(task.id, description="USER EDIT")

    await seed_mod.reset_module(sm, "deep_analyze")
    fresh = await repo.get_task(task.id)
    # After force reset, the original task row was deleted and replaced.
    assert fresh is None
    new_tasks = await repo.list_tasks(m.id)
    assert all(t.description != "USER EDIT" for t in new_tasks)
```

- [ ] **Step 8: Commit**

```bash
git add atria/core/modules/seed.py atria/core/modules/builtins/ tests/core/modules/test_seed.py
git commit -m "feat(modules): idempotent builtin seeding + deep_analyze starter"
```

---

## Task 10: Wire seed into server startup

**Files:**
- Modify: `atria/serve.py`

- [ ] **Step 1: Read current `atria/serve.py`**

Open the file and locate the FastAPI app's `startup` event handler (or the function that runs schema sync — search for `create_all` or `provisioner`).

- [ ] **Step 2: Add seed call after schema is ready**

Append after the existing schema/provisioner call. Use the existing async sessionmaker reference (search the file for `async_sessionmaker(`); reuse that variable. Example insertion:

```python
from atria.core.modules.seed import seed as seed_modules

# ... inside startup, after schema is ready and sessionmaker is built:
await seed_modules(sessionmaker)
```

If `serve.py` does not currently have a startup hook, add one using FastAPI's `lifespan` context manager. Refer to the existing pattern used by `atria/db/sync.py` if a similar hook already exists.

- [ ] **Step 3: Commit**

```bash
git add atria/serve.py
git commit -m "feat(modules): seed builtin modules on server startup"
```

---

## Task 11: Pydantic schemas + REST routes for modules

**Files:**
- Create: `atria/web/routes/modules.py`
- Modify: the file that registers other routers (search for `include_router` usages; commonly `atria/web/__init__.py` or `atria/serve.py`)
- Create: `tests/core/modules/test_modules_api.py`

- [ ] **Step 1: Create `atria/web/routes/modules.py`**

```python
"""REST API for module management (CRUD + skill + tools + tasks + runs)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from atria.core.modules.executor.validation import TaskValidationError, validate
from atria.core.modules.loader import ModuleLoader
from atria.core.modules.registry import ToolRegistry
from atria.core.modules.seed import reset_module
from atria.db.repositories.modules_repo import ModulesRepository
from atria.web.dependencies import get_sessionmaker, get_module_loader  # see Step 4


router = APIRouter(prefix="/api/modules", tags=["modules"])


# ---------- Pydantic models ----------


class ModuleOut(BaseModel):
    id: int
    name: str
    display_name: str
    description: Optional[str]
    enabled: bool
    is_builtin: bool


class ModuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None


class ModulePatch(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None


class SkillUpdate(BaseModel):
    content_md: str


class ToolBindingOut(BaseModel):
    id: int
    registry_id: str
    display_name: str
    enabled: bool
    config_json: Dict[str, Any]


class ToolBindingCreate(BaseModel):
    registry_id: str
    display_name: Optional[str] = None
    config_json: Dict[str, Any] = Field(default_factory=dict)


class ToolBindingPatch(BaseModel):
    enabled: Optional[bool] = None
    display_name: Optional[str] = None
    config_json: Optional[Dict[str, Any]] = None


class TaskOut(BaseModel):
    id: int
    name: str
    description: str
    input_schema: Dict[str, Any]
    graph_json: Dict[str, Any]
    enabled: bool


class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    graph_json: Dict[str, Any]


class TaskUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None
    graph_json: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class TaskRunRequest(BaseModel):
    inputs: Dict[str, Any] = Field(default_factory=dict)


class ToolCatalogOut(BaseModel):
    id: str
    description: str
    display_name: Optional[str]
    input_schema: Dict[str, Any]


# ---------- Helpers ----------


def _repo(sessionmaker = Depends(get_sessionmaker)) -> ModulesRepository:
    return ModulesRepository(sessionmaker)


def _module_to_out(m: Any) -> ModuleOut:
    return ModuleOut(
        id=m.id, name=m.name, display_name=m.display_name,
        description=m.description, enabled=m.enabled, is_builtin=m.is_builtin,
    )


# ---------- Routes ----------


@router.get("", response_model=List[ModuleOut])
async def list_modules(repo: ModulesRepository = Depends(_repo)) -> List[ModuleOut]:
    return [_module_to_out(m) for m in await repo.list_modules()]


@router.post("", response_model=ModuleOut, status_code=201)
async def create_module(
    body: ModuleCreate, repo: ModulesRepository = Depends(_repo)
) -> ModuleOut:
    if await repo.get_module_by_name(body.name) is not None:
        raise HTTPException(409, "module with this name already exists")
    m = await repo.create_module(
        name=body.name, display_name=body.display_name, description=body.description,
    )
    return _module_to_out(m)


@router.get("/{module_id}")
async def get_module(
    module_id: int, repo: ModulesRepository = Depends(_repo)
) -> Dict[str, Any]:
    m = await repo.get_module(module_id)
    if m is None:
        raise HTTPException(404)
    return {
        "module": _module_to_out(m).model_dump(),
        "skill": {"content_md": m.skill.content_md if m.skill else ""},
        "tools": [
            ToolBindingOut(
                id=t.id, registry_id=t.registry_id, display_name=t.display_name,
                enabled=t.enabled, config_json=t.config_json,
            ).model_dump()
            for t in m.tools
        ],
        "tasks": [
            TaskOut(
                id=t.id, name=t.name, description=t.description,
                input_schema=t.input_schema, graph_json=t.graph_json,
                enabled=t.enabled,
            ).model_dump()
            for t in m.tasks
        ],
    }


@router.patch("/{module_id}", response_model=ModuleOut)
async def patch_module(
    module_id: int, body: ModulePatch, repo: ModulesRepository = Depends(_repo),
    loader: ModuleLoader = Depends(get_module_loader),
) -> ModuleOut:
    m = await repo.patch_module(module_id, **body.model_dump(exclude_unset=True))
    if m is None:
        raise HTTPException(404)
    loader.invalidate(module_id)
    return _module_to_out(m)


@router.delete("/{module_id}", status_code=204)
async def delete_module(
    module_id: int, repo: ModulesRepository = Depends(_repo),
    loader: ModuleLoader = Depends(get_module_loader),
) -> None:
    ok = await repo.delete_module(module_id)
    if not ok:
        raise HTTPException(400, "module not found or is built-in")
    loader.invalidate(module_id)


@router.put("/{module_id}/skill")
async def update_skill(
    module_id: int, body: SkillUpdate, repo: ModulesRepository = Depends(_repo),
    loader: ModuleLoader = Depends(get_module_loader),
) -> Dict[str, Any]:
    if (await repo.get_module(module_id)) is None:
        raise HTTPException(404)
    skill = await repo.upsert_skill(module_id, body.content_md)
    loader.invalidate(module_id)
    return {"content_md": skill.content_md}


@router.post("/{module_id}/tools", response_model=ToolBindingOut, status_code=201)
async def add_tool_binding(
    module_id: int, body: ToolBindingCreate, repo: ModulesRepository = Depends(_repo),
    loader: ModuleLoader = Depends(get_module_loader),
) -> ToolBindingOut:
    if not ToolRegistry.instance().has(body.registry_id):
        raise HTTPException(400, f"unknown registry_id: {body.registry_id}")
    if (await repo.get_module(module_id)) is None:
        raise HTTPException(404)
    spec = ToolRegistry.instance().get(body.registry_id)
    tb = await repo.add_tool(
        module_id=module_id,
        registry_id=body.registry_id,
        display_name=body.display_name or spec.display_name or spec.id,
        config_json=body.config_json,
    )
    loader.invalidate(module_id)
    return ToolBindingOut(
        id=tb.id, registry_id=tb.registry_id, display_name=tb.display_name,
        enabled=tb.enabled, config_json=tb.config_json,
    )


@router.patch("/{module_id}/tools/{binding_id}", response_model=ToolBindingOut)
async def patch_tool_binding(
    module_id: int, binding_id: int, body: ToolBindingPatch,
    repo: ModulesRepository = Depends(_repo),
    loader: ModuleLoader = Depends(get_module_loader),
) -> ToolBindingOut:
    tb = await repo.patch_tool(binding_id, **body.model_dump(exclude_unset=True))
    if tb is None:
        raise HTTPException(404)
    loader.invalidate(module_id)
    return ToolBindingOut(
        id=tb.id, registry_id=tb.registry_id, display_name=tb.display_name,
        enabled=tb.enabled, config_json=tb.config_json,
    )


@router.delete("/{module_id}/tools/{binding_id}", status_code=204)
async def delete_tool_binding(
    module_id: int, binding_id: int, repo: ModulesRepository = Depends(_repo),
    loader: ModuleLoader = Depends(get_module_loader),
) -> None:
    if not await repo.remove_tool(binding_id):
        raise HTTPException(404)
    loader.invalidate(module_id)


@router.post("/{module_id}/tasks", response_model=TaskOut, status_code=201)
async def create_task(
    module_id: int, body: TaskCreate, repo: ModulesRepository = Depends(_repo),
    loader: ModuleLoader = Depends(get_module_loader),
) -> TaskOut:
    try:
        validate(body.graph_json)
    except TaskValidationError as exc:
        raise HTTPException(400, f"graph invalid: {exc}")
    t = await repo.create_task(
        module_id=module_id, name=body.name, description=body.description,
        input_schema=body.input_schema, graph_json=body.graph_json,
    )
    loader.invalidate(module_id)
    return TaskOut(
        id=t.id, name=t.name, description=t.description,
        input_schema=t.input_schema, graph_json=t.graph_json, enabled=t.enabled,
    )


@router.put("/{module_id}/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    module_id: int, task_id: int, body: TaskUpdate,
    repo: ModulesRepository = Depends(_repo),
    loader: ModuleLoader = Depends(get_module_loader),
) -> TaskOut:
    payload = body.model_dump(exclude_unset=True)
    if "graph_json" in payload:
        try:
            validate(payload["graph_json"])
        except TaskValidationError as exc:
            raise HTTPException(400, f"graph invalid: {exc}")
    t = await repo.update_task(task_id, **payload)
    if t is None:
        raise HTTPException(404)
    loader.invalidate(module_id)
    return TaskOut(
        id=t.id, name=t.name, description=t.description,
        input_schema=t.input_schema, graph_json=t.graph_json, enabled=t.enabled,
    )


@router.delete("/{module_id}/tasks/{task_id}", status_code=204)
async def delete_task(
    module_id: int, task_id: int, repo: ModulesRepository = Depends(_repo),
    loader: ModuleLoader = Depends(get_module_loader),
) -> None:
    if not await repo.delete_task(task_id):
        raise HTTPException(404)
    loader.invalidate(module_id)


@router.post("/{module_id}/tasks/{task_id}/run")
async def run_task(
    module_id: int, task_id: int, body: TaskRunRequest,
    repo: ModulesRepository = Depends(_repo),
    loader: ModuleLoader = Depends(get_module_loader),
) -> Dict[str, Any]:
    loaded = await loader.load(module_id)
    callable_ = next((c for c in loaded.callables if c.kind == "task" and c.source_id == task_id), None)
    if callable_ is None:
        raise HTTPException(404, "task not found in loaded module")
    try:
        result = await callable_.invoke(body.inputs)
        return {"status": "ok", "output": result}
    except Exception as exc:  # surfaced from executor
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


@router.get("/{module_id}/tasks/{task_id}/runs")
async def list_runs(
    module_id: int, task_id: int, repo: ModulesRepository = Depends(_repo),
) -> List[Dict[str, Any]]:
    return [
        {
            "id": r.id, "status": r.status, "inputs": r.inputs_json,
            "outputs": r.outputs_json, "error": r.error,
            "duration_ms": r.duration_ms, "created_at": r.created_at.isoformat(),
        }
        for r in await repo.recent_runs(task_id)
    ]


@router.post("/{module_id}/reset", status_code=204)
async def reset(
    module_id: int, repo: ModulesRepository = Depends(_repo),
    sessionmaker = Depends(get_sessionmaker),
    loader: ModuleLoader = Depends(get_module_loader),
) -> None:
    m = await repo.get_module(module_id)
    if m is None or not m.is_builtin:
        raise HTTPException(400, "can only reset built-in modules")
    await reset_module(sessionmaker, m.name)
    loader.invalidate(module_id)


# ---------- Tool registry catalog (sibling endpoint) ----------


catalog_router = APIRouter(prefix="/api/tool-registry", tags=["modules"])


@catalog_router.get("", response_model=List[ToolCatalogOut])
async def tool_catalog() -> List[ToolCatalogOut]:
    return [
        ToolCatalogOut(
            id=s.id, description=s.description,
            display_name=s.display_name, input_schema=s.input_schema,
        )
        for s in ToolRegistry.instance().list()
    ]
```

- [ ] **Step 2: Add dependency providers in `atria/web/dependencies/`**

Inspect `atria/web/dependencies/` (it already exists per `ls` output). Add a new file `atria/web/dependencies/modules.py` exporting `get_sessionmaker` (reuse the existing one if defined elsewhere — search for `async_sessionmaker(` first) and `get_module_loader`:

```python
"""FastAPI dependency providers for the modules subsystem."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from atria.core.modules.loader import ModuleLoader


# These two providers are wired by the existing app initialization. If the
# project already exposes a sessionmaker via FastAPI dependency injection,
# import that one instead of redefining; otherwise expose this stub and bind
# the real instance at startup via `app.dependency_overrides`.

_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_loader: ModuleLoader | None = None


def set_sessionmaker(sm: async_sessionmaker[AsyncSession]) -> None:
    global _sessionmaker
    _sessionmaker = sm


def set_module_loader(loader: ModuleLoader) -> None:
    global _loader
    _loader = loader


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("sessionmaker not initialized")
    return _sessionmaker


def get_module_loader() -> ModuleLoader:
    if _loader is None:
        raise RuntimeError("ModuleLoader not initialized")
    return _loader
```

Then re-export from `atria/web/dependencies/__init__.py`:

```python
from atria.web.dependencies.modules import (
    get_sessionmaker, get_module_loader,
    set_sessionmaker, set_module_loader,
)
```

(If `atria/web/dependencies/__init__.py` already re-exports other names, append these to the existing exports rather than overwriting.)

- [ ] **Step 3: Wire dependencies at startup**

In `atria/serve.py`, after the sessionmaker and base LLM client are constructed, add:

```python
from atria.core.modules.loader import ModuleLoader
from atria.web.dependencies import set_sessionmaker, set_module_loader

set_sessionmaker(sessionmaker)
set_module_loader(ModuleLoader(sessionmaker=sessionmaker, llm_client=base_llm_client))
```

`base_llm_client` is whatever async wrapper your global config already exposes — search the file for the existing model invocation site. If a function exists like `get_model_client()`, adapt to it: the loader needs an `async def (prompt: str) -> str` callable.

- [ ] **Step 4: Register routers**

In the file that registers other API routers (search for `include_router(personas`), add:

```python
from atria.web.routes import modules as modules_routes

app.include_router(modules_routes.router)
app.include_router(modules_routes.catalog_router)
```

- [ ] **Step 5: Create `tests/core/modules/test_modules_api.py`**

```python
"""Route tests using FastAPI TestClient + sqlite-backed app."""

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atria.core.modules.loader import ModuleLoader
from atria.core.modules.registry import ToolRegistry, register_tool
from atria.core.modules.seed import seed
from atria.db.models import Base
from atria.web.dependencies import set_sessionmaker, set_module_loader
from atria.web.routes import modules as routes


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)

    async def fake_llm(prompt: str) -> str:
        return f"LLM:{prompt}"

    set_sessionmaker(sm)
    set_module_loader(ModuleLoader(sessionmaker=sm, llm_client=fake_llm))

    # Register a single test tool (avoid importing real builtins to keep tests hermetic)
    ToolRegistry.instance().clear()

    @register_tool(id="test.echo", description="echo")
    def _echo(text: str) -> str:
        return text

    await seed(sm)  # no-op since builtins import is now empty here; safe to call

    app = FastAPI()
    app.include_router(routes.router)
    app.include_router(routes.catalog_router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c

    ToolRegistry.instance().clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_and_list_modules(client):
    r = await client.post("/api/modules", json={"name": "m1", "display_name": "M1"})
    assert r.status_code == 201
    r = await client.get("/api/modules")
    assert r.status_code == 200
    assert any(m["name"] == "m1" for m in r.json())


@pytest.mark.asyncio
async def test_skill_and_tool_binding_roundtrip(client):
    mid = (await client.post("/api/modules", json={"name": "m2", "display_name": "M2"})).json()["id"]
    assert (await client.put(f"/api/modules/{mid}/skill", json={"content_md": "x"})).status_code == 200
    r = await client.post(f"/api/modules/{mid}/tools", json={"registry_id": "test.echo"})
    assert r.status_code == 201
    detail = (await client.get(f"/api/modules/{mid}")).json()
    assert detail["skill"]["content_md"] == "x"
    assert detail["tools"][0]["registry_id"] == "test.echo"


@pytest.mark.asyncio
async def test_create_task_with_invalid_graph_rejected(client):
    mid = (await client.post("/api/modules", json={"name": "m3", "display_name": "M3"})).json()["id"]
    r = await client.post(
        f"/api/modules/{mid}/tasks",
        json={"name": "bad", "description": "", "input_schema": {}, "graph_json": {"nodes": []}},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_run_task(client):
    mid = (await client.post("/api/modules", json={"name": "m4", "display_name": "M4"})).json()["id"]
    await client.post(f"/api/modules/{mid}/tools", json={"registry_id": "test.echo"})
    graph = {
        "nodes": [{
            "id": "n1", "type": "tool", "registry_id": "test.echo",
            "inputs": {"text": "{{input.msg}}"}, "output_var": "v",
        }],
        "edges": [],
        "output": "{{n1.v}}",
    }
    tid = (await client.post(
        f"/api/modules/{mid}/tasks",
        json={"name": "echo_task", "description": "", "input_schema": {}, "graph_json": graph},
    )).json()["id"]
    r = await client.post(
        f"/api/modules/{mid}/tasks/{tid}/run", json={"inputs": {"msg": "hi"}},
    )
    assert r.status_code == 200
    assert r.json()["output"] == "hi"
```

- [ ] **Step 6: Commit**

```bash
git add atria/web/routes/modules.py atria/web/dependencies/ atria/serve.py tests/core/modules/test_modules_api.py
git commit -m "feat(modules): REST API for module CRUD + tool/task/run + catalog"
```

---

## Task 12: Agent integration (callables + skill prompt section)

**Files:**
- Modify: `atria/core/agents/main_agent.py`
- Modify: `atria/core/agents/prompts/composition.py`
- Create: `tests/core/modules/test_agent_integration.py`

- [ ] **Step 1: Inspect `main_agent.py`**

Read `atria/core/agents/main_agent.py` to find:
- where the tool list passed to the ReAct loop is built (search for `tools=` or `tool_registry`)
- where the system prompt is composed
- whether the agent receives the `Conversation` (it likely does — look for `conversation` or `session` parameter).

- [ ] **Step 2: Add adapter function near top of `main_agent.py`**

After existing imports, add:

```python
from atria.core.modules.loader import ModuleLoader
from atria.core.modules.models import Callable_ as ModuleCallable
```

Then add this helper above the `MainAgent` class (or wherever utility functions live):

```python
def _adapt_module_callables(callables: list[ModuleCallable]) -> list[dict]:
    """Wrap module callables in the same dict shape the ReAct tool registry uses."""
    adapted: list[dict] = []
    for c in callables:
        adapted.append({
            "name": c.name,
            "description": c.description,
            "parameters": c.input_schema,
            "invoke": c.invoke,
        })
    return adapted
```

- [ ] **Step 3: Integrate into agent construction**

Inside the method that builds tools (look for `self.tools = ` or the equivalent), after the existing tool list is populated:

```python
if conversation is not None and conversation.active_module_id is not None:
    loaded = await self._module_loader.load(conversation.active_module_id)
    self.tools.extend(_adapt_module_callables(loaded.callables))
    self.module_skill_md = loaded.skill_md
else:
    self.module_skill_md = ""
```

Add `module_loader: ModuleLoader` as a constructor parameter to `MainAgent` (or extend the `AgentDependencies` injection). The constructor must accept and store it as `self._module_loader`.

- [ ] **Step 4: Inject skill into system prompt**

Find the `PromptComposer` usage in `main_agent.py`. After the existing sections are added:

```python
if self.module_skill_md:
    composer.add_section(
        name="module_skill",
        priority=20,   # after core instructions, before tool listings (adjust to fit existing priorities)
        content=self.module_skill_md,
    )
```

If `PromptComposer.add_section` does not match this signature, adapt to the existing API; the key requirement is that the markdown is included in the assembled system prompt.

- [ ] **Step 5: Update `atria/core/agents/prompts/composition.py`**

Open the file. If sections are statically registered with a fixed list, add `module_skill` to the allowed-section-names registry (no template file needed — the content is supplied at runtime). If section names are open-ended, no change needed.

- [ ] **Step 6: Wire `ModuleLoader` through `AgentDependencies`**

Open `atria/models/agent_deps.py`. Add:

```python
from atria.core.modules.loader import ModuleLoader

# inside the dataclass:
    module_loader: ModuleLoader
```

Find the place where `AgentDependencies(...)` is constructed (likely in `serve.py` or a factory) and pass the same `ModuleLoader` instance used by the web routes (which was created in Task 11 Step 3).

- [ ] **Step 7: Create `tests/core/modules/test_agent_integration.py`**

```python
"""Light integration: loader -> adapter -> tool list contains module callables."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atria.core.modules.loader import ModuleLoader
from atria.core.modules.registry import ToolRegistry, register_tool
from atria.core.modules.seed import seed
from atria.db.models import Base
from atria.db.repositories.modules_repo import ModulesRepository


@pytest_asyncio.fixture
async def sm():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_loader_returns_callables_after_seed(sm):
    ToolRegistry.instance().clear()

    @register_tool(id="deep_analyze.extract_entities", description="x")
    def fn(text: str) -> list[str]:
        return text.split()

    await seed(sm)
    repo = ModulesRepository(sm)
    mod = await repo.get_module_by_name("deep_analyze")

    async def fake_llm(p: str) -> str:
        return "ok"

    loader = ModuleLoader(sessionmaker=sm, llm_client=fake_llm)
    loaded = await loader.load(mod.id)

    names = {c.name for c in loaded.callables}
    assert any(n.lower().startswith("extract") for n in names)
    assert isinstance(loaded.skill_md, str) and len(loaded.skill_md) > 0
```

- [ ] **Step 8: Commit**

```bash
git add atria/core/agents/main_agent.py atria/core/agents/prompts/composition.py atria/models/agent_deps.py tests/core/modules/test_agent_integration.py
git commit -m "feat(modules): agent exposes module callables + injects skill prompt"
```

---

## Task 13: Active-module selection on conversations

**Files:**
- Modify: `atria/db/repositories/conversation_repo.py`
- Modify: `atria/web/routes/chat.py` or `atria/web/routes/sessions.py` (whichever owns conversation update)

- [ ] **Step 1: Add setter on the conversation repo**

Open `atria/db/repositories/conversation_repo.py`. Add:

```python
async def set_active_module(self, conversation_id: int, module_id: int | None) -> None:
    async with self._sessionmaker() as s:
        await s.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(active_module_id=module_id)
        )
        await s.commit()
```

(Imports: `from sqlalchemy import update` + `from atria.db.models import Conversation` — add if missing.)

- [ ] **Step 2: Add a route to set it**

In whichever file owns conversation routes (likely `atria/web/routes/sessions.py` or `atria/web/routes/chat.py` — search for `/api/conversations`):

```python
class ActiveModuleRequest(BaseModel):
    module_id: int | None


@router.put("/{conversation_id}/active-module")
async def set_active_module(
    conversation_id: int, body: ActiveModuleRequest,
    repo: ConversationRepository = Depends(get_conversation_repo),
) -> dict:
    await repo.set_active_module(conversation_id, body.module_id)
    return {"active_module_id": body.module_id}
```

- [ ] **Step 3: Commit**

```bash
git add atria/db/repositories/conversation_repo.py atria/web/routes/
git commit -m "feat(modules): set active module per conversation"
```

---

## Task 14: Full deep_analyze migration

**Files:**
- Modify: `atria/core/modules/builtins/deep_analyze/tools.py` (real implementations)
- Add: more JSON tasks under `atria/core/modules/builtins/deep_analyze/seed/tasks/`
- Modify: `atria/skills/builtin/deep_analyze/` (mark deprecated)

- [ ] **Step 1: Open `atria/skills/builtin/deep_analyze/` and inventory**

```bash
ls atria/skills/builtin/deep_analyze/
cat atria/skills/builtin/deep_analyze/SKILL.md
```

For each Python function exposed by `tools.py`, `dataloader.py`, `profiler.py`, write a migration row in a scratch list: *old path* → *new registry id*.

- [ ] **Step 2: Re-implement those tools in `atria/core/modules/builtins/deep_analyze/tools.py`**

Replace the placeholder `extract_entities` and `summarize` with real implementations, calling into the existing utility modules (`atria.skills.builtin.deep_analyze.profiler`, etc.) where possible to avoid duplication. Each gets a `@register_tool` decorator with stable id `deep_analyze.<name>`.

- [ ] **Step 3: Convert each entry in old `pipeline.py` into a JSON task graph**

For every pipeline orchestration in `atria/skills/builtin/deep_analyze/pipeline.py`, build a corresponding `seed/tasks/<name>.json` following the schema from Task 9. Prompt strings come from `prompts.py`; tool calls reference `deep_analyze.*` registry ids.

- [ ] **Step 4: Copy `SKILL.md` content verbatim into `seed/skill.md`** (overwrite the placeholder file from Task 9).

- [ ] **Step 5: Mark old folder deprecated**

Add a `DEPRECATED.md` to `atria/skills/builtin/deep_analyze/`:

```markdown
This module has been migrated to `atria/core/modules/builtins/deep_analyze/`.
Schedule for removal: one release after parity is confirmed.
```

Do **not** delete the old folder yet — keeping a one-release deprecation window is per the design.

- [ ] **Step 6: Commit**

```bash
git add atria/core/modules/builtins/deep_analyze/ atria/skills/builtin/deep_analyze/DEPRECATED.md
git commit -m "feat(modules): full deep_analyze migration to new module system"
```

---

## Task 15: Frontend — Modules list + detail (Skill + Tools tabs)

**Files:**
- Create: `web-ui/src/pages/modules/types.ts`
- Create: `web-ui/src/pages/modules/api.ts`
- Create: `web-ui/src/pages/modules/ModulesListPage.tsx`
- Create: `web-ui/src/pages/modules/ModuleDetailPage.tsx`
- Modify: the router file (search for `createBrowserRouter` or `Routes` in `web-ui/src/`)

- [ ] **Step 1: Inspect existing UI patterns**

```bash
ls web-ui/src/
grep -R "createBrowserRouter\|Routes>" web-ui/src/ -l | head
```

Read one of the existing simple pages (e.g. a sessions list) to learn the project's preferred styling (Tailwind? CSS modules?), data-fetching hook (raw fetch? react-query?), and state store usage. Match that style throughout.

- [ ] **Step 2: Create `web-ui/src/pages/modules/types.ts`**

```ts
export interface ModuleSummary {
  id: number;
  name: string;
  display_name: string;
  description: string | null;
  enabled: boolean;
  is_builtin: boolean;
}

export interface ToolBinding {
  id: number;
  registry_id: string;
  display_name: string;
  enabled: boolean;
  config_json: Record<string, unknown>;
}

export interface TaskNode {
  id: string;
  type: "llm" | "tool";
  prompt?: string;
  registry_id?: string;
  inputs?: Record<string, unknown>;
  output_var?: string;
}

export interface TaskGraph {
  nodes: TaskNode[];
  edges: { from: string; to: string }[];
  output: string;
}

export interface ModuleTask {
  id: number;
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  graph_json: TaskGraph;
  enabled: boolean;
}

export interface ModuleDetail {
  module: ModuleSummary;
  skill: { content_md: string };
  tools: ToolBinding[];
  tasks: ModuleTask[];
}

export interface ToolCatalogItem {
  id: string;
  description: string;
  display_name: string | null;
  input_schema: Record<string, unknown>;
}
```

- [ ] **Step 3: Create `web-ui/src/pages/modules/api.ts`**

```ts
import type {
  ModuleSummary, ModuleDetail, ToolBinding, ModuleTask, ToolCatalogItem,
} from "./types";

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

export const ModulesApi = {
  list: () => fetch("/api/modules").then(j<ModuleSummary[]>),
  get: (id: number) => fetch(`/api/modules/${id}`).then(j<ModuleDetail>),
  create: (body: { name: string; display_name: string; description?: string }) =>
    fetch("/api/modules", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(j<ModuleSummary>),
  patch: (id: number, body: Partial<Pick<ModuleSummary, "display_name" | "description" | "enabled">>) =>
    fetch(`/api/modules/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(j<ModuleSummary>),
  remove: (id: number) => fetch(`/api/modules/${id}`, { method: "DELETE" }).then((r) => { if (!r.ok) throw new Error(r.statusText); }),

  putSkill: (id: number, content_md: string) =>
    fetch(`/api/modules/${id}/skill`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content_md }) }).then(j<{ content_md: string }>),

  addTool: (id: number, body: { registry_id: string; display_name?: string }) =>
    fetch(`/api/modules/${id}/tools`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(j<ToolBinding>),
  patchTool: (mid: number, bid: number, body: Partial<Pick<ToolBinding, "enabled" | "display_name">>) =>
    fetch(`/api/modules/${mid}/tools/${bid}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(j<ToolBinding>),
  removeTool: (mid: number, bid: number) =>
    fetch(`/api/modules/${mid}/tools/${bid}`, { method: "DELETE" }).then((r) => { if (!r.ok) throw new Error(r.statusText); }),

  createTask: (id: number, body: { name: string; description: string; input_schema: object; graph_json: object }) =>
    fetch(`/api/modules/${id}/tasks`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(j<ModuleTask>),
  updateTask: (mid: number, tid: number, body: Partial<ModuleTask>) =>
    fetch(`/api/modules/${mid}/tasks/${tid}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(j<ModuleTask>),
  removeTask: (mid: number, tid: number) =>
    fetch(`/api/modules/${mid}/tasks/${tid}`, { method: "DELETE" }).then((r) => { if (!r.ok) throw new Error(r.statusText); }),
  runTask: (mid: number, tid: number, inputs: Record<string, unknown>) =>
    fetch(`/api/modules/${mid}/tasks/${tid}/run`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ inputs }) }).then(j<{ status: "ok" | "error"; output?: unknown; error?: string }>),

  reset: (id: number) => fetch(`/api/modules/${id}/reset`, { method: "POST" }).then((r) => { if (!r.ok) throw new Error(r.statusText); }),
  catalog: () => fetch("/api/tool-registry").then(j<ToolCatalogItem[]>),
};
```

- [ ] **Step 4: Create `web-ui/src/pages/modules/ModulesListPage.tsx`**

```tsx
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ModulesApi } from "./api";
import type { ModuleSummary } from "./types";

export default function ModulesListPage() {
  const [items, setItems] = useState<ModuleSummary[]>([]);
  const [creating, setCreating] = useState(false);

  useEffect(() => { ModulesApi.list().then(setItems); }, []);

  const toggle = async (m: ModuleSummary) => {
    const updated = await ModulesApi.patch(m.id, { enabled: !m.enabled });
    setItems((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
  };

  const create = async () => {
    setCreating(true);
    const name = prompt("Module name (lowercase, no spaces):") ?? "";
    if (!name) { setCreating(false); return; }
    const display_name = prompt("Display name:", name) ?? name;
    const created = await ModulesApi.create({ name, display_name });
    setItems((prev) => [...prev, created]);
    setCreating(false);
  };

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-semibold">Modules</h1>
        <button className="px-3 py-1 rounded bg-blue-600 text-white" disabled={creating} onClick={create}>
          + New module
        </button>
      </div>
      <table className="w-full text-left">
        <thead><tr><th>Name</th><th>Type</th><th>Enabled</th><th></th></tr></thead>
        <tbody>
          {items.map((m) => (
            <tr key={m.id} className="border-t">
              <td className="py-2"><Link className="underline" to={`/modules/${m.id}`}>{m.display_name}</Link></td>
              <td>{m.is_builtin ? "built-in" : "user"}</td>
              <td><input type="checkbox" checked={m.enabled} onChange={() => toggle(m)} /></td>
              <td>{!m.is_builtin && <button onClick={() => ModulesApi.remove(m.id).then(() => setItems((p) => p.filter((x) => x.id !== m.id)))}>Delete</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 5: Create `web-ui/src/pages/modules/ModuleDetailPage.tsx`**

```tsx
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ModulesApi } from "./api";
import type { ModuleDetail, ToolCatalogItem } from "./types";

type Tab = "skill" | "tools" | "tasks";

export default function ModuleDetailPage() {
  const { id } = useParams<{ id: string }>();
  const mid = Number(id);
  const [detail, setDetail] = useState<ModuleDetail | null>(null);
  const [tab, setTab] = useState<Tab>("skill");
  const [catalog, setCatalog] = useState<ToolCatalogItem[]>([]);

  useEffect(() => { ModulesApi.get(mid).then(setDetail); }, [mid]);
  useEffect(() => { if (tab === "tools") ModulesApi.catalog().then(setCatalog); }, [tab]);

  if (!detail) return <div className="p-6">Loading…</div>;

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold mb-2">{detail.module.display_name}</h1>
      <div className="flex gap-2 mb-4 border-b">
        {(["skill", "tools", "tasks"] as Tab[]).map((t) => (
          <button key={t} className={`px-3 py-1 ${tab === t ? "border-b-2 border-blue-600" : ""}`} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>

      {tab === "skill" && <SkillTab mid={mid} initial={detail.skill.content_md} />}
      {tab === "tools" && <ToolsTab mid={mid} bindings={detail.tools} catalog={catalog} onChange={() => ModulesApi.get(mid).then(setDetail)} />}
      {tab === "tasks" && <TasksTab mid={mid} tasks={detail.tasks} />}
    </div>
  );
}

function SkillTab({ mid, initial }: { mid: number; initial: string }) {
  const [content, setContent] = useState(initial);
  const [saving, setSaving] = useState(false);
  const over = content.length > 4000;
  return (
    <div>
      {over && <div className="mb-2 text-amber-700">Long skill text ({content.length} chars) will bloat every agent turn.</div>}
      <textarea className="w-full h-96 font-mono border rounded p-2" value={content} onChange={(e) => setContent(e.target.value)} />
      <button className="mt-2 px-3 py-1 bg-blue-600 text-white rounded" disabled={saving}
        onClick={async () => { setSaving(true); await ModulesApi.putSkill(mid, content); setSaving(false); }}>
        Save
      </button>
    </div>
  );
}

function ToolsTab(props: { mid: number; bindings: ModuleDetail["tools"]; catalog: ToolCatalogItem[]; onChange: () => void }) {
  const bound = new Set(props.bindings.map((b) => b.registry_id));
  return (
    <div className="grid grid-cols-2 gap-6">
      <div>
        <h2 className="font-semibold mb-2">Bound tools</h2>
        {props.bindings.map((b) => (
          <div key={b.id} className="flex items-center justify-between border-b py-1">
            <span>{b.display_name} <span className="text-gray-500 text-xs">({b.registry_id})</span></span>
            <span>
              <input type="checkbox" checked={b.enabled} onChange={async () => { await ModulesApi.patchTool(props.mid, b.id, { enabled: !b.enabled }); props.onChange(); }} />
              <button className="ml-2 text-red-600" onClick={async () => { await ModulesApi.removeTool(props.mid, b.id); props.onChange(); }}>Remove</button>
            </span>
          </div>
        ))}
      </div>
      <div>
        <h2 className="font-semibold mb-2">Add from registry</h2>
        {props.catalog.filter((c) => !bound.has(c.id)).map((c) => (
          <div key={c.id} className="flex items-center justify-between border-b py-1">
            <span>{c.display_name || c.id}<div className="text-xs text-gray-500">{c.description}</div></span>
            <button className="px-2 py-1 bg-blue-600 text-white rounded text-xs"
              onClick={async () => { await ModulesApi.addTool(props.mid, { registry_id: c.id }); props.onChange(); }}>
              Add
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function TasksTab({ mid, tasks }: { mid: number; tasks: ModuleDetail["tasks"] }) {
  return (
    <div>
      <Link to={`/modules/${mid}/tasks/new`} className="px-3 py-1 bg-blue-600 text-white rounded">+ New task</Link>
      <ul className="mt-3">
        {tasks.map((t) => (
          <li key={t.id} className="border-b py-2">
            <Link to={`/modules/${mid}/tasks/${t.id}`} className="font-medium underline">{t.name}</Link>
            <div className="text-xs text-gray-500">{t.description}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 6: Register routes**

Open the existing router file (found in Step 1). Add:

```tsx
import ModulesListPage from "./pages/modules/ModulesListPage";
import ModuleDetailPage from "./pages/modules/ModuleDetailPage";
import TaskEditorPage from "./pages/modules/TaskEditorPage";   // created in Task 16

// routes:
{ path: "/modules", element: <ModulesListPage /> },
{ path: "/modules/:id", element: <ModuleDetailPage /> },
{ path: "/modules/:id/tasks/new", element: <TaskEditorPage /> },
{ path: "/modules/:id/tasks/:tid", element: <TaskEditorPage /> },
```

- [ ] **Step 7: Commit**

```bash
git add web-ui/src/pages/modules/ web-ui/src/<router-file>
git commit -m "feat(modules): web UI for module list + detail (skill + tools tabs)"
```

---

## Task 16: Frontend — Linear-list TaskEditor

**Files:**
- Create: `web-ui/src/pages/modules/TaskEditorPage.tsx`

- [ ] **Step 1: Create `web-ui/src/pages/modules/TaskEditorPage.tsx`**

```tsx
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ModulesApi } from "./api";
import type { ModuleDetail, ModuleTask, TaskGraph, TaskNode, ToolCatalogItem } from "./types";

const EMPTY_GRAPH: TaskGraph = { nodes: [], edges: [], output: "" };

export default function TaskEditorPage() {
  const { id, tid } = useParams<{ id: string; tid?: string }>();
  const mid = Number(id);
  const nav = useNavigate();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [inputSchemaText, setInputSchemaText] = useState("{}");
  const [graph, setGraph] = useState<TaskGraph>(EMPTY_GRAPH);
  const [selected, setSelected] = useState<number | null>(null);
  const [catalog, setCatalog] = useState<ToolCatalogItem[]>([]);
  const [runOutput, setRunOutput] = useState<unknown>(null);
  const [runInputs, setRunInputs] = useState("{}");

  useEffect(() => { ModulesApi.catalog().then(setCatalog); }, []);
  useEffect(() => {
    if (!tid) return;
    ModulesApi.get(mid).then((d: ModuleDetail) => {
      const t: ModuleTask | undefined = d.tasks.find((x) => x.id === Number(tid));
      if (!t) return;
      setName(t.name);
      setDescription(t.description);
      setInputSchemaText(JSON.stringify(t.input_schema, null, 2));
      setGraph(t.graph_json);
    });
  }, [mid, tid]);

  const linearEdges = useMemo(
    () => graph.nodes.slice(1).map((n, i) => ({ from: graph.nodes[i].id, to: n.id })),
    [graph.nodes],
  );

  const updateNode = (idx: number, patch: Partial<TaskNode>) => {
    setGraph((g) => {
      const nodes = g.nodes.map((n, i) => (i === idx ? { ...n, ...patch } : n));
      return { ...g, nodes, edges: nodes.slice(1).map((n, i) => ({ from: nodes[i].id, to: n.id })) };
    });
  };

  const addNode = (type: "llm" | "tool") => {
    const nid = `n${graph.nodes.length + 1}`;
    const node: TaskNode = type === "llm"
      ? { id: nid, type, prompt: "" }
      : { id: nid, type, registry_id: catalog[0]?.id ?? "", inputs: {} };
    setGraph((g) => {
      const nodes = [...g.nodes, node];
      return { ...g, nodes, edges: nodes.slice(1).map((n, i) => ({ from: nodes[i].id, to: n.id })) };
    });
    setSelected(graph.nodes.length);
  };

  const removeNode = (idx: number) => {
    setGraph((g) => {
      const nodes = g.nodes.filter((_, i) => i !== idx);
      return { ...g, nodes, edges: nodes.slice(1).map((n, i) => ({ from: nodes[i].id, to: n.id })) };
    });
    setSelected(null);
  };

  const move = (idx: number, dir: -1 | 1) => {
    const j = idx + dir;
    if (j < 0 || j >= graph.nodes.length) return;
    setGraph((g) => {
      const nodes = [...g.nodes];
      [nodes[idx], nodes[j]] = [nodes[j], nodes[idx]];
      return { ...g, nodes, edges: nodes.slice(1).map((n, i) => ({ from: nodes[i].id, to: n.id })) };
    });
    setSelected(j);
  };

  const save = async () => {
    const input_schema = JSON.parse(inputSchemaText);
    const body = { name, description, input_schema, graph_json: { ...graph, edges: linearEdges } };
    if (tid) await ModulesApi.updateTask(mid, Number(tid), body as Partial<ModuleTask>);
    else { const created = await ModulesApi.createTask(mid, body); nav(`/modules/${mid}/tasks/${created.id}`); }
  };

  const run = async () => {
    const inputs = JSON.parse(runInputs);
    const r = await ModulesApi.runTask(mid, Number(tid), inputs);
    setRunOutput(r.status === "ok" ? r.output : `ERROR: ${r.error}`);
  };

  return (
    <div className="p-6 grid grid-cols-3 gap-6">
      <div className="col-span-3 flex gap-3 items-center">
        <input className="border rounded px-2 py-1 flex-1" placeholder="Task name" value={name} onChange={(e) => setName(e.target.value)} />
        <button className="px-3 py-1 bg-blue-600 text-white rounded" onClick={save}>Save</button>
        {tid && <button className="px-3 py-1 bg-green-600 text-white rounded" onClick={run}>Test run</button>}
      </div>
      <textarea className="col-span-3 border rounded p-2 font-mono text-xs"
        placeholder="Description shown to the agent" value={description} onChange={(e) => setDescription(e.target.value)} />
      <details className="col-span-3 border rounded p-2">
        <summary>Input schema (JSON)</summary>
        <textarea className="w-full border rounded p-2 font-mono text-xs" rows={6}
          value={inputSchemaText} onChange={(e) => setInputSchemaText(e.target.value)} />
      </details>

      <div className="col-span-2">
        <h3 className="font-semibold mb-2">Nodes</h3>
        <ul>
          {graph.nodes.map((n, i) => (
            <li key={n.id} className={`flex items-center gap-2 border-b py-2 ${selected === i ? "bg-blue-50" : ""}`}>
              <button className="text-xs" onClick={() => move(i, -1)}>▲</button>
              <button className="text-xs" onClick={() => move(i, +1)}>▼</button>
              <button className="flex-1 text-left" onClick={() => setSelected(i)}>
                <strong>{n.id}</strong> — {n.type === "llm" ? `LLM: ${(n.prompt ?? "").slice(0, 60)}` : `Tool: ${n.registry_id}`}
              </button>
              <button className="text-red-600 text-xs" onClick={() => removeNode(i)}>×</button>
            </li>
          ))}
        </ul>
        <div className="mt-3 flex gap-2">
          <button className="px-2 py-1 bg-gray-200 rounded" onClick={() => addNode("llm")}>+ LLM node</button>
          <button className="px-2 py-1 bg-gray-200 rounded" onClick={() => addNode("tool")}>+ Tool node</button>
        </div>
        <div className="mt-4">
          <label className="block text-sm font-medium">Output template</label>
          <input className="w-full border rounded p-1 font-mono text-xs"
            value={graph.output} onChange={(e) => setGraph((g) => ({ ...g, output: e.target.value }))} />
        </div>
      </div>

      <div>
        <h3 className="font-semibold mb-2">Node config</h3>
        {selected !== null && graph.nodes[selected] && (
          <NodeConfig
            node={graph.nodes[selected]}
            catalog={catalog}
            onChange={(p) => updateNode(selected, p)}
          />
        )}
        {tid && (
          <div className="mt-6">
            <h3 className="font-semibold mb-2">Test inputs (JSON)</h3>
            <textarea className="w-full border rounded p-1 font-mono text-xs" rows={4}
              value={runInputs} onChange={(e) => setRunInputs(e.target.value)} />
            <pre className="mt-2 p-2 bg-gray-50 border rounded text-xs whitespace-pre-wrap">{String(runOutput ?? "")}</pre>
          </div>
        )}
      </div>
    </div>
  );
}

function NodeConfig({ node, catalog, onChange }: {
  node: TaskNode; catalog: ToolCatalogItem[]; onChange: (p: Partial<TaskNode>) => void;
}) {
  if (node.type === "llm") {
    return (
      <div>
        <label className="block text-sm">Prompt</label>
        <textarea className="w-full border rounded p-1 font-mono text-xs" rows={10}
          value={node.prompt ?? ""} onChange={(e) => onChange({ prompt: e.target.value })} />
        <label className="block text-sm mt-2">Output variable</label>
        <input className="w-full border rounded p-1" value={node.output_var ?? ""}
          onChange={(e) => onChange({ output_var: e.target.value })} />
      </div>
    );
  }
  return (
    <div>
      <label className="block text-sm">Tool</label>
      <select className="w-full border rounded p-1" value={node.registry_id ?? ""}
        onChange={(e) => onChange({ registry_id: e.target.value })}>
        {catalog.map((c) => <option key={c.id} value={c.id}>{c.display_name || c.id}</option>)}
      </select>
      <label className="block text-sm mt-2">Inputs (JSON)</label>
      <textarea className="w-full border rounded p-1 font-mono text-xs" rows={8}
        value={JSON.stringify(node.inputs ?? {}, null, 2)}
        onChange={(e) => { try { onChange({ inputs: JSON.parse(e.target.value) }); } catch { /* keep typing */ } }} />
      <label className="block text-sm mt-2">Output variable</label>
      <input className="w-full border rounded p-1" value={node.output_var ?? ""}
        onChange={(e) => onChange({ output_var: e.target.value })} />
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web-ui/src/pages/modules/TaskEditorPage.tsx
git commit -m "feat(modules): linear-list TaskEditor with LLM + Tool nodes and test-run"
```

---

## Task 17: Module picker in chat header

**Files:**
- Modify: an existing chat header component (search `web-ui/src/` for a header/topbar component that owns the current chat)

- [ ] **Step 1: Locate the component**

```bash
grep -R "Conversation\|chat" web-ui/src/components/ -l | head
```

Pick the topmost header that has access to the current conversation id.

- [ ] **Step 2: Add a `<select>` showing available modules**

```tsx
import { useEffect, useState } from "react";
import { ModulesApi } from "../pages/modules/api";

export function ModulePicker({ conversationId, activeModuleId }: { conversationId: number; activeModuleId: number | null }) {
  const [items, setItems] = useState<{ id: number; display_name: string }[]>([]);
  useEffect(() => { ModulesApi.list().then((xs) => setItems(xs.filter((x) => x.enabled))); }, []);
  return (
    <select className="border rounded px-1 text-sm"
      value={activeModuleId ?? ""}
      onChange={async (e) => {
        const v = e.target.value ? Number(e.target.value) : null;
        await fetch(`/api/conversations/${conversationId}/active-module`, {
          method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ module_id: v }),
        });
      }}>
      <option value="">(no module)</option>
      {items.map((m) => <option key={m.id} value={m.id}>{m.display_name}</option>)}
    </select>
  );
}
```

Mount `<ModulePicker conversationId={...} activeModuleId={...} />` in the header. The conversation state store likely already holds `active_module_id`; thread it through.

- [ ] **Step 3: Commit**

```bash
git add web-ui/src/components/<header-file>.tsx web-ui/src/components/ModulePicker.tsx
git commit -m "feat(modules): per-conversation module picker in chat header"
```

---

## Task 18: REPL `/modules` slash command

**Files:**
- Modify: `atria/repl/commands/__init__.py` (or wherever slash commands are registered — `ls atria/repl/commands/`)

- [ ] **Step 1: Inspect the commands directory**

```bash
ls atria/repl/commands/
```

Pick a small existing command (e.g. `mcp`-related or `personas`) as a template.

- [ ] **Step 2: Add `modules.py`**

```python
"""/modules slash command: list modules and pick the active one."""

from atria.repl.commands.base import Command  # adjust to actual base import


class ModulesCommand(Command):
    name = "modules"
    help = "List modules and set the active one for this conversation"

    async def run(self, args: list[str], ctx) -> None:
        repo = ctx.modules_repo  # injected via your existing DI pattern
        items = await repo.list_modules()
        if not args:
            for m in items:
                marker = "*" if ctx.conversation.active_module_id == m.id else " "
                print(f"{marker} [{m.id}] {m.display_name}")
            return
        target = args[0]
        try:
            mid: int | None = int(target) if target != "none" else None
        except ValueError:
            print("usage: /modules [<id>|none]")
            return
        await ctx.conversation_repo.set_active_module(ctx.conversation.id, mid)
        print(f"active module set to {mid}")
```

- [ ] **Step 3: Register the command in the existing command registry** (follow the pattern used by the template command you copied).

- [ ] **Step 4: Commit**

```bash
git add atria/repl/commands/modules.py
git commit -m "feat(modules): REPL /modules slash command"
```

---

## Task 19: End-to-end real-API integration test

Per CLAUDE.md, "test" includes real API calls. This task verifies the full agent → module → LLM round-trip with `OPENAI_API_KEY`.

**Files:**
- Create: `tests/integration/test_modules_e2e.py`

- [ ] **Step 1: Create `tests/integration/test_modules_e2e.py`**

```python
"""End-to-end: agent uses a Task callable that calls a real LLM."""

import os
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atria.core.modules.loader import ModuleLoader
from atria.core.modules.registry import ToolRegistry
from atria.core.modules.seed import seed
from atria.db.models import Base
from atria.db.repositories.modules_repo import ModulesRepository


pytestmark = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"), reason="needs OPENAI_API_KEY"
)


@pytest_asyncio.fixture
async def sm():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_e2e_run_seeded_task_against_real_llm(sm):
    # Use the project's existing base-model factory.
    # Replace the import path with whatever your codebase exposes.
    from atria.core.runtime.config import get_base_llm_client  # adjust to real symbol

    llm = get_base_llm_client()
    await seed(sm)
    loader = ModuleLoader(sessionmaker=sm, llm_client=llm)

    repo = ModulesRepository(sm)
    mod = await repo.get_module_by_name("deep_analyze")
    loaded = await loader.load(mod.id)

    task = next(c for c in loaded.callables if c.kind == "task")
    out = await task.invoke({"text": "Ada Lovelace wrote the first algorithm in 1843."})
    assert isinstance(out, str) and len(out) > 0
```

NOTE: replace `from atria.core.runtime.config import get_base_llm_client` with the actual current factory the codebase uses to obtain the base async-callable LLM client. Search the repo for `OPENAI_API_KEY` or `AsyncOpenAI` to locate it.

- [ ] **Step 2: Commit**

```bash
git add tests/integration/test_modules_e2e.py
git commit -m "test(modules): end-to-end test against real LLM"
```

---

## Task 20: Final verification

- [ ] **Step 1: Run formatter, lint, typecheck**

```bash
make check
```

Resolve any reported issues.

- [ ] **Step 2: Run full test suite**

```bash
make test
```

All tests must pass. Per project memory ([[feedback_skip_per_task_tests]]) this is the **single** pytest run for the entire plan execution.

- [ ] **Step 3: Real-API end-to-end smoke (per CLAUDE.md)**

```bash
export OPENAI_API_KEY="..."
uv run pytest tests/integration/test_modules_e2e.py -v
```

Then start the app and verify in a browser:

```bash
make build-ui
make run
```

Open `/modules`, create a user module, edit Skill text, add a tool from the registry, build a 2-node Task in the editor, hit **Test run** with sample input, and confirm the output appears. Then open a chat conversation, pick the module from the header dropdown, ask the agent to use the seeded task, and confirm it runs.

- [ ] **Step 4: Commit final fixes (if any)**

```bash
git status
git add -A
git commit -m "chore(modules): post-verification fixes"
```

---

## Out of scope (deferred to a follow-up plan)

- Branch / loop / conditional nodes
- React Flow visual editor
- Per-step model override
- Module export/import as files
- Marketplace / third-party publishing
- Optimistic-concurrency `updated_at` enforcement (currently best-effort; revisit when multi-user editing is real)
- Migration of `domain_enrich` (mirror Task 14 once `deep_analyze` is proven)
