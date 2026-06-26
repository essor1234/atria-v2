"""Filesystem-backed CRUD for modules.

A module is a folder ``<root>/<name>/`` containing at minimum ``SKILL.md``.
Conventionally it also has ``scripts/*.py`` (runnable tools) and
``templates/*.html`` (dashboards), but any tree layout is allowed — only the
presence of ``SKILL.md`` is enforced.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

try:
    import yaml

    _YAML_AVAILABLE = True
except ImportError:  # pragma: no cover — yaml is a hard dep in practice
    _YAML_AVAILABLE = False

logger = logging.getLogger(__name__)


MODULE_NAME_RE = re.compile(r"[a-z0-9_-]+")
# Leading YAML frontmatter block: --- ... --- at the very top of a markdown file.
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)
# Sub-skills live as markdown files under ``<module>/skills/``.
SUBSKILLS_DIR = "skills"
SKILL_FILE = "SKILL.md"
MANIFEST_FILE = "manifest.json"
SCRIPT_FILE = "script.py"  # legacy starter; tolerated but not required

# Recognised badge accents — anything else is ignored at parse time.
_BADGE_COLORS = {"info", "warning", "danger", "success", "neutral"}

# Caps so a giant folder can't blow up the registry or prompt.
_MAX_FILES = 200
_MAX_DEPTH = 4

Template = Literal["blank", "skill", "skill_script", "skill_dashboard"]


class InvalidModuleName(ValueError):
    """Raised when a module name contains disallowed characters."""


class ModuleExists(FileExistsError):
    """Raised when creating a module that already exists."""


class ModuleNotFound(FileNotFoundError):
    """Raised when reading/updating/deleting a module that does not exist."""


@dataclass
class ActivityLabel:
    """Friendly running/done wording for a module action (Simple Mode UI)."""

    running: str
    done: str


@dataclass
class ModuleDashboardManifest:
    title: Optional[str] = None
    default_height: Optional[int] = None
    badge_color: Optional[str] = None


@dataclass
class ModuleManifest:
    """User-authored module presentation config (manifest.json).

    All fields are optional — missing or malformed manifests fall back to
    folder name + ``icon.svg`` defaults so existing modules keep working.
    """

    display_name: Optional[str] = None
    tooltip: Optional[str] = None
    icon: Optional[str] = None  # rel path inside the module dir
    dashboard: Optional[ModuleDashboardManifest] = None
    activity_default: Optional[ActivityLabel] = None
    activity_actions: Dict[str, ActivityLabel] = field(default_factory=dict)


@dataclass
class SubSkill:
    """A lazily-loadable sub-skill: a frontmatter'd markdown file under ``skills/``.

    Only ``name`` + ``description`` are surfaced in the prompt catalog; the body
    is loaded on demand via ``invoke_skill("<module>:<name>")``.
    """

    name: str
    description: str
    rel_path: str  # e.g. "skills/reporting.md"


@dataclass
class Module:
    name: str
    skill_md: str
    dir: Path
    mtime: float
    files: List[str] = field(default_factory=list)
    manifest: Optional[ModuleManifest] = None
    # One-line summary for the prompt catalog (frontmatter ``description`` or the
    # first non-heading line of SKILL.md).
    description: str = ""
    subskills: List[SubSkill] = field(default_factory=list)


def _validate_name(name: str) -> None:
    if not MODULE_NAME_RE.fullmatch(name):
        raise InvalidModuleName(
            f"module name {name!r} must match [a-z0-9_-]+ (no spaces, slashes, or uppercase)"
        )


def _module_dir(root: Path, name: str) -> Path:
    _validate_name(name)
    return root / name


def _ensure_root(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)


def _starter_skill_md(name: str, summary: str = "") -> str:
    body = summary or "Describe what this module does and when to use it."
    return (
        f"# {name}\n\n"
        f"{body}\n\n"
        "## When to use\n- describe trigger conditions\n\n"
        "## How to use\n"
        f"Run scripts via the bash tool: `python <modules>/{name}/scripts/<name>.py`\n"
        "(``<modules>`` resolves to the active modules directory — see the SKILL block "
        "header in the system prompt.)\n"
    )


def _starter_main_script() -> str:
    return (
        "#!/usr/bin/env python\n"
        '"""Entry point for this module."""\n\n'
        "from __future__ import annotations\n\n\n"
        "def main() -> None:\n"
        '    print("hello from module")\n\n\n'
        'if __name__ == "__main__":\n'
        "    main()\n"
    )


def _starter_manifest_json(name: str, has_dashboard: bool) -> str:
    """Scaffolded manifest.json — covers the v1 sidebar + dashboard fields."""
    payload: dict = {
        "display_name": name.replace("_", " ").replace("-", " ").title(),
        "tooltip": f"Open the {name} module",
        "icon": "icon.svg",
    }
    if has_dashboard:
        payload["dashboard"] = {
            "title": f"{name.replace('_', ' ').replace('-', ' ').title()} · dashboard",
            "default_height": 720,
            "badge_color": "warning",
        }
    return json.dumps(payload, indent=2) + "\n"


def _read_manifest(module_dir: Path) -> Optional[ModuleManifest]:
    """Lenient manifest.json loader — returns ``None`` on any failure.

    Unknown keys are ignored so we can evolve the schema without breaking old
    modules; malformed JSON or wrong types log a warning and degrade to None
    (callers then fall back to folder name + icon.svg).
    """
    p = module_dir / MANIFEST_FILE
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("invalid manifest.json in %s: %s", module_dir, exc)
        return None
    if not isinstance(raw, dict):
        logger.warning("manifest.json in %s is not an object", module_dir)
        return None

    activity_default, activity_actions = _parse_activity(raw.get("activity"))
    return ModuleManifest(
        display_name=_nonempty_str(raw.get("display_name")),
        tooltip=_nonempty_str(raw.get("tooltip")),
        icon=_nonempty_str(raw.get("icon")),
        dashboard=_parse_dashboard(raw.get("dashboard")),
        activity_default=activity_default,
        activity_actions=activity_actions,
    )


def _nonempty_str(v: Any) -> Optional[str]:
    return v if isinstance(v, str) and v.strip() else None


def _parse_dashboard(raw: Any) -> Optional[ModuleDashboardManifest]:
    if not isinstance(raw, dict):
        return None
    height = raw.get("default_height")
    badge = raw.get("badge_color")
    return ModuleDashboardManifest(
        title=_nonempty_str(raw.get("title")),
        default_height=int(height) if isinstance(height, (int, float)) and height > 0 else None,
        badge_color=badge if isinstance(badge, str) and badge in _BADGE_COLORS else None,
    )


def _parse_activity(
    raw: Any,
) -> tuple[Optional[ActivityLabel], Dict[str, ActivityLabel]]:
    """Parse the optional ``activity`` manifest block leniently.

    Shape: ``{"default": {running, done}, "actions": {name: {running, done}}}``.
    Anything malformed degrades to ``(None, {})`` so old/invalid manifests keep
    working.
    """
    if not isinstance(raw, dict):
        return None, {}

    def _label(d: Any) -> Optional[ActivityLabel]:
        if not isinstance(d, dict):
            return None
        running = _nonempty_str(d.get("running"))
        done = _nonempty_str(d.get("done"))
        if running is None and done is None:
            return None
        return ActivityLabel(running=running or "Working…", done=done or "Done")

    default = _label(raw.get("default"))
    actions: Dict[str, ActivityLabel] = {}
    raw_actions = raw.get("actions")
    if isinstance(raw_actions, dict):
        for key, value in raw_actions.items():
            label = _label(value)
            if label is not None:
                actions[str(key)] = label
    return default, actions


def _starter_dashboard_html(name: str) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8" />\n'
        f"  <title>{name} dashboard</title>\n"
        "  <style>body{font-family:system-ui;padding:2rem;color:#222}</style>\n"
        "</head>\n"
        "<body>\n"
        f"  <h1>{name}</h1>\n"
        "  <p>Edit this template to build your module's dashboard.</p>\n"
        "</body>\n"
        "</html>\n"
    )


def _atomic_write(path: Path, content: str) -> None:
    _atomic_write_bytes(path, content.encode("utf-8"))


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".tmp-{path.name}")
    # Write + fsync the file body before the atomic rename so a crash between
    # the rename and the next sync can't leave the new inode pointing at
    # unflushed (zeroed) blocks.
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _walk_files(d: Path) -> List[str]:
    """Return relative POSIX-style file paths inside ``d``, capped + depth-limited."""
    out: List[str] = []
    for dirpath, dirnames, filenames in os.walk(d):
        rel_dir = Path(dirpath).relative_to(d)
        depth = 0 if rel_dir == Path(".") else len(rel_dir.parts)
        if depth >= _MAX_DEPTH:
            dirnames[:] = []
        # Skip noise.
        dirnames[:] = [n for n in dirnames if not n.startswith(".") and n != "__pycache__"]
        for fn in filenames:
            if fn.startswith(".tmp-"):
                continue
            rel = (rel_dir / fn).as_posix() if rel_dir != Path(".") else fn
            out.append(rel)
            if len(out) >= _MAX_FILES:
                return sorted(out)
    return sorted(out)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split leading YAML frontmatter from a markdown document.

    Returns ``(metadata, body)``. If there is no frontmatter, ``metadata`` is
    empty and ``body`` is the original text.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw = m.group(1)
    data: dict = {}
    if _YAML_AVAILABLE:
        try:
            loaded = yaml.safe_load(raw)
            if isinstance(loaded, dict):
                data = loaded
        except yaml.YAMLError as exc:
            logger.warning("invalid frontmatter: %s", exc)
    else:
        data = _simple_yaml(raw)
    return data, text[m.end() :]


def _simple_yaml(text: str) -> dict:
    """Minimal ``key: value`` parser used only when PyYAML is unavailable."""
    out: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip().strip("\"'")
        out[key.strip()] = value
    return out


def _description_from(meta: dict, body: str, fallback_name: str) -> str:
    """Derive a 1-line description: frontmatter ``description`` else first prose line."""
    desc = meta.get("description")
    if isinstance(desc, str) and desc.strip():
        return desc.strip()[:200]
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        return line[:200]
    return f"Module: {fallback_name}"


def _read_subskills(module_dir: Path) -> List[SubSkill]:
    """Discover ``<module>/skills/*.md`` sub-skills (sorted), reading only metadata."""
    skills_dir = module_dir / SUBSKILLS_DIR
    if not skills_dir.is_dir():
        return []
    out: List[SubSkill] = []
    for p in sorted(skills_dir.glob("*.md")):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        meta, body = parse_frontmatter(text)
        name = meta.get("name")
        if not (isinstance(name, str) and name.strip()):
            name = p.stem
        out.append(
            SubSkill(
                name=name.strip(),
                description=_description_from(meta, body, name),
                rel_path=f"{SUBSKILLS_DIR}/{p.name}",
            )
        )
    return out


def _read_module(root: Path, name: str) -> Module:
    d = _module_dir(root, name)
    skill_path = d / SKILL_FILE
    if not skill_path.is_file():
        raise ModuleNotFound(name)
    files = _walk_files(d)
    mtime = skill_path.stat().st_mtime
    for rel in files:
        try:
            mtime = max(mtime, (d / rel).stat().st_mtime)
        except OSError:
            continue
    skill_md = skill_path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(skill_md)
    return Module(
        name=name,
        skill_md=skill_md,
        dir=d,
        mtime=mtime,
        files=files,
        manifest=_read_manifest(d),
        description=_description_from(meta, body, name),
        subskills=_read_subskills(d),
    )


def list_modules(root: Path) -> List[Module]:
    """List all valid modules under ``root`` sorted by name. Creates ``root`` if missing."""
    _ensure_root(root)
    out: List[Module] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        try:
            _validate_name(entry.name)
        except InvalidModuleName:
            logger.warning("skipping module folder with invalid name: %s", entry.name)
            continue
        try:
            out.append(_read_module(root, entry.name))
        except ModuleNotFound:
            logger.warning("skipping malformed module folder (no SKILL.md): %s", entry.name)
    return out


def read_module(root: Path, name: str) -> Module:
    _ensure_root(root)
    return _read_module(root, name)


def create_module(
    root: Path,
    name: str,
    *,
    template: Template = "skill",
    summary: str = "",
) -> Module:
    _ensure_root(root)
    d = _module_dir(root, name)
    if d.exists():
        raise ModuleExists(name)
    d.mkdir()

    _atomic_write(d / SKILL_FILE, _starter_skill_md(name, summary) if template != "blank" else "")

    if template in ("skill_script", "skill_dashboard"):
        _atomic_write(d / "scripts" / "main.py", _starter_main_script())
    if template == "skill_dashboard":
        _atomic_write(d / "templates" / "dashboard.html", _starter_dashboard_html(name))

    if template != "blank":
        _atomic_write(
            d / MANIFEST_FILE,
            _starter_manifest_json(name, has_dashboard=template == "skill_dashboard"),
        )

    return _read_module(root, name)


def delete_module(root: Path, name: str) -> None:
    _ensure_root(root)
    d = _module_dir(root, name)
    if not d.is_dir():
        raise ModuleNotFound(name)
    shutil.rmtree(d)


# ── Per-file ops (used by the fs-style HTTP endpoints) ─────────────────────────


def _resolve_in_module(root: Path, name: str, rel_path: str) -> Path:
    """Resolve ``rel_path`` inside module ``name``, refusing traversal."""
    if not rel_path or rel_path.startswith(("/", "\\")):
        raise ValueError("invalid path")
    d = _module_dir(root, name).resolve()
    if not d.is_dir():
        raise ModuleNotFound(name)
    target = (d / rel_path).resolve()
    try:
        target.relative_to(d)
    except ValueError as exc:
        raise ValueError("path outside module") from exc
    return target


def read_file(root: Path, name: str, rel_path: str) -> bytes:
    target = _resolve_in_module(root, name, rel_path)
    if not target.is_file():
        raise FileNotFoundError(rel_path)
    return target.read_bytes()


def write_file(root: Path, name: str, rel_path: str, content: str) -> None:
    target = _resolve_in_module(root, name, rel_path)
    _atomic_write(target, content)


def write_file_bytes(root: Path, name: str, rel_path: str, data: bytes) -> None:
    target = _resolve_in_module(root, name, rel_path)
    _atomic_write_bytes(target, data)


def delete_file(root: Path, name: str, rel_path: str) -> None:
    target = _resolve_in_module(root, name, rel_path)
    if _is_skill_md(root, name, target):
        raise ValueError("cannot delete SKILL.md")
    if target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()
    else:
        raise FileNotFoundError(rel_path)


def _is_skill_md(root: Path, name: str, target: Path) -> bool:
    skill = _module_dir(root, name).resolve() / SKILL_FILE
    if not skill.exists() or not target.exists():
        return target == skill
    return target.samefile(skill)


def mkdir(root: Path, name: str, rel_path: str) -> None:
    """Create a directory inside module ``name`` (with parents). No-op if it already exists."""
    target = _resolve_in_module(root, name, rel_path)
    if target.exists() and not target.is_dir():
        raise ValueError("path exists and is not a directory")
    target.mkdir(parents=True, exist_ok=True)


def touch_file(root: Path, name: str, rel_path: str) -> None:
    """Create an empty file inside module ``name``. Refuses to overwrite."""
    target = _resolve_in_module(root, name, rel_path)
    if target.exists():
        raise FileExistsError(rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()


def rename_path(root: Path, name: str, src: str, dst: str, *, force: bool = False) -> None:
    """Rename/move ``src`` to ``dst`` inside module ``name``. Atomic os.rename."""
    src_t = _resolve_in_module(root, name, src)
    if not src_t.exists():
        raise FileNotFoundError(src)
    if _is_skill_md(root, name, src_t):
        raise ValueError("cannot rename SKILL.md")
    dst_t = _resolve_in_module(root, name, dst)
    if dst_t.exists():
        if not force:
            raise FileExistsError(dst)
    dst_t.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src_t, dst_t)


def list_dir(root: Path, name: str, rel_path: str = "") -> list[dict]:
    """List immediate children of ``rel_path`` inside module ``name``."""
    if rel_path == "":
        target = _module_dir(root, name).resolve()
        if not target.is_dir():
            raise ModuleNotFound(name)
    else:
        target = _resolve_in_module(root, name, rel_path)
        if not target.is_dir():
            raise NotADirectoryError(rel_path)
    out: list[dict] = []
    for child in target.iterdir():
        if child.name.startswith(".tmp-") or child.name == "__pycache__":
            continue
        try:
            stat = child.stat()
        except OSError:
            continue
        is_dir = child.is_dir()
        out.append(
            {
                "name": child.name,
                "kind": "dir" if is_dir else "file",
                "size": 0 if is_dir else stat.st_size,
                "mtime": stat.st_mtime,
                "ext": "" if is_dir else child.suffix.lower(),
            }
        )
    out.sort(key=lambda e: (e["kind"] != "dir", e["name"].lower()))
    return out
