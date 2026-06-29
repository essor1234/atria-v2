"""Configuration API endpoints."""

from typing import Dict, Any, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from atria.web.state import get_state, broadcast_to_all_clients
from atria.config import get_model_registry
from atria.core.runtime.approval.constants import AutonomyLevel, ThinkingLevel
from atria.core.runtime.mode_manager import OperationMode
from atria.web.protocol import WSMessageType

router = APIRouter(prefix="/api/config", tags=["config"])


class ConfigUpdate(BaseModel):
    """Configuration update model."""

    model: str | None = None
    model_thinking: str | None = None
    model_vlm: str | None = None
    model_critique: str | None = None
    model_compact: str | None = None
    api_base_url: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    enable_bash: bool | None = None


@router.get("")
async def get_config() -> Dict[str, Any]:
    """Get current configuration.

    Returns:
        Current configuration (with masked API keys)

    Raises:
        HTTPException: If retrieval fails
    """
    try:
        state = get_state()
        config = state.config_manager.get_config()

        # Mask API key
        api_key = config.api_key
        masked_key = None
        if api_key:
            if len(api_key) > 8:
                masked_key = f"{api_key[:4]}...{api_key[-4:]}"
            else:
                masked_key = "***"

        # Get mode, autonomy, working dir, and git branch
        mode = state.mode_manager.current_mode.value
        autonomy_level = state.get_autonomy_level()
        session = await state.session_manager.get_current_session()
        working_dir = session.working_directory if session else ""
        git_branch = await state.get_git_branch()

        return {
            "model": config.model,
            "model_thinking": config.model_thinking,
            "model_vlm": config.model_vlm,
            "model_critique": config.model_critique,
            "model_compact": config.model_compact,
            "api_base_url": config.api_base_url,
            "api_key": masked_key,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "enable_bash": config.enable_bash,
            "simple_mode": config.simple_mode,
            "mode": mode,
            "autonomy_level": autonomy_level,
            "thinking_level": state.get_thinking_level(),
            "working_dir": working_dir or "",
            "git_branch": git_branch,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("")
async def update_config(update: ConfigUpdate) -> Dict[str, str]:
    """Update configuration.

    Args:
        update: Configuration updates

    Returns:
        Status response

    Raises:
        HTTPException: If update fails
    """
    try:
        state = get_state()
        config = state.config_manager.get_config()

        if update.model is not None:
            config.model = update.model
        if update.model_thinking is not None:
            config.model_thinking = update.model_thinking
        if update.model_vlm is not None:
            config.model_vlm = update.model_vlm
        if update.model_critique is not None:
            config.model_critique = update.model_critique
        if update.model_compact is not None:
            config.model_compact = update.model_compact
        if update.api_base_url is not None:
            config.api_base_url = update.api_base_url
        if update.temperature is not None:
            config.temperature = update.temperature
        if update.max_tokens is not None:
            config.max_tokens = update.max_tokens
        if update.enable_bash is not None:
            config.enable_bash = update.enable_bash
            # Also update permissions.bash.enabled for consistency
            if hasattr(config, "permissions"):
                config.permissions.bash.enabled = update.enable_bash

        # Save configuration with the updated config object
        state.config_manager.save_config(config, global_config=True)

        return {"status": "success", "message": "Configuration updated"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ModeUpdate(BaseModel):
    """Mode update model."""

    mode: str


class AutonomyUpdate(BaseModel):
    """Autonomy update model."""

    level: str


@router.post("/mode")
async def set_mode(update: ModeUpdate) -> Dict[str, str]:
    """Set operation mode (normal/plan).

    Args:
        update: Mode update

    Returns:
        Status response
    """
    try:
        state = get_state()
        mode = OperationMode(update.mode)
        state.mode_manager.set_mode(mode)

        # Broadcast status update to all clients
        session = await state.session_manager.get_current_session()
        await broadcast_to_all_clients(
            {
                "type": WSMessageType.STATUS_UPDATE,
                "data": {
                    "mode": mode.value,
                    "autonomy_level": state.get_autonomy_level(),
                    "thinking_level": state.get_thinking_level(),
                    "working_dir": session.working_directory if session else "",
                    "git_branch": await state.get_git_branch(),
                },
            }
        )

        return {"status": "success", "message": f"Mode set to {mode.value}"}
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {update.mode}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/autonomy")
async def set_autonomy(update: AutonomyUpdate) -> Dict[str, str]:
    """Set autonomy level (Manual/Semi-Auto/Auto).

    Args:
        update: Autonomy update

    Returns:
        Status response
    """
    try:
        valid_levels = {level.value for level in AutonomyLevel}
        if update.level not in valid_levels:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid autonomy level: {update.level}. Must be one of {valid_levels}",
            )

        state = get_state()
        state.set_autonomy_level(update.level)

        # Broadcast status update to all clients
        session = await state.session_manager.get_current_session()
        await broadcast_to_all_clients(
            {
                "type": WSMessageType.STATUS_UPDATE,
                "data": {
                    "mode": state.mode_manager.current_mode.value,
                    "autonomy_level": update.level,
                    "thinking_level": state.get_thinking_level(),
                    "working_dir": session.working_directory if session else "",
                    "git_branch": await state.get_git_branch(),
                },
            }
        )

        return {"status": "success", "message": f"Autonomy set to {update.level}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ThinkingUpdate(BaseModel):
    """Thinking level update model."""

    level: str


@router.post("/thinking")
async def set_thinking(update: ThinkingUpdate) -> Dict[str, str]:
    """Set thinking level (Off/Low/Medium/High).

    Args:
        update: Thinking level update

    Returns:
        Status response
    """
    try:
        valid_levels = {level.value for level in ThinkingLevel}
        if update.level not in valid_levels:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid thinking level: {update.level}. Must be one of {valid_levels}",
            )

        state = get_state()
        state.set_thinking_level(update.level)

        # Broadcast status update to all clients
        session = await state.session_manager.get_current_session()
        await broadcast_to_all_clients(
            {
                "type": WSMessageType.STATUS_UPDATE,
                "data": {
                    "mode": state.mode_manager.current_mode.value,
                    "autonomy_level": state.get_autonomy_level(),
                    "thinking_level": update.level,
                    "working_dir": session.working_directory if session else "",
                    "git_branch": await state.get_git_branch(),
                },
            }
        )

        return {"status": "success", "message": f"Thinking level set to {update.level}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/providers")
async def list_providers() -> List[Dict[str, Any]]:
    """List all available AI providers.

    Returns:
        List of provider information

    Raises:
        HTTPException: If listing fails
    """
    try:
        registry = get_model_registry()
        providers = []

        for provider_info in registry.list_providers():
            # Format models with context info (no pricing)
            models = []
            for model_info in provider_info.list_models():
                description = f"{model_info.context_length//1000}k context"
                if model_info.recommended:
                    description = "Recommended • " + description

                models.append(
                    {
                        "id": model_info.id,
                        "name": model_info.name,
                        "description": description,
                    }
                )

            providers.append(
                {
                    "id": provider_info.id,
                    "name": provider_info.name,
                    "description": provider_info.description,
                    "models": models,
                }
            )

        return providers

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
