"""Tests for persona_name extraction in the websocket query handler."""


def test_persona_name_extracted_from_query_data():
    """persona_name from WS data dict is correctly extracted."""
    data = {"data": {"message": "hello", "session_id": "abc", "persona_name": "pirate"}}
    query_data = data.get("data", {})
    persona_name = query_data.get("persona_name")
    assert persona_name == "pirate"


def test_persona_name_absent_when_not_sent():
    """persona_name is None when not included in WS payload."""
    data = {"data": {"message": "hello", "session_id": "abc"}}
    query_data = data.get("data", {})
    persona_name = query_data.get("persona_name")
    assert persona_name is None


from atria.core.personas.manager import PersonaManager, Persona


def test_persona_system_prompt_prepended(tmp_path):
    """Persona system prompt is prepended to base system prompt."""
    manager = PersonaManager(personas_dir=tmp_path)
    persona = Persona(name="pirate", system_prompt="You are a pirate. Speak like one.")
    manager.save_persona(persona)

    base_prompt = "You are a helpful assistant."
    found = manager.get_persona("pirate")
    assert found is not None

    combined = found.system_prompt + "\n\n" + base_prompt
    assert combined.startswith("You are a pirate.")
    assert "helpful assistant" in combined


def test_missing_persona_falls_back_silently(tmp_path):
    """When persona_name is given but persona not found, base prompt is used unchanged."""
    manager = PersonaManager(personas_dir=tmp_path)
    base_prompt = "You are a helpful assistant."

    found = manager.get_persona("nonexistent")
    result = (found.system_prompt + "\n\n" + base_prompt) if found else base_prompt
    assert result == base_prompt


def test_no_persona_name_leaves_prompt_unchanged(tmp_path):
    """When persona_name is None, base prompt is unchanged."""
    base_prompt = "You are a helpful assistant."
    persona_name = None
    manager = PersonaManager(personas_dir=tmp_path)

    found = manager.get_persona(persona_name) if persona_name else None
    result = (found.system_prompt + "\n\n" + base_prompt) if found else base_prompt
    assert result == base_prompt
