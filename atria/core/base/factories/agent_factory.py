"""Factory helpers for assembling agent instances."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from atria.core.agents import MainAgent
from atria.core.agents.subagents import SubAgentManager
from atria.core.base.interfaces import AgentInterface, ToolRegistryInterface
from atria.core.runtime import ModeManager
from atria.models.config import AppConfig

if TYPE_CHECKING:
    from atria.core.skills import SkillLoader
    from atria.core.runtime.config import ConfigManager

logger = logging.getLogger(__name__)


@dataclass
class AgentSuite:
    """Agent suite for runtime."""

    normal: AgentInterface
    subagent_manager: SubAgentManager | None = None
    skill_loader: "SkillLoader | None" = None


class AgentFactory:
    """Creates conversational agents bound to a shared mode manager and tools."""

    def __init__(
        self,
        config: AppConfig,
        tool_registry: ToolRegistryInterface,
        mode_manager: ModeManager,
        working_dir: Any = None,
        enable_subagents: bool = True,
        config_manager: "ConfigManager | None" = None,
        env_context: Any = None,
    ) -> None:
        self._config = config
        self._tool_registry = tool_registry
        self._mode_manager = mode_manager
        self._working_dir = working_dir
        self._enable_subagents = enable_subagents
        self._config_manager = config_manager
        self._env_context = env_context
        self._subagent_manager: SubAgentManager | None = None
        self._skill_loader: "SkillLoader | None" = None

    def create_agents(self) -> AgentSuite:
        """Instantiate both normal and planning agents.

        If subagents are enabled, also creates and registers the SubAgentManager
        with default subagents (general-purpose, researcher, code-reviewer, etc.).

        Also initializes the skills system if skill directories exist.
        """
        # Initialize skills system
        self._initialize_skills()

        # Create subagent manager if enabled
        if self._enable_subagents:
            self._subagent_manager = SubAgentManager(
                config=self._config,
                tool_registry=self._tool_registry,
                mode_manager=self._mode_manager,
                working_dir=self._working_dir,
                env_context=self._env_context,
            )
            # Register default subagents
            self._subagent_manager.register_defaults()

            # Register custom agents from config files
            self._register_custom_agents()

            # Register dedicated subagents derived from agent-backed modules
            self._register_module_subagents()

            # Register manager with tool registry for task tool execution
            self._tool_registry.set_subagent_manager(self._subagent_manager)

        # Create main agent
        normal = MainAgent(
            self._config,
            self._tool_registry,
            self._mode_manager,
            self._working_dir,
            env_context=self._env_context,
        )

        return AgentSuite(
            normal=normal,
            subagent_manager=self._subagent_manager,
            skill_loader=self._skill_loader,
        )

    def _initialize_skills(self) -> None:
        """Initialize the skills system from configured directories."""
        if not self._config_manager:
            return

        try:
            from atria.core.skills import SkillLoader

            skill_dirs = self._config_manager.get_skill_dirs()
            if skill_dirs:
                self._skill_loader = SkillLoader(skill_dirs)
                # Pre-discover skills for the index
                skills = self._skill_loader.discover_skills()
                if skills:
                    logger.info(
                        f"Discovered {len(skills)} skills from {len(skill_dirs)} directories"
                    )
                # Register with tool registry
                self._tool_registry.set_skill_loader(self._skill_loader)
        except ImportError:
            logger.debug("Skills module not available")
        except Exception as e:
            logger.warning(f"Failed to initialize skills system: {e}")

    def _register_custom_agents(self) -> None:
        """Register custom agents from config files."""
        if not self._config_manager or not self._subagent_manager:
            return

        try:
            custom_agents = self._config_manager.load_custom_agents()
            if custom_agents:
                self._subagent_manager.register_custom_agents(custom_agents)
                logger.info(f"Registered {len(custom_agents)} custom agents")
        except Exception as e:
            logger.warning(f"Failed to load custom agents: {e}")

    def _register_module_subagents(self) -> None:
        """Register one dedicated subagent per agent-backed module (opt-in)."""
        if not self._subagent_manager:
            return
        try:
            from atria.core.modules.registry import get_registry
            from atria.core.modules.subagent import module_subagent_specs

            specs = module_subagent_specs(get_registry())
            for spec in specs:
                self._subagent_manager.register_subagent(spec)
            if specs:
                logger.info("Registered %d module subagent(s)", len(specs))
        except Exception as exc:
            logger.warning("Failed to register module subagents: %s", exc)

    def refresh_tools(self, suite: AgentSuite) -> None:
        """Refresh tool metadata for the agent."""
        if hasattr(suite.normal, "refresh_tools"):
            suite.normal.refresh_tools()
