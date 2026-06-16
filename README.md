# Atria

## Repo Layout

```
opendev-py/
├── atria/                  # Main py pkg
│   ├── cli/                # CLI entry + cmds
│   ├── config/             # Cfg load + models
│   ├── core/               # Agent core
│   │   ├── agents/         # Main, planning, sub-agents + prompt tmpls
│   │   ├── context_engineering/   # Tools, MCP, mem, compaction, history
│   │   └── runtime/        # Cfg, mode mgr, approval
│   ├── models/             # Shared data models / agent deps
│   ├── ui_textual/         # Textual TUI
│   ├── web/                # FastAPI + WS + static UI
│   └── skills/             # Built-in skills
├── modules/                # Domain modules (SKILL.md + manifest.json + dashboard.html + blocks/ + data/ + scripts/)
│   └── warehouse/          # Example: inventory mgmt module
├── web-ui/                 # React/Vite/Zustand → builds atria/web/static
├── tests/                  # Pytest
├── docs/                   # Provider setup + guides
├── schema.sql              # Postgres schema (auto-load on init)
├── Dockerfile
├── docker-compose.yml      # Prod: db + adminer + atria
├── docker-compose.dev.yml  # Dev override (live reload + mounted vols)
├── Makefile                # install / format / lint / typecheck / test / build-ui
├── pyproject.toml
└── requirements.txt
```

## Docker Compose Run

Req: Docker + Compose v2.

```bash
# 1. Env
cp .env.example .env
# edit → set OPENAI_API_KEY

# 2. Up
docker compose up -d --build

# 3. Logs
docker compose logs -f atria
```

Svcs:

- **atria** — http://localhost:8080 (UI + API)
- **adminer** — http://localhost:8081 (DB browser, server `db`, u/p `atria`/`atria`)
- **db** — Postgres 16 internal, schema `schema.sql`

### Dev (live reload, src mounted)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

### Common ops

```bash
docker compose ps              # status
docker compose restart atria   # app only
docker compose down            # stop (keep vols)
docker compose down -v         # stop + wipe pg vol
```

## Modules

Module = self-contained domain skill. Lives in `modules/<name>/`. Agent picks up at start.

### Layout

```
modules/<name>/
├── manifest.json     # Required. Display + dashboard cfg
├── SKILL.md          # Required. Agent prompt: when/how to use, data model, ops
├── icon.svg          # Optional. Tile icon
├── dashboard.html    # Optional. Iframe-embedded UI (sandbox=allow-scripts allow-forms)
├── blocks/           # Optional. HTML snippets pushed into chat via SandboxedBlock
│   └── *.html
├── data/             # Optional. CSV/JSON state + *.template.* seeds
└── scripts/          # Optional. Py CLIs agent invokes via bash (chmod +x)
```

### `manifest.json`

```json
{
  "display_name": "Warehouse",
  "tooltip": "Inventory, SKUs, low-stock signals",
  "icon": "icon.svg",
  "dashboard": {
    "title": "Warehouse · Inventory",
    "default_height": 760,
    "badge_color": "warning"
  }
}
```

Fields: `display_name`, `tooltip`, `icon` (relative path), `dashboard.{title, default_height, badge_color}`.

### `SKILL.md`

Markdown prompt the agent reads. Sections:

- `# <name>` + 1-line purpose
- `## When to use` — trigger phrases
- `## Data model` — schemas, file paths (use `<modules>` placeholder for absolute root)
- `## How to use` — exact commands the agent should run (`python <modules>/<name>/scripts/foo.py …`)
- `## Constraints` — what NOT to do (e.g. "never mutate CSV by hand, always via script")

Keep <200 lines. Plain prose + bullets — no tables (LLMs parse tables poorly).

### Scripts

Py CLIs in `scripts/` invoked by agent via bash. Conventions:

- Shebang `#!/usr/bin/env python` + `chmod +x`
- Resolve repo paths from `__file__` (not CWD — chat CWD ≠ module root)
- Print JSON to stdout on success → agent parses
- Exit non-zero + stderr msg on error

### Blocks + dashboard

`blocks/*.html` = sandboxed iframe snippets pushed into chat via `SandboxedBlock` (`postMessage` back to parent for callbacks).

`dashboard.html` = full-page module UI loaded in `ModuleDashboardView` iframe. Both run with `sandbox="allow-scripts allow-forms"`.

### Create new module

```bash
mkdir -p modules/myorders/{blocks,data,scripts}
cd modules/myorders
# Write manifest.json (see above)
# Write SKILL.md (purpose + when-to-use + data model + how-to-use)
# Drop icon.svg
# Add scripts/myorders.py (CRUD CLI)
# Optional: blocks/order_form.html, dashboard.html
chmod +x scripts/*.py
```

Restart atria → new tile appears in UI, agent loads SKILL.md.

Reference impl: `modules/warehouse/` (CSV-backed inventory).

## File Upload + Artifacts

User upload files/imgs via UI → agent read + analyze.

### User

- **Upload**: attachment btn in input → pick files
- **Scope**:
  - **Conversation** (curr chat only)
  - **Project** (all chats in project)
- **Limits**:
  - Max 50MB
  - Any type
  - Img formats agent reads: PNG, JPG, JPEG, GIF, WebP, SVG
- **Mgmt**: view in panel, filter by scope, search by filename, delete

### Agent

`list_artifact_images(scope)` → discover
`read_artifact_image(artifact_id)` → fetch (base64 for imgs)

### Tech

**Storage**:
- Conv: `.artifacts/conversations/{conversation_id}/` (cwd)
- Project: `.artifacts/project/` (project root)
- UUID prefix → no collision

**API**:
- `POST /api/artifacts/upload` (multipart)
- `DELETE /api/artifacts/{id}`
- `GET /api/artifacts` (q: conversation_id | project_id)

**DB**:
- Artifacts tbl: scope, local_path, type
- Hard delete = file + row gone
- Soft delete = hidden from agent tools

### Flow

```
User: "Analyze this image"
[uploads photo.png → conversation scope]

Agent:
- list_artifact_images(scope='conversation')
  → [{id: 123, filename: 'photo.png', type: 'image', ...}]
- read_artifact_image(artifact_id=123)
  → {id: 123, base64_content: 'iVBORw0KGgo...', content_type: 'image/png'}
- Analyze → respond
```

### Status

- ✅ Upload endpoint (50MB, multipart)
- ✅ Storage (conv + project)
- ✅ Agent tools (list + read, scope filter)
- ✅ UI (upload widget, panel, thumbs)
- ✅ DB integration
- ✅ Hard delete
- ✅ 58 E2E + integration tests
