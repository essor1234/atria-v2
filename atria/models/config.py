"""Configuration models."""

import os
import re
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from atria.core.paths import APP_DIR_NAME, atria_dir as _atria_home


class ToolPermission(BaseModel):
    """Permission settings for a specific tool."""

    enabled: bool = True
    always_allow: bool = False
    deny_patterns: list[str] = Field(default_factory=list)
    compiled_patterns: list[re.Pattern[str]] = Field(default_factory=list, exclude=True)

    def model_post_init(self, __context: Any) -> None:
        """Compile regex patterns after initialization."""
        self.compiled_patterns = [re.compile(pattern) for pattern in self.deny_patterns]

    def is_allowed(self, target: str) -> bool:
        """Check if a target (file path, command, etc.) is allowed."""
        if not self.enabled:
            return False
        if self.always_allow:
            return True
        return not any(pattern.match(target) for pattern in self.compiled_patterns)


class PermissionConfig(BaseModel):
    """Global permission configuration."""

    file_write: ToolPermission = Field(default_factory=ToolPermission)
    file_read: ToolPermission = Field(default_factory=ToolPermission)
    bash: ToolPermission = Field(
        default_factory=lambda: ToolPermission(
            enabled=True,  # Enabled for development
            always_allow=False,
            deny_patterns=["rm -rf /", "sudo rm -rf /*", "chmod -R 777 /*"],
        )
    )
    git: ToolPermission = Field(default_factory=ToolPermission)
    web_fetch: ToolPermission = Field(default_factory=ToolPermission)


class AutoModeConfig(BaseModel):
    """Auto mode configuration."""

    enabled: bool = False
    max_operations: int = 10  # Max operations before requiring approval
    require_confirmation_after: int = 5  # Ask for confirmation after N operations
    dangerous_operations_require_approval: bool = True


class OperationConfig(BaseModel):
    """Operation-specific settings."""

    show_diffs: bool = True
    backup_before_edit: bool = True
    max_file_size: int = 1_000_000  # 1MB max file size
    allowed_extensions: list[str] = Field(default_factory=list)  # Empty = all allowed


class PlaybookScoringWeights(BaseModel):
    """Scoring weights for ACE playbook bullet selection."""

    effectiveness: float = Field(default=0.5, ge=0.0, le=1.0)
    recency: float = Field(default=0.3, ge=0.0, le=1.0)
    semantic: float = Field(default=0.2, ge=0.0, le=1.0)

    @field_validator("effectiveness", "recency", "semantic")
    @classmethod
    def validate_weight(cls, v: float) -> float:
        """Ensure weights are between 0 and 1."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Weight must be between 0.0 and 1.0")
        return v

    def to_dict(self) -> dict[str, float]:
        """Convert to dictionary format for BulletSelector."""
        return {
            "effectiveness": self.effectiveness,
            "recency": self.recency,
            "semantic": self.semantic,
        }


class PlaybookConfig(BaseModel):
    """ACE playbook configuration."""

    max_strategies: int = Field(default=30, ge=1)
    use_selection: bool = True
    embedding_model: str = "text-embedding-3-small"
    embedding_provider: str = "openai"
    scoring_weights: PlaybookScoringWeights = Field(default_factory=PlaybookScoringWeights)
    cache_embeddings: bool = True  # Phase 4: Enable embedding persistence
    cache_file: Optional[str] = None  # Path to embedding cache file (None = session-based default)


class IframeRpcConfig(BaseModel):
    """RPC settings for custom-block iframes (push_block)."""

    tool_allowlist: list[str] = Field(default_factory=list)


def _default_redis_url() -> str:
    """Default Redis URL for all Redis-backed subsystems.

    Honors ``ATRIA_REDIS_URL`` so a single env var points the whole stack at the
    same Redis (e.g. ``redis://redis:6379/0`` in Docker). Falls back to localhost
    for local/dev. Matches the broker singleton in ``atria.core.tasks.broker``.
    """
    return os.environ.get("ATRIA_REDIS_URL", "redis://localhost:6379/0")


class BusConfig(BaseModel):
    """Cross-process message bus for routing push_block / block_event when the
    WS owner and the publisher are different worker processes."""

    kind: str = "in_memory"  # "in_memory" | "redis"
    redis_url: str = Field(default_factory=_default_redis_url)


class TasksConfig(BaseModel):
    """Distributed task queue (TaskIQ) settings for background subagents."""

    redis_url: str = Field(default_factory=_default_redis_url)
    result_ttl: int = 3600  # seconds a task result lives in Redis
    orphan_after: int = 1800  # seconds before an unfinished task is deemed orphaned


class BlackboardConfig(BaseModel):
    """Shared verified blackboard (DeLM) settings."""

    enabled: bool = False  # opt-in; the blackboard is an accelerant, off by default
    redis_url: str = Field(default_factory=_default_redis_url)
    ttl: int = 3600  # seconds a task's blackboard lives in Redis
    window_tokens: int = 2000  # digest token budget injected into context
    # Admission-time LLM verification (DeLM §A.3) — the paper's largest single accuracy
    # contributor. Notes are checked for grounding before entering shared state.
    verify: bool = True
    # Cheap model for verification; None resolves model_critique -> model_compact -> model.
    # Fig 4c: a cheap model matches a frontier model for this check.
    verify_model: Optional[str] = None


class ParallelConfig(BaseModel):
    """Parallel multi-solver (DeLM Phase 2b) settings."""

    max_solvers: int = 5
    default_solvers: int = 3
    solver_start_stagger_seconds: float = 0.0
    # DeLM W2: split the N solvers into this many sequential waves so later waves read
    # earlier waves' verified blackboard notes (shared progress) instead of running fully
    # isolated (pass@k). 1 = original single simultaneous fan-out.
    waves: int = 2
    pjob_ttl: int = 3600
    redis_url: str = Field(default_factory=_default_redis_url)


class DivideConfig(BaseModel):
    """Work-division multi-agent (DeLM Phase 2c) settings."""

    max_tasks: int = 8  # cap on decomposed subtasks
    max_parallel: int = 3  # max workers running at once
    # DeLM stage 4: when the queue drains, the orchestrator inspects the shared context
    # and may enqueue more subtasks. Bounds the number of such follow-up rounds (0 = off).
    max_redecompose_rounds: int = 1
    pjob_ttl: int = 3600  # seconds a divide job lives in Redis
    job_timeout_s: int = 600  # coordinator total/no-progress timeout
    redis_url: str = Field(default_factory=_default_redis_url)


class WebConfig(BaseModel):
    """Web-UI specific settings."""

    iframe_rpc: IframeRpcConfig = Field(default_factory=IframeRpcConfig)
    bus: BusConfig = Field(default_factory=BusConfig)


class ModelVariant(BaseModel):
    """A named model configuration variant."""

    name: str
    model: str
    provider: str
    temperature: float = 0.6
    max_tokens: int = 8192
    description: str = ""


class AppConfig(BaseModel):
    """Application configuration."""

    model_config = {"protected_namespaces": ()}

    # AI model settings — OpenAI-compatible endpoint
    model: str = "gpt-4o"

    # Fallback model used automatically when a call with `model` fails
    # (transport error, rate limit, model unavailable, server error). Empty = no
    # fallback. Same provider/endpoint as `model`.
    fallback_model: str = ""

    # Optional model slots (fall back to normal model if not set)
    model_thinking: Optional[str] = None
    model_vlm: Optional[str] = None
    model_critique: Optional[str] = None
    model_compact: Optional[str] = None

    api_key: Optional[str] = None
    api_base_url: Optional[str] = None  # defaults to https://api.openai.com/v1/chat/completions
    max_tokens: int = 8192
    temperature: float = 0.6

    # Session settings
    auto_save_interval: int = 5  # Save every N turns
    max_context_tokens: int = 100000  # Dynamically set from model context_length (80%)

    # UI settings
    verbose: bool = False
    debug_logging: bool = False  # Show [QUERY], [REACT], [LLM] debug messages
    color_scheme: str = "monokai"
    show_token_count: bool = True
    enable_sound: bool = True
    # Simple Mode: non-technical UX — auto-approve tool calls (safety floor still
    # refuses dangerous commands) and show friendly activity lines instead of
    # technical tool cards. Developers can disable via settings.json.
    simple_mode: bool = True

    # Permissions
    permissions: PermissionConfig = Field(default_factory=PermissionConfig)

    # Phase 2: Operation settings
    enable_bash: bool = True  # Enable bash execution for development
    bash_timeout: int = 30  # Timeout in seconds for bash commands
    auto_mode: AutoModeConfig = Field(default_factory=AutoModeConfig)
    operation: OperationConfig = Field(default_factory=OperationConfig)
    max_undo_history: int = 50  # Maximum operations to track for undo

    # Session intelligence
    topic_detection: bool = True

    # ACE Playbook settings
    playbook: PlaybookConfig = Field(default_factory=PlaybookConfig)

    # Plan mode configuration
    plan_mode_workflow: str = "5-phase"  # "5-phase" or "iterative"
    plan_mode_explore_agent_count: int = 3
    plan_mode_plan_agent_count: int = 1
    plan_mode_explore_variant: str = "enabled"  # "enabled" or "disabled"

    # Custom instructions (accumulated across config levels)
    instructions: Optional[str] = None

    # Model variants
    model_variants: dict[str, ModelVariant] = Field(default_factory=dict)

    # Web UI nested settings (iframe RPC, etc.)
    web: WebConfig = Field(default_factory=WebConfig)

    # Distributed task queue settings
    tasks: TasksConfig = Field(default_factory=TasksConfig)

    # Shared verified blackboard settings
    blackboard: BlackboardConfig = Field(default_factory=BlackboardConfig)

    # Parallel multi-solver settings
    parallel: ParallelConfig = Field(default_factory=ParallelConfig)

    # Work-division multi-agent settings
    divide: DivideConfig = Field(default_factory=DivideConfig)

    # Paths - resolved via atria_dir() so they honor the ATRIA_DIR override
    # (default ~/.atria). Factories run at instantiation, after env is loaded.
    atria_dir: str = Field(default_factory=lambda: str(_atria_home()))
    session_dir: str = Field(default_factory=lambda: str(_atria_home() / "sessions"))
    log_dir: str = Field(default_factory=lambda: str(_atria_home() / "logs"))
    command_dir: str = f"{APP_DIR_NAME}/commands"

    def get_api_key(self) -> str:
        """Get API key from config or environment.

        Resolution order: an explicit ``api_key`` value, then a
        provider-appropriate environment variable. When the configured
        endpoint is OpenRouter, ``OPENROUTER_API_KEY`` is preferred; otherwise
        ``OPENAI_API_KEY``. Both are accepted as fallbacks so either key works
        against any OpenAI-compatible endpoint.
        """
        import os

        if self.api_key:
            return self.api_key

        base_url = (self.api_base_url or "").lower()
        if "openrouter.ai" in base_url:
            env_order = ("OPENROUTER_API_KEY", "OPENAI_API_KEY")
        else:
            env_order = ("OPENAI_API_KEY", "OPENROUTER_API_KEY")

        for var in env_order:
            key = os.getenv(var)
            if key:
                return key

        raise ValueError(
            "No API key found. Set OPENAI_API_KEY or OPENROUTER_API_KEY "
            "environment variable."
        )

    def get_model_info(self):
        """Get model information from the registry.

        Returns:
            ModelInfo object or None if model not found
        """
        from atria.config import get_model_registry

        registry = get_model_registry()
        result = registry.find_model_by_id(self.model)
        if result:
            return result[2]  # Return ModelInfo
        return None

    def get_thinking_model_info(self):
        """Get thinking model info, fallback to normal model."""
        from atria.config import get_model_registry

        registry = get_model_registry()
        if self.model_thinking:
            result = registry.find_model_by_id(self.model_thinking)
            if result:
                return result
        return registry.find_model_by_id(self.model)

    def get_vlm_model_info(self):
        """Get VLM model info, fallback to normal model."""
        from atria.config import get_model_registry

        registry = get_model_registry()
        if self.model_vlm:
            result = registry.find_model_by_id(self.model_vlm)
            if result:
                return result
        return registry.find_model_by_id(self.model)

    def get_critique_model_info(self):
        """Get critique model info, fallback to thinking then normal."""
        from atria.config import get_model_registry

        registry = get_model_registry()
        for model_id in [self.model_critique, self.model_thinking, self.model]:
            if model_id:
                result = registry.find_model_by_id(model_id)
                if result:
                    return result
        return None

    def get_compact_model_info(self):
        """Get compact model info, fallback to normal model."""
        from atria.config import get_model_registry

        registry = get_model_registry()
        if self.model_compact:
            result = registry.find_model_by_id(self.model_compact)
            if result:
                return result
        return registry.find_model_by_id(self.model)

    def get_variant(self, name: str) -> ModelVariant | None:
        """Get a named model variant configuration."""
        return self.model_variants.get(name)

    def apply_variant(self, name: str) -> bool:
        """Apply a named model variant to the current config.

        Returns True if variant was found and applied.
        """
        variant = self.model_variants.get(name)
        if not variant:
            return False
        self.model = variant.model
        self.temperature = variant.temperature
        self.max_tokens = variant.max_tokens
        return True
