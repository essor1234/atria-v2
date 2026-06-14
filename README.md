# Atria

## Repository Structure

```
opendev-py/
├── atria/                  # Main Python package
│   ├── cli/                # CLI entry points & commands
│   ├── config/             # Config loading & models
│   ├── core/               # Agent core
│   │   ├── agents/         # Main, planning, sub-agents + prompt templates
│   │   ├── context_engineering/   # Tools, MCP, memory, compaction, history
│   │   └── runtime/        # Config, mode manager, approval system
│   ├── models/             # Shared data models / agent deps
│   ├── ui_textual/         # Textual TUI (chat_app, runner, ui_callback)
│   ├── web/                # FastAPI backend + websocket + static UI
│   └── skills/             # Built-in skills
├── web-ui/                 # React/Vite/Zustand frontend (builds into atria/web/static)
├── tests/                  # Pytest suite
├── docs/                   # Provider setup & guides
├── schema.sql              # Postgres schema (loaded by db container on init)
├── Dockerfile              # Atria app image
├── docker-compose.yml      # Prod-ish stack: db + adminer + atria
├── docker-compose.dev.yml  # Dev overrides (live reload, mounted volumes)
├── Makefile                # install / format / lint / typecheck / test / build-ui
├── pyproject.toml          # Package metadata & deps
└── requirements.txt
```

## Run with Docker Compose

Requirements: Docker + Docker Compose v2.

```bash
# 1. Copy env template and set your keys
cp .env.example .env
# edit .env -> set OPENAI_API_KEY (or your provider key)

# 2. Build and start the full stack (postgres + adminer + atria)
docker compose up -d --build

# 3. Tail logs
docker compose logs -f atria
```

Services:

- **atria** — http://localhost:8080 (web UI + API)
- **adminer** — http://localhost:8081 (DB browser, server `db`, user/pass `atria`/`atria`)
- **db** — Postgres 16 on internal network, schema auto-loaded from `schema.sql`

### Dev mode (live reload, source mounted)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

### Common ops

```bash
docker compose ps                 # status
docker compose restart atria      # restart app only
docker compose down               # stop stack (keeps volumes)
docker compose down -v            # stop + wipe postgres volume
```

## File Upload & Artifact Management

Users can upload files and images through the web UI, and the agent can read and analyze them.

### User Features

- **Upload via Web UI**: Click the attachment button in the message input and select files
- **Scope Selection**: Choose whether the artifact is visible to:
  - **Conversation** (current chat only)
  - **Project** (all conversations in the project)
- **File Limits**:
  - Maximum file size: 50MB
  - Supported formats: All (any file type accepted)
  - Image formats for agent analysis: PNG, JPG, JPEG, GIF, WebP, SVG
- **Artifact Management**:
  - View uploaded artifacts in the panel
  - Filter by scope (Conversation/Project/All)
  - Search artifacts by filename
  - Delete artifacts individually

### Agent Capabilities

The agent can list and read uploaded artifacts using dedicated tools:

**Discovery**: `list_artifact_images(scope)` returns all artifacts matching the scope
**Reading**: `read_artifact_image(artifact_id)` retrieves the file content (base64 for images)

### Technical Overview

**Storage**:
- Conversation artifacts: `.artifacts/conversations/{conversation_id}/` (in working directory)
- Project artifacts: `.artifacts/project/` (at project root)
- Files stored with UUID prefix to prevent collisions

**API Endpoints**:
- `POST /api/artifacts/upload` - Upload file (multipart/form-data)
- `DELETE /api/artifacts/{id}` - Delete artifact
- `GET /api/artifacts` - List artifacts (query: conversation_id or project_id)

**Database**:
- Artifacts table tracks scope, local_path, and type
- Hard delete removes both file and database record
- Soft delete marks as deleted (hidden from agent tools)

### Example Workflow

```
User: "Analyze this image"
[User uploads photo.png to conversation scope]

Agent: "I'll analyze the image for you..."
- Calls: list_artifact_images(scope='conversation')
- Response: [{id: 123, filename: 'photo.png', type: 'image', scope: 'conversation', ...}]
- Calls: read_artifact_image(artifact_id=123)
- Response: {id: 123, base64_content: 'iVBORw0KGgo...', content_type: 'image/png'}
- Analyzes image and responds with findings
```

### Implementation Status

- ✅ File upload endpoint (50MB limit, multipart form support)
- ✅ Artifact storage (conversation and project scopes)
- ✅ Agent tools (list and read with scope filtering)
- ✅ Web UI components (upload widget, artifact panel, thumbnails)
- ✅ Database integration (artifact metadata storage)
- ✅ Hard delete (file and DB record removed)
- ✅ Comprehensive testing (58 E2E and integration tests)
