# Web-UI → Workbench Wireframe: Layout/Structure Alignment

**Date:** 2026-07-01
**Status:** Approved design, pending implementation plan
**Scope:** Structural/layout changes only. Keep the current Figma-inspired design
system (colors, Inter/mono fonts, radii, shadows) unchanged. No visual re-theme,
no Kalam font, no cream/ink palette.

## Goal

Bring the React web-ui's *structure* into alignment with the "AI Workspace
Wireframe" ("Workbench"), reusing the existing components and Figma styling. The
two already share the same overall architecture (TopBar, left sidebar, center
chat/dispatch, right file/editor panel), so this is a targeted set of structural
changes — not a re-architecture and not a re-skin.

## Non-Goals

- No color/font/radius/shadow changes. The existing `tailwind.config.ts` design
  tokens stay as-is.
- No Kalam font, no hand-drawn "paper" aesthetic.
- No native module-dashboard rebuild (see Decision D1 — iframe stays).
- No removal of existing richer features except the sidebar tree flattening
  (Change 5), which preserves multi-project access via a switcher.

## Decisions

- **D1 — Module dashboards stay as iframe.** There is no generic per-module
  metrics API; each module's `dashboard.html` is bespoke and already renders its
  own KPIs/charts/tables via `AtriaDash.json(script)`
  (`atria/web/routes/module_dashboard.py`, `atria/web/dashboard_assets/__bridge.js`).
  A native KPI/chart/table would require a new backend metrics contract per module
  and would duplicate what modules already draw. `ModuleDashboardView.tsx` is left
  unchanged.
- **D2 — Composer pills use click-to-cycle**, not dropdown menus. Reuse the
  existing `toggleMode` / `cycleAutonomy` / `cycleThinkingLevel` setters. Persona
  keeps its existing dropdown. No new menu/popover component.

## Changes

### Change 1 — Right panel: vertical split (Explorer top / Editor bottom)

**File:** `web-ui/src/components/ArtifactViewer/ArtifactViewer.tsx` (desktop layout only).

**Current:** horizontal split — a width-resizable `FileTree`/`ModuleGallery` on the
left, a `TabBar` + `ViewerDispatcher` viewer on the right, sharing one row.

**Target:** vertical stack inside the existing width-resizable right panel:
- **Top zone (~42% height, vertically resizable):** `LeftPaneTabs` ([Files | Modules])
  + `FileTree` or `ModuleGallery` (per `leftMode`).
- **Bottom zone (~58% height):** `TabBar` + viewer area (`ViewerDispatcher` or empty state).
- A **horizontal drag handle** between the two zones. Reuse the same `Resizable`
  primitive already used for panel width; change its handle from `['e']`/`['w']`
  (east/west) to `['s']` (south) on the top zone, and constrain min/max heights.
- The outer west-edge width resize handle for the whole right panel is preserved.

**Reuse:** `LeftPaneTabs`, `FileTree`, `ModuleGallery`, `TabBar`, `ViewerDispatcher`
are used unchanged — only their container arrangement changes.

**Mobile:** the existing full-screen overlay + master/detail toggle behavior is
preserved (no vertical split on mobile).

### Change 2 — Composer control pills (Mode / Approval / Think / Persona)

**Files:** `web-ui/src/components/Chat/InputBox.tsx`; retire
`web-ui/src/components/Chat/StatusBar.tsx` into the new row;
reuse `web-ui/src/components/Chat/PersonaSelector.tsx`.

All four controls already exist and are backend-wired (`web-ui/src/stores/chat.ts`):
- **Mode** — values `normal` | `plan`; setter `toggleMode()` → `/config/mode`.
- **Approval** — values `Manual` | `Semi-Auto` | `Auto`; setter `cycleAutonomy()` → `/config/autonomy`.
- **Think** — values `Off` | `Low` | `Medium` | `High`; setter `cycleThinkingLevel()` → `/config/thinking`.
- **Persona** — `selectedPersona` per session; `setSelectedPersona()`; sent with each message.

**Target:** a single row of four labeled pills directly under the input, each
styled with the existing pill tokens, rendered as `Label: Value ▾`. Mode/Approval/
Think cycle on click (D2). Persona uses its existing dropdown. `StatusBar` is
removed as a standalone element; any status info it surfaced that isn't one of the
four pills (if any) is folded into `QueueBar` or dropped if redundant.

### Change 3 — Editor tab dirty-dots

**Files:** `web-ui/src/stores/viewerTabs.ts`, `web-ui/src/components/ArtifactViewer/TabBar.tsx`,
and editable viewers (Csv/Excel/Monaco).

**Target:** each open tab shows an unsaved-change dot.
- Add a per-tab `dirty: boolean` flag to the `viewerTabs` store, with
  `markDirty(tabId)` / `markClean(tabId)` actions.
- Editable viewers call `markDirty` on edit and `markClean` on save.
- `TabBar` renders the dot when `tab.dirty`; the close button remains.

### Change 4 — Dispatch summary cards

**File:** `web-ui/src/pages/DispatchPage.tsx`; helper in `web-ui/src/stores/solverJobs.ts`.

**Target:** a row of three summary cards above the job list — **Running / Queued /
Done** — computed across all jobs in the store.
- Divide-job task statuses: `pending` (→ Queued), `running` (→ Running),
  `done` | `failed` | `skipped` (→ Done).
- Parallel-job thread statuses: `running` (→ Running), `done` | `dropped` (→ Done);
  parallel jobs have no queued state.
- Add a selector (extending the existing `runningSolverCount` pattern) that returns
  `{ running, queued, done }` aggregated across `Object.values(jobs)`.
- Empty state: cards show zeros (or hide) when no jobs exist, consistent with the
  current empty-state handling.

### Change 5 — Flatten sidebar to Modules + Chats

**File:** `web-ui/src/components/Layout/ProjectSidebar.tsx`
(data from `web-ui/src/stores/projects.ts`, `web-ui/src/stores/chat.ts`).

**Current:** Projects → Conversations tree.

**Target:** two flat sections:
- **Modules** — existing flat module list (unchanged).
- **Chats** — flat list of the **active project's** conversations:
  title = `conv.name`, subtitle = `conv.updated_at` (formatted relative time),
  badge = `conv.message_count`, running pulse via `runningSessions.has(conv.id)`.
  Click → `loadSession(conv.id)`.
- **Project switching preserved:** the header-row **folder icon** becomes a project
  switcher (dropdown listing `projects`); selecting one sets the active project and
  loads its conversations via `loadConversations(projectId)`. Defaults to
  `workspaceProjectId`.
- Hover actions (new conversation, delete) are preserved on chat rows; project
  create/delete moves into the switcher.

### Change 6 — Nav tabs: underline style

**File:** `web-ui/src/components/Layout/TopBar.tsx` (`ViewSwitcher`).

**Target:** replace the segmented-pill [Chat | Dispatch] control with underline-style
tabs (active tab underlined). Markup/class change only; uses current colors. Routes
(`/chat`, `/dispatch`) and the crossfade `AppShell` behavior are unchanged.

## Components NOT changed

- `ModuleDashboardView.tsx` (D1 — iframe stays).
- All message-body components (`ThinkingBlock`, `SearchResultBlock`,
  `DeepResearchBlock`, `ToolCallMessage`, `ImageMessage`, `TodoListCard`, etc.).
- `TenantSwitcher`, cost/context status pills, drag-and-drop upload, @file mention
  search, mobile overlay — all preserved.
- The Figma design tokens in `tailwind.config.ts`.

## Testing

Per project policy (`CLAUDE.md`): run unit tests with `uv run pytest` for any
backend-touching changes (none expected here — all changes are frontend), and do a
real end-to-end check in the running UI.

Frontend verification:
- `make build-ui` builds cleanly.
- Existing Vitest suites pass (`viewerTabs.test.ts`, `solverJobs.test.ts`,
  `chat.activity.test.ts`) plus new tests for: the dispatch counts selector, and
  the `viewerTabs` dirty flag actions.
- Manual e2e in `atria run ui`: right-panel vertical resize works; composer pills
  cycle and persist; editor tab shows/clears dirty dot on edit/save of a CSV;
  dispatch summary cards reflect a live job; sidebar Chats list switches sessions
  and the folder icon switches projects; nav underline tabs navigate.

## Risks / Open Points

- **R1 — Vertical resize + mobile:** ensure the new `['s']` handle is desktop-only
  and does not interfere with the mobile overlay path.
- **R2 — Sidebar flatten UX:** flattening assumes a single active project in view at
  a time. The folder-icon switcher must make the current project obvious to avoid
  "where did my other chats go" confusion.
- **R3 — StatusBar retirement:** confirm nothing else imports/depends on
  `StatusBar` before removing it; migrate any unique info it showed.
