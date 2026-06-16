"""FastAPI dependency providers."""

from atria.web.dependencies.auth import require_authenticated_user
from atria.web.dependencies.modules import get_modules_registry
from atria.web.dependencies.workspace import require_workspace, ensure_user_workspace

__all__ = [
    "require_authenticated_user",
    "require_workspace",
    "ensure_user_workspace",
    "get_modules_registry",
]
