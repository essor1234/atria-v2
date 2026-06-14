"""Persona management API endpoints."""

from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from atria.core.personas import PersonaManager, Persona

router = APIRouter(prefix="/api/personas", tags=["personas"])


class PersonaRequest(BaseModel):
    """Request model for creating/updating a persona."""

    name: str
    system_prompt: str


class PersonaResponse(BaseModel):
    """Response model for a persona."""

    name: str
    system_prompt: str
    is_built_in: bool
    created_at: str


@router.get("")
async def list_personas() -> List[PersonaResponse]:
    """List all available personas.

    Returns:
        List of personas
    """
    try:
        manager = PersonaManager()
        personas = manager.list_personas()
        return [
            PersonaResponse(
                name=p.name,
                system_prompt=p.system_prompt,
                is_built_in=p.is_built_in,
                created_at=p.created_at,
            )
            for p in personas
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{name}")
async def get_persona(name: str) -> PersonaResponse:
    """Get a persona by name.

    Args:
        name: Persona name

    Returns:
        Persona details

    Raises:
        HTTPException: If persona not found
    """
    try:
        manager = PersonaManager()
        persona = manager.get_persona(name)
        if not persona:
            raise HTTPException(status_code=404, detail=f"Persona '{name}' not found")
        return PersonaResponse(
            name=persona.name,
            system_prompt=persona.system_prompt,
            is_built_in=persona.is_built_in,
            created_at=persona.created_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
async def create_persona(request: PersonaRequest) -> PersonaResponse:
    """Create a new persona.

    Args:
        request: Persona creation request

    Returns:
        Created persona

    Raises:
        HTTPException: If creation fails
    """
    try:
        manager = PersonaManager()

        # Check if persona already exists
        if manager.get_persona(request.name):
            raise HTTPException(status_code=400, detail=f"Persona '{request.name}' already exists")

        persona = Persona(
            name=request.name,
            system_prompt=request.system_prompt,
            is_built_in=False,
        )

        manager.save_persona(persona)

        return PersonaResponse(
            name=persona.name,
            system_prompt=persona.system_prompt,
            is_built_in=persona.is_built_in,
            created_at=persona.created_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{name}")
async def update_persona(name: str, request: PersonaRequest) -> PersonaResponse:
    """Update an existing persona.

    Args:
        name: Persona name to update
        request: Updated persona data

    Returns:
        Updated persona

    Raises:
        HTTPException: If persona not found or update fails
    """
    try:
        manager = PersonaManager()
        existing = manager.get_persona(name)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Persona '{name}' not found")

        persona = Persona(
            name=request.name,
            system_prompt=request.system_prompt,
            is_built_in=False,
        )

        manager.save_persona(persona)

        # Delete old file if name changed
        if name != request.name:
            manager.delete_persona(name)

        return PersonaResponse(
            name=persona.name,
            system_prompt=persona.system_prompt,
            is_built_in=persona.is_built_in,
            created_at=persona.created_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{name}")
async def delete_persona(name: str) -> dict[str, str]:
    """Delete a persona.

    Args:
        name: Persona name to delete

    Returns:
        Confirmation message

    Raises:
        HTTPException: If persona not found or deletion fails
    """
    try:
        manager = PersonaManager()
        if not manager.delete_persona(name):
            raise HTTPException(status_code=404, detail=f"Persona '{name}' not found")
        return {"message": f"Persona '{name}' deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{name}/duplicate")
async def duplicate_persona(name: str, new_name: str) -> PersonaResponse:
    """Duplicate an existing persona.

    Args:
        name: Source persona name
        new_name: Name for the new persona

    Returns:
        New persona

    Raises:
        HTTPException: If source not found or duplication fails
    """
    try:
        manager = PersonaManager()
        persona = manager.duplicate_persona(name, new_name)
        if not persona:
            raise HTTPException(status_code=404, detail=f"Persona '{name}' not found")
        return PersonaResponse(
            name=persona.name,
            system_prompt=persona.system_prompt,
            is_built_in=persona.is_built_in,
            created_at=persona.created_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{name}/preview")
async def preview_persona(name: str) -> dict[str, str]:
    """Preview the system prompt for a persona.

    Args:
        name: Persona name

    Returns:
        Preview containing the system prompt

    Raises:
        HTTPException: If persona not found
    """
    try:
        manager = PersonaManager()
        persona = manager.get_persona(name)
        if not persona:
            raise HTTPException(status_code=404, detail=f"Persona '{name}' not found")

        return {"preview": persona.system_prompt}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
