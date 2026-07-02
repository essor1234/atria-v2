"""Filesystem-backed CRUD for modules.

A module is a folder ``<root>/<name>/`` containing at minimum ``SKILL.md``.
Conventionally it also has ``scripts/*.py`` (runnable tools) and
``templates/*.html`` (dashboards), but any tree layout is allowed — only the
presence of ``SKILL.md`` is enforced.
"""

from __future__ import annotations

import csv
import io
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

# Caps for the editable-dataset read/write path (see read_dataset/write_dataset).
_MAX_DATA_ROWS = 50_000
_MAX_DATA_COLS = 200
_MAX_DATA_BYTES = 50 * 1024 * 1024  # 50 MB, matching the upload limit

Template = Literal["blank", "skill", "skill_script", "skill_dashboard", "data"]


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
class ModuleSubagentManifest:
    """Opt-in config for routing a module's work to a dedicated subagent."""

    enabled: bool = False
    model: Optional[str] = None
    tools: Optional[List[str]] = None


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
    subagent: Optional[ModuleSubagentManifest] = None


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
        subagent=_parse_subagent(raw.get("subagent")),
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


def _parse_subagent(raw: Any) -> Optional[ModuleSubagentManifest]:
    """Lenient parser for the optional ``subagent`` manifest block.

    Anything malformed degrades to ``None`` so old/invalid manifests keep working.
    """
    if not isinstance(raw, dict):
        return None
    enabled = raw.get("enabled")
    if not isinstance(enabled, bool):
        enabled = False
    tools_raw = raw.get("tools")
    tools: Optional[List[str]] = None
    if isinstance(tools_raw, list):
        cleaned = [t for t in tools_raw if isinstance(t, str) and t.strip()]
        tools = cleaned or None
    return ModuleSubagentManifest(
        enabled=enabled,
        model=_nonempty_str(raw.get("model")),
        tools=tools,
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


# ── "data" template: build a warehouse-style module from uploaded datasets ─────

_GENERIC_DATA_ICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
    '<ellipse cx="12" cy="5" rx="8" ry="3"/>'
    '<path d="M4 5v6c0 1.66 3.58 3 8 3s8-1.34 8-3V5"/>'
    '<path d="M4 11v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6"/></svg>\n'
)

# Generic CSV explorer CLI dropped into scripts/data.py. Dataset-agnostic; the
# dashboard and the agent both drive it. Wrapped in single-quoted triple quotes
# because the script body uses double-quoted docstrings.
_GENERIC_DATA_SCRIPT = '''#!/usr/bin/env python
"""Generic CSV explorer for a data module (auto-generated).

All subcommands print JSON to stdout:
  list                                          -> {"datasets":[{name,rows,columns,size}]}
  preview --file F [--limit N]                  -> {"file","columns","rows":[[...]]}
  query --file F [--filter S] [--column C] [--limit N]

CSV datasets live in ../data/ next to this script.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def _csv_files():
    if not DATA_DIR.is_dir():
        return []
    return sorted(p for p in DATA_DIR.rglob("*.csv") if p.is_file())


def _rel(p: Path) -> str:
    return p.relative_to(DATA_DIR).as_posix()


def _resolve(file: str) -> Path:
    p = (DATA_DIR / file).resolve()
    try:
        p.relative_to(DATA_DIR.resolve())
    except ValueError:
        raise SystemExit(f"path outside data dir: {file}")
    if not p.is_file():
        raise SystemExit(f"file not found: {file}")
    return p


def _header_and_count(path: Path):
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, [])
        count = sum(1 for _ in reader)
    return header, count


def cmd_list() -> dict:
    out = []
    for p in _csv_files():
        try:
            header, count = _header_and_count(p)
            size = p.stat().st_size
        except OSError:
            continue
        out.append({"name": _rel(p), "rows": count, "columns": header, "size": size})
    return {"datasets": out}


def cmd_preview(file: str, limit: int) -> dict:
    p = _resolve(file)
    with p.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, [])
        rows = []
        for row in reader:
            if len(rows) >= limit:
                break
            rows.append(row)
    return {"file": file, "columns": header, "rows": rows}


def cmd_query(file: str, filter_s: str, column: str, limit: int) -> dict:
    p = _resolve(file)
    with p.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, [])
        col_idx = header.index(column) if column and column in header else None
        needle = (filter_s or "").lower()
        rows = []
        for row in reader:
            if needle:
                if col_idx is not None:
                    hay = row[col_idx] if col_idx < len(row) else ""
                else:
                    hay = " ".join(row)
                if needle not in hay.lower():
                    continue
            rows.append(row)
            if len(rows) >= limit:
                break
    return {"file": file, "columns": header, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser(description="Generic CSV explorer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p_prev = sub.add_parser("preview")
    p_prev.add_argument("--file", required=True)
    p_prev.add_argument("--limit", type=int, default=100)
    p_q = sub.add_parser("query")
    p_q.add_argument("--file", required=True)
    p_q.add_argument("--filter", default="")
    p_q.add_argument("--column", default="")
    p_q.add_argument("--limit", type=int, default=100)
    # Tolerate a stray --json flag from dashboard callers.
    for sp in (sub.choices["list"], p_prev, p_q):
        sp.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.cmd == "list":
        result = cmd_list()
    elif args.cmd == "preview":
        result = cmd_preview(args.file, args.limit)
    else:
        result = cmd_query(args.file, args.filter, args.column, args.limit)
    json.dump(result, sys.stdout, default=str)
    sys.stdout.write("\\n")


if __name__ == "__main__":
    main()
'''

# Generic, dataset-agnostic dashboard. Lists datasets, renders any CSV as a
# sortable/filterable table with row/column KPIs. Uses the AtriaDash bridge.
_GENERIC_DASHBOARD_HTML = '''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Data</title>
  <link rel="stylesheet" href="__base.css" />
  <style>
    body { font-family: system-ui, sans-serif; margin: 0; padding: 16px; }
    .kpis { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
    .kpi { border: 1px solid rgba(127,127,127,.25); border-radius: 10px; padding: 10px 14px; min-width: 110px; }
    .kpi .label { font-size: 11px; opacity: .6; text-transform: uppercase; letter-spacing: .04em; }
    .kpi .value { font-size: 22px; font-weight: 600; margin-top: 2px; }
    .controls { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }
    select, input { padding: 6px 8px; border: 1px solid rgba(127,127,127,.35); border-radius: 8px; background: transparent; color: inherit; font: inherit; }
    input { flex: 1; min-width: 160px; }
    .table-wrap { overflow: auto; border: 1px solid rgba(127,127,127,.2); border-radius: 10px; max-height: 70vh; }
    table { border-collapse: collapse; width: 100%; font-size: 13px; }
    th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid rgba(127,127,127,.15); white-space: nowrap; }
    th { position: sticky; top: 0; background: rgba(127,127,127,.10); cursor: pointer; user-select: none; }
    th .arrow { opacity: .55; font-size: 10px; }
    .empty { padding: 24px; opacity: .6; text-align: center; }
  </style>
</head>
<body>
  <div class="kpis">
    <div class="kpi"><div class="label">Datasets</div><div class="value" id="kpi-datasets">-</div></div>
    <div class="kpi"><div class="label">Rows</div><div class="value" id="kpi-rows">-</div></div>
    <div class="kpi"><div class="label">Columns</div><div class="value" id="kpi-cols">-</div></div>
  </div>
  <div class="controls">
    <select id="dataset"></select>
    <input id="filter" type="text" placeholder="Filter rows..." />
  </div>
  <div class="table-wrap"><table><thead id="thead"></thead><tbody id="tbody"></tbody></table></div>
  <div class="empty" id="empty" style="display:none">No data yet. Upload files to this module.</div>

  <script src="__bridge.js"></script>
  <script>
  (function () {
    var datasets = [];
    var current = null;          // {file, columns, rows}
    var sortCol = -1, sortDir = 1;
    function $(id){ return document.getElementById(id); }
    function resize(){ try { AtriaDash.resize(document.body.scrollHeight + 24); } catch(e){} }

    function renderTable(){
      var thead = $('thead'), tbody = $('tbody');
      thead.innerHTML = ''; tbody.innerHTML = '';
      if (!current || !current.columns || current.columns.length === 0){
        $('empty').style.display = 'block';
        $('kpi-rows').textContent = '0'; $('kpi-cols').textContent = '0';
        resize(); return;
      }
      $('empty').style.display = 'none';
      var trh = document.createElement('tr');
      current.columns.forEach(function(c, i){
        var th = document.createElement('th');
        th.textContent = c;
        if (i === sortCol){ var a = document.createElement('span'); a.className='arrow'; a.textContent = sortDir>0?' ^':' v'; th.appendChild(a); }
        th.onclick = function(){ if (sortCol===i){ sortDir=-sortDir; } else { sortCol=i; sortDir=1; } applyView(); };
        trh.appendChild(th);
      });
      thead.appendChild(trh);
      var rows = current.rows || [];
      var frag = document.createDocumentFragment();
      rows.forEach(function(r){
        var tr = document.createElement('tr');
        for (var i=0;i<current.columns.length;i++){
          var td = document.createElement('td');
          td.textContent = (r[i]==null?'':r[i]);
          tr.appendChild(td);
        }
        frag.appendChild(tr);
      });
      tbody.appendChild(frag);
      $('kpi-rows').textContent = String(rows.length);
      $('kpi-cols').textContent = String(current.columns.length);
      resize();
    }

    function applyView(){
      if (sortCol >= 0 && current && current.rows){
        current.rows.sort(function(a,b){
          var x=(a[sortCol]==null?'':a[sortCol]), y=(b[sortCol]==null?'':b[sortCol]);
          var nx=parseFloat(x), ny=parseFloat(y);
          if(!isNaN(nx)&&!isNaN(ny)) return (nx-ny)*sortDir;
          return String(x).localeCompare(String(y))*sortDir;
        });
      }
      renderTable();
    }

    function loadDataset(file, filter){
      var args = filter ? ['query','--file',file,'--filter',filter,'--limit','2000']
                        : ['preview','--file',file,'--limit','2000'];
      return AtriaDash.json('data.py', args).then(function(res){
        current = res; sortCol=-1; sortDir=1; applyView();
      }).catch(function(){ current={columns:[],rows:[]}; renderTable(); });
    }

    function refresh(){
      return AtriaDash.json('data.py', ['list','--json']).then(function(res){
        datasets = (res && res.datasets) || [];
        var sel = $('dataset'); var prev = sel.value; sel.innerHTML='';
        datasets.forEach(function(d){
          var o=document.createElement('option'); o.value=d.name; o.textContent=d.name+' ('+d.rows+' rows)'; sel.appendChild(o);
        });
        $('kpi-datasets').textContent = String(datasets.length);
        try { AtriaDash.setBadge(datasets.length || null); } catch(e){}
        if (datasets.length){
          var pick = datasets.some(function(d){return d.name===prev;}) ? prev : datasets[0].name;
          sel.value = pick; return loadDataset(pick, $('filter').value.trim());
        } else { current=null; renderTable(); }
      }).catch(function(){ datasets=[]; $('kpi-datasets').textContent='0'; current=null; renderTable(); });
    }

    var ft;
    $('filter').addEventListener('input', function(){
      clearTimeout(ft); var v = $('filter').value.trim();
      ft = setTimeout(function(){ if ($('dataset').value) loadDataset($('dataset').value, v); }, 250);
    });
    $('dataset').addEventListener('change', function(){ loadDataset($('dataset').value, $('filter').value.trim()); });

    if (window.AtriaDash){
      AtriaDash.ready();
      AtriaDash.onChange(function(){ refresh(); });
      AtriaDash.onVisibility(function(v){ if(v) resize(); });
    }
    refresh();
  })();
  </script>
</body>
</html>
'''


def _data_manifest_json(name: str) -> str:
    title = name.replace("_", " ").replace("-", " ").title()
    payload = {
        "display_name": title,
        "tooltip": f"Explore the {title} datasets",
        "icon": "icon.svg",
        "dashboard": {
            "title": f"{title} · data",
            "default_height": 720,
            "badge_color": "info",
        },
    }
    return json.dumps(payload, indent=2) + "\n"


def _data_skill_md(name: str, summary: str, datasets: Optional[List[dict]]) -> str:
    lines = [
        f"# {name}",
        "",
        summary or "Data module created from uploaded files.",
        "",
        "## When to use",
        f"- When the user asks about the datasets bundled in the {name} module.",
        "",
        "## Data",
        f"CSV datasets live in `<modules>/{name}/data/` (original uploads such as "
        ".xlsx are kept alongside their converted .csv).",
        "",
    ]
    if datasets:
        lines.append("### Datasets")
        for ds in datasets:
            cols = ", ".join(ds.get("columns", [])[:20]) or "(no header)"
            lines.append(f"- `{ds['name']}` - {ds.get('rows', 0)} rows. Columns: {cols}")
        lines.append("")
    lines += [
        "## How to use",
        "Run the data explorer via the bash tool (`<modules>` resolves to the active "
        "modules directory - see the SKILL block header in the system prompt):",
        f"- `python <modules>/{name}/scripts/data.py list` - datasets, row counts, columns",
        f"- `python <modules>/{name}/scripts/data.py preview --file <file.csv> --limit 20`",
        f"- `python <modules>/{name}/scripts/data.py query --file <file.csv> --filter <text> "
        "[--column <col>]`",
        "",
        "The dashboard (`dashboard.html`) lists the datasets and renders any CSV as a "
        "sortable, filterable table. Hand-tailor it (domain KPIs, charts) by editing "
        "`dashboard.html`.",
        "",
    ]
    return "\n".join(lines)


def _scan_datasets(data_dir: Path) -> List[dict]:
    """Read header + row count for each CSV under ``data_dir`` (for SKILL.md)."""
    out: List[dict] = []
    if not data_dir.is_dir():
        return out
    for p in sorted(data_dir.rglob("*.csv")):
        if not p.is_file():
            continue
        try:
            with p.open("r", newline="", encoding="utf-8") as fh:
                reader = csv.reader(fh)
                header = next(reader, [])
                rows = sum(1 for _ in reader)
        except OSError:
            continue
        out.append({"name": p.relative_to(data_dir).as_posix(), "columns": header, "rows": rows})
    return out


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


def _atomic_write(path: Path, content: str) -> None:
    _atomic_write_bytes(path, content.encode("utf-8"))


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

    if template == "data":
        # A warehouse-style, dataset-agnostic module: generic explorer script +
        # dashboard + manifest (so it shows as a tile). Data is added afterwards
        # via write_data_files(); SKILL.md is regenerated then to list datasets.
        _atomic_write(d / SKILL_FILE, _data_skill_md(name, summary, None))
        _atomic_write(d / "scripts" / "data.py", _GENERIC_DATA_SCRIPT)
        _atomic_write(d / "dashboard.html", _GENERIC_DASHBOARD_HTML)
        _atomic_write(d / "icon.svg", _GENERIC_DATA_ICON)
        _atomic_write(d / MANIFEST_FILE, _data_manifest_json(name))
        (d / "data").mkdir(parents=True, exist_ok=True)
        return _read_module(root, name)

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
    """Binary sibling of write_file (for uploaded data: xlsx, csv, images...)."""
    target = _resolve_in_module(root, name, rel_path)
    _atomic_write_bytes(target, data)


# Backwards-compatible alias used by the data-module template builder.
write_bytes = write_file_bytes


def _sanitize_data_relpath(rel: str) -> Optional[str]:
    """Clean an uploaded file's relative path (e.g. from webkitRelativePath).

    Returns a POSIX path with safe segments (no traversal, drive letters, or
    empty parts), or ``None`` if the path is unusable / explicitly traversal.
    The ``data/`` prefix is added by the caller.
    """
    rel = (rel or "").replace("\\", "/")
    out: List[str] = []
    for seg in rel.split("/"):
        seg = seg.strip().strip("\x00")
        if seg in ("", "."):
            continue
        if seg == "..":
            return None  # reject explicit traversal outright
        if ":" in seg:  # strip Windows drive / NTFS stream prefixes
            seg = seg.split(":")[-1]
        if not seg:
            continue
        out.append(seg)
    return "/".join(out) if out else None


def write_data_files(root: Path, name: str, files: List[tuple[str, bytes]]) -> List[str]:
    """Write uploaded files under ``<module>/data/`` (binary-safe, folder-aware).

    Each entry is ``(relative_path, bytes)``. Relative paths are sanitized and
    rooted at ``data/``. Enforces the same depth/count caps as the rest of the
    store and validates containment via :func:`_resolve_in_module`.

    Returns the list of written ``data/...`` relative paths.
    """
    d = _module_dir(root, name)
    if not (d / SKILL_FILE).is_file():
        raise ModuleNotFound(name)

    plan: List[tuple[str, bytes]] = []
    for raw_rel, data in files:
        clean = _sanitize_data_relpath(raw_rel)
        if clean is None:
            raise ValueError(f"invalid data path: {raw_rel!r}")
        full_rel = f"data/{clean}"
        if len(full_rel.split("/")) > _MAX_DEPTH:
            raise ValueError(f"path too deep (max {_MAX_DEPTH} levels): {full_rel}")
        plan.append((full_rel, data))

    existing = len(_walk_files(d))
    if existing + len(plan) > _MAX_FILES:
        raise ValueError(f"module would exceed {_MAX_FILES} files")

    written: List[str] = []
    for full_rel, data in plan:
        write_bytes(root, name, full_rel, data)
        written.append(full_rel)
    return written


def regenerate_data_skill(root: Path, name: str, summary: str = "") -> None:
    """Rewrite SKILL.md for a data module to describe the datasets on disk."""
    d = _module_dir(root, name)
    if not (d / SKILL_FILE).is_file():
        raise ModuleNotFound(name)
    datasets = _scan_datasets(d / "data")
    _atomic_write(d / SKILL_FILE, _data_skill_md(name, summary, datasets or None))


def _data_rel(rel_file: str) -> str:
    """Sanitize a caller-supplied dataset path and root it at ``data/``.

    ``rel_file`` is relative to the module's ``data/`` dir (e.g. ``worldcups.csv``
    or ``sub/dir/x.csv``). Rejects traversal and non-``.csv`` targets.
    """
    clean = _sanitize_data_relpath(rel_file)
    if clean is None:
        raise ValueError(f"invalid dataset path: {rel_file!r}")
    # Tolerate an already-"data/"-prefixed path (e.g. a round-tripped source.file
    # whose value is the read_dataset return) so we never double it into
    # data/data/... — read and write must resolve to the same file.
    while clean.startswith("data/"):
        clean = clean[len("data/"):]
    if not clean or not clean.lower().endswith(".csv"):
        raise ValueError("dataset must be a .csv file under data/")
    return f"data/{clean}"


def _decode_csv_bytes(raw: bytes) -> str:
    """Decode CSV bytes as utf-8 (BOM-aware), falling back to latin-1."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def read_dataset(root: Path, name: str, rel_file: str) -> dict:
    """Read a module CSV dataset into ``{file, columns, rows}``.

    ``columns`` is ``[{"name", "type": "string"}]`` and ``rows`` is a list of
    dicts keyed by column name — the same shape the chat data bubble consumes.
    Rows past :data:`_MAX_DATA_ROWS` are dropped and reported via ``warning``.
    """
    full_rel = _data_rel(rel_file)
    raw = read_file(root, name, full_rel)  # raises FileNotFoundError if missing
    reader = csv.reader(io.StringIO(_decode_csv_bytes(raw)))
    all_rows = list(reader)
    if not all_rows:
        return {"file": full_rel, "columns": [], "rows": []}

    header = [str(c).strip() or f"column_{i + 1}" for i, c in enumerate(all_rows[0])]
    if len(header) > _MAX_DATA_COLS:
        header = header[:_MAX_DATA_COLS]

    warning = None
    body = all_rows[1:]
    if len(body) > _MAX_DATA_ROWS:
        warning = f"Showing first {_MAX_DATA_ROWS} of {len(body)} rows"
        body = body[:_MAX_DATA_ROWS]

    rows: List[dict] = []
    for raw_row in body:
        obj: dict = {}
        for i, col in enumerate(header):
            obj[col] = raw_row[i] if i < len(raw_row) else ""
        rows.append(obj)

    columns = [{"name": h, "type": "string"} for h in header]
    out = {"file": full_rel, "columns": columns, "rows": rows}
    if warning:
        out["warning"] = warning
    return out


def _coerce_header(columns: Any) -> List[str]:
    """Extract a clean, de-duplicated header from columns (list of str or dicts)."""
    header: List[str] = []
    seen: dict[str, int] = {}
    for c in columns or []:
        if isinstance(c, str):
            name = c.strip()
        elif isinstance(c, dict):
            name = str(c.get("name", "")).strip()
        else:
            name = str(c).strip()
        if not name:
            name = "column"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        header.append(name)
    return header


def write_dataset(
    root: Path, name: str, rel_file: str, columns: Any, rows: Any
) -> dict:
    """Write edited rows back to a module CSV dataset (atomic, with one .bak).

    ``columns`` may be a list of names or ``{"name": ...}`` dicts; ``rows`` is a
    list of dicts keyed by column name. The previous file (if any) is copied to
    ``<file>.bak`` before the atomic replace. Raises ``ValueError`` on bad input.
    """
    full_rel = _data_rel(rel_file)
    if not isinstance(rows, list):
        raise ValueError("rows must be a list")
    if len(rows) > _MAX_DATA_ROWS:
        raise ValueError(f"too many rows (max {_MAX_DATA_ROWS})")

    header = _coerce_header(columns)
    if not header and rows and isinstance(rows[0], dict):
        header = _coerce_header(list(rows[0].keys()))
    if not header:
        raise ValueError("no columns to write")
    if len(header) > _MAX_DATA_COLS:
        raise ValueError(f"too many columns (max {_MAX_DATA_COLS})")

    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(header)
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each row must be an object")
        writer.writerow(["" if row.get(col) is None else str(row.get(col)) for col in header])
    data = buf.getvalue().encode("utf-8")
    if len(data) > _MAX_DATA_BYTES:
        raise ValueError(f"dataset exceeds {_MAX_DATA_BYTES} bytes")

    target = _resolve_in_module(root, name, full_rel)  # validates containment
    # Best-effort single backup of the prior version before overwriting.
    if target.is_file():
        try:
            shutil.copy2(target, target.with_name(target.name + ".bak"))
        except OSError:
            pass
    _atomic_write_bytes(target, data)
    return {"written": full_rel, "rows": len(rows), "columns": header}


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
