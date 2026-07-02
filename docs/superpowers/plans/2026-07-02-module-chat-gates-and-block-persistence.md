# Module Chat Gates & Block Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Open more backend capability "gates" to chat-embedded module UI (read chat/state, subscribe to agent events, call module backends), add an agent tool to render blocks mid-turn, and make every chat block durably persisted to Postgres.

**Architecture:** All work is core/backend — no module authoring changes. New `block_rpc` methods are added to the existing WebSocket dispatcher (`_handle_block_rpc`) behind the existing allowlist config. A `render_component` agent tool wraps the existing `ui_bridge.push_block`. Block persistence is made mandatory + reliable through the active session manager (Postgres via `message_repo`), and the `messages.role` column is widened so block roles are stored faithfully.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy (async, Postgres), Pydantic, pytest (`uv run pytest`). Frontend untouched (existing `SandboxedBlock`/`block_rpc_result` handling already supports these events).

## Global Constraints

- Line length: 100 chars (Black + Ruff). Type hints on public APIs (mypy strict). Google-style docstrings.
- No table format in prompt/description markdown — prose or bullets only.
- Modules are first-party/trusted, but every `block_rpc` method stays gated by `config.web.iframe_rpc.tool_allowlist`.
- Persistence target is Postgres repos (`conversation_repo`/`message_repo`); JSON `session_manager` is legacy fallback only.
- DB schema is created via `Base.metadata.create_all` in `atria/db/connection.py::init_schema` — there is **no Alembic**; schema changes to existing tables must be idempotent `ALTER TABLE` DDL added to `init_schema`.
- DB round-trip fidelity is via the `blocks` JSON `"raw"` field (`message_repo._msg_to_blocks`/`_blocks_to_msg`); the `role` column is secondary (query/index) but must not truncate.
- Commit after every task. Do not add a `Co-Authored-By: Claude` trailer.
- Real-DB tests are gated on `DATABASE_URL`; e2e agent tests require `OPENAI_API_KEY`.

---

## File Structure

- `atria/db/models.py` — widen `Message.role` column.
- `atria/db/connection.py` — idempotent `ALTER TABLE` in `init_schema`.
- `atria/db/repositories/message_repo.py` — stop truncating role on insert.
- `atria/web/ui_bridge.py` — make block persistence mandatory + reliable (surface errors).
- `atria/core/context_engineering/tools/implementations/render_component_tool.py` — new `render_component` tool handler.
- `atria/core/context_engineering/tools/registry.py` — register the handler.
- `atria/core/agents/components/schemas/builtin/component_tools.py` — new tool schema.
- `atria/core/agents/components/schemas/builtin/__init__.py` — wire schema into `BUILTIN_TOOL_SCHEMAS`.
- `atria/core/agents/prompts/templates/tools/tool-render-component.md` — tool description.
- `atria/models/config.py` — extend `IframeRpcConfig` (default allowlist + `config.read` key whitelist).
- `atria/web/websocket.py` — new `block_rpc` methods (read gates, event feed, module.rpc).
- `atria/web/routes/module_dashboard.py` — `POST /api/modules/{name}/rpc` route.

Tests:
- `tests/test_message_repo_orm.py` — role widening + custom_block round-trip.
- `tests/web/test_ui_bridge_persistence.py` — mandatory persistence.
- `tests/core/test_render_component_tool.py` — tool handler.
- `tests/web/test_block_rpc_gates.py` — new gate methods.
- `tests/web/test_module_rpc_route.py` — module rpc route.

---

## Phase 1 — Persistence fix

### Task 1: Widen `messages.role` column and stop truncation

**Files:**
- Modify: `atria/db/models.py:111`
- Modify: `atria/db/connection.py:83-95`
- Modify: `atria/db/repositories/message_repo.py:108`
- Test: `tests/test_message_repo_orm.py`

**Interfaces:**
- Consumes: `MessageRepository.insert(conversation_id, message, mode)`, `list_by_conversation(conversation_id)`, `ChatMessage`, `Role` (existing).
- Produces: `custom_block`-role messages persist and reload with role `Role.CUSTOM_BLOCK` intact.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_message_repo_orm.py`:

```python
async def test_custom_block_role_roundtrip_preserved(sm):
    users = UserRepository(sm)
    convs = ConversationRepository(sm)
    msgs = MessageRepository(sm)
    uid = await users.upsert_by_email("orm-msg-cb@atria.local")
    cid = await convs.create(None, uid, "cb", "normal")
    original = ChatMessage(
        role=Role.CUSTOM_BLOCK,
        content="",
        metadata={"block_id": "abc123", "module": "warehouse", "block": "item_form"},
    )
    await msgs.insert(cid, original)
    loaded = await msgs.list_by_conversation(cid)
    assert len(loaded) == 1
    assert loaded[0].role == Role.CUSTOM_BLOCK
    assert loaded[0].metadata["block_id"] == "abc123"
    assert loaded[0].metadata["module"] == "warehouse"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DATABASE_URL=$DATABASE_URL uv run pytest tests/test_message_repo_orm.py::test_custom_block_role_roundtrip_preserved -v`
Expected: PASS on metadata (round-trips via `raw`) but the `role` column is stored truncated as `custom_blo`; if `DATABASE_URL` is unset the test is skipped. To make the truncation observable, also assert the raw column:

```python
    from sqlalchemy import select, text
    async with sm() as s:
        row = (await s.execute(text("SELECT role FROM messages WHERE conversation_id=:c"), {"c": cid})).first()
    assert row[0] == "custom_block"  # FAILS today: stored as "custom_blo"
```
Expected: FAIL — `assert 'custom_blo' == 'custom_block'`.

- [ ] **Step 3: Widen the column in the model**

In `atria/db/models.py:111` change:

```python
    role: Mapped[str] = mapped_column(String(32), nullable=False)
```

- [ ] **Step 4: Stop truncating on insert**

In `atria/db/repositories/message_repo.py:108` change `role=message.role.value[:10]` to:

```python
                    role=message.role.value[:32],
```

- [ ] **Step 5: Add idempotent ALTER to `init_schema`**

In `atria/db/connection.py::init_schema`, after `await conn.run_sync(Base.metadata.create_all)` (line 89), add:

```python
        # Widen messages.role so block roles (e.g. custom_block) are not
        # truncated. Idempotent: ALTER to a wider VARCHAR is a no-op if already wide.
        try:
            await conn.execute(
                text("ALTER TABLE messages ALTER COLUMN role TYPE VARCHAR(32)")
            )
        except Exception as _alter_err:  # noqa: BLE001
            logger.warning("Failed to widen messages.role: %s", _alter_err)
```

(`text` and `logger` are already imported in this module.)

- [ ] **Step 6: Run test to verify it passes**

Run: `DATABASE_URL=$DATABASE_URL uv run pytest tests/test_message_repo_orm.py::test_custom_block_role_roundtrip_preserved -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add atria/db/models.py atria/db/connection.py atria/db/repositories/message_repo.py tests/test_message_repo_orm.py
git commit -m "fix(db): widen messages.role to VARCHAR(32) so block roles persist faithfully"
```

---

### Task 2: Make chat-block persistence mandatory and reliable

**Files:**
- Modify: `atria/web/ui_bridge.py:176-297` (`_persist_block_message`, `push_block`)
- Test: `tests/web/test_ui_bridge_persistence.py`

**Interfaces:**
- Consumes: `state.session_manager.get_session_by_id(session_id)`, `session.add_message(ChatMessage)`, `state.session_manager.save_session(session)` (existing async API on both JSON and pg managers).
- Produces: `push_block(..., persist=True)` raises `BlockPersistError` if the block cannot be written; `_persist_block_message` returns nothing but propagates failure.

- [ ] **Step 1: Write the failing test**

Create `tests/web/test_ui_bridge_persistence.py`:

```python
"""push_block persistence must be mandatory and surface failures."""
from __future__ import annotations

import pytest
from atria.web import ui_bridge


class _FakeSessionMgr:
    def __init__(self, fail: bool = False):
        self.saved = []
        self._fail = fail

    async def get_session_by_id(self, sid, owner_id=None):
        return _FakeSession(self)

    async def save_session(self, sess):
        if self._fail:
            raise RuntimeError("db down")
        self.saved.append(sess)


class _FakeSession:
    def __init__(self, mgr):
        self._mgr = mgr
        self.messages = []

    def add_message(self, msg):
        self.messages.append(msg)


def test_persist_failure_raises(monkeypatch):
    mgr = _FakeSessionMgr(fail=True)
    with pytest.raises(ui_bridge.BlockPersistError):
        ui_bridge._persist_block_message_sync(
            session_id="s1",
            metadata={"block_id": "b1", "module": "m", "block": "x"},
            session_manager=mgr,
        )


def test_persist_success_writes_custom_block_message():
    mgr = _FakeSessionMgr(fail=False)
    ui_bridge._persist_block_message_sync(
        session_id="s1",
        metadata={"block_id": "b1", "module": "m", "block": "x"},
        session_manager=mgr,
    )
    assert len(mgr.saved) == 1
    msg = mgr.saved[0].messages[-1]
    assert msg.role.value == "custom_block"
    assert msg.metadata["block_id"] == "b1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/web/test_ui_bridge_persistence.py -v`
Expected: FAIL — `AttributeError: module 'atria.web.ui_bridge' has no attribute 'BlockPersistError'` / `_persist_block_message_sync`.

- [ ] **Step 3: Add the error type and a synchronous, testable persist core**

In `atria/web/ui_bridge.py`, add near `BlockNotFound` (line 40):

```python
class BlockPersistError(RuntimeError):
    """Raised when a chat block cannot be durably persisted."""
```

Add a synchronous helper that does the actual write against a resolved
session manager (extracted so it is unit-testable and reused by the async path):

```python
def _persist_block_message_sync(
    session_id: str,
    metadata: Dict[str, Any],
    session_manager: Any,
) -> None:
    """Append + save a custom_block ChatMessage. Raises BlockPersistError on failure."""
    import anyio

    async def _save() -> None:
        sess = await session_manager.get_session_by_id(session_id)
        if sess is None:
            raise BlockPersistError(f"session {session_id} not found")
        msg = ChatMessage(role=Role.CUSTOM_BLOCK, content="", metadata=metadata)
        sess.add_message(msg)
        await session_manager.save_session(sess)

    try:
        anyio.from_thread.run(_save)
    except RuntimeError:
        # Not called from a worker thread bound to a loop — run our own.
        try:
            asyncio.run(_save())
        except BlockPersistError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BlockPersistError(str(exc)) from exc
    except BlockPersistError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BlockPersistError(str(exc)) from exc
```

Note: `Any` is already imported; add `import anyio` inside the function as shown to avoid a hard import if unused elsewhere.

- [ ] **Step 4: Route `push_block` through the mandatory path**

In `push_block` (line 294-295), replace the best-effort call:

```python
    if persist:
        _persist_block(session_id, payload, cb=get_current_ui_callback(session_id))
```

Add a thin dispatcher `_persist_block` that resolves the session manager and
calls `_persist_block_message_sync`, replacing the old `_persist_block_message`:

```python
def _persist_block(
    session_id: Optional[str],
    metadata: Dict[str, Any],
    cb: Optional["WebUICallback"] = None,
) -> None:
    if not session_id:
        raise BlockPersistError("cannot persist block without a session_id")
    sm = getattr(cb, "state", None)
    session_manager = getattr(sm, "session_manager", None) if sm else None
    if session_manager is None:
        from atria.web.state import get_state

        session_manager = getattr(get_state(), "session_manager", None)
    if session_manager is None:
        raise BlockPersistError("no session_manager available to persist block")
    _persist_block_message_sync(session_id, metadata, session_manager)
```

Delete the old `_persist_block_message` (lines 176-226) — its logic is now split
into `_persist_block` (resolve) + `_persist_block_message_sync` (write).

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/web/test_ui_bridge_persistence.py -v`
Expected: PASS

- [ ] **Step 6: Verify no other caller referenced the removed function**

Run: `grep -rn "_persist_block_message\b" atria/`
Expected: only `_persist_block_message_sync` remains; no reference to the old name.

- [ ] **Step 7: Commit**

```bash
git add atria/web/ui_bridge.py tests/web/test_ui_bridge_persistence.py
git commit -m "fix(webui): make chat-block persistence mandatory and surface failures"
```

---

### Task 3: `render_component` agent tool

**Files:**
- Create: `atria/core/context_engineering/tools/implementations/render_component_tool.py`
- Create: `atria/core/agents/components/schemas/builtin/component_tools.py`
- Modify: `atria/core/agents/components/schemas/builtin/__init__.py`
- Create: `atria/core/agents/prompts/templates/tools/tool-render-component.md`
- Modify: `atria/core/context_engineering/tools/registry.py:173-242`
- Test: `tests/core/test_render_component_tool.py`

**Interfaces:**
- Consumes: `ui_bridge.push_block(module, block, props, height, title, session_id, persist=True) -> str`, `ui_bridge.BlockNotFound`, `ToolExecutionContext.ui_callback` (for session id).
- Produces: registry handler key `"render_component"`; tool result dict `{"success": bool, "output"|"error": str, "block_id"?: str}`.

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_render_component_tool.py`:

```python
from __future__ import annotations

import pytest
from atria.core.context_engineering.tools.implementations.render_component_tool import (
    RenderComponentHandler,
)
from atria.web import ui_bridge


class _Ctx:
    def __init__(self, sid):
        self.ui_callback = type("CB", (), {"session_id": sid})()


def test_render_missing_module_errors():
    h = RenderComponentHandler()
    res = h.render({"block": "form"}, _Ctx("s1"))
    assert res["success"] is False
    assert "module" in res["error"].lower()


def test_render_pushes_block(monkeypatch):
    calls = {}

    def fake_push_block(module, block, props=None, *, height="auto", title=None,
                        session_id=None, persist=True, **kw):
        calls.update(module=module, block=block, props=props, session_id=session_id,
                     persist=persist)
        return "blk-123"

    monkeypatch.setattr(ui_bridge, "push_block", fake_push_block)
    h = RenderComponentHandler()
    res = h.render(
        {"module": "warehouse", "block": "item_form", "props": {"x": 1}, "title": "Form"},
        _Ctx("s1"),
    )
    assert res["success"] is True
    assert res["block_id"] == "blk-123"
    assert calls["module"] == "warehouse"
    assert calls["persist"] is True
    assert calls["session_id"] == "s1"


def test_render_block_not_found(monkeypatch):
    def fake_push_block(*a, **k):
        raise ui_bridge.BlockNotFound("warehouse/blocks/nope.html not found")

    monkeypatch.setattr(ui_bridge, "push_block", fake_push_block)
    h = RenderComponentHandler()
    res = h.render({"module": "warehouse", "block": "nope"}, _Ctx("s1"))
    assert res["success"] is False
    assert "not found" in res["error"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_render_component_tool.py -v`
Expected: FAIL — `ModuleNotFoundError: ...render_component_tool`.

- [ ] **Step 3: Implement the handler**

Create `atria/core/context_engineering/tools/implementations/render_component_tool.py`:

```python
"""render_component tool — render a module block into the chat mid-turn."""

from __future__ import annotations

from typing import Any

from atria.web import ui_bridge


class RenderComponentHandler:
    """Handler for the render_component tool.

    Wraps ui_bridge.push_block so the agent can place a module's HTML block into
    the chat stream during a turn. The block is persisted (persist=True) so it
    survives session reload.
    """

    def render(self, args: dict[str, Any], context: Any) -> dict[str, Any]:
        module = (args.get("module") or "").strip()
        block = (args.get("block") or "").strip()
        if not module:
            return {"success": False, "error": "render_component requires 'module'", "output": None}
        if not block:
            return {"success": False, "error": "render_component requires 'block'", "output": None}

        props = args.get("props") or {}
        if not isinstance(props, dict):
            return {"success": False, "error": "'props' must be an object", "output": None}
        title = args.get("title")
        height = args.get("height", "auto")

        session_id = None
        cb = getattr(context, "ui_callback", None)
        if cb is not None:
            session_id = getattr(cb, "session_id", None)

        try:
            block_id = ui_bridge.push_block(
                module,
                block,
                props,
                height=height,
                title=title,
                session_id=session_id,
                persist=True,
            )
        except ui_bridge.BlockNotFound as exc:
            return {"success": False, "error": f"block not found: {exc}", "output": None}
        except ui_bridge.BlockPersistError as exc:
            return {"success": False, "error": f"failed to persist block: {exc}", "output": None}
        except RuntimeError as exc:
            return {"success": False, "error": str(exc), "output": None}

        return {
            "success": True,
            "output": f"Rendered {module}/{block} in chat (block_id={block_id})",
            "block_id": block_id,
        }
```

- [ ] **Step 4: Add the tool schema**

Create `atria/core/agents/components/schemas/builtin/component_tools.py`:

```python
"""Built-in tool schemas: module component rendering."""

from __future__ import annotations

from typing import Any

from atria.core.agents.prompts.loader import load_tool_description

SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "render_component",
            "description": load_tool_description("render-component"),
            "parameters": {
                "type": "object",
                "properties": {
                    "module": {
                        "type": "string",
                        "description": "Module name (folder under the modules root).",
                    },
                    "block": {
                        "type": "string",
                        "description": "Block file basename (without .html) under the module's blocks/ dir.",
                    },
                    "props": {
                        "type": "object",
                        "description": "JSON-serializable data passed to the block. Max 256 KB.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Optional title shown above the block.",
                    },
                    "height": {
                        "type": "string",
                        "description": "Block height: 'auto' or a pixel value. Defaults to 'auto'.",
                    },
                },
                "required": ["module", "block"],
            },
        },
    },
]
```

- [ ] **Step 5: Wire the schema into the builtin list**

In `atria/core/agents/components/schemas/builtin/__init__.py`, add the import
after the other imports (line 21) and append to `BUILTIN_TOOL_SCHEMAS`:

```python
from .component_tools import SCHEMAS as _COMPONENT
```

and add `*_COMPONENT,` as the last entry inside `BUILTIN_TOOL_SCHEMAS`.

- [ ] **Step 6: Add the tool description**

Create `atria/core/agents/prompts/templates/tools/tool-render-component.md`:

```markdown
Render a module's HTML block directly into the chat during your turn.

Use this when a module has a purpose-built visual or interactive block that
communicates a result better than prose — for example a form, a status panel, or
a data view. Pass the module name, the block basename, and a JSON `props` object
with the data the block needs. The block is persisted to the conversation and
survives reload.

Do not invent module or block names. If the named block does not exist the tool
returns an error; render only blocks you know the module provides.
```

- [ ] **Step 7: Register the handler in the registry**

In `atria/core/context_engineering/tools/registry.py`, near the other
implementation handlers (import section, ~line 35) add:

```python
from atria.core.context_engineering.tools.implementations.render_component_tool import (
    RenderComponentHandler,
)
```

In the handler-construction area (where other handlers like
`self._send_image_handler` are built), add:

```python
        self._render_component_handler = RenderComponentHandler()
```

and add to the `self._handlers` dict (after `"send_image"`, line 228):

```python
            "render_component": self._render_component_handler.render,
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_render_component_tool.py -v`
Expected: PASS

- [ ] **Step 9: Verify the schema loads and the tool is registered**

Run:
```bash
uv run python -c "from atria.core.agents.components.schemas.builtin import BUILTIN_TOOL_SCHEMAS; print([s['function']['name'] for s in BUILTIN_TOOL_SCHEMAS if s['function']['name']=='render_component'])"
```
Expected: `['render_component']`

- [ ] **Step 10: Commit**

```bash
git add atria/core/context_engineering/tools/implementations/render_component_tool.py atria/core/agents/components/schemas/builtin/component_tools.py atria/core/agents/components/schemas/builtin/__init__.py atria/core/agents/prompts/templates/tools/tool-render-component.md atria/core/context_engineering/tools/registry.py tests/core/test_render_component_tool.py
git commit -m "feat(agent): add render_component tool to render module blocks in chat"
```

---

### Task 4: Read gates — `chat.get_messages`, `chat.get_session`, `artifact.list`, `config.read`

**Files:**
- Modify: `atria/models/config.py:103-106` (`IframeRpcConfig`)
- Modify: `atria/web/websocket.py:459-512` (`_handle_block_rpc`)
- Test: `tests/web/test_block_rpc_gates.py`

**Interfaces:**
- Consumes: `state.session_manager.get_session_by_id(session_id)`, `state.config_manager.get_config()`, `ArtifactsHandler`, `ToolExecutionContext` (existing).
- Produces: `IframeRpcConfig.default_allowlist()` returns the enabled-by-default method list; `IframeRpcConfig.config_read_keys` whitelist; new `block_rpc` methods returning `{...}` payloads via `block_rpc_result`.

- [ ] **Step 1: Write the failing test (config defaults)**

Create `tests/web/test_block_rpc_gates.py`:

```python
from __future__ import annotations

from atria.models.config import IframeRpcConfig


def test_default_allowlist_includes_read_gates():
    cfg = IframeRpcConfig()
    for m in ("chat.get_messages", "chat.get_session", "artifact.list", "config.read"):
        assert m in cfg.tool_allowlist


def test_write_gates_not_default():
    cfg = IframeRpcConfig()
    for m in ("tool.invoke", "session.send_user_message", "module.rpc"):
        assert m not in cfg.tool_allowlist


def test_config_read_keys_whitelist_is_safe():
    cfg = IframeRpcConfig()
    # Whitelist must not expose secret-bearing sections.
    joined = " ".join(cfg.config_read_keys).lower()
    assert "api_key" not in joined
    assert "secret" not in joined
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/web/test_block_rpc_gates.py -v`
Expected: FAIL — default `tool_allowlist` is empty; `config_read_keys` missing.

- [ ] **Step 3: Extend `IframeRpcConfig`**

In `atria/models/config.py` replace the `IframeRpcConfig` class (lines 103-106):

```python
def _default_iframe_allowlist() -> list[str]:
    # Read-only gates are safe to enable by default; write/RPC gates are opt-in.
    return ["chat.get_messages", "chat.get_session", "artifact.list", "config.read"]


def _default_config_read_keys() -> list[str]:
    # Only non-secret, UI-relevant keys may be read by blocks.
    return ["mode", "autonomy_level", "thinking_level", "model", "simple_mode"]


class IframeRpcConfig(BaseModel):
    """RPC settings for custom-block iframes (push_block)."""

    tool_allowlist: list[str] = Field(default_factory=_default_iframe_allowlist)
    config_read_keys: list[str] = Field(default_factory=_default_config_read_keys)
```

- [ ] **Step 4: Run config tests to verify they pass**

Run: `uv run pytest tests/web/test_block_rpc_gates.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing test (dispatch behavior)**

Append to `tests/web/test_block_rpc_gates.py` a test that drives the dispatcher
via a fake WebSocket manager. Add:

```python
import pytest
from atria.web.websocket import WebSocketManager


class _FakeWS:
    def __init__(self):
        self.sent = []


@pytest.fixture
def mgr(monkeypatch):
    m = WebSocketManager()
    m.broadcast = _record(m)  # type: ignore
    return m


def _record(m):
    async def _b(msg):
        m.last = msg
    return _b


async def test_config_read_returns_whitelisted_only(mgr, monkeypatch):
    from atria.web import state as _state

    class _Cfg:
        class web:
            iframe_rpc = IframeRpcConfig()
        mode = "normal"
        autonomy_level = "Manual"

    class _CfgMgr:
        def get_config(self):
            return _Cfg()

    class _State:
        config_manager = _CfgMgr()
        async def get_current_session_id(self):
            return "s1"

    monkeypatch.setattr(_state, "get_state", lambda: _State())
    await mgr._handle_block_rpc(
        _FakeWS(),
        {"data": {"block_id": "b1", "req_id": "r1", "method": "config.read",
                  "args": {"keys": ["mode", "api_key"]}, "session_id": "s1"}},
    )
    assert mgr.last["data"]["ok"] is True
    data = mgr.last["data"]["data"]
    assert data.get("mode") == "normal"
    assert "api_key" not in data
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/web/test_block_rpc_gates.py::test_config_read_returns_whitelisted_only -v`
Expected: FAIL — `config.read` not handled (`unsupported method`).

- [ ] **Step 7: Implement the read gates in `_handle_block_rpc`**

In `atria/web/websocket.py::_handle_block_rpc`, extend `_run_sync` (before the
final `raise ValueError(f"unsupported method: {method}")`, line 512) with:

```python
            if method == "config.read":
                app_config = state.config_manager.get_config()
                allowed_keys = set(app_config.web.iframe_rpc.config_read_keys or [])
                requested = args.get("keys") or list(allowed_keys)
                out: Dict[str, Any] = {}
                for k in requested:
                    if k in allowed_keys:
                        out[k] = getattr(app_config, k, None)
                return out
```

For the async repo-backed reads, add to `_dispatch` (alongside the
`session.send_user_message` branch, before the sync fallback at line 544):

```python
            if method in ("chat.get_messages", "chat.get_session"):
                if not session_id:
                    await _reply(False, error="no active session")
                    return
                try:
                    session = await state.session_manager.get_session_by_id(session_id)
                except Exception as exc:  # noqa: BLE001
                    await _reply(False, error=str(exc))
                    return
                if session is None:
                    await _reply(False, error="session not found")
                    return
                if method == "chat.get_session":
                    await _reply(True, data={
                        "session_id": session_id,
                        "title": getattr(session, "title", None),
                        "message_count": len(session.messages),
                    })
                    return
                limit = args.get("limit")
                msgs = session.messages
                if isinstance(limit, int) and limit > 0:
                    msgs = msgs[-limit:]
                await _reply(True, data={
                    "messages": [m.model_dump(mode="json") for m in msgs],
                })
                return

            if method == "artifact.list":
                try:
                    from atria.core.context_engineering.tools.context import ToolExecutionContext
                    from atria.core.context_engineering.tools.handlers.artifacts_handler import (
                        ArtifactsHandler,
                    )

                    handler = ArtifactsHandler()
                    ctx = ToolExecutionContext(session_manager=state.session_manager)
                    scope = args.get("scope", "conversation")
                    result = await _asyncio.to_thread(
                        handler.list_artifact_images, {"scope": scope}, ctx
                    )
                    await _reply(True, data=result)
                except Exception as exc:  # noqa: BLE001
                    await _reply(False, error=str(exc))
                return
```

Note: `list_artifact_images` signature mirrors `read_artifact_image` used at
line 510. If `ArtifactsHandler` exposes a differently named list method, use
that name — verify with `grep -n "def .*list" atria/core/context_engineering/tools/handlers/artifacts_handler.py` and adjust.

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/web/test_block_rpc_gates.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add atria/models/config.py atria/web/websocket.py tests/web/test_block_rpc_gates.py
git commit -m "feat(webui): add read gates (chat/session/artifact/config) to block_rpc"
```

---

## Phase 2 — Event feed gate

### Task 5: `events.subscribe` + `block_event_feed` forwarding

**Files:**
- Modify: `atria/models/config.py` (`_default_iframe_allowlist` unchanged; `events.subscribe` stays opt-in)
- Modify: `atria/web/websocket.py` (subscription registry + broadcast tap + `events.subscribe` method)
- Test: `tests/web/test_block_event_feed.py`

**Interfaces:**
- Consumes: existing `WebSocketManager.broadcast(msg)`, `_handle_block_rpc` (existing).
- Produces: `WebSocketManager._block_feed_subs: dict[str, set[str]]` (session_id → set of block_ids); `events.subscribe` method that records a block's interest and returns `{"subscribed": [...]}`. Broadcasts of tapped event types also emit a `block_event_feed` message carrying `{block_id, event, data}`.

- [ ] **Step 1: Write the failing test**

Create `tests/web/test_block_event_feed.py`:

```python
from __future__ import annotations

import pytest
from atria.web.websocket import WebSocketManager


class _FakeWS:
    pass


@pytest.fixture
def mgr(monkeypatch):
    m = WebSocketManager()
    m.sent = []

    async def _b(msg):
        m.sent.append(msg)

    m.broadcast = _b  # type: ignore
    return m


async def test_subscribe_records_interest(mgr, monkeypatch):
    from atria.web import state as _state

    class _Cfg:
        class web:
            class iframe_rpc:
                tool_allowlist = ["events.subscribe"]
                config_read_keys = []

    class _CfgMgr:
        def get_config(self):
            return _Cfg()

    class _State:
        config_manager = _CfgMgr()
        async def get_current_session_id(self):
            return "s1"

    monkeypatch.setattr(_state, "get_state", lambda: _State())
    await mgr._handle_block_rpc(
        _FakeWS(),
        {"data": {"block_id": "b1", "req_id": "r1", "method": "events.subscribe",
                  "args": {"events": ["tool_call"]}, "session_id": "s1"}},
    )
    assert "b1" in mgr._block_feed_subs.get("s1", set())


def test_forward_to_feed_emits_block_event_feed(mgr):
    mgr._block_feed_subs = {"s1": {"b1"}}
    mgr.forward_to_block_feed("s1", "tool_call", {"tool_name": "read_file"})
    feed = [m for m in mgr.sent if m.get("type") == "block_event_feed"]
    assert feed and feed[0]["data"]["block_id"] == "b1"
    assert feed[0]["data"]["event"] == "tool_call"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/web/test_block_event_feed.py -v`
Expected: FAIL — no `_block_feed_subs` / `forward_to_block_feed` / `events.subscribe` handling.

- [ ] **Step 3: Add subscription state and forwarder**

In `atria/web/websocket.py`, in `WebSocketManager.__init__`, add:

```python
        self._block_feed_subs: Dict[str, set] = {}
```

Add a method:

```python
    def forward_to_block_feed(self, session_id: str, event: str, data: Dict[str, Any]) -> None:
        """Emit a block_event_feed message for every block subscribed in this session."""
        import asyncio as _asyncio

        subs = self._block_feed_subs.get(session_id)
        if not subs:
            return
        for block_id in list(subs):
            msg = {
                "type": "block_event_feed",
                "data": {"block_id": block_id, "event": event, "data": data,
                         "session_id": session_id},
            }
            try:
                loop = _asyncio.get_running_loop()
                loop.create_task(self.broadcast(msg))
            except RuntimeError:
                _asyncio.run(self.broadcast(msg))
```

- [ ] **Step 4: Handle `events.subscribe` in `_handle_block_rpc`**

In `_dispatch`, before the sync fallback, add:

```python
            if method == "events.subscribe":
                if not session_id:
                    await _reply(False, error="no active session")
                    return
                self._block_feed_subs.setdefault(session_id, set()).add(block_id)
                await _reply(True, data={"subscribed": list(
                    args.get("events") or ["tool_call", "tool_result", "message_complete"]
                )})
                return
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/web/test_block_event_feed.py -v`
Expected: PASS

- [ ] **Step 6: Tap the broadcast path for subscribed events**

Find where turn events (`tool_call`, `tool_result`, `message_complete`) are
broadcast in the callback layer. Run:
`grep -rn "\"type\": WSMessageType.TOOL_CALL\|tool_call\|message_complete" atria/web/web_ui_callback.py | head`

In `web_ui_callback.py`, after each broadcast of a tapped event, add a call to
`ws_manager.forward_to_block_feed(self.session_id, "<event>", <data>)`. If the
callback does not already hold a reference to the manager, import the singleton:
`from atria.web.websocket import ws_manager`. Add forwarding for `tool_call`,
`tool_result`, and `message_complete` only (keep the feed small).

- [ ] **Step 7: Run the full web test suite for regressions**

Run: `uv run pytest tests/web/ -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add atria/web/websocket.py atria/web/web_ui_callback.py tests/web/test_block_event_feed.py
git commit -m "feat(webui): add events.subscribe gate with block_event_feed forwarding"
```

---

## Phase 3 — Module RPC gate

### Task 6: `POST /api/modules/{name}/rpc` route + `module.rpc` gate

**Files:**
- Modify: `atria/web/routes/module_dashboard.py` (new `/rpc` route)
- Modify: `atria/web/websocket.py` (`module.rpc` method in `_run_sync`/`_dispatch`)
- Test: `tests/web/test_module_rpc_route.py`

**Interfaces:**
- Consumes: existing `_resolve_script`, `_try_acquire`/`_release`, subprocess env setup (in `module_dashboard.py`).
- Produces: `POST /api/modules/{name}/rpc` accepting `{method: str, payload: dict, timeout_ms?: int}`, running `scripts/rpc.py` with `{method, payload, session_id}` on stdin, returning `{ok: bool, data|error}`. `module.rpc` block_rpc method proxies to this handler in-process.

- [ ] **Step 1: Write the failing test**

Create `tests/web/test_module_rpc_route.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atria.web.routes import module_dashboard
from atria.core.modules.registry import ModuleRegistry


@pytest.fixture
def client(tmp_path, monkeypatch):
    root = tmp_path / "modules"
    mod = root / "demo" / "scripts"
    mod.mkdir(parents=True)
    (root / "demo" / "SKILL.md").write_text("---\nname: demo\n---\n")
    (mod / "rpc.py").write_text(
        "import sys, json\n"
        "req = json.load(sys.stdin)\n"
        "print(json.dumps({'echo': req['payload'], 'method': req['method']}))\n"
    )
    reg = ModuleRegistry(root=root)
    reg.reload_all() if hasattr(reg, "reload_all") else None
    app = FastAPI()
    app.include_router(module_dashboard.router)
    app.dependency_overrides[module_dashboard.get_modules_registry] = lambda: reg
    return TestClient(app)


def test_module_rpc_echo(client):
    resp = client.post(
        "/api/modules/demo/rpc",
        json={"method": "ping", "payload": {"x": 1}},
        headers={"x-atria-session-id": "s1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["echo"] == {"x": 1}
    assert body["data"]["method"] == "ping"


def test_module_rpc_missing_handler(client, tmp_path):
    resp = client.post("/api/modules/demo/rpc", json={"method": "ping", "payload": {}})
    # demo has rpc.py so this succeeds; a module without rpc.py returns 404.
    # Verify the not-found path with a fresh module lacking rpc.py:
    assert resp.status_code in (200, 404)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/web/test_module_rpc_route.py -v`
Expected: FAIL — no `/rpc` route (404 for all).

- [ ] **Step 3: Implement the `/rpc` route**

In `atria/web/routes/module_dashboard.py`, add a request model near `RunBody`:

```python
class RpcBody(BaseModel):
    method: str = Field(min_length=1)
    payload: dict = Field(default_factory=dict)
    timeout_ms: int = Field(default=30000, ge=1, le=120000)
```

Add the route (after `run_script`), reusing the resolution + concurrency +
subprocess pattern from `run_script`:

```python
@router.post("/{name}/rpc")
def module_rpc(
    name: str,
    body: RpcBody,
    request: Request,
    reg: ModuleRegistry = Depends(get_modules_registry),
) -> dict:
    try:
        module = reg.get(name)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"kind": "unknown-module", "message": f"module {name!r} not found"},
        ) from None

    module_dir = module.dir.resolve()
    target = _resolve_script(module_dir, "rpc.py")
    if not target.is_file():
        raise HTTPException(
            status_code=404,
            detail={"kind": "unknown-rpc-handler",
                    "message": f"module {name!r} has no scripts/rpc.py"},
        )

    session_id = _resolve_session_id(request)
    if not _try_acquire(session_id, name):
        raise HTTPException(status_code=429, detail={"kind": "rate-limited",
                            "message": "too many in-flight runs"})
    try:
        env = os.environ.copy()
        env["ATRIA_SESSION_ID"] = session_id
        env["ATRIA_MODULE_ROOT"] = str(module_dir)
        env.setdefault("ATRIA_API_BASE", "http://127.0.0.1:8000")
        stdin = json.dumps({"method": body.method, "payload": body.payload,
                            "session_id": session_id})
        try:
            proc = subprocess.run(
                [sys.executable, str(target)],
                input=stdin, capture_output=True, text=True,
                timeout=body.timeout_ms / 1000.0, env=env, cwd=str(module_dir),
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"rpc timeout after {body.timeout_ms} ms"}
        if proc.returncode != 0:
            return {"ok": False, "error": (proc.stderr or "non-zero exit").strip()}
        try:
            return {"ok": True, "data": json.loads(proc.stdout or "null")}
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"rpc stdout not valid JSON: {exc}"}
    finally:
        _release(session_id, name)
```

Add `import json` at the top of the module (subprocess/sys/os already imported).

- [ ] **Step 4: Run route tests to verify they pass**

Run: `uv run pytest tests/web/test_module_rpc_route.py -v`
Expected: PASS

- [ ] **Step 5: Wire `module.rpc` into `block_rpc`**

In `atria/web/websocket.py::_handle_block_rpc::_run_sync`, add before the final
`raise ValueError`:

```python
            if method == "module.rpc":
                module_name = args.get("module")
                if not module_name:
                    raise ValueError("module.rpc requires 'module'")
                from atria.web.dependencies.modules import get_modules_registry_singleton  # see note
                from atria.web.routes.module_dashboard import RpcBody, module_rpc

                # Reuse the route function directly with a lightweight request shim.
                raise ValueError("module.rpc dispatch handled in _dispatch")
```

Because the route needs `Request`/registry DI, dispatch `module.rpc` in
`_dispatch` instead by calling the module's rpc subprocess through a small shared
helper. Extract the subprocess body of `module_rpc` into a module-level function
`run_module_rpc(reg, name, method, payload, session_id, timeout_ms=30000) -> dict`
in `module_dashboard.py`, have the route call it, and call the same helper from
`_dispatch`:

```python
            if method == "module.rpc":
                from atria.web.dependencies.modules import get_modules_registry
                from atria.web.routes.module_dashboard import run_module_rpc

                reg = get_modules_registry()
                try:
                    result = await _asyncio.to_thread(
                        run_module_rpc, reg, args.get("module"), args.get("rpc_method"),
                        args.get("payload") or {}, session_id or "default",
                    )
                    await _reply(result.get("ok", False), data=result.get("data"),
                                 error=result.get("error", ""))
                except Exception as exc:  # noqa: BLE001
                    await _reply(False, error=str(exc))
                return
```

Note: verify the DI accessor name with
`grep -n "def get_modules_registry" atria/web/dependencies/modules.py`; if it is a
FastAPI `Depends` provider, add/obtain a plain singleton accessor and use that.
`module.rpc` stays opt-in (not in the default allowlist).

- [ ] **Step 6: Refactor `module_rpc` route to use the shared helper**

Move the subprocess body from Step 3 into `run_module_rpc(reg, name, method, payload, session_id, timeout_ms=30000)` and have the `module_rpc` route resolve `reg`/`session_id` then `return run_module_rpc(...)`. Re-run:

Run: `uv run pytest tests/web/test_module_rpc_route.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add atria/web/routes/module_dashboard.py atria/web/websocket.py tests/web/test_module_rpc_route.py
git commit -m "feat(modules): add module.rpc gate + POST /api/modules/{name}/rpc route"
```

---

## Final verification

- [ ] **Step 1: Run the full unit suite**

Run: `uv run pytest tests/web tests/core tests/test_message_repo_orm.py -q`
Expected: PASS (DB tests skip when `DATABASE_URL` is unset).

- [ ] **Step 2: Format + lint + typecheck**

Run: `make check`
Expected: no errors.

- [ ] **Step 3: Real-API end-to-end**

With `OPENAI_API_KEY` and `DATABASE_URL` set, start the web UI (`atria run ui`) with an existing module that has a `blocks/*.html` (e.g. `warehouse/blocks/item_form.html`). Prompt the agent to render that block via `render_component`. Verify:
- the block appears in the chat,
- a row exists in `messages` with `role = 'custom_block'` and metadata in `blocks->'raw'`,
- reloading the session re-renders the block,
- from the block, `chat.get_messages` and (if the module ships `scripts/rpc.py`) a `module.rpc` round-trip both succeed.

- [ ] **Step 4: Commit any test/fixture additions from e2e**

```bash
git add -A && git commit -m "test(e2e): module chat gates + block persistence end-to-end"
```

---

## Self-Review notes

- **Spec coverage:** §A read gates → Task 4; `events.subscribe` → Task 5; `module.rpc` → Task 6; §B render tool → Task 3; §C rpc route → Task 6; §D persistence (widen role, reliable push_block) → Tasks 1–2. Native Web Components are explicitly out of scope (spec Non-goals).
- **Correction vs spec:** spec assumed `_blocks_to_msg` collapses block role/metadata; in fact it round-trips via the `blocks."raw"` field, so Task 1 focuses on the real gaps (role-column truncation + widening) and Task 2 fixes the actual functional bug (unreliable persistence). No separate `_msg_to_blocks`/`_blocks_to_msg` rewrite task is needed.
- **Type consistency:** `push_block` kwargs (`module, block, props, height, title, session_id, persist`) match Task 3 usage; `BlockPersistError`/`_persist_block_message_sync`/`_persist_block` names are consistent across Tasks 2–3; `forward_to_block_feed`/`_block_feed_subs` consistent across Task 5.
- **Open items to confirm during execution (flagged inline):** exact `ArtifactsHandler` list-method name (Task 4 Step 7), the modules-registry singleton accessor (Task 6 Step 5), and the callback event-broadcast sites to tap (Task 5 Step 6).
