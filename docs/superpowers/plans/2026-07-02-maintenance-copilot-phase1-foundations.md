# Maintenance Copilot — Phase 1: Foundations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the `maintenance_copilot` module skeleton, its module-local per-feature model-provider config + thin client, the four local docker-compose sidecars (TEI, Qdrant, Neo4j, local LLM), and a `health` command that verifies all four are reachable.

**Architecture:** A self-contained Python CLI (`modules/maintenance_copilot/scripts/copilot.py`) resolves every model call through a module-local config that maps four roles (`chunk_embed`, `index_embed`, `synthesis`, `kg_extract`) to OpenAI-compatible endpoints. Phase 1 delivers the config layer, a thin `RoleClient` over the `openai` SDK, and a `health` subcommand — no ingestion or retrieval yet.

**Tech Stack:** Python 3, `openai` SDK (OpenAI-compatible for both TEI embeddings and vLLM chat), `qdrant-client`, `neo4j` Python driver; docker-compose services `tei` / `qdrant` / `neo4j` / `copilot-llm`.

**Spec:** `docs/superpowers/specs/2026-07-02-maintenance-copilot-design.md`

## Global Constraints

- Line length: 100 characters (Black + Ruff).
- Type hints on public functions; Google-style docstrings.
- Tests run with `uv run pytest`. Module tests live at `tests/test_maintenance_copilot_*.py` and load the CLI via `importlib` (mirror `tests/test_rag_module.py`).
- Model configuration is **module-local only** — no coupling to Atria's provider system.
- All models run locally; OEM content must never be sent to a third party. The synthesis/extraction roles may fall back to an external `base_url` only via config, for no-GPU machines.
- Commits must NOT include a `Co-Authored-By: Claude` trailer (project rule).
- Module scripts resolve paths relative to the module dir: `ROOT = Path(__file__).resolve().parent.parent`; writable state lives under `ROOT/data` (gitignored).
- Branch: work on `design/maintenance-copilot` (already checked out).

---

### Task 1: Module scaffold, requirements, and role config

**Files:**
- Create: `modules/maintenance_copilot/scripts/config.py`
- Create: `modules/maintenance_copilot/requirements.txt`
- Create: `modules/maintenance_copilot/.gitignore`
- Test: `tests/test_maintenance_copilot_config.py`

**Interfaces:**
- Produces:
  - `ROLES: tuple[str, ...]` = `("chunk_embed", "index_embed", "synthesis", "kg_extract")`
  - `@dataclass(frozen=True) RoleConfig` with fields `provider: str`, `model: str`, `base_url: str`, `api_key: str`
  - `load_config(env: Mapping[str, str] | None = None) -> dict[str, RoleConfig]` — reads `MC_<ROLE>_MODEL`, `MC_<ROLE>_BASE_URL`, `MC_<ROLE>_API_KEY`, `MC_<ROLE>_PROVIDER` (role upper-cased), each falling back to a built-in default. `env` defaults to `os.environ`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_maintenance_copilot_config.py
"""Tests for the maintenance_copilot module-local model-provider config."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent
    / "modules" / "maintenance_copilot" / "scripts" / "config.py"
)


def _load_config_module():
    spec = importlib.util.spec_from_file_location("mc_config_under_test", _CONFIG_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_default_config_has_all_four_roles():
    mod = _load_config_module()
    cfg = mod.load_config(env={})
    assert set(cfg) == set(mod.ROLES)
    assert set(mod.ROLES) == {"chunk_embed", "index_embed", "synthesis", "kg_extract"}


def test_defaults_point_at_local_services():
    mod = _load_config_module()
    cfg = mod.load_config(env={})
    # Embeddings default to local TEI; synthesis defaults to local vLLM.
    assert "tei" in cfg["index_embed"].base_url or "8082" in cfg["index_embed"].base_url
    assert cfg["synthesis"].base_url.endswith("/v1")


def test_env_overrides_win_per_role():
    mod = _load_config_module()
    env = {
        "MC_SYNTHESIS_BASE_URL": "https://proxy.example/v1",
        "MC_SYNTHESIS_MODEL": "some-hosted-model",
    }
    cfg = mod.load_config(env=env)
    assert cfg["synthesis"].base_url == "https://proxy.example/v1"
    assert cfg["synthesis"].model == "some-hosted-model"
    # Untouched role keeps its default.
    assert cfg["index_embed"].base_url != "https://proxy.example/v1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_maintenance_copilot_config.py -v`
Expected: FAIL — `FileNotFoundError` / `spec is None` (config.py does not exist yet).

- [ ] **Step 3: Write the config module**

```python
# modules/maintenance_copilot/scripts/config.py
"""Module-local model-provider config for the maintenance_copilot module.

Maps four feature *roles* to OpenAI-compatible endpoints. Everything is read
from ``MC_<ROLE>_<FIELD>`` environment variables with local-service defaults,
so the module runs against the docker-compose sidecars with no configuration.
This layer is deliberately self-contained: it does not touch Atria's global
provider system.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Mapping, Optional

ROLES = ("chunk_embed", "index_embed", "synthesis", "kg_extract")


@dataclass(frozen=True)
class RoleConfig:
    """Endpoint + model for one feature role."""

    provider: str
    model: str
    base_url: str
    api_key: str


# Built-in defaults. Embedding roles point at local TEI; chat roles at local
# vLLM. Hosts use compose service DNS names when set via env; the literals here
# are the host-side fallbacks. TEI/vLLM ignore the api_key, so a sentinel is ok.
_DEFAULTS: Dict[str, RoleConfig] = {
    "chunk_embed": RoleConfig("tei", "Qwen/Qwen3-Embedding-0.6B",
                              "http://localhost:8082/v1", "sk-local"),
    "index_embed": RoleConfig("tei", "Qwen/Qwen3-Embedding-0.6B",
                              "http://localhost:8082/v1", "sk-local"),
    "synthesis": RoleConfig("vllm", "Qwen/Qwen2.5-1.5B-Instruct",
                            "http://localhost:8000/v1", "sk-local"),
    "kg_extract": RoleConfig("vllm", "Qwen/Qwen2.5-1.5B-Instruct",
                             "http://localhost:8000/v1", "sk-local"),
}


def load_config(env: Optional[Mapping[str, str]] = None) -> Dict[str, RoleConfig]:
    """Return the resolved config for all roles, applying env overrides.

    For each role, ``MC_<ROLE>_PROVIDER|MODEL|BASE_URL|API_KEY`` (role upper-
    cased) overrides the corresponding default field.
    """
    src = os.environ if env is None else env
    resolved: Dict[str, RoleConfig] = {}
    for role in ROLES:
        d = _DEFAULTS[role]
        prefix = f"MC_{role.upper()}_"
        resolved[role] = RoleConfig(
            provider=src.get(f"{prefix}PROVIDER", d.provider),
            model=src.get(f"{prefix}MODEL", d.model),
            base_url=src.get(f"{prefix}BASE_URL", d.base_url),
            api_key=src.get(f"{prefix}API_KEY", d.api_key),
        )
    return resolved
```

- [ ] **Step 4: Create requirements.txt and .gitignore**

```text
# modules/maintenance_copilot/requirements.txt
openai>=1.40
qdrant-client>=1.11
neo4j>=5.24
```

```text
# modules/maintenance_copilot/.gitignore
data/
.deps.sha256
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_maintenance_copilot_config.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add modules/maintenance_copilot/scripts/config.py \
        modules/maintenance_copilot/requirements.txt \
        modules/maintenance_copilot/.gitignore \
        tests/test_maintenance_copilot_config.py
git commit -m "feat(maintenance_copilot): module-local per-role model config"
```

---

### Task 2: Thin OpenAI-compatible RoleClient

**Files:**
- Create: `modules/maintenance_copilot/scripts/client.py`
- Test: `tests/test_maintenance_copilot_client.py`

**Interfaces:**
- Consumes: `config.load_config`, `config.RoleConfig` from Task 1.
- Produces:
  - `class RoleClient` constructed as `RoleClient(config: dict[str, RoleConfig], client_factory=None)`. `client_factory(base_url, api_key) -> openai.OpenAI` defaults to constructing a real `openai.OpenAI`; tests inject a fake.
  - `RoleClient.embed(role: str, texts: list[str]) -> list[list[float]]`
  - `RoleClient.chat(role: str, messages: list[dict], **kw) -> str`
  - Both raise `ValueError` for an unknown role.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_maintenance_copilot_client.py
"""Tests for the maintenance_copilot RoleClient (endpoint dispatch by role)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_BASE = Path(__file__).resolve().parent.parent / "modules" / "maintenance_copilot" / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"mc_{name}_uut", _BASE / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeEmbeddings:
    def create(self, model, input):
        # Echo one vector per input so we can assert dispatch + shape.
        return type("R", (), {"data": [type("E", (), {"embedding": [0.1, 0.2]})()
                                        for _ in input]})()


class _FakeChat:
    class completions:
        @staticmethod
        def create(model, messages, **kw):
            return type("R", (), {"choices": [type("C", (), {
                "message": type("M", (), {"content": f"reply from {model}"})()})()]})()


class _FakeOpenAI:
    def __init__(self, base_url, api_key):
        self.base_url = base_url
        self.api_key = api_key
        self.embeddings = _FakeEmbeddings()
        self.chat = _FakeChat()


def test_embed_returns_one_vector_per_text():
    config = _load("config")
    client_mod = _load("client")
    rc = client_mod.RoleClient(
        config.load_config(env={}),
        client_factory=lambda base_url, api_key: _FakeOpenAI(base_url, api_key),
    )
    vecs = rc.embed("index_embed", ["a", "b", "c"])
    assert len(vecs) == 3 and vecs[0] == [0.1, 0.2]


def test_chat_uses_the_roles_model():
    config = _load("config")
    client_mod = _load("client")
    rc = client_mod.RoleClient(
        config.load_config(env={"MC_SYNTHESIS_MODEL": "role-model-x"}),
        client_factory=lambda base_url, api_key: _FakeOpenAI(base_url, api_key),
    )
    out = rc.chat("synthesis", [{"role": "user", "content": "hi"}])
    assert out == "reply from role-model-x"


def test_unknown_role_raises():
    config = _load("config")
    client_mod = _load("client")
    rc = client_mod.RoleClient(config.load_config(env={}),
                               client_factory=lambda base_url, api_key: _FakeOpenAI(base_url, api_key))
    with pytest.raises(ValueError):
        rc.embed("nope", ["x"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_maintenance_copilot_client.py -v`
Expected: FAIL — `client.py` does not exist.

- [ ] **Step 3: Write the client**

```python
# modules/maintenance_copilot/scripts/client.py
"""Thin OpenAI-compatible client that dispatches calls by feature role.

One underlying ``openai.OpenAI`` is created per distinct (base_url, api_key)
so TEI and vLLM endpoints are reused across roles that share them.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

try:  # Import lazily so unit tests can inject a fake factory without openai.
    from openai import OpenAI as _OpenAI
except Exception:  # pragma: no cover - openai installed in real env
    _OpenAI = None  # type: ignore[assignment]

from config import RoleConfig  # type: ignore[import-not-found]

ClientFactory = Callable[[str, str], object]


def _default_factory(base_url: str, api_key: str) -> object:
    if _OpenAI is None:  # pragma: no cover
        raise RuntimeError("openai package is not installed")
    return _OpenAI(base_url=base_url, api_key=api_key)


class RoleClient:
    """Resolve embed/chat calls to the endpoint configured for a role."""

    def __init__(
        self,
        config: Dict[str, RoleConfig],
        client_factory: Optional[ClientFactory] = None,
    ) -> None:
        self._config = config
        self._factory = client_factory or _default_factory
        self._clients: Dict[tuple[str, str], object] = {}

    def _role(self, role: str) -> RoleConfig:
        if role not in self._config:
            raise ValueError(f"unknown role: {role!r}")
        return self._config[role]

    def _client_for(self, rc: RoleConfig) -> object:
        key = (rc.base_url, rc.api_key)
        if key not in self._clients:
            self._clients[key] = self._factory(rc.base_url, rc.api_key)
        return self._clients[key]

    def embed(self, role: str, texts: List[str]) -> List[List[float]]:
        rc = self._role(role)
        client = self._client_for(rc)
        resp = client.embeddings.create(model=rc.model, input=texts)  # type: ignore[attr-defined]
        return [item.embedding for item in resp.data]

    def chat(self, role: str, messages: List[dict], **kw) -> str:
        rc = self._role(role)
        client = self._client_for(rc)
        resp = client.chat.completions.create(  # type: ignore[attr-defined]
            model=rc.model, messages=messages, **kw
        )
        return resp.choices[0].message.content
```

Note: the module's `scripts/` dir must be importable by sibling name (`import config`). The test loads each module by file path, so `from config import RoleConfig` resolves at runtime only when `scripts/` is on `sys.path`. To make that robust in both the test and the CLI, add this guard at the top of `client.py` **before** the `from config import` line:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_maintenance_copilot_client.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add modules/maintenance_copilot/scripts/client.py \
        tests/test_maintenance_copilot_client.py
git commit -m "feat(maintenance_copilot): role-dispatching OpenAI-compatible client"
```

---

### Task 3: CLI skeleton with `health` command

**Files:**
- Create: `modules/maintenance_copilot/scripts/copilot.py`
- Test: `tests/test_maintenance_copilot_cli.py`

**Interfaces:**
- Consumes: `config.load_config`, `client.RoleClient` from Tasks 1–2.
- Produces:
  - `build_parser() -> argparse.ArgumentParser` with subcommand `health`.
  - `check_health(probes: dict[str, Callable[[], None]]) -> dict[str, str]` — runs each probe, returns `{name: "ok"}` or `{name: "error: <msg>"}`. Pure/injectable so it is unit-testable without live services.
  - `main(argv: list[str] | None = None) -> int` — `health` prints the health dict as JSON and returns `0` iff every probe is "ok", else `1`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_maintenance_copilot_cli.py
"""Tests for the maintenance_copilot CLI (health command)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_CLI = (
    Path(__file__).resolve().parent.parent
    / "modules" / "maintenance_copilot" / "scripts" / "copilot.py"
)


def _load_cli():
    spec = importlib.util.spec_from_file_location("mc_cli_uut", _CLI)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_check_health_reports_ok_and_errors():
    mod = _load_cli()

    def good():
        return None

    def bad():
        raise RuntimeError("boom")

    result = mod.check_health({"tei": good, "qdrant": bad})
    assert result["tei"] == "ok"
    assert result["qdrant"].startswith("error:")
    assert "boom" in result["qdrant"]


def test_main_health_exit_code_and_json(monkeypatch, capsys):
    mod = _load_cli()
    # Force all probes to succeed by patching the probe builder.
    monkeypatch.setattr(mod, "_build_probes", lambda: {"tei": lambda: None,
                                                       "qdrant": lambda: None,
                                                       "neo4j": lambda: None,
                                                       "llm": lambda: None})
    rc = mod.main(["health"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert all(v == "ok" for v in payload.values())


def test_main_health_fails_when_a_probe_errors(monkeypatch, capsys):
    mod = _load_cli()
    monkeypatch.setattr(mod, "_build_probes", lambda: {"tei": lambda: None,
                                                       "qdrant": (lambda: (_ for _ in ()).throw(RuntimeError("x")))})
    rc = mod.main(["health"])
    assert rc == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_maintenance_copilot_cli.py -v`
Expected: FAIL — `copilot.py` does not exist.

- [ ] **Step 3: Write the CLI**

```python
#!/usr/bin/env python
"""maintenance_copilot CLI.

Phase 1 ships the ``health`` subcommand: it verifies the four local sidecars
(TEI embeddings, Qdrant, Neo4j, local LLM) are reachable. Later phases add
``ingest``, ``index``, ``graph``, ``query``, ``validate``, and ``check``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import RoleConfig, load_config  # type: ignore[import-not-found]
from client import RoleClient  # type: ignore[import-not-found]


def check_health(probes: Dict[str, Callable[[], None]]) -> Dict[str, str]:
    """Run each probe; map name -> 'ok' or 'error: <message>'."""
    out: Dict[str, str] = {}
    for name, probe in probes.items():
        try:
            probe()
            out[name] = "ok"
        except Exception as exc:  # noqa: BLE001 - health must never raise
            out[name] = f"error: {exc}"
    return out


def _build_probes() -> Dict[str, Callable[[], None]]:
    """Build live probes against the configured sidecars."""
    cfg: Dict[str, RoleConfig] = load_config()
    rc = RoleClient(cfg)

    def tei_probe() -> None:
        rc.embed("index_embed", ["ping"])

    def llm_probe() -> None:
        rc.chat("synthesis", [{"role": "user", "content": "ping"}], max_tokens=1)

    def qdrant_probe() -> None:
        from qdrant_client import QdrantClient  # local import: optional dep

        url = _service_url("MC_QDRANT_URL", "http://localhost:6333")
        QdrantClient(url=url).get_collections()

    def neo4j_probe() -> None:
        from neo4j import GraphDatabase  # local import: optional dep

        uri = _service_url("MC_NEO4J_URI", "bolt://localhost:7687")
        user = _env("MC_NEO4J_USER", "neo4j")
        pwd = _env("MC_NEO4J_PASSWORD", "atria-neo4j")
        driver = GraphDatabase.driver(uri, auth=(user, pwd))
        try:
            driver.verify_connectivity()
        finally:
            driver.close()

    return {"tei": tei_probe, "llm": llm_probe,
            "qdrant": qdrant_probe, "neo4j": neo4j_probe}


def _env(key: str, default: str) -> str:
    import os

    return os.environ.get(key, default)


def _service_url(key: str, default: str) -> str:
    return _env(key, default)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="copilot", description="Maintenance Copilot CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health", help="Check that all four sidecar services are reachable.")
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "health":
        result = check_health(_build_probes())
        print(json.dumps(result, indent=2))
        return 0 if all(v == "ok" for v in result.values()) else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_maintenance_copilot_cli.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add modules/maintenance_copilot/scripts/copilot.py \
        tests/test_maintenance_copilot_cli.py
git commit -m "feat(maintenance_copilot): CLI skeleton with health command"
```

---

### Task 4: docker-compose sidecars + env wiring

**Files:**
- Modify: `docker-compose.dev.yml` (add `tei`, `qdrant`, `neo4j`, `copilot-llm` services + volumes; add `MC_*` env to `atria` and `atria-worker`)
- Modify: `docker-compose.yml` (same service additions)
- Modify: `.env` (add `MC_*` defaults pointing at compose service DNS names)
- Modify: `.env.example` (document the same keys)

**Interfaces:**
- Consumes: the `MC_*` env keys read by `config.load_config` (Task 1) and `_build_probes` (Task 3).
- Produces: a running compose stack where `copilot.py health` returns all-ok from inside the `atria` container.

- [ ] **Step 1: Add the four services + volumes to `docker-compose.dev.yml`**

Add these services under the top-level `services:` map (sibling of `db`, `redis`):

```yaml
  tei:
    image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.9
    command: ["--model-id", "Qwen/Qwen3-Embedding-0.6B"]
    ports:
      - "8082:80"
    volumes:
      - tei_data:/data
    restart: unless-stopped

  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage
    restart: unless-stopped

  neo4j:
    image: neo4j:5
    environment:
      - NEO4J_AUTH=neo4j/atria-neo4j
    ports:
      - "7474:7474"
      - "7687:7687"
    volumes:
      - neo4j_data:/data
    restart: unless-stopped

  # GPU-dependent. On a no-GPU host, do NOT start this service; instead point
  # MC_SYNTHESIS_BASE_URL / MC_KG_EXTRACT_BASE_URL at an external endpoint.
  copilot-llm:
    image: vllm/vllm-openai:latest
    command: ["--model", "Qwen/Qwen2.5-1.5B-Instruct", "--port", "8000"]
    ports:
      - "8000:8000"
    volumes:
      - hf_cache:/root/.cache/huggingface
    restart: unless-stopped
    profiles: ["gpu"]
```

Add to the bottom-level `volumes:` map (currently `atria_data`, `postgres_data`):

```yaml
  tei_data:
  qdrant_data:
  neo4j_data:
  hf_cache:
```

- [ ] **Step 2: Wire `MC_*` env into the `atria` and `atria-worker` services**

In `docker-compose.dev.yml`, in BOTH the `atria` and `atria-worker` `environment:` lists, add (right after the existing `ATRIA_DISABLED_MODULES` line added earlier):

```yaml
      - MC_INDEX_EMBED_BASE_URL=http://tei:80/v1
      - MC_CHUNK_EMBED_BASE_URL=http://tei:80/v1
      - MC_SYNTHESIS_BASE_URL=${MC_SYNTHESIS_BASE_URL:-http://copilot-llm:8000/v1}
      - MC_KG_EXTRACT_BASE_URL=${MC_KG_EXTRACT_BASE_URL:-http://copilot-llm:8000/v1}
      - MC_QDRANT_URL=http://qdrant:6333
      - MC_NEO4J_URI=bolt://neo4j:7687
      - MC_NEO4J_USER=neo4j
      - MC_NEO4J_PASSWORD=atria-neo4j
```

(The `${...:-default}` form lets a no-GPU host override the LLM endpoint via `.env` without editing compose.)

- [ ] **Step 3: Apply the same service + volume additions to `docker-compose.yml`**

Repeat Step 1's service and volume blocks in `docker-compose.yml`, and repeat Step 2's env additions in that file's `atria` and `atria-worker` `environment:` lists. (Use the same DNS names; the prod compose shares the network model.)

- [ ] **Step 4: Add `MC_*` documentation to `.env` and `.env.example`**

Append to `.env`:

```bash
# maintenance_copilot — LLM endpoint override for no-GPU hosts (else uses local vLLM).
# MC_SYNTHESIS_BASE_URL=https://proxy.onebot.meobeo.ai/v1
# MC_KG_EXTRACT_BASE_URL=https://proxy.onebot.meobeo.ai/v1
```

Append the same commented block to `.env.example`.

- [ ] **Step 5: Validate compose files parse**

Run: `docker compose -f docker-compose.dev.yml config >/dev/null && echo OK`
Expected: prints `OK` (no YAML/schema errors). If `docker` is unavailable in this environment, run `uv run python -c "import yaml,sys; yaml.safe_load(open('docker-compose.dev.yml')); yaml.safe_load(open('docker-compose.yml')); print('OK')"` instead.

- [ ] **Step 6: Real end-to-end health check**

Run (requires Docker + a GPU for `copilot-llm`; on a no-GPU host, start without the `gpu` profile and set the LLM override env first):

```bash
docker compose -f docker-compose.dev.yml --profile gpu up -d tei qdrant neo4j copilot-llm
# wait for TEI to finish pulling the model, then:
docker compose -f docker-compose.dev.yml exec atria \
    python /app/modules/maintenance_copilot/scripts/copilot.py health
```

Expected: JSON with `"tei": "ok"`, `"qdrant": "ok"`, `"neo4j": "ok"`, `"llm": "ok"` and exit code 0. Record the output; if the LLM is proxied (no GPU), confirm the other three are `ok`.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.dev.yml docker-compose.yml .env.example
git commit -m "feat(maintenance_copilot): add TEI/Qdrant/Neo4j/LLM sidecars + env wiring"
```

(Do not commit `.env` — it holds secrets and is environment-local.)

---

## Phase 1 self-review

- **Spec coverage (Phase 1 slice):** §3.1 sidecars → Task 4; §3.2 module-local provider layer → Tasks 1–2; `health` subcommand (§5 infra) → Task 3. Ingestion, retrieval, KG, guardrails, dashboard are explicitly deferred to later phases (below).
- **Placeholder scan:** none — every step ships runnable code or an exact command.
- **Type consistency:** `RoleConfig`/`ROLES`/`load_config` (Task 1) are consumed with identical names in Tasks 2–3; `RoleClient.embed/chat` signatures match between definition (Task 2) and use (Task 3); `check_health`/`_build_probes` names match between the CLI and its test.

## Roadmap — subsequent phases (each its own plan)

Written after Phase 1 lands and `health` is green:

- **Phase 2 — Ingestion & retrieval:** parse sample docs, Chonkie `SemanticChunker`, TEI embed, Qdrant upsert with metadata payload, `ingest`/`index`/`query` with citation anchors + version-aware filtering. Ships the synthetic sample AMM/MEL/CDL/TSM corpus.
- **Phase 3 — Knowledge graph:** `kg_extract` LLM → strict-JSON entities/edges, Neo4j schema, provenance/confidence/`status`, `graph` command + multi-hop context in `query`.
- **Phase 4 — Validation & guardrails:** `validate`, `recommend-refs`, `check`; citation post-validation, confidence thresholds, advisory-only framing, `data/audit.log.jsonl`.
- **Phase 5 — Dashboard:** Query / Graph / Audit tabs on `dashboard.html` via the module bridge.
