"""Persona management system for agent customization."""

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

from atria.core.paths import atria_dir


@dataclass
class Persona:
    """A persona configuration for an agent."""

    name: str
    system_prompt: str
    is_built_in: bool = False
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert persona to dictionary."""
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Persona":
        """Create persona from dictionary."""
        return Persona(**data)


class PersonaManager:
    """Manages custom personas for agents."""

    def __init__(self, personas_dir: Optional[Path] = None):
        """Initialize persona manager.

        Args:
            personas_dir: Directory to store personas. Defaults to ~/.atria/personas/
        """
        if personas_dir is None:
            personas_dir = atria_dir() / "personas"
        self.personas_dir = personas_dir
        self.personas_dir.mkdir(parents=True, exist_ok=True)

    def list_personas(self) -> List[Persona]:
        """List all available personas (built-in + custom).

        Returns:
            List of Persona objects
        """
        personas = []

        # Load custom personas
        for persona_file in self.personas_dir.glob("*.json"):
            try:
                data = json.loads(persona_file.read_text())
                personas.append(Persona.from_dict(data))
            except (json.JSONDecodeError, ValueError):
                continue

        # Sort by name
        personas.sort(key=lambda p: p.name)
        return personas

    def get_persona(self, name: str) -> Optional[Persona]:
        """Get a persona by name.

        Args:
            name: Persona name

        Returns:
            Persona object or None if not found
        """
        persona_file = self.personas_dir / f"{name}.json"
        # Guard against path traversal
        if not str(persona_file.resolve()).startswith(str(self.personas_dir.resolve())):
            return None
        if not persona_file.exists():
            return None

        try:
            data = json.loads(persona_file.read_text())
            return Persona.from_dict(data)
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            return None

    def save_persona(self, persona: Persona) -> Path:
        """Save a persona to disk.

        Args:
            persona: Persona to save

        Returns:
            Path to saved file
        """
        persona_file = self.personas_dir / f"{persona.name}.json"
        if not str(persona_file.resolve()).startswith(str(self.personas_dir.resolve())):
            raise ValueError(f"Invalid persona name: {persona.name!r}")
        persona_file.write_text(
            json.dumps(persona.to_dict(), indent=2),
            encoding="utf-8",
        )
        return persona_file

    def delete_persona(self, name: str) -> bool:
        """Delete a persona.

        Args:
            name: Persona name

        Returns:
            True if deleted, False if not found
        """
        persona_file = self.personas_dir / f"{name}.json"
        if not str(persona_file.resolve()).startswith(str(self.personas_dir.resolve())):
            raise ValueError(f"Invalid persona name: {name!r}")
        if not persona_file.exists():
            return False
        persona_file.unlink()
        return True

    def duplicate_persona(self, source_name: str, new_name: str) -> Optional[Persona]:
        """Duplicate an existing persona.

        Args:
            source_name: Name of persona to duplicate
            new_name: Name for the new persona

        Returns:
            New persona or None if source not found
        """
        source = self.get_persona(source_name)
        if not source:
            return None

        new_persona = Persona(
            name=new_name,
            system_prompt=source.system_prompt,
            is_built_in=False,
        )

        self.save_persona(new_persona)
        return new_persona
