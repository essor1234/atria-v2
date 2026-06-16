"""Filesystem-backed CRUD for modules.

A module is a folder ``<root>/<name>/`` containing at minimum ``SKILL.md``.
Conventionally it also has ``scripts/*.py`` (runnable tools) and
``templates/*.html`` (dashboards), but any tree layout is allowed — only the
presence of ``SKILL.md`` is enforced.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Literal, Optional

logger = logging.getLogger(__name__)


MODULE_NAME_RE = re.compile(r"[a-z0-9_-]+")
SKILL_FILE = "SKILL.md"
MANIFEST_FILE = "manifest.json"
SCRIPT_FILE = "script.py"  # legacy starter; tolerated but not required

# Recognised badge accents — anything else is ignored at parse time.
_BADGE_COLORS = {"info", "warning", "danger", "success", "neutral"}

# Caps so a giant folder can't blow up the registry or prompt.
_MAX_FILES = 200
_MAX_DEPTH = 4

Template = Literal["blank", "skill", "skill_script", "skill_dashboard", "data"]


class InvalidModuleName(ValueError):
    """Raised when a module name contains disallowed characters."""


class ModuleExists(FileExistsError):
    """Raised when creating a module that already exists."""


class ModuleNotFound(FileNotFoundError):
    """Raised when reading/updating/deleting a module that does not exist."""


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


@dataclass
class Module:
    name: str
    skill_md: str
    dir: Path
    mtime: float
    files: List[str] = field(default_factory=list)
    manifest: Optional[ModuleManifest] = None


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

    return ModuleManifest(
        display_name=_nonempty_str(raw.get("display_name")),
        tooltip=_nonempty_str(raw.get("tooltip")),
        icon=_nonempty_str(raw.get("icon")),
        dashboard=_parse_dashboard(raw.get("dashboard")),
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
    return Module(
        name=name,
        skill_md=skill_path.read_text(encoding="utf-8"),
        dir=d,
        mtime=mtime,
        files=files,
        manifest=_read_manifest(d),
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


def write_bytes(root: Path, name: str, rel_path: str, data: bytes) -> None:
    """Binary sibling of write_file (for uploaded data: xlsx, csv, images...)."""
    target = _resolve_in_module(root, name, rel_path)
    _atomic_write_bytes(target, data)


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
