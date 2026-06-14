# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Development Commands

A `Makefile` is provided for common tasks. Run `make help` to see all targets.

```bash
make install      # Create venv and install with dev dependencies
make format       # Format code with Black
make lint         # Lint with Ruff (auto-fix)
make typecheck    # Type-check with mypy
make check        # Run format + lint + typecheck in sequence
make test         # Run all tests
make test-cov     # Run tests with coverage report
make build-ui     # Build the web UI frontend
```

For cases not covered by `make`, the raw commands are:

```bash
# Activate the venv after install
source .venv/bin/activate

# Run specific tests
uv run pytest tests/test_session_manager.py     # Single file
uv run pytest tests/test_foo.py::test_bar       # Single test

# Or via make
make test-file FILE=tests/test_session_manager.py

# MCP server management
atria mcp list
atria mcp add myserver uvx mcp-server-sqlite
atria mcp enable/disable myserver

# CLI shortcuts
atria                    # Interactive TUI
atria -p "prompt"        # Non-interactive single prompt
atria --continue         # Resume most recent session
atria run ui             # Web UI
```

## Testing Requirements

**CRITICAL - THIS IS A MUST:** When the user asks to "test" any feature or change, you MUST:

1. **Always use OPENAI_API_KEY** - Ensure the environment variable is set and use it for all testing
2. **Run proper unit tests** - Write and execute unit tests with `uv run pytest`
3. **Perform real end-to-end simulation** - Test the actual feature in the running CLI with real API calls

Both unit tests AND end-to-end testing with real simulation are REQUIRED. Never skip either step. Unit tests alone are NOT sufficient. Real API calls must be made to verify changes work correctly.

```bash
# MUST have API key set
export OPENAI_API_KEY="your-key-here"

# Run unit tests
make test

# Then run real end-to-end testing
make run
# Execute real commands that exercise the changed code paths
```

## Architecture Overview

The CLI entry point is `atria` (mapped to `atria.cli:main`). The Python package is `atria/`.

```text
Entry Point (cli.py)
       |
UI Layer
  - ui_textual/: Textual-based TUI (chat_app.py, runner.py, ui_callback.py)
  - web/: FastAPI backend + React/Vite frontend (server.py, state.py, websocket.py)
       |
Agent Layer (core/agents/)
  - main_agent.py: Main ReAct agent (full tool access)
  - planning_agent.py: Plan mode (read-only tools)
  - subagents/agents/: ask_user, code_explorer, planner, web_clone, web_generator
       |
Prompt System (core/agents/prompts/)
  - composition.py: PromptComposer — modular section-based prompt assembly
  - templates/system/main/*.md: Individual prompt sections (security-policy, git-workflow, etc.)
  - templates/subagents/: Subagent-specific prompts
  - renderer.py + loader.py: Template rendering with variable substitution
       |
Runtime Services (core/runtime/)
  - config.py: Hierarchical config loading
  - mode_manager.py: Normal/Plan mode control
  - approval/: Operation approval system
       |
Tool Layer (core/context_engineering/tools/)
  - registry.py: Tool discovery & dispatch
  - handlers/: Tool handlers (file, process, web, mcp, thinking, critique, search, todo)
  - implementations/: Bash, file ops, web tools, ask_user, batch, notebook, etc.
       |
Context Engineering (core/context_engineering/)
  - compaction.py: Context compression
  - memory/: Memory systems
  - mcp/: MCP integration
  - symbol_tools/: AST-based code search
       |
Persistence (core/context_engineering/history/)
  - session_manager.py: Conversation persistence (~/.atria/sessions/)
```

## Key Patterns

**ReAct Loop** (`main_agent.py`): Agent reasons -> decides tool calls -> executes -> loops until completion (max 10 iterations).

**Dual-Agent System**: MainAgent has full tool access; PlanningAgent restricted to read-only tools. Switch via `/mode` or Shift+Tab.

**Dependency Injection** (`models/agent_deps.py`): Core services (mode manager, approval manager, undo manager, session manager) injected into agents via AgentDependencies.

**Tool Registry** (`registry.py`): Tools register with schemas; registry dispatches to specialized handlers. MCP tools integrate dynamically.

**Hierarchical Config**: Priority: `.atria/settings.json` (project) > `~/.atria/settings.json` (user) > env vars > defaults.

**Session Storage**: JSON files in `~/.atria/sessions/` with 8-character session IDs. Sessions auto-save on message add. Project-scoped sessions stored under `~/.atria/projects/{encoded-path}/`.

**Modular Prompt Composition**: System prompts are assembled from individual markdown sections in `templates/system/main/`. `PromptComposer` registers sections with priorities and optional conditions, then composes them at runtime based on context.

**Provider Cache**: Model/provider configs are fetched from models.dev API and cached in `~/.atria/cache/providers/*.json` with 24h TTL. No bundled fallback — if cache is empty, a blocking sync runs on first startup.

**Skills System**: Skills are discovered from `.atria/skills/` (project), `~/.atria/skills/` (user global), and `atria/skills/builtin/` (built-in).

**Web UI**: FastAPI backend with WebSocket for real-time updates. Frontend is React/Vite/Zustand in `web-ui/`, built to `atria/web/static/`. Agent runs in ThreadPoolExecutor, uses `asyncio.run_coroutine_threadsafe` for WS broadcasts.

## Agent Tools

### Artifact Management Tools

The agent has access to two tools for managing uploaded files and images:

**Tool: `list_artifact_images(scope)`**
- List artifacts available to the agent
- Parameters:
  - `scope` (string, required): 'conversation' (current chat only), 'project' (project-level artifacts), or 'both' (all artifacts)
- Returns: Array of artifacts with fields:
  - `id` (int): Artifact identifier
  - `filename` (string): Original filename
  - `type` (string): Artifact type (image, code, report, etc.)
  - `size` (int): File size in bytes
  - `scope` (string): 'conversation' or 'project'
  - `created_at` (string): ISO timestamp
- Example:
  ```
  Agent: list_artifact_images(scope='conversation')
  Response: [{id: 1, filename: 'photo.png', type: 'image', size: 102400, scope: 'conversation', created_at: '2026-06-12T...'}]
  ```

**Tool: `read_artifact_image(artifact_id)`**
- Read an artifact file and return base64-encoded content
- Parameters:
  - `artifact_id` (int, required): ID from list_artifact_images()
- Returns: Object with:
  - `id` (int): Artifact ID
  - `filename` (string): Filename
  - `base64_content` (string): Base64-encoded file content
  - `content_type` (string): MIME type (e.g., 'image/png')
  - OR `error` (string): Error message if file cannot be read
- Supported formats: PNG, JPG, JPEG, GIF, WebP, SVG
- Example:
  ```
  Agent: read_artifact_image(artifact_id=1)
  Response: {id: 1, filename: 'photo.png', base64_content: 'iVBORw0KGgo...', content_type: 'image/png'}
  ```

**Usage Pattern:**
1. Agent calls `list_artifact_images(scope='conversation')` to discover available artifacts
2. Agent calls `read_artifact_image(artifact_id)` to retrieve artifact content
3. Agent analyzes content and responds to user

**Scope Behavior:**
- `conversation`: Artifacts uploaded to the current conversation only
- `project`: Artifacts visible to all conversations in the project
- `both`: All artifacts (conversation + project)

## Agent Design

**CRITICAL:** Never hard-code if/else branching logic to handle LLM conversation flows. The LLM must decide the next step at each turn — not static conditionals. Design agent loops so the model reasons and chooses actions dynamically; hard-coded control flow defeats the purpose of an agentic system.

**CRITICAL:** When crafting system prompts, never use table format. Tables are poorly parsed by LLMs and waste tokens. Use plain prose, bullet lists, or structured sections instead.

## Code Style

- Line length: 100 characters (Black + Ruff)
- Type hints required on public APIs (mypy strict mode)
- Google-style docstrings
