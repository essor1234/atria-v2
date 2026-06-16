# Modules Rewrite — File-Based Skills + Scripts

Date: 2026-06-15
Status: Approved (design)

## Goal

Replace the current DB-backed module system (tools, tasks, Flowgram workflow editor, executor) with a minimal file-based system: each module is a folder containing one `SKILL.md` and one `script.py`. Modules live globally under `~/.atria/modules/`, autoload on file change, and are surfaced inside the Artifact Viewer as a new left-pane mode (sibling to the existing file tree).

## Non-Goals

- No workflow/graph editor.
- No per-tool registration. Scripts run via the existing bash tool.
- No per-conversation enable/disable. All modules are always on.
- No project-scoped modules. Global only.
- No multi-script modules. Exactly one `script.py` per module folder.
- No export of existing DB modules. Tables are dropped on first boot.

## Module Shape

```
~/.atria/modules/<name>/
  SKILL.md       # markdown; agent-facing description + usage
  script.py      # python; runnable as `python ~/.atria/modules/<name>/script.py`
```

Extra sibling files are allowed (the script may read them) but only `SKILL.md` and `script.py` are part of the editable surface.

Module `name` matches the folder name; must be a valid path slug (`[a-z0-9_-]+`).

## Backend

New layout under `atria/core/modules/` (same path, full rewrite):

```
atria/core/modules/
  __init__.py
  store.py        # filesystem read/write
  registry.py     # in-memory dict[str, Module]; loaded from store
  watcher.py      # watchdog observer + WS broadcast hook
  prompt.py       # build_skill_block(registry) -> str
```

`Module` dataclass: `name: str`, `skill_md: str`, `script_py: str`, `dir: Path`, `mtime: float`. No tools, tasks, nodes, validation, or templating.

`registry.load_all()` scans `~/.atria/modules/` on server boot. Missing root dir is created. Modules missing `SKILL.md` or `script.py` are skipped with a single warning log line.

`PromptComposer` gets one new section `modules_skills` registered in the cached prefix slot previously used by the old skill block (commit `bf422f0`). The section content is:

```
# Modules

The following modules are installed. Each module is a self-contained skill with
a runnable script. To execute a module, run via the bash tool:
  python ~/.atria/modules/<name>/script.py

<concatenated SKILL.md contents, each preceded by `## <name>`>
```

The composer reads a registry version counter; when the watcher bumps it, the next prompt build picks up the new content. In-flight turns are not mutated.

## HTTP API

New `atria/web/routes/modules.py` (replaces the deleted file):

- `GET /api/modules` → `[{name, skill_md, script_py, mtime}]`
- `GET /api/modules/{name}` → single module
- `POST /api/modules` body `{name, skill_md?, script_py?}` → creates folder with starter templates; returns the new module. `409` if folder exists.
- `PUT /api/modules/{name}` body `{skill_md, script_py}` → atomic write of both files (write-temp + rename), bumps mtime.
- `DELETE /api/modules/{name}` → removes folder.

Starter templates:

- `SKILL.md`: a one-line heading `# <name>` and a `## Usage` stub.
- `script.py`: shebang + `if __name__ == "__main__":` boilerplate.

## Autoload (Watcher)

`watcher.py` uses `watchdog` (add to `requirements.txt` / `pyproject.toml` if not present). On boot, the web server starts a single observer rooted at `~/.atria/modules/`.

Events:
- File created/modified/deleted with name `SKILL.md` or `script.py` → reload that module in the registry (or remove if its folder went away), bump version counter, broadcast WS event `{"type": "modules.changed", "name": "<name>"}`.
- Folder deleted → remove module from registry, broadcast the same event with `name: null`.
- Events for other filenames are ignored.

Debounce: 200ms per module to coalesce editor save bursts.

## Frontend

### Removals

- `web-ui/src/pages/modules/` — delete the entire folder (ModulesListPage, ModuleDetailPage, TaskEditorPage, flowgram/, api.ts, types.ts).
- Route `/modules` — remove from the router.
- "Modules" link in TopBar — remove.

### Artifact Viewer integration

`ArtifactViewer.tsx` left pane currently renders `FileTree`. Wrap it in a small mode switcher (two pill buttons at the top of the left pane): **Files** | **Modules**. Selection persisted in `localStorage` (`artifact-viewer.left-mode`).

New components under `web-ui/src/components/ArtifactViewer/`:

- `LeftPaneTabs.tsx` — the Files/Modules switcher.
- `ModuleList.tsx` — list of installed modules. Each row: name + first non-heading line of SKILL.md as subtitle. `+ New` button at top opens a name prompt, calls `POST /api/modules`, then opens the editor tab.
- `viewers/ModuleEditor.tsx` — new viewer dispatched when an active tab has `kind: 'module'`. Header (name, dirty dot, Save, Delete). Two stacked CodeMirror editors (project already uses CodeMirror): top = `SKILL.md` (markdown mode), bottom = `script.py` (python mode). Vertical split is resizable. Save calls `PUT /api/modules/{name}`.

New store `web-ui/src/stores/modules.ts` — Zustand store holding the module list and current loading state. Subscribes to the `modules.changed` WS event and refetches the list.

Viewer tab kind: extend `viewerTabs` store to support `kind: 'module'` with `name` as the identifier (no `path`/`ext`).

### WebSocket

Add `modules.changed` to the WS event union on the client; on receipt, the modules store calls its `refresh()`.

## Migration / Data Loss

A one-shot startup migration in the existing migration runner drops the legacy tables:

```sql
DROP TABLE IF EXISTS module_tasks;
DROP TABLE IF EXISTS module_tools;
DROP TABLE IF EXISTS modules;
```

No export. Existing module rows are discarded.

`~/.atria/modules/` is created if missing on first boot. Empty is a valid state.

## Testing

Unit:
- `store` — round-trip create/read/update/delete on a temp dir.
- `registry` — load skips malformed modules, version counter bumps on reload.
- `prompt.build_skill_block` — output shape, ordering by name, empty registry returns empty string.
- `watcher` — debounced event triggers exactly one reload (use a temp dir + manual file ops).

Route tests against the FastAPI test client for all five endpoints, including the `409` conflict.

End-to-end (per CLAUDE.md requirement):
- Boot the web UI with `OPENAI_API_KEY` set.
- Create a module via the editor that writes a file to `/tmp`.
- Send a chat message asking the agent to use that module; verify it runs `python ~/.atria/modules/<name>/script.py` via the bash tool and reports the result.
- Edit the SKILL.md externally (e.g. `echo` over the file) and confirm the WS event arrives and the next agent turn sees the new content.

## Open Questions

None at design approval. Implementation plan to follow via `writing-plans`.
