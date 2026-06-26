"""Build the SKILL catalog injected into every conversation's system prompt.

This is a *lazy* catalog: per module it emits the one-line description, the
"When to use" triggers, and an index of sub-skills — but NOT the full SKILL.md
body. The agent loads the full guide on demand with ``invoke_skill("<name>")``
and individual sub-skills with ``invoke_skill("<name>:<sub>")``. This keeps the
always-on prompt small even when a module documents many functions.
"""

from __future__ import annotations

import re
from pathlib import Path

from atria.core.modules.registry import ModuleRegistry
from atria.core.modules.store import parse_frontmatter

_HEADING_RE = re.compile(r"^#{1,6}\s")


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
        "a self-contained skill folder. Only a short summary is shown here; the "
        "full instructions load **on demand** so the prompt stays small.\n\n"
        "**Loading module instructions (lazy):**\n"
        '- ``invoke_skill("<name>")`` — load the module\'s full ``SKILL.md`` into '
        "context. Do this before using a module you haven't loaded yet.\n"
        '- ``invoke_skill("<name>:<sub-skill>")`` — load just one sub-skill\'s '
        "detailed guide (the sub-skills are listed per module below). Prefer this "
        "over loading the whole module when you only need one area.\n"
        "- Decide from each module's description + 'When to use' + sub-skill list "
        "whether (and what) to load — don't load everything preemptively.\n\n"
        "**Running scripts:** ``python <absolute-path>/<name>/scripts/<file>.py`` "
        "(via bash). **Always use absolute paths** — your bash CWD is the chat "
        f"workspace, NOT the modules root. Example: ``python {r}/<name>/scripts/<file>.py``.\n"
    )


def _extract_section(body: str, heading: str) -> str:
    """Return the text under a ``## <heading>`` (case-insensitive).

    Capture stops at the next markdown heading. Returns ``""`` if not found.
    """
    target = heading.strip().lower()
    out: list[str] = []
    capturing = False
    for line in body.splitlines():
        if _HEADING_RE.match(line):
            if capturing:
                break
            capturing = line.lstrip("#").strip().lower() == target
            continue
        if capturing:
            out.append(line)
    return "\n".join(out).strip()


def _format_files(files: list[str]) -> str:
    """Return a compact one-line listing of a module's files, capped for length."""
    interesting = [f for f in files if f != "SKILL.md" and not f.startswith("skills/")]
    if not interesting:
        return ""
    shown = interesting[:20]
    suffix = (
        "" if len(interesting) == len(shown) else f", … (+{len(interesting) - len(shown)} more)"
    )
    return f"Files: {', '.join(shown)}{suffix}"


def build_skill_block(registry: ModuleRegistry) -> str:
    """Return the lazy module catalog (header + a summary per module). Empty if none."""
    modules = registry.all()
    if not modules:
        return ""
    parts = [_header(registry.root)]
    for m in modules:
        _, body = parse_frontmatter(m.skill_md)
        section = [f"### {m.name}", "", (m.description or "").strip()]

        when = _extract_section(body, "When to use")
        if when:
            section += ["", "**When to use:**", when]

        if m.subskills:
            section += ["", "**Sub-skills** (load individually with `invoke_skill`):"]
            for s in m.subskills:
                section.append(f'- `invoke_skill("{m.name}:{s.name}")` — {s.description}')

        section += ["", f'Full guide: `invoke_skill("{m.name}")`']

        listing = _format_files(list(m.files))
        if listing:
            section += ["", listing]

        parts.append("\n".join(section) + "\n")
    return "\n".join(parts)
