# Simple Mode — Silent, Friendly Module Scripts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a non-technical user run module scripts without ever seeing an approval dialog or raw command text — module-script execution shows as a friendly activity line ("⏳ Receiving stock…" → "✅ Stock received").

**Architecture:** A deployment-level `simple_mode` config flag (default ON). When ON, the web approval gate auto-approves without broadcasting a dialog, and the chat UI renders a `ModuleActivityLine` instead of the technical tool-call card. Friendly wording comes from per-action labels declared in each module's `manifest.json`, resolved backend-side from the bash command and attached to the existing `tool_call` / `tool_result` WebSocket events.

**Tech Stack:** Python 3.14, FastAPI, Pydantic v2, pytest (backend); React + TypeScript + Zustand + Vite + Vitest, Tailwind (frontend). WebSocket for live tool events.

## Global Constraints

- Python line length 100 (Black + Ruff); type hints on public APIs (mypy strict); Google-style docstrings.
- The dangerous-command safety floor in `atria/core/context_engineering/tools/implementations/bash_tool/security.py` (`_is_command_allowed`, `_is_dangerous`) is **independent of approval** and must remain untouched — it *refuses* destructive commands rather than prompting, so auto-approving at the approval layer does not bypass it.
- `simple_mode` default is **True** (this deployment targets non-technical users; developers opt out via `settings.json`).
- No table format in any prompt/markdown the agent emits (project rule); not relevant to code here.
- Per project memory: omit `Co-Authored-By: Claude` trailer from commits.
- Per project memory: do not run per-task tests during execution if using batch flow — but this plan is TDD and each task runs its own tests; follow the chosen execution skill's convention.
- Backend tests run with `uv run pytest`; frontend tests with `npx vitest run` (run from `web-ui/`).

---

### Task 1: Add `simple_mode` config flag + expose via `/api/config`

**Files:**
- Modify: `atria/models/config.py` (add field to `AppConfig`, near line 161 `enable_sound`)
- Modify: `atria/web/routes/config.py:61-77` (add to `get_config()` return dict)
- Test: `tests/test_config_simple_mode.py` (create)

**Interfaces:**
- Produces: `AppConfig.simple_mode: bool` (default `True`); `/api/config` JSON gains `"simple_mode": bool`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_simple_mode.py`:

```python
from atria.models.config import AppConfig


def test_simple_mode_defaults_true():
    assert AppConfig().simple_mode is True


def test_simple_mode_can_be_disabled():
    assert AppConfig(simple_mode=False).simple_mode is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config_simple_mode.py -v`
Expected: FAIL — `AttributeError`/validation error, `simple_mode` not a field.

- [ ] **Step 3: Add the field**

In `atria/models/config.py`, inside `AppConfig`, in the `# UI settings` block (after `enable_sound: bool = True`):

```python
    # Simple Mode: non-technical UX — auto-approve tool calls (safety floor still
    # refuses dangerous commands) and show friendly activity lines instead of
    # technical tool cards. Developers can disable via settings.json.
    simple_mode: bool = True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config_simple_mode.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Expose in the config endpoint**

In `atria/web/routes/config.py`, in `get_config()`'s returned dict (after `"enable_bash": config.enable_bash,`):

```python
            "simple_mode": config.simple_mode,
```

- [ ] **Step 6: Commit**

```bash
git add atria/models/config.py atria/web/routes/config.py tests/test_config_simple_mode.py
git commit -m "feat(config): add simple_mode flag (default on) and expose via /api/config"
```

---

### Task 2: Auto-approve in `WebApprovalManager` when Simple Mode is on

**Files:**
- Modify: `atria/web/web_approval_manager.py` (top of `request_approval`, after line 67; add a private helper)
- Test: `tests/test_web_approval_simple_mode.py` (create)

**Interfaces:**
- Consumes: `AppConfig.simple_mode` (Task 1), `self.state.config_manager.get_config()`.
- Produces: `request_approval()` returns `ApprovalResult(approved=True, choice="approve")` **without** broadcasting when Simple Mode is on. New helper `WebApprovalManager._simple_mode_enabled() -> bool`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_web_approval_simple_mode.py`:

```python
from types import SimpleNamespace

from atria.models.config import AppConfig
from atria.models.operation import Operation, OperationType
from atria.web.web_approval_manager import WebApprovalManager


def _manager_with(simple_mode: bool) -> WebApprovalManager:
    # Build without touching the real event loop / ws; we only exercise the
    # early-return path, which uses self.state only.
    mgr = WebApprovalManager.__new__(WebApprovalManager)
    mgr.ws_manager = SimpleNamespace(broadcast=lambda *a, **k: None)
    mgr.loop = None
    mgr.session_id = "test"
    cfg = AppConfig(simple_mode=simple_mode)
    mgr.state = SimpleNamespace(
        config_manager=SimpleNamespace(get_config=lambda: cfg),
        get_autonomy_level=lambda: "Manual",
    )
    return mgr


def _bash_op() -> Operation:
    return Operation(
        type=OperationType.BASH_EXECUTE,
        target="python /tmp/modules/warehouse/scripts/inventory.py receive",
        parameters={"command": "python /tmp/modules/warehouse/scripts/inventory.py receive"},
    )


def test_simple_mode_auto_approves_without_broadcast():
    mgr = _manager_with(simple_mode=True)
    result = mgr.request_approval(_bash_op(), preview="", command="x")
    assert result.approved is True
    assert result.choice == "approve"


def test_simple_mode_off_still_consults_autonomy_manual():
    # With Simple Mode off and Manual autonomy, the early return must NOT fire;
    # the helper reports disabled.
    mgr = _manager_with(simple_mode=False)
    assert mgr._simple_mode_enabled() is False
```

> Note: confirm `OperationType.BASH_EXECUTE` is the correct enum member by reading `atria/models/operation.py`; adjust the import/member name if the codebase spells it differently (e.g. `BASH`). The test only needs a valid `Operation`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_web_approval_simple_mode.py -v`
Expected: FAIL — `_simple_mode_enabled` does not exist / no early return.

- [ ] **Step 3: Implement the gate**

In `atria/web/web_approval_manager.py`, add the helper method to the class:

```python
    def _simple_mode_enabled(self) -> bool:
        """True when Simple Mode is on — auto-approve all tool calls.

        The dangerous-command safety floor lives in the bash tool and is
        independent of approval, so this never bypasses it.
        """
        try:
            return bool(getattr(self.state.config_manager.get_config(), "simple_mode", False))
        except Exception:  # noqa: BLE001 — config access must never break the gate
            return False
```

Then at the very top of `request_approval`, before the autonomy check (currently line 68 `autonomy = self.state.get_autonomy_level()`), insert:

```python
        # Simple Mode (non-technical UX): never prompt. Safety floor still applies.
        if self._simple_mode_enabled():
            return ApprovalResult(approved=True, choice="approve")

```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_web_approval_simple_mode.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add atria/web/web_approval_manager.py tests/test_web_approval_simple_mode.py
git commit -m "feat(approval): auto-approve all tool calls when simple_mode is on"
```

---

### Task 3: Manifest `activity` schema (ActivityLabel + parsing)

**Files:**
- Modify: `atria/core/modules/store.py` (add `ActivityLabel` dataclass; add two fields to `ModuleManifest`; add `_parse_activity`; call it in `_read_manifest`)
- Test: `tests/test_modules_store.py` (append)

**Interfaces:**
- Produces:
  - `ActivityLabel` dataclass: `running: str`, `done: str`.
  - `ModuleManifest.activity_default: Optional[ActivityLabel]` and `ModuleManifest.activity_actions: Dict[str, ActivityLabel]` (default empty dict).
  - `_parse_activity(raw: Any) -> tuple[Optional[ActivityLabel], Dict[str, ActivityLabel]]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_modules_store.py`:

```python
def test_parse_activity_default_and_actions():
    from atria.core.modules.store import _parse_activity, ActivityLabel

    default, actions = _parse_activity(
        {
            "default": {"running": "Working in Warehouse…", "done": "Done"},
            "actions": {
                "receive": {"running": "Receiving stock…", "done": "Stock received"},
            },
        }
    )
    assert default == ActivityLabel(running="Working in Warehouse…", done="Done")
    assert actions["receive"] == ActivityLabel(running="Receiving stock…", done="Stock received")


def test_parse_activity_missing_degrades_to_empty():
    from atria.core.modules.store import _parse_activity

    assert _parse_activity(None) == (None, {})
    assert _parse_activity("nonsense") == (None, {})
    assert _parse_activity({}) == (None, {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_modules_store.py -k activity -v`
Expected: FAIL — `_parse_activity` / `ActivityLabel` not importable.

- [ ] **Step 3: Implement schema + parsing**

In `atria/core/modules/store.py`:

First, ensure `Dict` is imported (the file already imports `List, Optional` from `typing`):

```python
from typing import Dict, List, Optional
```

Add the dataclass (place it just above `class ModuleDashboardManifest`):

```python
@dataclass
class ActivityLabel:
    """Friendly running/done wording for a module action (Simple Mode UI)."""

    running: str
    done: str
```

Extend `ModuleManifest` (add two fields after `dashboard:`):

```python
    activity_default: Optional[ActivityLabel] = None
    activity_actions: Dict[str, ActivityLabel] = field(default_factory=dict)
```

Add the parser (place near `_parse_dashboard`):

```python
def _parse_activity(
    raw: Any,
) -> tuple[Optional[ActivityLabel], Dict[str, ActivityLabel]]:
    """Parse the optional ``activity`` manifest block leniently.

    Shape: ``{"default": {running, done}, "actions": {name: {running, done}}}``.
    Anything malformed degrades to ``(None, {})`` so old/invalid manifests keep
    working.
    """
    if not isinstance(raw, dict):
        return None, {}

    def _label(d: Any) -> Optional[ActivityLabel]:
        if not isinstance(d, dict):
            return None
        running = _nonempty_str(d.get("running"))
        done = _nonempty_str(d.get("done"))
        if running is None and done is None:
            return None
        return ActivityLabel(running=running or "Working…", done=done or "Done")

    default = _label(raw.get("default"))
    actions: Dict[str, ActivityLabel] = {}
    raw_actions = raw.get("actions")
    if isinstance(raw_actions, dict):
        for key, value in raw_actions.items():
            label = _label(value)
            if label is not None:
                actions[str(key)] = label
    return default, actions
```

> `Any` is already imported in this file (used by `_description_from(meta: dict, ...)` neighbours); if not, add `Any` to the `typing` import.

Finally, in `_read_manifest`, compute and pass the fields. Change the return (currently lines ~185-190) to:

```python
    activity_default, activity_actions = _parse_activity(raw.get("activity"))
    return ModuleManifest(
        display_name=_nonempty_str(raw.get("display_name")),
        tooltip=_nonempty_str(raw.get("tooltip")),
        icon=_nonempty_str(raw.get("icon")),
        dashboard=_parse_dashboard(raw.get("dashboard")),
        activity_default=activity_default,
        activity_actions=activity_actions,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_modules_store.py -k activity -v`
Expected: PASS (both tests).

- [ ] **Step 5: Run the full store + routes suites for regressions**

Run: `uv run pytest tests/test_modules_store.py tests/test_modules_routes.py -q`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add atria/core/modules/store.py tests/test_modules_store.py
git commit -m "feat(modules): parse optional activity labels from manifest.json"
```

---

### Task 4: `resolve_activity_label` — command → friendly label

**Files:**
- Create: `atria/core/modules/activity.py`
- Test: `tests/test_modules_activity.py` (create)

**Interfaces:**
- Consumes: `ActivityLabel`, `_read_manifest` (Task 3).
- Produces: `resolve_activity_label(command: str, modules_root: Path) -> Optional[ActivityLabel]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_modules_activity.py`:

```python
import json
from pathlib import Path

from atria.core.modules.activity import resolve_activity_label
from atria.core.modules.store import ActivityLabel


def _make_module(root: Path) -> Path:
    mod = root / "warehouse"
    (mod / "scripts").mkdir(parents=True)
    (mod / "scripts" / "inventory.py").write_text("# script\n")
    (mod / "manifest.json").write_text(
        json.dumps(
            {
                "activity": {
                    "default": {"running": "Working in Warehouse…", "done": "Done"},
                    "actions": {
                        "receive": {"running": "Receiving stock…", "done": "Stock received"},
                    },
                }
            }
        )
    )
    return mod


def test_resolves_action_label(tmp_path: Path):
    mod = _make_module(tmp_path)
    cmd = f"python {mod}/scripts/inventory.py receive --sku SKU-001 --qty 50"
    assert resolve_activity_label(cmd, tmp_path) == ActivityLabel(
        running="Receiving stock…", done="Stock received"
    )


def test_falls_back_to_default_for_unknown_action(tmp_path: Path):
    mod = _make_module(tmp_path)
    cmd = f"python {mod}/scripts/inventory.py teleport"
    assert resolve_activity_label(cmd, tmp_path) == ActivityLabel(
        running="Working in Warehouse…", done="Done"
    )


def test_flags_skipped_when_finding_subcommand(tmp_path: Path):
    mod = _make_module(tmp_path)
    cmd = f"python {mod}/scripts/inventory.py --json receive"
    assert resolve_activity_label(cmd, tmp_path).running == "Receiving stock…"


def test_non_module_command_returns_none(tmp_path: Path):
    _make_module(tmp_path)
    assert resolve_activity_label("grep -r foo .", tmp_path) is None


def test_module_without_activity_returns_none(tmp_path: Path):
    mod = tmp_path / "bare"
    (mod / "scripts").mkdir(parents=True)
    (mod / "scripts" / "main.py").write_text("# s\n")
    (mod / "manifest.json").write_text(json.dumps({"display_name": "Bare"}))
    cmd = f"python {mod}/scripts/main.py run"
    assert resolve_activity_label(cmd, tmp_path) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_modules_activity.py -v`
Expected: FAIL — module `atria.core.modules.activity` does not exist.

- [ ] **Step 3: Implement the resolver**

Create `atria/core/modules/activity.py`:

```python
"""Resolve a friendly activity label from a bash command invoking a module script.

Used by the web tool broadcaster (Simple Mode) to turn
``python <modules>/warehouse/scripts/inventory.py receive …`` into
``ActivityLabel(running="Receiving stock…", done="Stock received")``.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Optional

from atria.core.modules.store import ActivityLabel, _read_manifest


def resolve_activity_label(command: str, modules_root: Path) -> Optional[ActivityLabel]:
    """Map a shell command to a module's friendly activity label.

    Returns ``None`` for non-module commands or modules without an ``activity``
    block, in which case the caller falls back to a generic label.

    Args:
        command: The full shell command (may include flags and args).
        modules_root: Absolute path to the active modules directory.

    Returns:
        The matched ``ActivityLabel`` (action-specific, else the module default)
        or ``None``.
    """
    if not command:
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    root = modules_root.resolve()
    for i, token in enumerate(tokens):
        if not token.endswith(".py"):
            continue
        script = Path(token)
        if not script.is_absolute():
            continue
        try:
            rel = script.resolve().relative_to(root)
        except ValueError:
            continue
        if not rel.parts:
            continue
        manifest = _read_manifest(root / rel.parts[0])
        if manifest is None:
            return None

        subcommand: Optional[str] = None
        for nxt in tokens[i + 1 :]:
            if nxt.startswith("-"):
                continue
            subcommand = nxt
            break

        if subcommand and subcommand in manifest.activity_actions:
            return manifest.activity_actions[subcommand]
        return manifest.activity_default
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_modules_activity.py -v`
Expected: PASS (all five tests).

- [ ] **Step 5: Commit**

```bash
git add atria/core/modules/activity.py tests/test_modules_activity.py
git commit -m "feat(modules): resolve friendly activity label from bash command"
```

---

### Task 5: Attach `activity` to tool_call / tool_result broadcasts

**Files:**
- Modify: `atria/web/ws_tool_broadcaster.py` (add `_activity_for`; include in `_broadcast_tool_call` data and `_build_result_payload`)
- Test: `tests/test_ws_tool_broadcaster_activity.py` (create)

**Interfaces:**
- Consumes: `resolve_activity_label` (Task 4), `resolve_modules_root` (existing in `atria.core.modules.registry`).
- Produces: `WebSocketToolBroadcaster._activity_for(tool_name: str, arguments: dict) -> Optional[dict]` returning `{"running": str, "done": str}` or `None`; the `tool_call` and `tool_result` WS payloads gain an `"activity"` key (value may be `None`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_ws_tool_broadcaster_activity.py`:

```python
import json
from pathlib import Path

from atria.web.ws_tool_broadcaster import WebSocketToolBroadcaster


def _broadcaster() -> WebSocketToolBroadcaster:
    # Build without wiring a real registry/ws/loop; we only call _activity_for.
    b = WebSocketToolBroadcaster.__new__(WebSocketToolBroadcaster)
    return b


def test_activity_for_bash_module_script(tmp_path: Path, monkeypatch):
    mod = tmp_path / "warehouse"
    (mod / "scripts").mkdir(parents=True)
    (mod / "scripts" / "inventory.py").write_text("# s\n")
    (mod / "manifest.json").write_text(
        json.dumps(
            {"activity": {"actions": {"receive": {"running": "Receiving stock…", "done": "Stock received"}}}}
        )
    )
    monkeypatch.setattr(
        "atria.core.modules.registry.resolve_modules_root", lambda: tmp_path
    )
    b = _broadcaster()
    args = {"command": f"python {mod}/scripts/inventory.py receive --sku A"}
    assert b._activity_for("bash_execute", args) == {
        "running": "Receiving stock…",
        "done": "Stock received",
    }


def test_activity_for_non_bash_is_none():
    assert _broadcaster()._activity_for("read_file", {"file_path": "/x"}) is None


def test_activity_for_non_module_bash_is_none(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "atria.core.modules.registry.resolve_modules_root", lambda: tmp_path
    )
    assert _broadcaster()._activity_for("bash_execute", {"command": "ls -la"}) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ws_tool_broadcaster_activity.py -v`
Expected: FAIL — `_activity_for` does not exist.

- [ ] **Step 3: Implement `_activity_for` and wire it in**

In `atria/web/ws_tool_broadcaster.py`, add the method to the class:

```python
    _BASH_TOOLS: frozenset[str] = frozenset({"bash_execute", "run_command"})

    def _activity_for(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """Friendly running/done labels for a module-script bash call, else None."""
        if tool_name not in self._BASH_TOOLS:
            return None
        command = arguments.get("command") if isinstance(arguments, dict) else None
        if not command:
            return None
        try:
            from atria.core.modules.activity import resolve_activity_label
            from atria.core.modules.registry import resolve_modules_root

            label = resolve_activity_label(str(command), resolve_modules_root())
        except Exception:  # noqa: BLE001 — labelling must never break broadcasting
            return None
        if label is None:
            return None
        return {"running": label.running, "done": label.done}
```

In `_broadcast_tool_call`, add `"activity"` to the `data` dict (alongside `"description"`):

```python
                        "description": f"Calling {tool_name}",
                        "activity": self._activity_for(tool_name, arguments),
                        "session_id": self.session_id,
```

In `_build_result_payload`, add `"activity"` to the returned dict (alongside `"raw_result"`):

```python
            "raw_result": self._make_json_safe(result),
            "activity": self._activity_for(tool_name, arguments),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ws_tool_broadcaster_activity.py -v`
Expected: PASS (all three tests).

- [ ] **Step 5: Commit**

```bash
git add atria/web/ws_tool_broadcaster.py tests/test_ws_tool_broadcaster_activity.py
git commit -m "feat(web): attach friendly activity label to tool_call/result events"
```

---

### Task 6: Add the `activity` block to the warehouse manifest

**Files:**
- Modify: `modules/warehouse/manifest.json`
- Test: `tests/test_warehouse_manifest_activity.py` (create)

**Interfaces:**
- Consumes: Task 3 parsing, Task 4 resolver.
- Produces: warehouse manifest declares friendly labels for `receive`, `ship`, `adjust`, `move`, `list`, `add`, `update`, `remove`, `summary`, `low-stock`, `valuation`, `history`, `set-reorder`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_warehouse_manifest_activity.py`:

```python
from pathlib import Path

from atria.core.modules.store import _read_manifest

WAREHOUSE = Path(__file__).resolve().parents[1] / "modules" / "warehouse"


def test_warehouse_manifest_has_receive_label():
    manifest = _read_manifest(WAREHOUSE)
    assert manifest is not None
    assert "receive" in manifest.activity_actions
    assert manifest.activity_actions["receive"].running == "Receiving stock…"
    assert manifest.activity_default is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_warehouse_manifest_activity.py -v`
Expected: FAIL — no `activity` block yet.

- [ ] **Step 3: Add the activity block**

Replace `modules/warehouse/manifest.json` with:

```json
{
  "display_name": "Warehouse",
  "tooltip": "Inventory, SKUs, low-stock signals",
  "icon": "icon.svg",
  "dashboard": {
    "title": "Warehouse · Inventory",
    "default_height": 760,
    "badge_color": "warning"
  },
  "activity": {
    "default": { "running": "Working in Warehouse…", "done": "Done" },
    "actions": {
      "list":        { "running": "Checking inventory…",  "done": "Inventory loaded" },
      "summary":     { "running": "Building summary…",     "done": "Summary ready" },
      "low-stock":   { "running": "Finding low stock…",    "done": "Low-stock report ready" },
      "valuation":   { "running": "Valuing inventory…",    "done": "Valuation ready" },
      "history":     { "running": "Loading history…",      "done": "History loaded" },
      "query":       { "running": "Looking that up…",      "done": "Done" },
      "add":         { "running": "Adding item…",          "done": "Item added" },
      "update":      { "running": "Updating item…",        "done": "Item updated" },
      "remove":      { "running": "Removing item…",        "done": "Item removed" },
      "receive":     { "running": "Receiving stock…",      "done": "Stock received" },
      "ship":        { "running": "Shipping items…",       "done": "Items shipped" },
      "adjust":      { "running": "Adjusting stock…",      "done": "Stock adjusted" },
      "move":        { "running": "Moving stock…",         "done": "Stock moved" },
      "set-reorder": { "running": "Updating reorder level…", "done": "Reorder level updated" },
      "export":      { "running": "Exporting data…",       "done": "Export ready" },
      "import":      { "running": "Importing data…",       "done": "Import complete" },
      "migrate":     { "running": "Migrating data…",       "done": "Migration complete" },
      "reset":       { "running": "Resetting data…",       "done": "Data reset" }
    }
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_warehouse_manifest_activity.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add modules/warehouse/manifest.json tests/test_warehouse_manifest_activity.py
git commit -m "feat(warehouse): declare friendly activity labels in manifest"
```

---

### Task 7: Frontend — types + chat store carry `activity` and `simple_mode`

**Files:**
- Modify: `web-ui/src/types/index.ts` (add `ActivityLabel`; add `activity` to `Message`; add `simple_mode` to the status/config shape — search for `autonomy_level`)
- Modify: `web-ui/src/stores/chat.ts` (tool_call handler ~line 680; config refresh ~line 333)
- Test: `web-ui/src/stores/chat.activity.test.ts` (create)

**Interfaces:**
- Consumes: WS `tool_call` event now carries `data.activity` (Task 5); `/api/config` carries `simple_mode` (Task 1).
- Produces: `Message.activity?: ActivityLabel | null`; `status.simple_mode: boolean`; `ActivityLabel` type `{ running: string; done: string }`.

- [ ] **Step 1: Add the type**

In `web-ui/src/types/index.ts`, add near the other small interfaces:

```typescript
export interface ActivityLabel {
  running: string;
  done: string;
}
```

In the `Message` interface (where `tool_args_display` is declared, ~line 76), add:

```typescript
  activity?: ActivityLabel | null;
```

In the status interface (search for `autonomy_level: string`), add:

```typescript
  simple_mode?: boolean;
```

- [ ] **Step 2: Write the failing test**

Create `web-ui/src/stores/chat.activity.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';

// Pure shape check: the tool_call WS payload maps data.activity onto the message.
function buildToolCallMessage(data: any) {
  return {
    role: 'tool_call' as const,
    content: data.description || `Calling ${data.tool_name}`,
    tool_call_id: data.tool_call_id,
    tool_name: data.tool_name,
    tool_args: data.arguments,
    tool_args_display: data.arguments_display || null,
    activity: data.activity || null,
  };
}

describe('tool_call activity mapping', () => {
  it('carries the activity payload onto the message', () => {
    const msg = buildToolCallMessage({
      tool_call_id: 'c1',
      tool_name: 'bash_execute',
      arguments: { command: 'python /m/warehouse/scripts/inventory.py receive' },
      activity: { running: 'Receiving stock…', done: 'Stock received' },
    });
    expect(msg.activity).toEqual({ running: 'Receiving stock…', done: 'Stock received' });
  });

  it('defaults activity to null when absent', () => {
    const msg = buildToolCallMessage({ tool_call_id: 'c2', tool_name: 'read_file', arguments: {} });
    expect(msg.activity).toBeNull();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run (from `web-ui/`): `npx vitest run src/stores/chat.activity.test.ts`
Expected: FAIL until the file/logic exists — if it passes immediately (pure helper), that's acceptable since it locks the mapping contract; proceed to wire the real store.

- [ ] **Step 4: Wire the store**

In `web-ui/src/stores/chat.ts`, in the `tool_call` handler's `toolCallMessage` object (~line 681), add:

```typescript
    activity: message.data.activity || null,
```

In the config refresh block (~line 333, the `status` object), add:

```typescript
          simple_mode: configData.simple_mode ?? true,
```

> If `apiClient.getConfig()`'s return type is typed, add `simple_mode?: boolean` to that type in `web-ui/src/types/index.ts` (search for the config interface containing `autonomy_level`).

- [ ] **Step 5: Run test to verify it passes + typecheck**

Run (from `web-ui/`): `npx vitest run src/stores/chat.activity.test.ts && npx tsc --noEmit`
Expected: PASS and no type errors.

- [ ] **Step 6: Commit**

```bash
git add web-ui/src/types/index.ts web-ui/src/stores/chat.ts web-ui/src/stores/chat.activity.test.ts
git commit -m "feat(ui): carry activity label and simple_mode through types and store"
```

---

### Task 8: Frontend — `ModuleActivityLine` component

**Files:**
- Create: `web-ui/src/components/Chat/ModuleActivityLine.tsx`
- Test: `web-ui/src/components/Chat/ModuleActivityLine.test.tsx` (create)

**Interfaces:**
- Consumes: `Message` with optional `activity`, `tool_result`, `tool_success`, `tool_error` (Task 7).
- Produces: `ModuleActivityLine({ message, hasResult }: { message: Message; hasResult: boolean })` React component. Generic fallback labels `"Working…"` / `"Done"` when `message.activity` is absent.

- [ ] **Step 1: Write the failing test**

Create `web-ui/src/components/Chat/ModuleActivityLine.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { ModuleActivityLine } from './ModuleActivityLine';
import type { Message } from '../../types';

function msg(over: Partial<Message>): Message {
  return { role: 'tool_call', content: '', timestamp: '', ...over } as Message;
}

describe('ModuleActivityLine', () => {
  it('shows the running label while running', () => {
    const { getByText } = render(
      <ModuleActivityLine
        message={msg({ activity: { running: 'Receiving stock…', done: 'Stock received' } })}
        hasResult={false}
      />,
    );
    expect(getByText('Receiving stock…')).toBeTruthy();
  });

  it('shows the done label after completion', () => {
    const { getByText } = render(
      <ModuleActivityLine
        message={msg({
          activity: { running: 'Receiving stock…', done: 'Stock received' },
          tool_result: { success: true },
          tool_success: true,
        })}
        hasResult={true}
      />,
    );
    expect(getByText('Stock received')).toBeTruthy();
  });

  it('shows a friendly error when the tool failed', () => {
    const { getByText } = render(
      <ModuleActivityLine
        message={msg({ tool_result: { success: false }, tool_success: false, tool_error: 'boom' })}
        hasResult={true}
      />,
    );
    expect(getByText(/Couldn’t finish that/)).toBeTruthy();
  });

  it('falls back to generic labels with no activity payload', () => {
    const { getByText } = render(<ModuleActivityLine message={msg({})} hasResult={false} />);
    expect(getByText('Working…')).toBeTruthy();
  });
});
```

> If `@testing-library/react` is not already a dev dependency, add it: `npm i -D @testing-library/react @testing-library/jest-dom` (run in `web-ui/`). Check `web-ui/package.json` first; the repo already has vitest configured.

- [ ] **Step 2: Run test to verify it fails**

Run (from `web-ui/`): `npx vitest run src/components/Chat/ModuleActivityLine.test.tsx`
Expected: FAIL — component does not exist.

- [ ] **Step 3: Implement the component**

Create `web-ui/src/components/Chat/ModuleActivityLine.tsx`:

```tsx
import type { Message } from '../../types';

interface Props {
  message: Message;
  hasResult: boolean;
}

const GENERIC = { running: 'Working…', done: 'Done' };

/**
 * Friendly, non-technical activity line shown in Simple Mode in place of the
 * technical tool-call card. No commands, paths, or buttons — just plain
 * language with a spinner while running and a quiet checkmark when done.
 */
export function ModuleActivityLine({ message, hasResult }: Props) {
  const labels = message.activity ?? GENERIC;
  const isRunning = !hasResult;
  const failed =
    message.tool_success === false ||
    (message.tool_result && (message.tool_result as any).success === false) ||
    !!message.tool_error;

  if (failed) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 text-[13px] text-block-coral">
        <span aria-hidden>⚠️</span>
        <span>Couldn’t finish that — nothing was changed.</span>
      </div>
    );
  }

  if (isRunning) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 text-[13px] text-ink/70">
        <span className="inline-block w-3 h-3 border-[1.5px] border-ink/30 border-t-transparent rounded-full animate-spin flex-shrink-0" />
        <span>{labels.running}</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 px-3 py-2 text-[13px] text-semantic-success">
      <span aria-hidden>✅</span>
      <span>{labels.done}</span>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `web-ui/`): `npx vitest run src/components/Chat/ModuleActivityLine.test.tsx`
Expected: PASS (all four tests).

- [ ] **Step 5: Commit**

```bash
git add web-ui/src/components/Chat/ModuleActivityLine.tsx web-ui/src/components/Chat/ModuleActivityLine.test.tsx
git commit -m "feat(ui): add friendly ModuleActivityLine component"
```

---

### Task 9: Frontend — render `ModuleActivityLine` in Simple Mode

**Files:**
- Modify: `web-ui/src/components/Chat/MessageList.tsx:214-216`
- Test: covered by Task 8 + the end-to-end run in Task 10 (no separate unit test; this is a one-line render branch).

**Interfaces:**
- Consumes: `useChatStore` status `simple_mode` (Task 7), `ModuleActivityLine` (Task 8).

- [ ] **Step 1: Import the component and read Simple Mode**

In `web-ui/src/components/Chat/MessageList.tsx`, add the import near the `ToolCallMessage` import (line 9):

```typescript
import { ModuleActivityLine } from './ModuleActivityLine';
```

Ensure the component reads Simple Mode from the store. If `MessageList` is not already subscribed, add near the top of the component body:

```typescript
  const simpleMode = useChatStore(s => s.status?.simple_mode ?? true);
```

> Confirm `useChatStore` is imported in this file; if not, add `import { useChatStore } from '../../stores/chat';`. Verify the status selector path matches the store (Task 7 sets `status.simple_mode`).

- [ ] **Step 2: Branch the render**

Replace lines 214-216:

```typescript
  if (message.role === 'tool_call') {
    const hasResult = message.tool_result != null && Object.keys(message.tool_result).length > 0;
    body = <ToolCallMessage message={message} hasResult={hasResult} />;
```

with:

```typescript
  if (message.role === 'tool_call') {
    const hasResult = message.tool_result != null && Object.keys(message.tool_result).length > 0;
    body = simpleMode
      ? <ModuleActivityLine message={message} hasResult={hasResult} />
      : <ToolCallMessage message={message} hasResult={hasResult} />;
```

- [ ] **Step 3: Typecheck**

Run (from `web-ui/`): `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add web-ui/src/components/Chat/MessageList.tsx
git commit -m "feat(ui): show friendly activity line instead of tool card in simple mode"
```

---

### Task 10: Build UI + full verification (unit + real end-to-end)

**Files:**
- No source changes (build + verification only). Per `CLAUDE.md`, both unit tests AND a real end-to-end run with `OPENAI_API_KEY` are REQUIRED.

- [ ] **Step 1: Run the full backend suite**

Run: `uv run pytest -q`
Expected: PASS (including all new tests from Tasks 1–6).

- [ ] **Step 2: Run the full frontend suite + typecheck**

Run (from `web-ui/`): `npx vitest run && npx tsc --noEmit`
Expected: PASS, no type errors.

- [ ] **Step 3: Build the web UI bundle**

Run: `make build-ui`
Expected: build succeeds; assets emitted to `atria/web/static/`.

- [ ] **Step 4: Real end-to-end simulation**

```bash
export OPENAI_API_KEY="<your-key>"
make run   # or: atria run ui
```

In the running Web UI, with `simple_mode` ON (default):
- Ask the agent to receive stock, e.g. "receive 50 units of SKU-001 into the warehouse".
- **Confirm:** (a) NO approval dialog appears; (b) a friendly line "⏳ Receiving stock…" shows while running and collapses to "✅ Stock received"; (c) no raw command/path is visible.
- Verify the ledger actually changed:
  `python modules/warehouse/scripts/inventory.py history --sku SKU-001`
  Expected: a `receive` movement of +50.

Then set `simple_mode: false` in `~/.atria/settings.json` (or project `.atria/settings.json`), restart, and confirm the technical tool card + approval behavior returns.

- [ ] **Step 5: Final commit (if any build artifacts changed)**

```bash
git add atria/web/static
git commit -m "build(ui): rebuild web assets for simple mode"
```

---

## Self-Review

**Spec coverage:**
- Full-auto, no prompt → Task 2. ✓
- Safety floor preserved → Global Constraints + Task 2 (independent floor, untouched). ✓
- Friendly activity line, no commands/paths/buttons → Tasks 8–9. ✓
- Per-action labels from `manifest.json` → Tasks 3, 4, 6. ✓
- Backend attaches labels to events → Task 5. ✓
- Simple Mode default ON, `settings.json` toggle, developer escape hatch → Tasks 1, 9 + Task 10 Step 4. ✓
- Friendly error wording / generic fallback / non-module generic → Tasks 4 (None → generic), 8 (GENERIC + error branch). ✓
- Testing: backend unit + frontend unit + real e2e → Tasks 1–8 unit, Task 10 e2e. ✓
- Warehouse "no description" bug → explicitly out of scope (already fixed separately). ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; commands have expected output. Two flagged *verification* notes (enum member name in Task 2; testing-library dep in Task 8) instruct the engineer to confirm exact names against the codebase rather than leaving logic vague — acceptable.

**Type consistency:** `ActivityLabel{running,done}` is consistent across store.py (Task 3), activity.py (Task 4), broadcaster dict `{running,done}` (Task 5), TS `ActivityLabel` (Task 7), and component (Task 8). `simple_mode` (snake_case) is consistent backend→config endpoint→store→`status.simple_mode`. `_activity_for(tool_name, arguments)` signature matches its two call sites.
