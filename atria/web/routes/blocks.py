"""HTTP gateway around ``ui_bridge.push_block`` for subprocess scripts.

Module scripts run in a separate Python process spawned by the bash tool, so
they cannot reach the agent process's ``WebUICallback`` directly. This router
gives them an HTTP entry point that performs the in-process call.

Callers must include the ``session_id`` of the target chat session. The bash
tool exports it as the ``ATRIA_SESSION_ID`` env var.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from atria.web import ui_bridge

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/blocks", tags=["blocks"])


class PushBlockBody(BaseModel):
    session_id: str = Field(min_length=1)
    module: str = Field(min_length=1)
    block: str = Field(min_length=1)
    props: Optional[Dict[str, Any]] = None
    block_id: Optional[str] = None
    height: Any = "auto"
    title: Optional[str] = None
    persist: bool = True


class UpdateBlockBody(BaseModel):
    session_id: str = Field(min_length=1)
    block_id: str = Field(min_length=1)
    props: Dict[str, Any]


class RemoveBlockBody(BaseModel):
    session_id: str = Field(min_length=1)
    block_id: str = Field(min_length=1)


def _no_active_session(detail: str) -> HTTPException:
    return HTTPException(status_code=404, detail=detail)


@router.post("/push")
def push_block_endpoint(body: PushBlockBody) -> Dict[str, str]:
    try:
        bid = ui_bridge.push_block(
            module=body.module,
            block=body.block,
            props=body.props,
            block_id=body.block_id,
            height=body.height,
            title=body.title,
            session_id=body.session_id,
            persist=body.persist,
        )
    except ui_bridge.BlockNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise _no_active_session(str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"block_id": bid}


@router.post("/update", status_code=204)
def update_block_endpoint(body: UpdateBlockBody) -> None:
    try:
        ui_bridge.update_block(body.block_id, body.props, session_id=body.session_id)
    except RuntimeError as exc:
        raise _no_active_session(str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/remove", status_code=204)
def remove_block_endpoint(body: RemoveBlockBody) -> None:
    try:
        ui_bridge.remove_block(body.block_id, session_id=body.session_id)
    except RuntimeError as exc:
        raise _no_active_session(str(exc))
