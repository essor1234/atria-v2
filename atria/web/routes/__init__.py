"""API routes for web UI."""

from atria.web.routes.chat import router as chat_router
from atria.web.routes.sessions import router as sessions_router
from atria.web.routes.config import router as config_router
from atria.web.routes.commands import router as commands_router
from atria.web.routes.mcp import router as mcp_router
from atria.web.routes.auth import router as auth_router
from atria.web.routes.projects import router as projects_router
from atria.web.routes.artifacts import router as artifacts_router
from atria.web.routes.fs import router as fs_router
from atria.web.routes.personas import router as personas_router
from atria.web.routes.analyze import router as analyze_router
from atria.web.routes.modules import router as modules_router
from atria.web.routes.blocks import router as blocks_router
from atria.web.routes.module_dashboard import router as module_dashboard_router
from atria.web.routes.me import router as me_router

__all__ = [
    "chat_router",
    "sessions_router",
    "config_router",
    "commands_router",
    "mcp_router",
    "auth_router",
    "projects_router",
    "artifacts_router",
    "fs_router",
    "personas_router",
    "analyze_router",
    "modules_router",
    "blocks_router",
    "module_dashboard_router",
    "me_router",
]
