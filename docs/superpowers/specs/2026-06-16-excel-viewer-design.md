# Excel Viewer with Live Formulas — Design

Date: 2026-06-16
Status: Draft

## Goal

Replace the existing read-only `ExcelViewer` in the artifact viewer with a
Univer-hosted spreadsheet that:

- Loads any `.xlsx` from the artifact viewer (`conv` or `module` scope).
- Renders multi-sheet workbooks with sheet tabs.
- Lets the user edit values and formulas with live recalculation.
- Debounced auto-saves the workbook back to its original path on disk.
- Broadcasts `artifact.changed` so any open dashboard module refreshes
  (reusing the WebSocket pipe added for the CSV viewer).

The current `ExcelViewer.tsx` parses with SheetJS and renders cached cell
values into the read-only `DataTable`. It supports multi-sheet tabs but
neither editing nor formula recalculation.

## In Scope

- Cell values, formulas (full Univer OSS formula engine), multi-sheet,
  merged cells, basic number formats, column widths / row heights.
- Auto-save on edit (1s debounce) → xlsx written to original path.
- Reuse the `artifact.changed` WS event to notify dashboard iframes.

## Non-Goals (Explicit)

- Charts, images, pivot tables, conditional formatting, data validation
  rules. These will be **dropped on save** when the round-trip goes
  through SheetJS. A one-time confirmation modal warns the user before
  the first edit per file (see Lossy-Roundtrip Mitigation below).
- Multi-user real-time collaboration (Univer Pro feature).
- Sheets > ~50k populated cells get a "may stutter" hint; not blocked.
- Edit history / undo across reloads.

## Library Choice

**Univer OSS** (`@univerjs/preset-sheets-core`, MIT) for the spreadsheet
UI and formula engine. Native xlsx import/export is a Univer Pro feature,
so we **bridge with SheetJS** (`xlsx`, already a dependency): xlsx →
SheetJS workbook → `IWorkbookData` snapshot for load, and the reverse
chain for save.

Considered and rejected:

- **Fortune-sheet** — bundles LuckyExcel for native xlsx round-trip, but
  community-maintained with less momentum; formula coverage weaker than
  Univer.
- **Univer Pro** — first-class xlsx I/O, but commercial license required;
  unlicensed builds carry watermarks and file-size limits.
- **HyperFormula + custom DataTable** — minimal aesthetic, but
  multi-week dev work to build cell selection, formula bar, range refs,
  copy/paste from scratch.

## Architecture

```
                  ┌─────────────────────────────────────┐
   .xlsx on disk  │  FastAPI fs/read  (existing)        │
   ───────────────┤  GET /api/{scope}/fs/read?path=...  │
                  └────────────┬────────────────────────┘
                               │ binary bytes
                               ▼
                  ┌─────────────────────────────────────┐
                  │  ExcelViewer.tsx  (React, lazy)     │
                  │   ├─ SheetJS: XLSX.read(ArrayBuf)   │
                  │   ├─ xlsxBridge: WB → IWorkbookData │
                  │   └─ mount Univer (single instance) │
                  └────────────┬────────────────────────┘
                               │ user edits cell/formula
                               ▼
                  ┌─────────────────────────────────────┐
                  │  Univer formula engine recalcs      │
                  │  → CommandExecuted event fires      │
                  │  → 1s debounce: save()              │
                  │     ├─ univerAPI.getActiveWorkbook  │
                  │     │   .save() → IWorkbookData     │
                  │     ├─ xlsxBridge: snapshot → WB    │
                  │     ├─ SheetJS: XLSX.write(WB)      │
                  │     └─ PUT fs/write-binary          │
                  └────────────┬────────────────────────┘
                               │ bytes
                               ▼
                  ┌─────────────────────────────────────┐
                  │  FastAPI fs/write-binary (NEW)      │
                  │   ├─ safe-path guard                │
                  │   ├─ write to disk                  │
                  │   └─ broadcast artifact.changed     │ ── WS ──▶ dashboard iframe
                  └─────────────────────────────────────┘
```

## Components

### Frontend

- **`web-ui/src/components/ArtifactViewer/viewers/ExcelViewer.tsx`**
  Rewritten. Lazy-loaded as today. Mounts Univer into a container div,
  owns load-status / save-status / first-edit-modal state, wires the
  debounced save. Does **not** mirror cell state in React — Univer owns
  the workbook once mounted.

- **`web-ui/src/components/ArtifactViewer/viewers/excel/setupUniver.ts`**
  Factory: `createUniverInstance(container: HTMLDivElement, snapshot:
  IWorkbookData, readOnly: boolean): UniverHandle`. Wires
  `UniverSheetsCorePreset`, locale, CSS imports. `UniverHandle` exposes
  `{ univerAPI, dispose() }`.

- **`web-ui/src/components/ArtifactViewer/viewers/excel/xlsxBridge.ts`**
  Two pure functions, independently unit-testable:
  - `workbookToSnapshot(wb: XLSX.WorkBook): IWorkbookData`
  - `snapshotToWorkbook(snap: IWorkbookData): XLSX.WorkBook`
  Throws `BridgeError(kind, cellRef?)` on encoding failure.

- **`web-ui/src/api/client.ts`** — new method:
  `writeFsBinary(scope: FsScope, path: string, bytes: Uint8Array):
  Promise<void>` that POSTs raw octet-stream to the new endpoint.

### Backend

- **`atria/web/routes/fs.py`** — new
  `PUT /api/conversations/{id}/fs/write-binary`. Accepts
  `Content-Type: application/octet-stream` body; reuses the safe-path
  guard from `_resolve_safe`; enforces 25 MB cap (parity with read);
  writes to disk; broadcasts
  `{type: 'artifact.changed', scope: 'conv', conversation_id, path}`.

- **`atria/web/routes/modules.py`** — mirrored
  `PUT /api/modules/{name}/fs/write-binary` with the existing
  `store.write_file` helper extended to accept bytes (or a sibling
  `store.write_bytes` if separation is cleaner — implementer's call).
  Broadcasts `{type: 'artifact.changed', scope: 'module', module, path}`.

## Data Flow

### Load (mount)

1. React mounts `ExcelViewer` for `(scope, path)`. Shows "Parsing
   workbook…".
2. `apiClient.readFsBlob(scope, path)` → `ArrayBuffer`.
3. `XLSX.read(buf, { type: 'array', cellFormula: true, cellNF: true,
   cellStyles: true })`.
4. `workbookToSnapshot(wb)` produces `IWorkbookData`:
   - Each `WorkSheet` → one `IWorksheetData` keyed by a sanitized id
     derived from the sheet name.
   - For each non-empty cell: `{ v, f?, s?, t }` (value, optional
     formula, optional style id, cell type). Number formats mapped via
     Univer `numfmt` keys; unsupported formats fall back to `General`.
   - Merged ranges → `mergeData`.
   - Column widths / row heights copied.
5. `createUniverInstance(container, snapshot, readOnly=false)` is called
   the first time the viewer mounts in the page; subsequent mounts for
   different files reuse the module-level singleton and call
   `univerAPI.createWorkbook(snapshot)` to swap content. (Validate
   singleton behavior in spike; fall back to per-mount instance if
   teardown is unreliable.)
6. Univer renders. Formula engine is configured with
   `initialFormulaComputing: WHEN_EMPTY`, meaning Univer trusts the
   cached `v` SheetJS read from the file and only recalculates cells
   whose formula has no cached value. This matches Excel's behavior on
   open and avoids a full-workbook recalc spike on every load. After
   the first user edit, Univer recalculates dependents normally.

### Edit + auto-save

1. Subscribe to `univerAPI.addEvent(univerAPI.Event.CommandExecuted, ...)`
   filtered to mutating command ids. Exact allowlist captured at
   implementation time; expected set includes: `sheet.command.set-range-values`,
   `sheet.command.insert-row`, `sheet.command.remove-row`,
   `sheet.command.insert-col`, `sheet.command.remove-col`,
   `sheet.command.set-formula`, `sheet.command.set-style`,
   `sheet.command.add-merge`, `sheet.command.remove-merge`.
2. On a matching event: set status `pending`, reset 1s debounce timer.
3. Timer fires → status `saving`:
   - `snapshot = univerAPI.getActiveWorkbook().save()`.
   - `wb = snapshotToWorkbook(snapshot)`.
   - `bytes = XLSX.write(wb, { bookType: 'xlsx', type: 'array' })` →
     `Uint8Array`.
   - `ignoreNextChangeRef.current = true`.
   - `apiClient.writeFsBinary(scope, path, bytes)`.
   - On success: status `saved`.
   - On failure: status `error`, surface message in header bar, clear
     `ignoreNextChangeRef`, keep local edits.
4. Backend writes file, broadcasts `artifact.changed` → dashboard iframe
   re-fetches via existing `useModuleBridge` pipe.

## Lossy-Roundtrip Mitigation

SheetJS preserves cells / formulas / basic styles, but charts / images /
pivot tables / data-validation rules / conditional formatting get
dropped on write.

On the **first edit per file per session** (and not already opted-out
via `localStorage`), the viewer enters a `confirming` state:

- Debounced save timer is **paused** until the modal resolves; status
  badge shows `pending — needs confirmation`.
- Edits continue to apply in Univer; further edits do not advance the
  state past `confirming`.

Modal copy:

> Saving will preserve cells, formulas, and basic formatting. Charts,
> images, pivot tables, conditional formatting, and data-validation
> rules in this file will be removed.
>
> [ ] Don't show again for this file
>
> Cancel | Save anyway

If the user clicks **Save anyway**: persist the "don't show again" flag
to `localStorage` keyed by `${scope}:${path}` (if checked), exit
`confirming`, resume the debounce timer, and save normally on the next
tick.

If the user clicks **Cancel**: call `univerAPI.undo()` repeatedly until
the workbook state matches the pre-edit baseline (tracked at first-edit
detection), exit `confirming`, leave status as `idle`. No save fires.

## Edge Cases

- **Date cells.** xlsx stores dates as serial numbers + a format.
  `workbookToSnapshot` preserves the serial + maps the format; Univer
  renders as a date. The reverse keeps the same serial + format.
- **Shared formulas.** SheetJS materializes them per-cell; treated as
  regular formulas. Round-trip is lossy on the shared-formula structure
  but correct on values.
- **Cells with both `f` and cached `v`.** Pass `v` as cached value into
  Univer; Univer overwrites on first recalc. Avoids a "blank then
  filled" flash.
- **Workbook too large** (>5 MB or >50k populated cells). Show a one-time
  header hint: "Large workbook — saving may take a few seconds per
  edit." Hard cap: refuse to load if blob > 25 MB (matches existing
  `fs/read` cap).
- **Parse failure.** Falls back to existing `BinaryFallback` (current
  behavior).
- **Save failure (HTTP / disk).** Status `error`, retain local edits,
  retry on next edit. No silent data loss.
- **Concurrent remote write.** WS `artifact.changed` arrives during/after
  a local edit:
  - If `ignoreNextChangeRef` is set → consume and clear (self-write).
  - Else → toast "This file was changed elsewhere. Reload to see
    latest? (your edits will be discarded)" with a Reload button. No
    auto-merge.
- **Module-scope files.** Same edit affordance; saves go through the new
  `modules/{name}/fs/write-binary` endpoint.

## Error Handling Boundaries

- Bridge functions throw `BridgeError(kind, cellRef?)`. ExcelViewer
  catches and surfaces in the header bar.
- Backend write endpoint returns:
  - `413` if body > 25 MB.
  - `403` if path resolves outside workspace.
  - `400` if path is absolute or names a directory.
  - `500` with `{detail}` on disk error.

## Testing Plan

### Unit (Vitest, frontend)

- `xlsxBridge.test.ts` — round-trip identity for: simple values,
  formulas (`=A1+B1`, `=SUM(A1:A10)`, `=IF(...)`), merged cells,
  multi-sheet, dates, common number formats, empty workbooks.
  Assertion: `snapshotToWorkbook(workbookToSnapshot(wb))` yields a
  workbook whose `sheet_to_json({header:1})` matches the original for
  every sheet.

### Unit (pytest, backend)

- `tests/web/test_fs_write_binary.py` — safe-path guard (absolute path
  → 400, `../` escape → 403), size cap (413), success path writes bytes
  verbatim and broadcasts `artifact.changed`.

### Component (Vitest + React Testing Library)

- Mount `ExcelViewer` with a mocked `apiClient`. Fire a synthetic Univer
  command. Assert `writeFsBinary` is called after debounce. Assert
  status badge transitions `pending → saving → saved`.

### Manual E2E (REQUIRED per CLAUDE.md, with `OPENAI_API_KEY` set)

- Drop a multi-sheet xlsx with formulas into `.artifacts/`. Open via
  artifact viewer. Edit a value. Confirm dependents recalc. Wait 2s.
  Reload page → edits persisted on disk.
- Open a dashboard module that reads the same xlsx. Edit value. Confirm
  dashboard receives `artifact:change` postMessage and re-renders.
- Trigger save failure (e.g., chmod 444 the file) → status `error`,
  edits preserved in UI.

## Open Questions / Future Work

- Style fidelity beyond basic (borders, fonts) — Univer ↔ SheetJS style
  mappings are partial; future work could expand the mapping table.
- Chart / image passthrough — would require a separate "raw assets"
  sidecar or switching to Univer Pro.
- Multi-user concurrent edit (Univer Pro).
- Undo across reloads.

## Touched Files

New:

- `web-ui/src/components/ArtifactViewer/viewers/excel/setupUniver.ts`
- `web-ui/src/components/ArtifactViewer/viewers/excel/xlsxBridge.ts`
- `web-ui/src/components/ArtifactViewer/viewers/excel/xlsxBridge.test.ts`
- `tests/web/test_fs_write_binary.py`

Modified:

- `web-ui/src/components/ArtifactViewer/viewers/ExcelViewer.tsx`
- `web-ui/src/api/client.ts`
- `web-ui/package.json` (Univer presets + CSS)
- `atria/web/routes/fs.py`
- `atria/web/routes/modules.py`
- `atria/core/modules/store.py` (if `write_bytes` helper added)
