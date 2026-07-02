"""render_component tool — render a module block into the chat mid-turn."""

from __future__ import annotations

from typing import Any


class RenderComponentHandler:
    """Handler for the render_component tool.

    Wraps ui_bridge.push_block so the agent can place a module's HTML block into
    the chat stream during a turn. The block is persisted (persist=True) so it
    survives session reload.
    """

    def render(self, args: dict[str, Any], context: Any) -> dict[str, Any]:
        # Lazy import to avoid circular dependency: atria.web -> atria.core -> atria.web
        from atria.web import ui_bridge  # noqa: PLC0415

        module = (args.get("module") or "").strip()
        block = (args.get("block") or "").strip()
        if not module:
            return {"success": False, "error": "render_component requires 'module'", "output": None}
        if not block:
            return {"success": False, "error": "render_component requires 'block'", "output": None}

        props = args.get("props") or {}
        if not isinstance(props, dict):
            return {"success": False, "error": "'props' must be an object", "output": None}
        title = args.get("title")
        height = args.get("height", "auto")

        session_id = None
        cb = getattr(context, "ui_callback", None)
        if cb is not None:
            session_id = getattr(cb, "session_id", None)

        try:
            block_id = ui_bridge.push_block(
                module,
                block,
                props,
                height=height,
                title=title,
                session_id=session_id,
                persist=True,
            )
        except ui_bridge.BlockNotFound as exc:
            return {"success": False, "error": f"block not found: {exc}", "output": None}
        except ui_bridge.BlockPersistError as exc:
            return {"success": False, "error": f"failed to persist block: {exc}", "output": None}
        except RuntimeError as exc:
            return {"success": False, "error": str(exc), "output": None}

        return {
            "success": True,
            "output": f"Rendered {module}/{block} in chat (block_id={block_id})",
            "block_id": block_id,
        }
