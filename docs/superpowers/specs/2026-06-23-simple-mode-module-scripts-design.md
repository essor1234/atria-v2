# Simple Mode — Silent, Friendly Module Scripts

**Date:** 2026-06-23
**Status:** Approved design (pending spec review)

## Problem

The app targets **non-technical users**. Today, when the agent runs a module
script (e.g. `python <modules>/warehouse/scripts/inventory.py receive --sku …`),
the chat screen shows:

1. A blocking **approval dialog** with raw command text, file paths, and
   approve/deny/auto-approve buttons.
2. A technical **tool-call card** showing the command and its stdout/exit code.

Both are confusing and intimidating for the target user. We want module scripts
to run **silently** (no approval prompt) and to surface as **plain-language
activity** ("⏳ Receiving stock…" → "✅ Stock received") instead of technical
cards.

## Goals

- A non-technical user **never** sees an approval dialog or raw command text.
- Module script execution shows as a friendly, animated activity line that
  collapses to a quiet confirmation when done.
- Keep a hard safety floor: genuinely dangerous commands are still **refused**
  (not prompted) — "never ask" is not "run anything."
- Developers can revert to the full technical view + approvals via a setting.

## Non-goals

- Per-command granular trust UI for end users (they see nothing technical).
- Changing the agent loop / ReAct behavior.
- Reworking the existing approval-rules engine; we gate on top of it.

## Design decisions (from brainstorming)

- **Trust scope:** full auto — nothing prompts. (User choice.)
- **In-chat display:** friendly activity line, no commands/paths/buttons.
- **Label source:** per-action labels declared in the module's `manifest.json`.
- **Simple Mode default:** ON globally; toggled in `settings.json`.

## Architecture overview

A deployment-level **Simple Mode** flag (default ON). When ON:

- Every tool call is **auto-approved** at the existing approval gate — no
  approval request is ever broadcast, so the frontend dialog never mounts.
- The frontend replaces the technical tool-call card with a
  **`ModuleActivityLine`** driven by an `activity` payload attached to the
  tool-call event.
- A backend helper resolves a friendly `{running, done}` label from the module
  manifest based on the script path + first subcommand token.

When OFF (developer mode): everything reverts to today's behavior — approvals
and technical cards. Nothing is removed, only gated.

## Components

### 1. Simple Mode config flag

- Add a boolean to the app config / `settings.json` schema, default **True**
  (e.g. `ui.simple_mode` in `atria/models/config.py`).
- Surfaced to the web layer so both the backend approval gate and the frontend
  can read it (frontend reads it via existing session/config state).

### 2. Backend auto-approve gate

- At the single existing decision point
  (`atria/web/web_approval_manager.py` request logic, reached from
  `atria/core/context_engineering/tools/handlers/process_handlers.py:_ensure_command_approval`):
  when Simple Mode is ON, return an approved result **without** broadcasting an
  approval request.
- **Safety floor preserved:** the existing `DANGEROUS_PATTERNS` / deny-pattern
  checks in `atria/core/context_engineering/tools/implementations/bash_tool/security.py`
  still run and **hard-block** (refuse, not prompt) destructive commands
  (`rm -rf /`, `sudo`, etc.). Simple Mode means "never ask," not "bypass safety."

### 3. Manifest `activity` schema

Extend `manifest.json` (parsed in `atria/core/modules/store.py:_read_manifest`,
modeled by `ModuleManifest`) with an optional `activity` block:

```json
{
  "display_name": "Warehouse",
  "activity": {
    "default": { "running": "Working in Warehouse…", "done": "Done" },
    "actions": {
      "receive": { "running": "Receiving stock…",   "done": "Stock received" },
      "ship":    { "running": "Shipping items…",     "done": "Items shipped" },
      "list":    { "running": "Checking inventory…", "done": "Inventory loaded" },
      "remove":  { "running": "Removing item…",      "done": "Item removed" }
    }
  }
}
```

- New optional dataclass fields on `ModuleManifest`
  (`activity_default`, `activity_actions`) parsed leniently — unknown/missing
  keys degrade to `None` and fall back gracefully (consistent with the existing
  lenient manifest loader).

### 4. Label resolver

`resolve_activity_label(command: str, modules_root: Path, registry) ->
ActivityLabel | None`:

1. Detect whether `command` invokes a script under `modules_root`; if not,
   return `None` (caller uses the global generic).
2. Extract the module name from the path
   (`…/modules/warehouse/scripts/inventory.py` → `warehouse`).
3. Extract the **first subcommand token** after the script
   (`inventory.py receive --sku …` → `receive`).
4. Look up `actions[subcommand]`; on miss fall back to the module `default`;
   on miss fall back to a global generic (`"Working…"` / `"Done"`).

The resolved `{running, done}` pair is attached to the tool-call start/finish
events sent over WebSocket so the frontend can render it.

### 5. Frontend `ModuleActivityLine`

- New component `web-ui/src/components/.../ModuleActivityLine.tsx`.
- Rendered **instead of** the technical tool-call card when Simple Mode is ON
  and the event carries an `activity` payload.
- States:
  - `running`: spinner + `running` text — e.g. "⏳ Receiving stock…".
  - `done`: collapses to a quiet line — "✅ Stock received".
  - `error`: "⚠️ Couldn't finish that — nothing was changed." (plain language,
    no stack trace).
- The technical `ToolCallCard` is gated behind `!simpleMode`. `ApprovalDialog`
  stays in the tree but never receives a request in Simple Mode.
- Visual polish applied via the `ui-ux-pro-max` skill (calm, minimal, generous
  spacing, subtle motion) suited to non-technical users.

## Data flow

```
Agent decides tool call (bash: module script)
  → process_handlers._ensure_command_approval
      → security floor: dangerous? → REFUSE (hard block)
      → Simple Mode ON? → auto-approve (no dialog broadcast)
  → resolve_activity_label(command) → {running, done} | null
  → tool-call START event (+ activity payload) over WebSocket
      → frontend: ModuleActivityLine (running)
  → script executes
  → tool-call FINISH event (success/error)
      → frontend: ModuleActivityLine (done | error)
```

## Error handling

- **Dangerous command:** refused by the safety floor; user sees a plain
  "⚠️ Couldn't do that safely" line, not a crash or raw error.
- **Script non-zero exit:** friendly error line stating nothing was changed
  where applicable; raw stderr is kept out of the non-technical view (still
  available to developers in non-Simple Mode).
- **Missing/malformed `activity` in manifest:** falls back through
  action → default → global generic. Never blocks execution.
- **Non-module command in Simple Mode:** generic "Working…/Done"; never a raw
  command.

## Testing

Per `CLAUDE.md`, both unit tests **and** a real end-to-end run are required.

- **Unit (backend):**
  - `resolve_activity_label`: path-under-modules detection, module-name
    extraction, subcommand extraction, full fallback chain (action → default →
    generic), and non-module → `None`.
  - Auto-approve gate: Simple Mode ON → approved with no broadcast; Simple Mode
    OFF → existing behavior; dangerous command → still refused in both modes.
  - Manifest parsing: `activity` block parsed; malformed degrades to `None`.
- **Unit (frontend):** `ModuleActivityLine` state transitions
  (running → done → error); card gating by `simpleMode`.
- **End-to-end (real API, `OPENAI_API_KEY` set):** drive a warehouse `receive`
  through the running app; confirm (a) no approval dialog appears, (b) the
  friendly running line shows and collapses to the done line, (c) the ledger
  was actually updated.

## Developer escape hatch

- `simple_mode: false` in `settings.json` restores approvals + technical cards.
- The non-technical end user never sees this toggle.

## Out of scope / follow-ups

- Localization of activity labels.
- Richer progress (percent complete) for long-running scripts.
- (Separately tracked) The warehouse "no description" bug — the API `ModuleOut`
  serializer drops the computed `description`, and the gallery parses raw
  `skill_md` (grabbing the `---` frontmatter fence). Not part of this design.
