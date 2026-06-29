"""Wire the application's configured LLM into the skill-tool context."""

from __future__ import annotations

from typing import Any

from atria.core.skill_tools import SkillToolContext


def _wire_llm_into_ctx(skill_ctx: SkillToolContext, app_config: Any | None) -> None:
    """Build llm_chat/llm_vision closures that reuse the app's configured LLM.

    If app_config is None, the skill engines fall back to env-var-driven OpenAI
    calls (the original behaviour). When wired, the same api_key/api_base_url/
    model the main agent uses are reused.
    """
    if app_config is None:
        return

    def _client():
        from openai import OpenAI  # noqa: PLC0415

        try:
            api_key = app_config.get_api_key()
        except Exception:
            return None
        base_url = getattr(app_config, "api_base_url", None) or "https://api.openai.com/v1"
        # AppConfig stores ".../chat/completions" in some configs — strip the suffix
        # since the OpenAI SDK appends it.
        if base_url.endswith("/chat/completions"):
            base_url = base_url[: -len("/chat/completions")]
        return OpenAI(api_key=api_key, base_url=base_url)

    model = getattr(app_config, "model", None) or "gpt-4o-mini"
    vlm_model = getattr(app_config, "model_vlm", None) or model

    def llm_chat(system: str, user: str) -> str:
        client = _client()
        if client is None:
            raise RuntimeError("No API key configured for atria")
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return (resp.choices[0].message.content or "").strip()

    def llm_vision(system: str, user: str, image_b64: str) -> str:
        client = _client()
        if client is None:
            raise RuntimeError("No API key configured for atria")
        resp = client.chat.completions.create(
            model=vlm_model,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                    ],
                },
            ],
        )
        return (resp.choices[0].message.content or "").strip()

    skill_ctx.llm_chat = llm_chat
    skill_ctx.llm_vision = llm_vision
    skill_ctx.llm_model = model
