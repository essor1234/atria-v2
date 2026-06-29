# Module Subagent Gateway — Design

**Status:** Approved (brainstorming) — ready for implementation planning.
**Date:** 2026-06-27
**First consumer:** `modules/item_flow_tracking/`

## Goal

Let a module declare that its operations run through a **dedicated, specialized
subagent** instead of being executed inline by the main agent. A **gateway**
injects the module's own context (its skill summary + lazy sub-skill index) into
that subagent's system prompt, so the subagent is a domain expert from the first
turn. The mechanism is **general for every module**, not hard-wired to
`item_flow_tracking`.

This satisfies four motivations the user selected:

1. **Context isolation** — noisy `flow.py` CLI output stays in the subagent's
   context, not the main conversation.
2. **Background/durable (TaskIQ)** — reuses the existing `run_in_background`
   path; it becomes durable automatically once the in-progress TaskIQ work
   (Tasks 3–10 of `2026-06-27-taskiq-background-subagents.md`) lands. The gateway
   does **not** block on TaskIQ.
3. **Module-specialized agent** — one subagent type per agent-backed module,
   shown by name in the `spawn_subagent` enum so the model picks the right
   specialist.
4. **General mechanism for all modules** — any module opts in via
   `manifest.json`; no per-module code.

## Decisions locked during brainstorming

- **Gateway context shape:** *summary + lazy sub-skills* — the subagent receives
  the same lazy module block the main agent sees (description, "When to use",
  sub-skill index, modules root, how to run scripts) and pulls detail on demand
  with `invoke_skill`. Not the full `SKILL.md` inlined.
- **Dispatch trigger:** *delegate by judgement* — the main agent decides;
  heavy/multi-step work (create order, move several lots) → delegate, quick
  lookups (`order list`, "where is X") → inline. The inline path is **kept**.
  Guidance lives in the Active Modules prompt block; no hard-coded routing
  (per the CLAUDE.md rule against if/else branching for conversation flow).
- **TaskIQ sequencing:** *independent* — build now, reuse `run_in_background`
  as-is. Foreground works today; background gains durability when TaskIQ is done.
- **Registration approach (A):** module-derived `SubAgentSpec`s registered
  through the existing `SubAgentManager.register_subagent`, so they flow into
  `get_agent_configs()` and the `spawn_subagent` enum with no schema changes.

## Architecture

```
manifest.json (subagent block)
        │
        ▼
ModuleRegistry ──► module_subagent_specs(registry) ──► [SubAgentSpec, …]
        │                     │
        │                     ├─ build_module_gateway_block(module)  ← THE GATEWAY
        │                     └─ WORKER_BASE prompt (templates/subagents/module-worker.md)
        ▼                     ▼
AgentFactory.create() ──► manager.register_subagent(spec)  (after register_defaults + custom)
        │
        ▼
SubAgentManager.get_agent_configs() ──► spawn_subagent enum  (type = module name)
        │
        ▼
Main agent (reads Active Modules block) ──judgement──► spawn_subagent(subagent_type="<module>", …)
```

## Components

### a. Manifest declaration

`manifest.json` gains an optional block:

```json
"subagent": {
  "enabled": true,
  "model": null,
  "tools": null
}
```

- `enabled: true` opts the module in. Absent block → unchanged behaviour
  (module runs inline exactly as today). This is what makes the mechanism
  universal without forcing it on every module.
- `model` — optional model override for the subagent (else inherits parent).
- `tools` — optional tool-name list. Default:
  `["run_command", "invoke_skill", "read_file", "write_file"]`
  (`run_command` is the bash tool; `invoke_skill` loads sub-skills lazily;
  read/write cover data export/inspection).

### b. Gateway builder — `atria/core/modules/subagent.py` (new)

- `build_module_gateway_block(module) -> str` — single-module variant of the
  logic in `atria/core/modules/prompt.py`. Emits: one-line description,
  "When to use" triggers, sub-skill index, modules root, and the absolute-path
  rule for running `scripts/*.py`. **This block is the gateway** — the module
  context handed to the subagent.
- `module_subagent_specs(registry) -> list[SubAgentSpec]` — iterates
  agent-backed modules and builds, per module:
  `SubAgentSpec(name=<module-name>, description=<module description>,
  system_prompt=WORKER_BASE + "\n\n" + gateway_block, tools=<resolved>,
  model=<optional>)`.
- `WORKER_BASE` — a base worker prompt loaded from
  `templates/subagents/module-worker.md`: "You are the dedicated worker for
  module X. Load detail with invoke_skill before guessing flags. Always use
  absolute paths. Return a concise result, not a transcript."

### c. Registration — `atria/core/base/factories/agent_factory.py`

`AgentFactory.create()` calls a new `_register_module_subagents()` **after**
`register_defaults()` and `_register_custom_agents()`:

1. `from atria.core.modules.registry import get_registry`
2. `for spec in module_subagent_specs(registry): manager.register_subagent(spec)`

Registered specs land in `SubAgentManager._agents`, surface through
`get_agent_configs()` (custom-agent path), and therefore appear in the
`spawn_subagent` enum automatically. Wrapped in try/except + log; a registry or
manifest failure must not break agent construction.

Runtime add/remove: the module watcher refreshes the registry; re-sync by
re-deriving and re-registering specs (registry is versioned, so changes are
detectable). Built-in names win on collision (existing
`if any(c.name == name)` guard); module specs are named after the module, so
collisions are unlikely.

### d. Dispatch guidance — `atria/core/modules/prompt.py`

The Active Modules block annotates each agent-backed module: "This module has a
dedicated subagent `<name>`. For multi-step/heavy work, delegate with
`spawn_subagent(subagent_type='<name>')`; quick lookups may run inline." The
model decides per turn — no code-level routing.

## Data flow

1. User asks (e.g. "tạo đơn 3 bin cho 090…").
2. Main agent reads the Active Modules block, judges the task heavy → calls
   `spawn_subagent(subagent_type="item_flow_tracking", prompt="…full context…")`.
3. Manager builds the subagent with the gateway-injected system prompt.
4. Subagent uses `invoke_skill` (only if it needs a flag it doesn't know) and
   `run_command` to run `flow.py`; CLI noise stays in the subagent's context.
5. Subagent returns a concise result to the main agent, which summarizes for the
   user. → context isolation achieved.

Background variant: identical, but the main agent passes
`run_in_background=true`; today it runs in-thread, later durably via TaskIQ —
no gateway change required.

## Error handling

- No `subagent` block / `enabled` falsey → module not registered (safe default;
  inline path unchanged).
- Malformed manifest or missing field → swallow + `logger.warning` (mirrors the
  existing `_safe_module_block` pattern); never block the factory.
- Empty/erroring registry → `module_subagent_specs` returns `[]`.
- Name collision with a built-in subagent → built-in wins (existing guard).

## Testing

Per CLAUDE.md, both unit tests **and** real end-to-end simulation with
`OPENAI_API_KEY` are required.

- **Unit:**
  - `build_module_gateway_block` contains description, sub-skill index, modules
    root, and the absolute-path rule.
  - `module_subagent_specs` yields a spec only for modules with
    `subagent.enabled == true`; a manifest without the block yields zero specs.
  - Default tool list resolves to
    `["run_command", "invoke_skill", "read_file", "write_file"]`; explicit
    `tools`/`model` overrides are honoured.
- **Integration:** after `AgentFactory.create()`,
  `manager.get_agent_configs()` includes `item_flow_tracking`, and the
  `spawn_subagent` schema enum lists it.
- **E2E:** spawn the `item_flow_tracking` subagent to create a real order and
  run `order list`; verify the result returns to the main agent concisely and
  the CLI noise does not appear in the main conversation.

## Scope / YAGNI

**In scope:** manifest declaration, gateway builder, factory registration,
dispatch guidance in the Active Modules block, `item_flow_tracking` as the first
opted-in module.

**Out of scope:** live streaming from subagent; forcing background by default;
any UI for choosing a subagent; changes to the local TUI's synchronous inline
path; changes to the TaskIQ tasks themselves (we only reuse `run_in_background`).

## Related

- `docs/superpowers/plans/2026-06-27-taskiq-background-subagents.md` — supplies
  the durable background substrate that `run_in_background` will use; this design
  is independent of its completion.
