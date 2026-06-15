# Modulize the Repo — Design

Date: 2026-06-15
Status: Approved (brainstorming)

## Goal

Turn the existing "skill" concept (e.g. `atria/skills/builtin/deep_analyze/`) into a first-class **Module** abstraction whose internals are configurable through the Web UI. Two motivations:

1. End-user customization — non-developers can edit prompts, toggle tools, and compose multi-step task workflows without touching code.
2. Faster developer iteration — devs can change prompts and pipelines without redeploys.

## Concept Model

A **Module** has three configurable layers:

- **Skill** — a markdown document (like `SKILL.md`) that guides the agent on *what this module is for*, *when to use it*, and *how to think about the flow*. Edited as text in the UI.
- **Tools** — Python functions registered with stable IDs (`@register_tool`). Atomic units of execution. Devs write these; the UI lists/toggles/configures them per module.
- **Tasks** — user-built workflow pipelines made of nodes (v1: LLM node + Tool node). Each Task is exposed to the agent as a single callable. Tasks let the user compose multi-step flows that a single tool can't express.

The agent sees a **unified flat list of callables** combining bound Tools and Tasks. Whether a callable is a Python function or a multi-node workflow is invisible to the agent.

Model parameters are **not** per-step. Every LLM node uses the global base model from configuration.

## Architecture

New top-level package `atria/core/modules/` owns the abstraction. Built-in modules (`deep_analyze`, `domain_enrich`) migrate into it as seeded DB rows plus registered Python tools.

```
atria/core/modules/
  __init__.py
  registry.py        # global ToolRegistry (Python-side decorator registration)
  loader.py          # DB row -> runtime Module (lazy + cached)
  models.py          # Module, ToolCallable, TaskCallable, Node dataclasses
  executor/
    task_executor.py # walks the Task graph, validates, runs nodes
    nodes/
      llm_node.py
      tool_node.py
  builtins/
    deep_analyze/
      tools.py       # @register_tool('deep_analyze.extract_entities') ...
      seed/
        skill.md
        tasks/*.json
    domain_enrich/
      tools.py
      seed/...
  seed.py            # idempotent DB seeding of built-in modules

atria/db/repositories/modules_repo.py    # CRUD for the new tables
atria/web/routes/modules.py              # REST endpoints
web-ui/src/pages/modules/                # UI pages
```

The Agent layer (`atria/core/agents/main_agent.py`) gets a thin adapter that asks `ModuleLoader` for the active module's callables and exposes them as ReAct tools. Module `skill_md` is injected into the system prompt as a `PromptComposer` section.

## Data Model

Five tables (added to `schema.sql`):

```sql
CREATE TABLE modules (
  id           INTEGER PRIMARY KEY,
  name         TEXT NOT NULL UNIQUE,        -- e.g. 'deep_analyze'
  display_name TEXT NOT NULL,
  description  TEXT,
  enabled      INTEGER NOT NULL DEFAULT 1,
  is_builtin   INTEGER NOT NULL DEFAULT 0,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);

CREATE TABLE module_skills (
  module_id    INTEGER PRIMARY KEY REFERENCES modules(id) ON DELETE CASCADE,
  content_md   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);

CREATE TABLE module_tools (
  id             INTEGER PRIMARY KEY,
  module_id      INTEGER NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
  registry_id    TEXT NOT NULL,
  display_name   TEXT NOT NULL,
  enabled        INTEGER NOT NULL DEFAULT 1,
  config_json    TEXT NOT NULL DEFAULT '{}',
  UNIQUE(module_id, registry_id)
);

CREATE TABLE module_tasks (
  id              INTEGER PRIMARY KEY,
  module_id       INTEGER NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
  name            TEXT NOT NULL,
  description     TEXT NOT NULL,
  input_schema    TEXT NOT NULL DEFAULT '{}',
  graph_json      TEXT NOT NULL,
  enabled         INTEGER NOT NULL DEFAULT 1,
  updated_at      TEXT NOT NULL,
  UNIQUE(module_id, name)
);

CREATE TABLE task_runs (
  id              INTEGER PRIMARY KEY,
  task_id         INTEGER NOT NULL REFERENCES module_tasks(id) ON DELETE CASCADE,
  status          TEXT NOT NULL,             -- 'ok' | 'error'
  inputs_json     TEXT NOT NULL,
  outputs_json    TEXT,
  error           TEXT,
  duration_ms     INTEGER,
  created_at      TEXT NOT NULL
);
```

Sessions get a new column: `sessions.active_module_id INTEGER NULL REFERENCES modules(id)`.

### `graph_json` shape (v1)

```json
{
  "nodes": [
    {"id":"n1","type":"llm","prompt":"Extract entities from {{input.text}}","output_var":"entities"},
    {"id":"n2","type":"tool","registry_id":"deep_analyze.lookup","inputs":{"name":"{{n1.entities[0]}}"},"output_var":"hits"}
  ],
  "edges": [{"from":"n1","to":"n2"}],
  "output":"{{n2.hits}}"
}
```

Variable interpolation: Jinja2 sandbox against a context built from `input.*` and prior nodes' `output_var` results.

### Versioning policy

Single mutable row per module. Built-in seeds populate the row on first run; subsequent runs do not overwrite user edits. A **Reset to default** UI action re-runs the seeder for that specific module.

## Runtime

### `ToolRegistry` — `atria/core/modules/registry.py`

Process-wide singleton populated at import time:

```python
@register_tool(
    id="deep_analyze.extract_entities",
    description="Extract named entities from text",
    input_schema={...},
)
def extract_entities(text: str) -> list[str]: ...
```

API: `registry.get(id) -> ToolSpec`, `registry.list() -> list[ToolSpec]`. Built-ins under `atria/core/modules/builtins/*/tools.py` are imported by `atria/core/modules/__init__.py` so registration always happens at startup.

### `ModuleLoader` — `atria/core/modules/loader.py`

Reads DB rows into a runtime `Module`:

```python
@dataclass
class Module:
    name: str
    skill_md: str
    callables: list[Callable]   # union of ToolCallable | TaskCallable
```

Both `ToolCallable` and `TaskCallable` implement the same interface: `name`, `description`, `input_schema`, `invoke(inputs) -> output`. Loader is lazy and per-module cached; cache invalidated on UI edit via `bump_version(module_id)`.

### `TaskExecutor` — `atria/core/modules/executor/task_executor.py`

```python
def execute(graph: dict, inputs: dict) -> Any:
    validate(graph)                      # cycle detection, dangling edges, unknown node types
    ctx = {"input": inputs}
    for node in topological_order(graph):
        result = NODE_TYPES[node["type"]].run(node, ctx)
        if node.get("output_var"):
            ctx[node["id"]] = {node["output_var"]: result}
    return render_template(graph["output"], ctx)
```

Node runners:
- `LlmNode.run` — render prompt template against `ctx`, call base model from global config, return text. Optional JSON-parse if `output_schema` set on the node.
- `ToolNode.run` — look up registry tool by id, render each mapped input value, invoke, return result.

v1 rejects cyclic graphs at validation time with a clear error.

## UI

### Backend endpoints — `atria/web/routes/modules.py`

```
GET    /api/modules
POST   /api/modules
GET    /api/modules/{id}
PATCH  /api/modules/{id}
DELETE /api/modules/{id}                  # only if !is_builtin
PUT    /api/modules/{id}/skill
GET    /api/modules/{id}/tools
POST   /api/modules/{id}/tools
PATCH  /api/modules/{id}/tools/{bid}
DELETE /api/modules/{id}/tools/{bid}
GET    /api/modules/{id}/tasks
POST   /api/modules/{id}/tasks
GET    /api/modules/{id}/tasks/{tid}
PUT    /api/modules/{id}/tasks/{tid}
DELETE /api/modules/{id}/tasks/{tid}
POST   /api/modules/{id}/tasks/{tid}/run
GET    /api/modules/{id}/tasks/{tid}/runs
GET    /api/tool-registry                 # full Python registry catalog
POST   /api/modules/{id}/reset            # re-seed a builtin module
```

PUT requests carry the row's `updated_at` for optimistic concurrency; mismatch returns 409.

### Frontend pages — `web-ui/src/pages/modules/`

1. **ModulesListPage** — table of modules, enable toggle, "+ New module" button.
2. **ModuleDetailPage** — three tabs:
   - **Skill** — full-width markdown editor (CodeMirror w/ markdown mode). UI shows a soft warning when content exceeds ~4k chars.
   - **Tools** — left: bound tools list (enable toggle, edit config). Right: "Add tool" drawer showing the registry catalog. Missing registry IDs render as a red "missing implementation" row.
   - **Tasks** — list of tasks with name/description; click to open the task editor.
3. **TaskEditorPage** — **linear list editor for v1** (ordered list of nodes, drag-handle reorder, add/remove). Each row shows node type + summary; clicking opens a side panel:
   - LLM node panel — prompt template editor with `{{var}}` autocomplete over `input.*` and prior `output_var` names.
   - Tool node panel — registry picker, input mapping form (key → `{{...}}` template).
   - Top bar — name, description, input schema editor (simple JSON Schema form), Save, "Test run" drawer (sample-input form → output + per-node trace from the most recent `task_runs` row).

Linear list is the v1 editor because the v1 graph is effectively linear (no branch/loop). When branch/loop nodes are added later, swap in React Flow.

### Auth/scoping

Uses existing auth context in `atria/core/auth/`. Built-in modules (`is_builtin=1`) cannot be deleted from UI, but their skill/tools/tasks are user-editable.

## Agent Integration

A conversation has at most one active module (`sessions.active_module_id`, nullable — `NULL` means agent uses only its built-in tool set).

Switching is user-driven: a module picker in the chat header (Web UI) and a `/modules` slash command in the REPL. The agent cannot switch modules mid-turn; it can only recommend.

In `main_agent.py`:

```python
if session.active_module_id:
    module = module_loader.load(session.active_module_id)
    agent_tools.extend(adapt_to_agent_tools(module.callables))
    system_prompt = compose(system_prompt, module.skill_md)
```

`adapt_to_agent_tools` wraps each `Callable` as the dict shape `ToolRegistry` already expects. Tools and Tasks share the same interface, so the adapter has no branch logic.

`skill_md` is injected by `PromptComposer` as a new `module_skill` section, priority high enough to land after core agent instructions but before tool descriptions. A `verbose_tasks` setting (off by default) controls whether per-node task traces stream into the chat as collapsible events.

## Error Handling

- **Registry miss** — DB binding references a `registry_id` not present in the Python registry. Loader skips the binding, logs a warning, surfaces a red "missing implementation" row in the Tools tab. Module remains loadable.
- **Task graph errors** — cycle, dangling edge, unknown node type, malformed Jinja, missing variable. `TaskExecutor` validates before execution and raises `TaskValidationError` with the offending node id. The task editor calls the same validator on save and surfaces errors inline.
- **Tool runtime errors** — caught by `TaskExecutor`, written to `task_runs`, surfaced to the agent as a normal tool error so the ReAct loop can recover.
- **LLM errors** (rate-limit/timeout) — retried once with backoff by the existing model client; otherwise surfaced as tool errors.
- **Concurrent UI edits** — optimistic concurrency via `updated_at` mismatch → 409.

## Testing

- **Unit** (`tests/core/modules/`): registry registration, loader DB→Module mapping, executor per-node logic, Jinja rendering edge cases, cycle detection, graph validator.
- **Integration**: end-to-end task run against a sqlite test DB — create module → bind tool → build task → invoke → assert `task_runs` row + return value.
- **Agent**: `MainAgent` runs with an active module, picks a Task callable, task executes, agent sees the result. Per CLAUDE.md, uses `OPENAI_API_KEY`.
- **UI**: Playwright smoke test through the three tabs + linear task editor save/test-run.

Per project memory, no per-task pytest runs during plan execution — single pytest run at the end.

## Migration

Existing `atria/skills/builtin/deep_analyze/` mixes code with the SKILL doc. Migration steps:

1. Move atomic Python functions from `tools.py`, `dataloader.py`, `profiler.py` into `atria/core/modules/builtins/deep_analyze/tools.py`. Register each with a stable `deep_analyze.*` id.
2. Convert the current `pipeline.py` orchestration into one or more **seeded Tasks** as JSON graph files under `atria/core/modules/builtins/deep_analyze/seed/tasks/*.json`.
3. Convert prompt strings from `prompts.py` into LLM node prompt templates inside those task graphs.
4. Convert `SKILL.md` into the seeded `skill_md` content (verbatim).
5. `seed.py` upserts the module + skill + tool bindings + tasks at first run (idempotent by name; does not overwrite existing rows).
6. Leave the old `atria/skills/builtin/deep_analyze/` directory in place for one release marked deprecated; remove after parity is verified.
7. `domain_enrich` follows the same procedure.

During transition, agent code checks both the legacy skills surface and the new `ModuleLoader`, preferring the new one when both define a same-named callable.

## Out of Scope (v1)

- Branch / conditional / loop nodes — deferred until linear is proven.
- Visual DAG editor (React Flow) — added when branch/loop arrive.
- Per-step model override — base model from global config only.
- Plugin marketplace / third-party module distribution.
- Multi-user permissions on modules.
- Fork-on-edit versioning of builtin modules (single mutable row + Reset action instead).
- Export/import of modules as files (can be added later by serializing the same JSON shape stored in DB).
