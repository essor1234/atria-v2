# Chat Message Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add hover-toolbar actions to chat messages — copy single message, copy entire turn, delete entire turn (persisted) — and explicitly omit any edit affordance for user messages.

**Architecture:** A small `<MessageActions>` row renders under each item in `MessageList`; turn boundaries are derived in a pure helper (`computeTurns`) bounded by `user` messages. The block-level Copy/Delete actions are shown only on the last item of each turn. Delete calls a new `DELETE /api/sessions/{sid}/turns/{turn_index}` route that soft-deletes the rows for that turn slice in Postgres and broadcasts a `session_messages_replaced` WebSocket event so other tabs reconcile. Copy writes plain text (markdown stripped) via the Clipboard API with an `execCommand('copy')` fallback.

**Tech Stack:** FastAPI + SQLAlchemy/asyncpg (backend), React + Zustand + Vitest + Virtuoso + Tailwind (frontend).

**Project conventions for this plan (per repo memory):**
- Skip per-task test runs during execution. Each task ends with a commit; the final task runs the whole test suite once.
- Commits use Conventional-Commits style; **do not** add a `Co-Authored-By: Claude` trailer.

---

## File Structure

**Backend (new + modified):**
- `atria/db/repositories/message_repo.py` — add `list_ids_by_conversation` and `soft_delete_by_ids`.
- `atria/core/context_engineering/history/session_manager/pg_manager.py` — add `delete_turn(session_id, turn_index)`.
- `atria/web/routes/sessions.py` — add `DELETE /{session_id}/turns/{turn_index}` route + `broadcast_session_messages_replaced` helper call.
- `atria/web/websocket.py` (or wherever broadcast helpers live) — small helper `broadcast_session_messages_replaced(session_id, messages)` if not already trivial.

**Backend tests:**
- `tests/test_message_actions.py` — new test file covering repo, manager, route.

**Frontend (new + modified):**
- `web-ui/src/lib/turns.ts` — pure helpers: `computeTurns`, `serializeMessageForClipboard`, `serializeTurnForClipboard`.
- `web-ui/src/lib/turns.test.ts` — vitest tests for the helpers.
- `web-ui/src/lib/clipboard.ts` — `writeClipboardText(text): Promise<boolean>` with `execCommand` fallback.
- `web-ui/src/components/Chat/MessageActions.tsx` — the toolbar component.
- `web-ui/src/hooks/useMessageActions.ts` — wires store + clipboard + toast.
- `web-ui/src/api/client.ts` — add `deleteSessionTurn`.
- `web-ui/src/stores/chat.ts` — add `deleteTurn` action + WS handler for `session_messages_replaced`.
- `web-ui/src/components/Chat/MessageList.tsx` — derive turn info and pass to items; render `<MessageActions>` in each row.

---

## Task 1: Backend — `MessageRepository` helpers for index → ids and soft-delete by ids

**Files:**
- Modify: `atria/db/repositories/message_repo.py`
- Test: `tests/test_message_actions.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_message_actions.py`:

```python
"""Tests for chat-message action endpoints (copy/delete)."""

from __future__ import annotations

import asyncio

import pytest

from atria.db.repositories.message_repo import MessageRepository
from atria.db.repositories.conversation_repo import ConversationRepository
from atria.models.message import ChatMessage, Role


@pytest.mark.asyncio
async def test_list_ids_by_conversation_returns_in_insertion_order(pg_session_factory):
    conv_repo = ConversationRepository(pg_session_factory)
    msg_repo = MessageRepository(pg_session_factory)

    conv_id = await conv_repo.create(user_id=None, mode="normal", working_directory=None)

    inserted: list[int] = []
    for content in ["hello", "world", "again"]:
        inserted.append(
            await msg_repo.insert(conv_id, ChatMessage(role=Role.USER, content=content))
        )

    ids = await msg_repo.list_ids_by_conversation(conv_id)
    assert ids == inserted


@pytest.mark.asyncio
async def test_soft_delete_by_ids_marks_rows_deleted(pg_session_factory):
    conv_repo = ConversationRepository(pg_session_factory)
    msg_repo = MessageRepository(pg_session_factory)

    conv_id = await conv_repo.create(user_id=None, mode="normal", working_directory=None)
    ids = [
        await msg_repo.insert(conv_id, ChatMessage(role=Role.USER, content="a")),
        await msg_repo.insert(conv_id, ChatMessage(role=Role.ASSISTANT, content="b")),
        await msg_repo.insert(conv_id, ChatMessage(role=Role.USER, content="c")),
    ]

    deleted = await msg_repo.soft_delete_by_ids([ids[0], ids[1]])
    assert deleted == 2

    remaining = await msg_repo.list_by_conversation(conv_id)
    assert [m.content for m in remaining] == ["c"]
```

- [ ] **Step 2: Add the helpers to `MessageRepository`**

In `atria/db/repositories/message_repo.py`, append two methods to `MessageRepository` (alongside the existing `insert` / `list_by_conversation`):

```python
    async def list_ids_by_conversation(self, conversation_id: int) -> list[int]:
        """Return live (not soft-deleted) message ids in insertion order."""
        async with self._sessionmaker() as session:
            stmt = (
                select(Message.id)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.is_deleted.is_(False),
                )
                .order_by(Message.id.asc())
            )
            result = await session.execute(stmt)
        return [int(row[0]) for row in result.all()]

    async def soft_delete_by_ids(self, ids: list[int]) -> int:
        """Soft-delete the given message ids. Returns rows affected."""
        if not ids:
            return 0
        async with self._sessionmaker() as session:
            stmt = (
                update(Message)
                .where(Message.id.in_(ids), Message.is_deleted.is_(False))
                .values(is_deleted=True)
            )
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)
```

If `update` is not imported at the top of `message_repo.py`, add it to the existing `sqlalchemy` import (e.g. `from sqlalchemy import select, update`). Verify the existing import line and adjust accordingly.

- [ ] **Step 3: Commit**

```bash
git add atria/db/repositories/message_repo.py tests/test_message_actions.py
git commit -m "feat(history): list_ids_by_conversation + soft_delete_by_ids on MessageRepository"
```

---

## Task 2: Backend — `PgSessionManager.delete_turn`

**Files:**
- Modify: `atria/core/context_engineering/history/session_manager/pg_manager.py`
- Test: `tests/test_message_actions.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_message_actions.py`:

```python
from atria.core.context_engineering.history.session_manager.pg_manager import PgSessionManager


@pytest.mark.asyncio
async def test_delete_turn_drops_user_message_only(pg_session_factory):
    mgr = PgSessionManager(sessionmaker=pg_session_factory)
    session = await mgr.create_session(working_directory=None)

    await mgr.add_message(ChatMessage(role=Role.USER, content="u1"), auto_save_interval=1)
    await mgr.add_message(ChatMessage(role=Role.ASSISTANT, content="a1"), auto_save_interval=1)
    await mgr.add_message(ChatMessage(role=Role.USER, content="u2"), auto_save_interval=1)
    await mgr.add_message(ChatMessage(role=Role.ASSISTANT, content="a2"), auto_save_interval=1)

    # Delete the second user turn (turn_index = 2): drops u2 + a2.
    remaining = await mgr.delete_turn(session.id, turn_index=2)
    assert [m.content for m in remaining] == ["u1", "a1"]


@pytest.mark.asyncio
async def test_delete_turn_rejects_out_of_range(pg_session_factory):
    mgr = PgSessionManager(sessionmaker=pg_session_factory)
    session = await mgr.create_session(working_directory=None)
    await mgr.add_message(ChatMessage(role=Role.USER, content="u1"), auto_save_interval=1)

    with pytest.raises(IndexError):
        await mgr.delete_turn(session.id, turn_index=5)


@pytest.mark.asyncio
async def test_delete_turn_rejects_when_not_user_message(pg_session_factory):
    mgr = PgSessionManager(sessionmaker=pg_session_factory)
    session = await mgr.create_session(working_directory=None)
    await mgr.add_message(ChatMessage(role=Role.USER, content="u1"), auto_save_interval=1)
    await mgr.add_message(ChatMessage(role=Role.ASSISTANT, content="a1"), auto_save_interval=1)

    with pytest.raises(ValueError):
        await mgr.delete_turn(session.id, turn_index=1)  # assistant, not user
```

- [ ] **Step 2: Implement `delete_turn` in `PgSessionManager`**

Add this method to `PgSessionManager` (near `delete_session`):

```python
    async def delete_turn(self, session_id: str, turn_index: int) -> list[ChatMessage]:
        """Soft-delete the contiguous slice [turn_index, next_user_index).

        Raises:
            FileNotFoundError: session unknown
            IndexError: turn_index out of range
            ValueError: turn_index does not point to a USER message
        """
        from atria.models.message import Role

        try:
            conv_id = int(session_id)
        except ValueError:
            raise FileNotFoundError(session_id)

        _, msg_repo = await self._get_repos()
        messages = await msg_repo.list_by_conversation(conv_id)

        if turn_index < 0 or turn_index >= len(messages):
            raise IndexError(f"turn_index {turn_index} out of range (len={len(messages)})")
        if messages[turn_index].role != Role.USER:
            raise ValueError(f"turn_index {turn_index} is not a USER message")

        end = turn_index + 1
        while end < len(messages) and messages[end].role != Role.USER:
            end += 1

        ids = await msg_repo.list_ids_by_conversation(conv_id)
        # ids is the same length & order as messages (both filtered to is_deleted=False)
        ids_to_delete = ids[turn_index:end]
        await msg_repo.soft_delete_by_ids(ids_to_delete)

        # Keep in-memory current_session in sync if it matches.
        if self.current_session and self.current_session.id == session_id:
            self.current_session.messages = (
                self.current_session.messages[:turn_index]
                + self.current_session.messages[end:]
            )
            remaining = self.current_session.messages
        else:
            remaining = messages[:turn_index] + messages[end:]

        return remaining
```

- [ ] **Step 3: Commit**

```bash
git add atria/core/context_engineering/history/session_manager/pg_manager.py tests/test_message_actions.py
git commit -m "feat(history): PgSessionManager.delete_turn soft-deletes a turn slice"
```

---

## Task 3: Backend — `DELETE /api/sessions/{sid}/turns/{turn_index}` route + WS broadcast

**Files:**
- Modify: `atria/web/routes/sessions.py`
- Test: `tests/test_message_actions.py`

- [ ] **Step 1: Inspect existing broadcast helpers**

Before writing code, run:

```bash
grep -n "broadcast\|websocket\|session_messages" atria/web/routes/sessions.py atria/web/websocket.py atria/web/state.py | head -40
```

Use whichever broadcast helper the existing `delete_session` route already uses (or a sibling). If none exists, fall back to calling `state.connection_manager.broadcast_to_session(session_id, {...})` — verify the actual method name in the same grep pass.

- [ ] **Step 2: Add the failing route test**

Append to `tests/test_message_actions.py`:

```python
from fastapi.testclient import TestClient


def test_delete_turn_endpoint_success(client: TestClient, seeded_session_with_two_turns):
    sid, turn_index = seeded_session_with_two_turns  # turn_index = 2 (second user msg)
    r = client.delete(f"/api/sessions/{sid}/turns/{turn_index}")
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] >= 1
    assert isinstance(body["messages"], list)
    # only the first turn remains
    assert all(m["role"] != "user" or m["content"] == "u1" for m in body["messages"])


def test_delete_turn_endpoint_out_of_range_returns_404(client, seeded_session_with_two_turns):
    sid, _ = seeded_session_with_two_turns
    r = client.delete(f"/api/sessions/{sid}/turns/9999")
    assert r.status_code == 404


def test_delete_turn_endpoint_rejects_non_user_index_404(client, seeded_session_with_two_turns):
    sid, _ = seeded_session_with_two_turns
    # index 1 is assistant
    r = client.delete(f"/api/sessions/{sid}/turns/1")
    assert r.status_code == 404
```

If `client` / `seeded_session_with_two_turns` fixtures don't exist, copy the seeding pattern from any existing route test (`tests/test_sessions_routes.py` is a likely model) and add the fixtures at the top of `tests/test_message_actions.py`. Don't invent new harness — reuse what's already there.

- [ ] **Step 3: Add the route**

In `atria/web/routes/sessions.py`, near `delete_session` (around line 299), insert:

```python
@router.delete("/{session_id}/turns/{turn_index}")
async def delete_session_turn(
    session_id: str,
    turn_index: int,
    user=Depends(require_authenticated_user),
) -> Dict[str, Any]:
    """Delete a single turn from the session (soft-delete, persisted)."""
    state = get_state()
    try:
        remaining = await state.session_manager.delete_turn(session_id, turn_index)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except IndexError:
        raise HTTPException(status_code=404, detail="turn_index out of range")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    payload = [
        MessageResponse(
            role=m.role.value,
            content=m.content,
            timestamp=m.timestamp.isoformat() if getattr(m, "timestamp", None) else None,
            tool_calls=[tool_call_to_info(tc) for tc in m.tool_calls] if m.tool_calls else None,
            thinking_trace=m.thinking_trace,
            reasoning_content=m.reasoning_content,
            metadata=m.metadata if m.metadata else None,
        )
        for m in remaining
        if not m.metadata.get("display_hidden")
    ]

    # Best-effort broadcast so other connected tabs reconcile.
    try:
        await state.connection_manager.broadcast_to_session(
            session_id,
            {"type": "session_messages_replaced", "messages": [p.dict() for p in payload]},
        )
    except Exception:
        pass

    return {"deleted": len(remaining), "messages": [p.dict() for p in payload]}
```

If the helper name turned up in Step 1 is different (e.g. `broadcast_message_to_session`), use that name exactly. Do **not** silently swallow exceptions other than the broadcast — only the broadcast is best-effort.

- [ ] **Step 4: Commit**

```bash
git add atria/web/routes/sessions.py tests/test_message_actions.py
git commit -m "feat(api): DELETE /api/sessions/{sid}/turns/{turn_index}"
```

---

## Task 4: Frontend — pure helpers `computeTurns` and clipboard serializers

**Files:**
- Create: `web-ui/src/lib/turns.ts`
- Create: `web-ui/src/lib/turns.test.ts`

- [ ] **Step 1: Write the failing vitest**

Create `web-ui/src/lib/turns.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { computeTurns, serializeMessageForClipboard, serializeTurnForClipboard } from './turns';
import type { Message } from '../types';

const u = (content: string): Message => ({ role: 'user', content });
const a = (content: string): Message => ({ role: 'assistant', content });
const tc = (name: string, summary: string): Message => ({
  role: 'tool_call',
  content: '',
  tool_name: name,
  tool_args: { x: 1 },
  tool_summary: summary,
});

describe('computeTurns', () => {
  it('returns one turn per user message, extending to next user', () => {
    const msgs = [u('hi'), a('hello'), tc('bash', 'ran'), u('again'), a('ok')];
    const turns = computeTurns(msgs);
    expect(turns).toEqual([
      { turnId: 'turn-0', startIndex: 0, endIndex: 2 },
      { turnId: 'turn-3', startIndex: 3, endIndex: 4 },
    ]);
  });

  it('handles transcript that does not start with a user message', () => {
    const msgs = [a('orphan'), u('hi'), a('hello')];
    const turns = computeTurns(msgs);
    expect(turns).toEqual([
      { turnId: 'turn-0', startIndex: 0, endIndex: 0 },
      { turnId: 'turn-1', startIndex: 1, endIndex: 2 },
    ]);
  });

  it('returns empty for empty input', () => {
    expect(computeTurns([])).toEqual([]);
  });
});

describe('serializeMessageForClipboard', () => {
  it('strips simple markdown from assistant text', () => {
    const m: Message = { role: 'assistant', content: '**bold** and `code` and _i_' };
    expect(serializeMessageForClipboard(m)).toBe('bold and code and i');
  });

  it('renders tool_call with summary', () => {
    expect(serializeMessageForClipboard(tc('bash', 'exit 0'))).toContain('[tool: bash]');
    expect(serializeMessageForClipboard(tc('bash', 'exit 0'))).toContain('exit 0');
  });

  it('falls back to placeholder for empty image message', () => {
    const m: Message = { role: 'image_message', content: '' };
    expect(serializeMessageForClipboard(m)).toBe('[image]');
  });
});

describe('serializeTurnForClipboard', () => {
  it('joins items with double newline and skips system', () => {
    const msgs: Message[] = [
      u('hi'),
      { role: 'system', content: 'hidden' },
      a('hello'),
    ];
    const turn = { turnId: 'turn-0', startIndex: 0, endIndex: 2 };
    const out = serializeTurnForClipboard(msgs, turn);
    expect(out).toBe('hi\n\nhello');
  });

  it('returns [empty turn] when nothing serializes', () => {
    const msgs: Message[] = [{ role: 'system', content: '' }];
    const turn = { turnId: 'turn-0', startIndex: 0, endIndex: 0 };
    expect(serializeTurnForClipboard(msgs, turn)).toBe('[empty turn]');
  });
});
```

- [ ] **Step 2: Implement `web-ui/src/lib/turns.ts`**

```ts
import type { Message } from '../types';

export interface TurnInfo {
  turnId: string;
  startIndex: number;
  endIndex: number; // inclusive
}

export function computeTurns(messages: Message[]): TurnInfo[] {
  if (messages.length === 0) return [];
  const turns: TurnInfo[] = [];
  let cursor = 0;

  // Leading non-user prefix becomes a turn rooted at index 0.
  if (messages[0].role !== 'user') {
    let end = 0;
    while (end + 1 < messages.length && messages[end + 1].role !== 'user') end++;
    turns.push({ turnId: 'turn-0', startIndex: 0, endIndex: end });
    cursor = end + 1;
  }

  while (cursor < messages.length) {
    const start = cursor;
    let end = cursor;
    while (end + 1 < messages.length && messages[end + 1].role !== 'user') end++;
    turns.push({ turnId: `turn-${start}`, startIndex: start, endIndex: end });
    cursor = end + 1;
  }

  return turns;
}

const MARKDOWN_STRIP_RE = /(\*\*|__|`+|^#{1,6}\s*|^\s*[-*+]\s+|^\s*\d+\.\s+|_(?=\w))/gm;

function stripMarkdown(text: string): string {
  return text.replace(MARKDOWN_STRIP_RE, '').replace(/[*_`]/g, '').trim();
}

const TOOL_RESULT_BYTE_CAP = 4096;
function truncate(s: string, cap = TOOL_RESULT_BYTE_CAP): string {
  return s.length > cap ? s.slice(0, cap) + '…' : s;
}

export function serializeMessageForClipboard(m: Message): string {
  switch (m.role) {
    case 'user':
    case 'assistant': {
      const stripped = stripMarkdown(m.content);
      return stripped || m.content;
    }
    case 'thinking':
      return `[thinking] ${m.content}`;
    case 'tool_call': {
      const argText = m.tool_args_display ?? JSON.stringify(m.tool_args ?? {});
      const result =
        typeof m.tool_summary === 'string'
          ? m.tool_summary
          : Array.isArray(m.tool_summary)
            ? m.tool_summary.join('\n')
            : (m.tool_result && typeof m.tool_result === 'string'
              ? m.tool_result
              : m.tool_result
                ? JSON.stringify(m.tool_result)
                : '');
      return `[tool: ${m.tool_name ?? 'unknown'}] ${argText}\n→ ${truncate(result)}`;
    }
    case 'tool_result':
      return ''; // collapsed into its parent tool_call
    case 'search_result': {
      const items = (m.search_results ?? [])
        .map(r => `  - ${r.title} — ${r.url}`)
        .join('\n');
      return `[search: ${m.search_query ?? ''}]\n${items}`;
    }
    case 'image_message':
      return m.image_caption || '[image]';
    case 'data_message':
      return `[data: ${m.data_title ?? m.data_message_id ?? ''}]`;
    case 'deep_research':
      return `[deep research: ${m.dr_topic ?? ''}]`;
    case 'deep_analyze':
      return `[deep analyze: ${m.da_job_id ?? ''}]`;
    case 'custom_block':
      return `[block: ${m.block_title ?? m.block_id ?? ''}]`;
    case 'system':
      return '';
    default:
      return m.content || '';
  }
}

export function serializeTurnForClipboard(messages: Message[], turn: TurnInfo): string {
  const parts: string[] = [];
  for (let i = turn.startIndex; i <= turn.endIndex; i++) {
    const s = serializeMessageForClipboard(messages[i]);
    if (s) parts.push(s);
  }
  return parts.length === 0 ? '[empty turn]' : parts.join('\n\n');
}
```

- [ ] **Step 3: Commit**

```bash
git add web-ui/src/lib/turns.ts web-ui/src/lib/turns.test.ts
git commit -m "feat(web-ui): turn computation + clipboard serializers"
```

---

## Task 5: Frontend — clipboard helper

**Files:**
- Create: `web-ui/src/lib/clipboard.ts`

- [ ] **Step 1: Implement**

```ts
export async function writeClipboardText(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // fall through
    }
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add web-ui/src/lib/clipboard.ts
git commit -m "feat(web-ui): writeClipboardText with execCommand fallback"
```

---

## Task 6: Frontend — `deleteSessionTurn` in API client

**Files:**
- Modify: `web-ui/src/api/client.ts`

- [ ] **Step 1: Inspect**

```bash
grep -n "deleteSession\b\|export const apiClient\|axios\|fetch" web-ui/src/api/client.ts | head -20
```

- [ ] **Step 2: Add the method**

Add to the existing `apiClient` object (match the style of `deleteSession`):

```ts
async deleteSessionTurn(sessionId: string, turnIndex: number): Promise<{
  deleted: number;
  messages: any[];
}> {
  const r = await fetch(`/api/sessions/${sessionId}/turns/${turnIndex}`, {
    method: 'DELETE',
    headers: this.authHeaders(),
  });
  if (!r.ok) throw new Error(`deleteSessionTurn failed: ${r.status}`);
  return r.json();
},
```

If the file uses axios instead of `fetch`, mirror the axios style of the sibling `deleteSession` call.

- [ ] **Step 3: Commit**

```bash
git add web-ui/src/api/client.ts
git commit -m "feat(web-ui): apiClient.deleteSessionTurn"
```

---

## Task 7: Frontend — `chat.ts` store `deleteTurn` action + WS handler

**Files:**
- Modify: `web-ui/src/stores/chat.ts`

- [ ] **Step 1: Inspect WS handler shape**

```bash
grep -n "type ===\|case '\|'data_message'\|ws.onmessage\|handleWsMessage" web-ui/src/stores/chat.ts | head -30
```

Find where typed WS payloads are dispatched and identify the helper/function in the store that returns the imperative API (the one that exposes `addMessage`, `setLoading`, etc).

- [ ] **Step 2: Add `deleteTurn` to the store**

Inside the existing Zustand store creator, add (alongside other actions like `addMessage`):

```ts
deleteTurn: async (sessionId: string, turnIndex: number) => {
  const prev = get().sessionStates[sessionId]?.messages ?? [];
  try {
    const { messages } = await apiClient.deleteSessionTurn(sessionId, turnIndex);
    set(state => {
      const ss = getSessionState(state.sessionStates, sessionId);
      ss.messages = messages as Message[];
      return { sessionStates: { ...state.sessionStates } };
    });
  } catch (e: any) {
    useToastStore.getState().push({
      kind: 'error',
      title: 'Delete failed',
      body: e?.message ?? 'Could not delete turn',
    });
    // restore (best effort — state was unchanged on failure, but explicit no-op for clarity)
    set(state => {
      const ss = getSessionState(state.sessionStates, sessionId);
      ss.messages = prev;
      return { sessionStates: { ...state.sessionStates } };
    });
  }
},
```

If `useToastStore` import / shape differs, check `web-ui/src/stores/toast.ts` and adjust the call. Likewise mirror the existing pattern other actions use to obtain `apiClient`.

Also expose `deleteTurn` on the store's public interface (TypeScript type for state). Find the existing `interface ChatState` (or similar) and add:

```ts
deleteTurn: (sessionId: string, turnIndex: number) => Promise<void>;
```

- [ ] **Step 3: Add WS handler for `session_messages_replaced`**

In the same file's WS dispatch switch (whatever shape it has — look for existing case labels like `'session_state'` or similar), add:

```ts
case 'session_messages_replaced': {
  const sid = message.data?.session_id ?? state.currentSessionId;
  const replacement = message.data?.messages ?? message.messages;
  if (!sid || !Array.isArray(replacement)) break;
  set(s => {
    const ss = getSessionState(s.sessionStates, sid);
    ss.messages = replacement as Message[];
    return { sessionStates: { ...s.sessionStates } };
  });
  break;
}
```

The route in Task 3 broadcasts `{type, messages}` — adjust the destructure to whatever envelope the existing WS code uses (e.g., `message.data.messages` vs `message.messages`). Match the existing convention by grepping for one or two existing cases first.

- [ ] **Step 4: Commit**

```bash
git add web-ui/src/stores/chat.ts
git commit -m "feat(web-ui): chat store deleteTurn + session_messages_replaced WS handler"
```

---

## Task 8: Frontend — `useMessageActions` hook

**Files:**
- Create: `web-ui/src/hooks/useMessageActions.ts`

- [ ] **Step 1: Implement**

```ts
import { useCallback } from 'react';
import { useChatStore } from '../stores/chat';
import { useToastStore } from '../stores/toast';
import { writeClipboardText } from '../lib/clipboard';
import {
  serializeMessageForClipboard,
  serializeTurnForClipboard,
  type TurnInfo,
} from '../lib/turns';
import type { Message } from '../types';

export function useMessageActions() {
  const sessionId = useChatStore(s => s.currentSessionId);
  const deleteTurn = useChatStore(s => s.deleteTurn);
  const messages = useChatStore(s => {
    const sid = s.currentSessionId;
    return sid ? s.sessionStates[sid]?.messages ?? [] : [];
  });
  const isLoading = useChatStore(s => {
    const sid = s.currentSessionId;
    return sid ? s.sessionStates[sid]?.isLoading ?? false : false;
  });
  const toast = useToastStore.getState();

  const copyMessage = useCallback(async (m: Message) => {
    const text = serializeMessageForClipboard(m) || m.content;
    const ok = await writeClipboardText(text);
    toast.push({
      kind: ok ? 'success' : 'error',
      title: ok ? 'Copied message' : 'Copy failed',
    });
  }, [toast]);

  const copyTurn = useCallback(async (turn: TurnInfo) => {
    const ok = await writeClipboardText(serializeTurnForClipboard(messages, turn));
    toast.push({
      kind: ok ? 'success' : 'error',
      title: ok ? 'Copied turn' : 'Copy failed',
    });
  }, [messages, toast]);

  const deleteTurnAction = useCallback(async (turn: TurnInfo) => {
    if (!sessionId) return;
    await deleteTurn(sessionId, turn.startIndex);
  }, [sessionId, deleteTurn]);

  return { copyMessage, copyTurn, deleteTurn: deleteTurnAction, isLoading };
}
```

If `useToastStore.push` does not exist, adapt to whatever method the toast store actually exposes (`add`, `show`, etc) by reading `web-ui/src/stores/toast.ts`.

- [ ] **Step 2: Commit**

```bash
git add web-ui/src/hooks/useMessageActions.ts
git commit -m "feat(web-ui): useMessageActions hook"
```

---

## Task 9: Frontend — `<MessageActions>` component

**Files:**
- Create: `web-ui/src/components/Chat/MessageActions.tsx`

- [ ] **Step 1: Implement**

```tsx
import { useState, useEffect } from 'react';
import { Copy, CopyPlus, Trash2, Check, X } from 'lucide-react';

interface Props {
  align?: 'left' | 'right';
  onCopyMessage: () => void;
  onCopyBlock?: () => void;
  onDeleteBlock?: () => void;
  deleteDisabled?: boolean;
}

export function MessageActions({
  align = 'left',
  onCopyMessage,
  onCopyBlock,
  onDeleteBlock,
  deleteDisabled,
}: Props) {
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    if (!confirming) return;
    const id = setTimeout(() => setConfirming(false), 4000);
    return () => clearTimeout(id);
  }, [confirming]);

  const wrapClass =
    'flex items-center gap-1.5 mt-1 ' +
    (align === 'right' ? 'justify-end ' : 'pl-[26px] ') +
    'opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity ' +
    'md:opacity-0 max-md:opacity-30';

  const btn =
    'p-1 rounded-md text-ink/50 hover:text-ink hover:bg-surface-soft ' +
    'focus-visible:outline focus-visible:outline-2 focus-visible:outline-ink/40 ' +
    'disabled:opacity-40 disabled:cursor-not-allowed';

  return (
    <div className={wrapClass}>
      <button
        type="button"
        className={btn}
        onClick={onCopyMessage}
        aria-label="Copy message"
        title="Copy message"
      >
        <Copy className="w-3.5 h-3.5" />
      </button>

      {onCopyBlock && (
        <button
          type="button"
          className={btn}
          onClick={onCopyBlock}
          aria-label="Copy entire turn"
          title="Copy entire turn"
        >
          <CopyPlus className="w-3.5 h-3.5" />
        </button>
      )}

      {onDeleteBlock && !confirming && (
        <button
          type="button"
          className={btn}
          onClick={() => setConfirming(true)}
          aria-label="Delete turn"
          title="Delete turn"
          disabled={deleteDisabled}
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      )}

      {onDeleteBlock && confirming && (
        <span className="inline-flex items-center gap-1">
          <button
            type="button"
            className={btn + ' text-red-600'}
            onClick={() => {
              setConfirming(false);
              onDeleteBlock?.();
            }}
            aria-label="Confirm delete"
            title="Confirm"
          >
            <Check className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            className={btn}
            onClick={() => setConfirming(false)}
            aria-label="Cancel delete"
            title="Cancel"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </span>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web-ui/src/components/Chat/MessageActions.tsx
git commit -m "feat(web-ui): MessageActions hover toolbar component"
```

---

## Task 10: Frontend — wire `<MessageActions>` into `MessageList`

**Files:**
- Modify: `web-ui/src/components/Chat/MessageList.tsx`

- [ ] **Step 1: Replace turn derivation + per-item wrapping**

In `web-ui/src/components/Chat/MessageList.tsx`:

1. Add imports near the top:

```ts
import { computeTurns, type TurnInfo } from '../../lib/turns';
import { MessageActions } from './MessageActions';
import { useMessageActions } from '../../hooks/useMessageActions';
```

2. Extend `ListContext` (≈ line 190):

```ts
interface ListContext {
  isLoading: boolean;
  progressMessage: string | null;
  totalCount: number;
  turnByIndex: Map<number, { turn: TurnInfo; isLastInTurn: boolean }>;
  actions: ReturnType<typeof useMessageActions>;
}
```

3. Inside `MessageList()` after the existing `messages` memo, add:

```ts
const turnInfos = useMemo(() => computeTurns(messages), [messages]);
const turnByIndex = useMemo(() => {
  const map = new Map<number, { turn: TurnInfo; isLastInTurn: boolean }>();
  for (const t of turnInfos) {
    for (let i = t.startIndex; i <= t.endIndex; i++) {
      map.set(i, { turn: t, isLastInTurn: i === t.endIndex });
    }
  }
  return map;
}, [turnInfos]);

const actions = useMessageActions();
```

4. Update the `context` memo:

```ts
const context = useMemo<ListContext>(
  () => ({ isLoading, progressMessage, totalCount: messages.length, turnByIndex, actions }),
  [isLoading, progressMessage, messages.length, turnByIndex, actions]
);
```

5. Update `MessageItem`'s signature and body to render actions. Replace the existing `MessageItem` definition with:

```tsx
const MessageItem = memo(function MessageItem({
  message,
  index,
  context,
}: {
  message: Message;
  index: number;
  context: ListContext;
}) {
  const { isLoading, totalCount, turnByIndex, actions } = context;
  const turnEntry = turnByIndex.get(index);

  let body: React.ReactNode;
  if (message.role === 'tool_call') {
    const hasResult = message.tool_result != null && Object.keys(message.tool_result).length > 0;
    body = <ToolCallMessage message={message} hasResult={hasResult} />;
  } else if (message.role === 'thinking') {
    const isLastThinking = (isLoading || !!message.streaming) && index === totalCount - 1;
    body = <ThinkingBlock content={message.content} level={message.metadata?.level} isActive={isLastThinking} />;
  } else if (message.role === 'search_result') body = <SearchResultBlock message={message} />;
  else if (message.role === 'data_message') body = <DataMessage message={message} />;
  else if (message.role === 'image_message') body = <ImageMessage message={message} />;
  else if (message.role === 'custom_block' && message.block_id && message.block_src) {
    body = (
      <SandboxedBlock
        blockId={message.block_id}
        src={message.block_src}
        props={message.block_props || {}}
        height={message.block_height}
        title={message.block_title}
      />
    );
  }
  else if (message.role === 'deep_research') body = <DeepResearchBlock message={message} />;
  else if (message.role === 'deep_analyze') body = <DeepAnalyzeBlock message={message} />;
  else body = message.role === 'user'
    ? <UserTurn content={message.content} />
    : <AssistantMarkdown content={message.content} />;

  const showBlockActions = !!turnEntry?.isLastInTurn;
  const align = message.role === 'user' ? 'right' : 'left';

  return (
    <div className="group">
      {body}
      <MessageActions
        align={align}
        onCopyMessage={() => actions.copyMessage(message)}
        onCopyBlock={showBlockActions && turnEntry ? () => actions.copyTurn(turnEntry.turn) : undefined}
        onDeleteBlock={showBlockActions && turnEntry ? () => actions.deleteTurn(turnEntry.turn) : undefined}
        deleteDisabled={actions.isLoading}
      />
    </div>
  );
});
```

(Make sure `React` is imported as a type if you reference `React.ReactNode` — otherwise switch the type to `ReactNode` from `'react'`.)

- [ ] **Step 2: Commit**

```bash
git add web-ui/src/components/Chat/MessageList.tsx
git commit -m "feat(web-ui): hover toolbar (copy/delete) on chat messages"
```

---

## Task 11: Run the full test suite (single pass at the end)

**Goal:** Per the project memory rule, all tests run once at the end, not per-task.

- [ ] **Step 1: Frontend type-check + tests**

```bash
cd web-ui && pnpm tsc --noEmit && pnpm vitest run
```

Expected: zero TypeScript errors, all vitest cases pass (including the new `turns.test.ts`).

- [ ] **Step 2: Backend tests**

```bash
make test
```

Expected: all of `tests/test_message_actions.py` passes plus the existing suite is unaffected. If a backend test depends on fixtures that don't exist (`pg_session_factory`, `client`, `seeded_session_with_two_turns`), copy the pattern from an existing test file (`tests/test_session_manager.py` or `tests/test_modules_routes.py`) and add them at the top of `tests/test_message_actions.py`, then re-run.

- [ ] **Step 3: End-to-end manual verification (required per CLAUDE.md)**

```bash
export OPENAI_API_KEY=...   # must be set
make run                    # starts the web UI
```

In the browser:
1. Send a user message, wait for a full assistant turn (text + at least one tool call).
2. Hover the assistant text — confirm the toolbar appears with three icons.
3. Click `Copy` on a single message — paste somewhere, confirm plain text content matches.
4. Click `Copy block` on the same turn — paste, confirm whole-turn serialization (assistant text + tool call summary) is present.
5. Click `Delete` → `Confirm` — confirm the entire turn disappears from the UI.
6. Reload the page — confirm the deleted turn is **still gone** (persistence works).
7. Confirm `user` messages have **no edit affordance** anywhere.
8. Open the same session in a second tab; delete in tab A; confirm tab B reconciles via the WS event.

- [ ] **Step 4: Commit any test-only adjustments (no functional changes)**

If steps 1–3 surfaced harmless test fixture tweaks, commit them as a separate change:

```bash
git add tests/
git commit -m "test: harness adjustments for message-actions tests"
```

If no adjustments were needed, skip this step.

---

## Self-review (already applied)

- **Spec coverage:** Turn model (Task 4), UI toolbar (Tasks 9–10), per-role copy serialization (Task 4), delete persistence + WS (Tasks 1–3, 7), no-edit constraint (Task 10 — no edit handler anywhere), streaming-disable on delete (Task 10 via `deleteDisabled={actions.isLoading}`), fallback clipboard (Task 5), empty turn → `[empty turn]` (Task 4 test).
- **Placeholders:** None — every step has runnable code or a concrete inspection command.
- **Type consistency:** `TurnInfo`, `computeTurns`, `serializeMessageForClipboard`, `serializeTurnForClipboard`, `deleteSessionTurn`, `deleteTurn`, `session_messages_replaced` all match across tasks.
