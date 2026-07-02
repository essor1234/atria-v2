# Module Chat Gates & Block Persistence — Design

**Date:** 2026-07-02
**Status:** Draft for review

## Summary

Open more capability "gates" from the **core/backend** so chat-embedded module
UI (blocks/components) can interact with the chat, read system state, and call
back into the system — **without changing how modules are authored**. Existing
modules keep working and opt into new power purely from their client-side JS.

Separately, make **every block put into the chat durably persisted to the
Postgres database** (currently persistence is best-effort, JSON-only, and lossy
for block messages).

This spec covers the backend gate layer and the persistence fix. A later phase
(native Web Components + `<ModuleComponent>` mount) is a frontend consumer of
these gates and is out of scope here.

## Background / current state

Module chat UI today flows through two asymmetric surfaces:

- **Chat surface** (`web-ui/src/components/Chat/SandboxedBlock.tsx`): an iframe
  that is intentionally **view-only** — it drops all outbound RPC/events and
  allows only a single free-text `chat` message back to the agent.
- **Dashboard surface** (`atria/web/dashboard_assets/__bridge.js`, `AtriaDash`):
  fully interactive — can `run()` the module's own scripts via
  `POST /api/modules/{name}/run`.

Backend capability gates for blocks live in
`atria/web/websocket.py::_handle_block_rpc`, dispatched over the WebSocket and
gated by an allowlist config `config.web.iframe_rpc.tool_allowlist`
(`atria/models/config.py:103`). Current methods:

- `tool.invoke` — invoke any registered agent tool (approval-managed)
- `artifact.read` — read one artifact
- `session.send_user_message` — inject a user message

Server → chat rendering is done by `atria/web/ui_bridge.py::push_block`, which
broadcasts a `custom_block` WS event and (when `persist=True`) appends a
`custom_block`-role `ChatMessage`.

### Persistence: current gaps (grounding)

- `push_block` persistence (`ui_bridge.py::_persist_block_message`, lines
  176–226) is **fire-and-forget, error-swallowing, and routed through whatever
  `session_manager` is bound** — historically the JSON file manager.
- The Postgres path loses block messages entirely:
  - `atria/db/models.py:111` — `messages.role` is `String(10)`;
    `message_repo.insert` does `role=message.role.value[:10]`, so
    `custom_block` (12 chars) truncates to `custom_blo`.
  - `message_repo._blocks_to_msg` (line 49) reconstructs role as
    `Role.ASSISTANT if tool_calls else Role.USER` — it **does not preserve the
    `custom_block` role or its metadata** (block_id, module, block, src, props,
    height, title). Blocks collapse to a plain user/assistant message on reload.
  - `pg_manager.save_session` inserts unpersisted messages "by count."

## Goals

1. Widen the backend gate set available to chat blocks (read chat/state,
   subscribe to agent events, list artifacts, typed module RPC, read config) —
   all implemented core-side, gated and permissioned.
2. Let the agent render a module block into the chat mid-turn via a first-class
   tool.
3. Make every chat block **mandatorily and faithfully persisted to Postgres**,
   surviving reload with full role + metadata.

## Non-goals

- No changes to module authoring contract. Modules are not required to add or
  edit files to keep working; new gates are opt-in from client JS.
- Native Web Component embedding / `<ModuleComponent>` mount — deferred to a
  later phase.
- Multi-tenant/untrusted hardening beyond the existing allowlist + permission
  checks (modules are first-party/trusted).

## Design

### A. Backend gate layer (widen `block_rpc`)

Extend `_handle_block_rpc` (`atria/web/websocket.py:429`) with new methods,
each added to the `tool_allowlist` config and subject to the existing
allowlist check. All read paths are **session-scoped** — a block may only read
the session it was rendered in (resolved via the existing
`session_id`/contextvar path).

New methods:

- `chat.get_messages` — return the conversation transcript for the active
  session. Reads via the active session manager
  (`state.session_manager.get_session_by_id` → messages). Supports optional
  `limit`/`before` args for windowing. Returns serialized `ChatMessage`s.
- `chat.get_session` — return session/conversation metadata + status (id,
  title, mode, message count, running state).
- `events.subscribe` — register the calling block to receive a **filtered feed**
  of agent turn events the backend already broadcasts (`tool_call`,
  `tool_result`, `message_chunk`/`message_complete`, `thinking`,
  `turn`/`session_activity`). Implemented by tagging the block on the WS
  connection and forwarding matching broadcasts as a new `block_event_feed`
  WS message. Unsubscribe on block removal / socket close.
- `artifact.list` — list artifacts for a scope (`conversation|project|both`),
  complementing existing `artifact.read`. Uses `ArtifactsHandler` /
  `artifact_repo`.
- `config.read` — read a **whitelisted** subset of config keys (read-only). A
  hardcoded key allowlist prevents leaking secrets.
- `module.rpc` — typed call into a module's own backend handler. Dispatches to
  `POST /api/modules/{name}/rpc` (see §C). The gate exists regardless of whether
  a given module ships a handler; modules opt in with a `scripts/rpc.py`. No
  change forced on existing modules.

Existing methods (`tool.invoke`, `artifact.read`,
`session.send_user_message`) are unchanged.

Method dispatch keeps the current structure: synchronous/off-thread work via
`_run_sync` with the 5s `wait_for` timeout; async injection paths in
`_dispatch`. `chat.get_messages`/`chat.get_session`/`artifact.list` run through
async repo calls; `events.subscribe` mutates per-connection subscription state;
`config.read` is a cheap sync read.

**Permissioning.** Each method remains gated by
`config.web.iframe_rpc.tool_allowlist`. Add sensible defaults so the new
read-only gates (`chat.get_messages`, `chat.get_session`, `events.subscribe`,
`artifact.list`, `config.read`) are enabled out of the box; `tool.invoke`,
`session.send_user_message`, and `module.rpc` stay opt-in. `tool.invoke`
continues to route through `approval_manager`.

### B. Agent-triggerable render tool

Add a first-class agent tool `render_component` (backend, in the tool registry)
so the agent can put a block into the chat mid-turn:

`render_component(module, block, props, height="auto", title=None)` →
calls `ui_bridge.push_block(...)` with the active session bound via the
contextvar. Returns the resolved `block_id`. Reuses `push_block`'s existing
resolution, prop serialization (256 KB cap), WS broadcast, and — via §D —
mandatory DB persistence.

Schema follows the existing tool-schema conventions
(`atria/core/agents/components/schemas/builtin/`). Prompt guidance: the agent
renders a module block when a visual/interactive result is more useful than
prose; it must not fabricate module/block names (validated against the
registry, raising `BlockNotFound`).

### C. Typed module RPC route (`module.rpc` target)

New route `POST /api/modules/{name}/rpc` in
`atria/web/routes/module_dashboard.py`, reusing the existing subprocess
infrastructure (`_resolve_script`, concurrency caps via `_try_acquire`/
`_release`, timeout, `ATRIA_SESSION_ID`/`ATRIA_MODULE_ROOT`/`ATRIA_API_BASE`
env). It runs the module's declared handler `scripts/rpc.py` with a JSON
`{method, payload, session_id}` on stdin and returns the handler's JSON stdout.

Distinct from `tool.invoke` (generic tool registry) — this is a **module-owned,
typed channel**. Existing modules without `scripts/rpc.py` simply return a
404-style "no rpc handler" error; nothing breaks.

### D. Mandatory DB block persistence

Route **every** chat block through one persistence path that writes to Postgres
transactionally and surfaces errors (no more fire-and-forget).

1. **Widen the role column.** DB migration: `messages.role` `String(10)` →
   `String(32)`. Update `message_repo.insert` to stop truncating (`role=
   message.role.value` or `[:32]`).
2. **Preserve block role + metadata across the round-trip.** Extend
   `message_repo._msg_to_blocks` to serialize the `custom_block` role and its
   metadata (block_id, module, block, src, props, height, title) into the
   `blocks` JSON, and `_blocks_to_msg` to reconstruct a `Role.CUSTOM_BLOCK`
   message from it (instead of collapsing to user/assistant). Keep the existing
   user/assistant/tool reconstruction as the fallback.
3. **Make `push_block` persistence reliable and DB-first.** Replace
   `ui_bridge._persist_block_message`'s best-effort JSON write with a call that
   appends the `custom_block` message to the active session and persists it —
   when `pg_manager` is active this inserts via `message_repo`. Persistence is
   **mandatory** when `persist=True`: a persistence failure is logged and
   surfaced to the caller (the `render_component` tool result / `push_block`
   return), not silently swallowed. Ordering: persist before or independently of
   the WS broadcast so a reload always reflects what the user saw.

Since the primary target is Postgres repos, the JSON `session_manager` remains a
legacy fallback but is not the guarantee surface.

## Data flow

- **Agent renders a block:** agent turn → `render_component` tool →
  `push_block` → (a) mandatory DB insert via `message_repo`, (b) `custom_block`
  WS broadcast → frontend renders the block.
- **Block reads chat/state:** block JS → `block_rpc {method:"chat.get_messages"}`
  → allowlist check → session-scoped repo read → `block_rpc_result`.
- **Block subscribes to turns:** block JS → `block_rpc {method:"events.subscribe"}`
  → connection tagged → subsequent agent events forwarded as `block_event_feed`.
- **Block calls its own backend:** block JS → `block_rpc {method:"module.rpc"}`
  → `POST /api/modules/{name}/rpc` → `scripts/rpc.py` → JSON → `block_rpc_result`.
- **Reload:** session loads from Postgres → block messages reconstructed with
  full role + metadata → re-rendered.

## Error handling

- Method not in allowlist → `method_not_allowed` (existing pattern).
- `chat.*`/`artifact.list` with no resolvable session → `no active session`.
- `module.rpc` with no `scripts/rpc.py` → `unknown-rpc-handler` 404-style error;
  non-zero exit / bad JSON / timeout → structured error (mirrors `/run`).
- `config.read` of a non-whitelisted key → `key_not_allowed`.
- Block persistence failure → logged at error level and returned to the caller;
  the `render_component` tool reports the failure rather than claiming success.
- Unregistered module/block in `render_component` → `BlockNotFound`.

## Testing

Per project policy: unit tests **and** real-API end-to-end (`OPENAI_API_KEY`).

**Unit**
- New `block_rpc` methods: allowlist enforcement, session scoping,
  `chat.get_messages`/`chat.get_session` shape, `artifact.list`, `config.read`
  whitelist, `events.subscribe` tagging + `block_event_feed` forwarding.
- `POST /api/modules/{name}/rpc`: path-escape rejection, timeout, non-zero exit,
  JSON round-trip, missing-handler error.
- `render_component` tool: schema validation, `BlockNotFound` on bad name,
  successful `push_block` invocation.
- Persistence: migration widens `messages.role`; `_msg_to_blocks`/
  `_blocks_to_msg` round-trip preserves `custom_block` role + metadata;
  `push_block(persist=True)` inserts via `message_repo`; persistence failure
  surfaces (not swallowed).

**End-to-end (real API)**
- Start the web UI with Postgres configured. Have the agent call
  `render_component` for an existing module block; confirm the block renders,
  a row lands in `messages` with the full role/metadata, and it survives a
  session reload.
- From the rendered block, exercise `chat.get_messages`, `events.subscribe`
  (observe a live agent turn), and — for a module that ships `scripts/rpc.py` —
  a `module.rpc` round-trip.

## Phasing

- **Phase 1:** DB persistence fix (§D) + `chat.get_messages` / `chat.get_session`
  / `artifact.list` / `config.read` gates + `render_component` tool.
- **Phase 2:** `events.subscribe` + `block_event_feed` forwarding.
- **Phase 3:** `module.rpc` route + gate.
- **Later (out of scope):** native Web Component mount (`<ModuleComponent>`,
  `host` SDK) consuming these gates.

## Open questions

- Exact default `tool_allowlist` entries shipped enabled vs opt-in.
- Whitelisted key set for `config.read`.
- Windowing/pagination defaults for `chat.get_messages` on long sessions.
