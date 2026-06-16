"""Build the SKILL block injected into every conversation's system prompt."""

from __future__ import annotations

from pathlib import Path

from atria.core.modules.registry import ModuleRegistry


def _format_root(root: Path) -> str:
    """Render the modules root as ``~/...`` when under $HOME, else absolute."""
    try:
        home = Path.home()
        if root.is_relative_to(home):
            return "~/" + str(root.relative_to(home))
    except (AttributeError, ValueError):
        pass
    return str(root)


def _header(root: Path) -> str:
    r = _format_root(root)
    return (
        "## Active Modules\n\n"
        f"Modules root: ``{r}``\n\n"
        f"The following modules are installed under ``{r}/<name>/``. Each module is "
        "a self-contained skill folder; ``SKILL.md`` is authoritative for how to "
        "invoke it. Runnable scripts live in ``scripts/``, blocks in ``blocks/``, "
        "dashboards in ``templates/``.\n\n"
        "**Two ways to use a module:**\n"
        "- ``invoke_skill(\"<name>\")`` — loads the module's full ``SKILL.md`` "
        "into context. Use this when you need the detailed instructions inline.\n"
        "- ``python <absolute-path>/<name>/scripts/<file>.py`` (via bash) — runs "
        "an attached script. **Always use absolute paths** — your bash CWD is "
        "the chat workspace, NOT the modules root, so relative paths like "
        "``modules/<name>/...`` will fail. Example: "
        f"``python {r}/<name>/scripts/<file>.py``.\n"
    )


def _format_files(files: list[str]) -> str:
    """Return a compact one-line listing of a module's files, capped for length."""
    interesting = [f for f in files if f != "SKILL.md"]
    if not interesting:
        return ""
    shown = interesting[:20]
    suffix = (
        "" if len(interesting) == len(shown) else f", … (+{len(interesting) - len(shown)} more)"
    )
    return f"Files: {', '.join(shown)}{suffix}"


def build_skill_block(registry: ModuleRegistry) -> str:
    """Return the SKILL block (header + every module's SKILL.md). Empty if no modules."""
    modules = registry.all()
    if not modules:
        return ""
    parts = [_header(registry.root)]
    for m in modules:
        section = [f"### {m.name}", "", m.skill_md.strip()]
        listing = _format_files(list(m.files))
        if listing:
            section.append("")
            section.append(listing)
        parts.append("\n".join(section) + "\n")
    return "\n".join(parts)
