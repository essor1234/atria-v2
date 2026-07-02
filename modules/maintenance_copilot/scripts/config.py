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
