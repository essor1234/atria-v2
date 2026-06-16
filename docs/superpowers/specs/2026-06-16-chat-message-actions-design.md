# Chat Message Actions — Copy & Delete

Date: 2026-06-16
Status: Draft for review

## Goal

Add three actions to the chat transcript in the web UI:

- **Copy message** — copy a single rendered item to the clipboard.
- **Copy block** — copy an entire conversational turn (assistant text + its tool calls, thinking, etc.) to the clipboard.
- **Delete block** — drop an entire turn from the session, persisted to the backend.

Explicit non-goal: **no edit affordance** is added for user messages (or assistant messages). User messages remain read-only.

## Definitions

- **Message** — one item in the linear `messages: Message[]` array rendered by `MessageList`. May be `user`, `assistant`, `thinking`, `tool_call`, `search_result`, `data_message`, `image_message`, `custom_block`, `deep_research`, `deep_analyze`, `tool_result`, `system`.
- **Turn (a.k.a. block)** — a contiguous slice of the array bounded by `user` messages. A `user` message is itself a single-item turn. Everything after a `user` message until the next `user` message is one assistant turn.
- **`turnId`** — `turn-<userIndex>`, derived from the absolute index of the user message that opens the turn. Stable for the lifetime of the array; recomputed whenever messages change.

## Architecture

### Turn model

`computeTurns(messages: Message[]): TurnInfo[]` is a pure function that scans the array once and emits:

```ts
interface TurnInfo {
  turnId: string;       // "turn-<userIndex>"
  startIndex: number;   // inclusive
  endIndex: number;     // inclusive
}
```

`MessageList` keeps a `turnByIndex: Map<number, { turnId, isLastInTurn }>` derived from `turnInfos` and passes the per-item lookup through Virtuoso `context`. `MessageItem` reads its own entry.

### Action toolbar

A new `<MessageActions>` component renders a single-row icon toolbar below each item:

- `Copy` (always shown) — tooltip "Copy message"
- `Copy block` (only when `isLastInTurn`) — tooltip "Copy entire turn"
- `Delete` (only when `isLastInTurn`) — tooltip "Delete turn"

Visibility uses Tailwind's `group` / `group-hover` / `focus-within` pattern with `opacity-0 group-hover:opacity-100`. On touch (`md` breakpoint and below) the row stays at low opacity instead of fully hidden.

Alignment: right-aligned under `user` bubbles; left-aligned with `pl-[26px]` for everything else to match `AssistantMarkdown` indent.

Delete confirmation: inline. First click swaps the trash icon for `[Confirm] [Cancel]` mini-buttons for ~4 seconds; second click commits. No modal.

While `useChatStore` reports `isLoading` for the active session, the delete icon is disabled (backend would 409 anyway).

### Clipboard serialization

Plain text only (per product decision). Helpers live in `web-ui/src/lib/turns.ts`:

- `serializeMessageForClipboard(m: Message): string`
- `serializeTurnForClipboard(messages: Message[], turn: TurnInfo): string` — joins serialized items with `\n\n`.

Per-role serialization:

- `user`, `assistant`: `m.content` with markdown punctuation stripped via a small regex pass (`**`, `_`, backticks, headings, list bullets). If the strip pass produces an empty string we fall back to the raw `content`.
- `thinking`: `"[thinking] " + content`
- `tool_call`: `"[tool: <tool_name>] <tool_args_display or JSON(tool_args)>\n→ <tool_summary or tool_result>"` (truncate result to 4 KB).
- `tool_result`: included implicitly via its `tool_call` parent; standalone `tool_result` items are skipped.
- `search_result`: header + `title — url` lines.
- `image_message`: `image_caption` if present else `[image]`.
- `data_message`: `[data: <data_title or data_message_id>]`
- `deep_research`: `[deep research: <dr_topic>]`
- `deep_analyze`: `[deep analyze: <da_job_id>]`
- `custom_block`: `[block: <block_title or block_id>]`
- `system`: skipped.

If the joined output is empty, copy the literal string `[empty turn]` and toast a warning.

Clipboard write: `navigator.clipboard.writeText` first; if `clipboard` is undefined or rejects, fall back to a hidden `<textarea>` + `document.execCommand('copy')`. On total failure, toast "Copy failed — select and copy manually."

A success toast confirms each copy ("Copied message", "Copied turn").

### Delete persistence

#### HTTP

`DELETE /api/sessions/{session_id}/turns/{turn_index}`

- `turn_index` is the absolute index of the user message that opens the turn (matches `turnId` numeric suffix).
- Response: `{ "deleted": number, "messages": Message[] }`.
- Errors:
  - 404 — session not found, or `turn_index` out of range, or `messages[turn_index].role != "user"`.
  - 409 — session is currently streaming (`session.is_loading == True`).

#### Backend wiring

- `atria/web/routes/sessions.py`: new `delete_session_turn` route handler.
- `atria/core/context_engineering/history/session_manager.py`: new `delete_turn(session_id: str, turn_index: int) -> list[Message]` method. Computes the slice by scanning forward from `turn_index` until the next `user` message or end of array, mutates the in-memory session, persists JSON, broadcasts a `session_messages_replaced` WS event with the full new array.

#### Frontend store

- `web-ui/src/api/client.ts`: `deleteSessionTurn(sessionId, turnIndex)` wrapper.
- `web-ui/src/stores/chat.ts`: new action `deleteTurn(sessionId, turnIndex)` that calls the API and replaces `sessionStates[sid].messages` with the response payload on success; toast on failure.
- WS handler for `session_messages_replaced` does the same replacement so other tabs reconcile.

## Files touched

New:
- `web-ui/src/components/Chat/MessageActions.tsx`
- `web-ui/src/lib/turns.ts`
- `web-ui/src/hooks/useMessageActions.ts`

Modified:
- `web-ui/src/components/Chat/MessageList.tsx`
- `web-ui/src/stores/chat.ts`
- `web-ui/src/api/client.ts`
- `atria/web/routes/sessions.py`
- `atria/core/context_engineering/history/session_manager.py`

Tests:
- `tests/test_sessions_routes.py` (extend or create) — delete-turn happy path, 404 cases, 409 while streaming.
- `web-ui/src/lib/turns.test.ts` — vitest unit tests for `computeTurns`, `serializeMessageForClipboard`, `serializeTurnForClipboard` (vitest is already wired in `web-ui/package.json`).

## Edge cases

- **Streaming.** Backend refuses with 409; frontend disables the icon while `isLoading`.
- **Last turn deleted.** Allowed. `MessageList` already falls back to `WelcomeScreen` when `allMessages.length === 0`.
- **Mid-conversation delete.** Allowed; transcript is just edited. No agent rewind. This is the user's call; not our problem to prevent.
- **Concurrent clients.** `session_messages_replaced` broadcast keeps other tabs in sync.
- **Clipboard API unavailable.** Fallback to `execCommand('copy')`; final fallback is a toast.
- **Empty serialized turn.** Copy `[empty turn]` and warn-toast.
- **Nested tool calls** (`parent_tool_call_id`, `depth > 0`). Treated as ordinary turn members; turn-delete drops them with the rest. Per-item copy on a nested tool call copies just that one call.

## Out of scope

- Edit user message (explicitly disallowed).
- Edit assistant message.
- "Regenerate from here" / branching history.
- Multi-select / bulk delete.
- Undo for delete (could come later via a toast undo affordance + soft-delete on the backend; not in this scope).

## Rollout

- No feature flag — small additive surface.
- No session format migration; the JSON shape on disk is unchanged.
- Tests run once at the end of implementation per project convention.
