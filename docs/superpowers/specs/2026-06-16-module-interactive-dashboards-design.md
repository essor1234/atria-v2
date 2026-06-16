# Module Interactive Dashboards — Design

Date: 2026-06-16
Status: Approved (brainstorming)

## Goal

Let every module under `modules/<name>/` ship an optional, fully interactive
HTML dashboard that appears as a button in the left sidebar. Clicking the
button replaces the chat view with the dashboard. The dashboard runs real
JavaScript in a sandboxed iframe and can execute the module's own Python
scripts from the browser, getting stdout/stderr back. The CSV/file changes
that those scripts produce flow back to the dashboard live, via the existing
module file watcher.

The work also normalizes asset ownership: all URLs used by a module
(dashboard, blocks, virtual platform helpers, vendor libs) live under
`/api/modules/<name>/...`. The global `/static/blocks/` mount goes away.

## Non-goals (v1)

- Streaming subprocess output. `run()` is buffered.
- Cross-module communication (one dashboard reading another module's data).
- User-installable platform vendor libs at runtime; the v1 vendor list is
  fixed in the host (Chart.js + htmx).
- Full-screen modal view of a single dashboard card (an earlier sketch
  proposed it; the click-to-replace-chat-view model supersedes it).
- Permission gating on `run()` per script. The module folder is the trust
  boundary; the user already trusted the module by placing it under
  `modules/`. Same trust level the agent has when calling the same script
  via the bash tool.

## File layout

A module gains a dashboard purely by convention — adding `dashboard.html`.

```
modules/<name>/
  SKILL.md                 (unchanged)
  dashboard.html           NEW. Optional. Presence → sidebar button.
  icon.svg                 NEW. Optional. Sidebar button icon. Falls back
                           to a generated single-letter avatar.
  blocks/*.html            existing push-block iframes
  scripts/*.py             existing CLI scripts
  vendor/*                 NEW. Optional. Module-supplied client libs.
  data/*                   existing module-owned data
```

Nothing in the module folder duplicates platform code. The host serves
virtual files (bridge, base CSS, platform vendor libs) under the module's
URL namespace.

## URL surface

All URLs the dashboard or block iframe loads sit under a single prefix
per module:

```
GET  /api/modules/<name>/dashboard.html       file on disk, 404 if absent
GET  /api/modules/<name>/icon.svg             file on disk, 404 if absent
GET  /api/modules/<name>/blocks/<file>        file on disk
GET  /api/modules/<name>/vendor/<file>        file on disk under vendor/
GET  /api/modules/<name>/__bridge.js          virtual (AtriaDash + AtriaBlock)
GET  /api/modules/<name>/__base.css           virtual (theme tokens + reset)
GET  /api/modules/<name>/__vendor/<lib>/<file>  virtual platform vendor

POST /api/modules/<name>/run                  spawn a module script
```

Path resolution rules for all `GET` routes:

- Resolve to absolute path; reject anything outside `modules/<name>/`.
- `__bridge.js`, `__base.css`, and `__vendor/*` are reserved virtual names;
  any file physically present at those paths in the module is shadowed and
  unreachable. (The host wins.)

`POST /api/modules/<name>/run`:

```json
{
  "script": "inventory.py",
  "args": ["adjust", "--sku", "SKU-001", "--delta", "-1"],
  "stdin": null,
  "timeout_ms": 30000
}
```

Response (always 200, even on non-zero exit):

```json
{
  "exit_code": 0,
  "stdout": "adjusted: SKU-001 -> quantity=47\n",
  "stderr": "",
  "duration_ms": 84
}
```

Errors that prevent the spawn (path escape, unknown script, rate limit,
spawn failure) return HTTP 4xx with a typed body:

```json
{ "kind": "path-escape" | "unknown-script" | "rate-limited" | "spawn-failed",
  "message": "…" }
```

`script` MUST resolve under `modules/<name>/scripts/`. Absolute paths and
any path containing `..` are rejected with `path-escape`. The subprocess
runs with the same Python interpreter the agent uses, with env:

```
ATRIA_SESSION_ID=<current session>
ATRIA_API_BASE=<server base URL>
ATRIA_MODULE_ROOT=<absolute path to modules/<name>>
```

Concurrency: at most 4 in-flight `run` calls per (session, module). The
5th returns HTTP 429 with `kind: rate-limited`. `timeout_ms` defaults to
30000, max 120000. On timeout the process is killed and the response has
`exit_code: -1` plus a stderr note.

## WebSocket events

The existing per-session WebSocket gains two event types. Both originate
from `atria/core/modules/watcher.py` (in-flight in current branch); we
extend it to broadcast on any file change inside a module dir.

```json
{ "type": "module:changed", "module": "warehouse",
  "paths": ["data/inventory.csv"] }

{ "type": "module:removed", "module": "warehouse" }
```

`module:changed` is debounced server-side over a 150ms window per
(session, module). The frontend re-fans it into the matching iframe.

## Frontend

### Sidebar buttons

"Active module" means a module discovered by `atria/core/modules/registry.py`
under `modules/` — i.e. any module directory present on disk. The set is
session-independent. The watcher keeps it live: a new module folder adds
buttons in real time; removal removes them.

`ProjectSidebar.tsx` adds a new "Modules" group below the project tree.
One button per active module that ships a `dashboard.html`. Each button:

- Icon: `icon.svg` if present; else a generated single-letter avatar from
  the module name.
- Label: module name.
- Active state: same highlight treatment the active conversation uses.
- Badge dot: shown when the module called `AtriaDash.setBadge`. Color
  follows severity (`info | warning | danger`).

Clicking the button:

- Routes to `/m/<name>`.
- Swaps the main `<Outlet>` from `<ChatView>` to
  `<ModuleDashboardView moduleName="…" />`.
- Clicking the same button again, or selecting any chat, routes back to
  the chat view. The module iframe stays mounted in the background.

Collapsed sidebar (`w-12` rail) shrinks each button to a 32×32 icon with
a tooltip. Badge dot remains visible.

### Main area when a dashboard is active

```
┌─────────────────────────────────────────────────┐
│ ← back to Chat 1     warehouse · dashboard   ⟳  │  thin header
├─────────────────────────────────────────────────┤
│                                                 │
│   <iframe sandbox="allow-scripts"               │
│           src="/api/modules/warehouse/          │
│                dashboard.html"></iframe>        │
│                                                 │
└─────────────────────────────────────────────────┘
```

- Header has back-to-chat, module title, refresh icon. No tabs.
- Iframe fills the rest; the dashboard owns its own layout.
- Iframe is keyed by module name and **persists** across visibility
  toggles. The host sends `{type:'visibility', visible}` so the
  dashboard can pause polling/animations when hidden.

### State and routing

`useChatStore` (or a new `useModulesStore`) tracks:

- `activeModuleDashboard: string | null` — currently shown module, or null
  for chat view.
- `badges: Record<string, {count, severity}>` — per-module sidebar badges.
- `modulesWithDashboards: string[]` — populated from a new
  `GET /api/modules?dashboards=1` endpoint, refreshed when watcher
  reports any module add/remove.

URL `/m/<name>` resolves to dashboard view; any chat URL resolves to chat.
The two are toggles, not stacked overlays.

## AtriaDash JS API

Loaded by `<script src="__bridge.js"></script>`. Exposes two globals,
`AtriaDash` (dashboards) and `AtriaBlock` (existing block API, re-homed
here so blocks can drop the global `/static/blocks/` mount).

```js
// Lifecycle
AtriaDash.ready();
AtriaDash.onTheme(fn);
AtriaDash.onContext(({sessionId, moduleName, moduleRoot}) => …);
AtriaDash.onChange((paths) => …);
AtriaDash.onVisibility((visible) => …);

// Actions
AtriaDash.run(script, args, opts?)  // Promise<{exit_code, stdout, stderr, duration_ms}>
AtriaDash.json(script, args, opts?) // throws on non-zero; parses stdout
AtriaDash.setBadge({count, severity} | null);
AtriaDash.setTitle(string);
AtriaDash.toast({message, severity});
AtriaDash.openBlock(blockName, props);  // pushes module's block into chat
AtriaDash.openChat();                   // route back to chat
```

`opts`: `{stdin?: string, timeout_ms?: number}`.

`AtriaDash.run` rejects with a typed error matching the HTTP error body,
plus a `kind: 'non-zero'` case when the subprocess returned non-zero —
that case still resolves with the result object so the dashboard can show
stderr. (`AtriaDash.json` is the throw-on-non-zero variant.)

### Wire protocol (postMessage)

```
host → iframe : {type:'theme',   tokens}
                {type:'context', sessionId, moduleName, moduleRoot}
                {type:'change',  paths}
                {type:'visibility', visible}
                {type:'run:result', requestId, exit_code, stdout, stderr, duration_ms}
                {type:'run:error',  requestId, kind, message}

iframe → host : {type:'ready'}
                {type:'run', requestId, script, args, stdin?, timeout_ms?}
                {type:'badge', value: {count, severity} | null}
                {type:'title', text}
                {type:'toast', message, severity}
                {type:'openBlock', block, props}
                {type:'openChat'}
```

Iframe sandbox attributes (matching today's blocks): `allow-scripts`. No
`allow-same-origin`. CSP served with each module HTML response:

```
default-src 'none';
script-src 'self' 'unsafe-inline';
style-src 'self' 'unsafe-inline';
img-src 'self' data:;
font-src 'self' data:;
connect-src 'self';
```

`'self'` resolves to `/api/modules/<name>/` only — the iframe can fetch
its own dashboard/vendor/bridge but cannot reach other modules' URLs.

## Platform vendor tier

Two pinned libraries ship in v1 under `/api/modules/<name>/__vendor/`:

- `chartjs@4/chart.min.js`
- `htmx@2/htmx.min.js`

Selection criteria: small, no build step, framework-agnostic. Adding
another vendor in the future is a host-side change, no module migration.

Modules that want React/Vue/Svelte bundle their own under
`modules/<name>/vendor/` and load it with a relative URL.

## Backend changes

- `atria/web/routes/modules.py` — new file. Implements the URL surface
  above. Reuses `atria/core/modules/registry.py` for the active-module
  list. Reuses the existing subprocess machinery from
  `atria/core/context_engineering/tools/implementations/bash_tool/tool.py`
  for `run` (same env, same Python interpreter).
- `atria/core/modules/watcher.py` — extend the existing watcher to
  broadcast `module:changed` / `module:removed` per session WebSocket.
- `atria/web/routes/blocks.py` — `push` endpoint stays. Block content
  served from the new module-scoped URL. The standalone
  `/static/blocks/_base.js` and `_base.css` mounts are removed; existing
  block HTML files referencing them are migrated.

## Frontend changes

- `web-ui/src/components/Layout/ProjectSidebar.tsx` — add the Modules
  group with one button per active module. Wire badge state.
- `web-ui/src/components/ModuleDashboard/ModuleDashboardView.tsx` — new.
  Renders the iframe with header bar.
- `web-ui/src/components/ModuleDashboard/useModuleBridge.ts` — new.
  postMessage bridge: forwards WS events into the iframe, handles
  iframe→host messages, owns the run() proxy and badge state.
- `web-ui/src/pages/ChatPage.tsx` — route on `activeModuleDashboard` /
  URL to either `<ChatView>` or `<ModuleDashboardView>`.
- `web-ui/src/stores/modules.ts` — new store, or extend `chat.ts`.

## Migration of existing blocks/

Drop `/static/blocks/_base.js` and `/static/blocks/_base.css`. Every
existing block HTML (currently `modules/warehouse/blocks/item_form.html`
and any other modules' blocks) gets its `<link>` and `<script>` rewritten
to `__base.css` / `__bridge.js`. Same content, new URL prefix scoped to
the module. The `push_block` server-side path that loads block content
from disk is updated to serve via the new module routes.

## Warehouse module concrete use

To complete the loop, the warehouse module is augmented:

- `modules/warehouse/dashboard.html` — KPIs (SKU count, total units, low
  stock), bar list of stock per SKU with quick `+1` / `-1` steppers,
  "+ Add item" button that calls `AtriaDash.openBlock('item_form',
  {mode:'create'})`, "Recent activity" list driven by `inventory.py`
  output. Uses Chart.js from `__vendor/`.
- `modules/warehouse/scripts/inventory.py` — `list` subcommand gains a
  `--json` flag that emits `{items: [...], low_stock: [...]}` on stdout.
  Existing text output retained for tty use.
- `modules/warehouse/icon.svg` — small package icon.
- Existing `blocks/item_form.html` migrated to the new bridge URL.

## Open implementation notes

- Watcher debounce window: 150ms. Tunable per module via env var if a
  module's data file changes too rapidly for the default.
- `run` requests carry the current session ID server-side from cookie
  (no need to pass it in the body). The dashboard never sees other
  sessions' data.
- Iframe sandbox is per-message origin-checked: host verifies the
  `event.source` matches the expected `contentWindow` for each registered
  module iframe. Prevents a malicious page in another tab from spoofing
  iframe→host events.

## Out of scope, parked for later

- Streaming `run()` output via Server-Sent Events.
- Per-script permission prompts for sensitive scripts (we'd add a
  manifest declaring such scripts; deferred until a real need).
- Dashboard-defined sidebar widgets (mini-widget below the button).
- Shared platform vendor versions per module (right now all modules see
  the same `__vendor/chartjs@4/...`).
