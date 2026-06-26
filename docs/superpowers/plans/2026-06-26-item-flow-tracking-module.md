# Item Flow Tracking Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `item_flow_tracking` module that tracks laundry orders (one customer per phone number) split into parts ("lots") flowing through a fixed step pipeline over a shared pool of physical resources, with a CLI, embedded SQLite store, on-demand sub-skills, and a dashboard.

**Architecture:** Mirror the existing `modules/warehouse/` module exactly. An embedded SQLite store (`scripts/_db.py`) holds four tables (`orders`, `lots`, `resources`, `lot_events`). A single argparse subcommand CLI (`scripts/flow.py`) is the only entry point; every mutation logs to the `lot_events` ledger. A `dashboard.html` iframe reads JSON from the CLI via the `AtriaDash` bridge. `SKILL.md` + three lazy-loaded `skills/*.md` sub-skills + `manifest.json` wire the module into the host app.

**Tech Stack:** Python 3 stdlib only (`sqlite3`, `argparse`, `csv`, `json`), pytest (subprocess-based), vanilla HTML/JS dashboard using the host `AtriaDash` bridge.

## Global Constraints

- Module lives at `modules/item_flow_tracking/` (repo-root `modules/` dir, source-tracked like `warehouse`).
- Python stdlib only — no new dependencies; no `requirements.txt` needed.
- Code style: line length 100, type hints on public functions, Google-style docstrings (matches `inventory.py`).
- DB path override env var: **`ATRIA_FLOW_DB`** (tests point this at a temp file).
- Fixed step keys (ordered): `nhan_hang`, `giat`, `say`, `gap`, `kiem_dem`, `giao_hang`, `done`.
- Resource kinds + default pool: `bin`×15, `washer`×10, `dryer`×10, `fold`×1, `count`×1.
- Step is auto-inferred from the resource a lot moves into: `washer→giat`, `dryer→say`, `fold→gap`, `count→kiem_dem`; moving into a `bin` keeps the current step.
- Every CLI command supports `--json` for machine-readable output.
- Commits in this project: **omit** the `Co-Authored-By: Claude` trailer.
- **Test cadence (project preference):** do NOT run pytest per-task. Write each task's test code and implementation, commit, and run the full suite **once** in the final verification task. The per-task "run test" steps below are written for completeness but are batched into Task 10.

---

### Task 1: Embedded SQLite store (`_db.py`)

**Files:**
- Create: `modules/item_flow_tracking/scripts/_db.py`
- Test: `tests/test_item_flow_tracking.py` (created here, extended by later tasks)

**Interfaces:**
- Produces (consumed by every later task):
  - Constants: `STEPS: list[str]`, `STEP_LABELS: dict[str,str]`, `RESOURCE_KIND_TO_STEP: dict[str,str]`, `RESOURCE_KIND_LABELS: dict[str,str]`, `DEFAULT_POOL: dict[str,int]`.
  - `now() -> str`, `db_path() -> Path`, `connect() -> sqlite3.Connection`, `connect_readonly() -> sqlite3.Connection`.
  - `seed_resources(conn) -> int`.
  - `log_event(conn, lot_id, order_id, event_type, *, from_step=None, to_step=None, from_resource=None, to_resource=None, item_count=None, notes=None, commit=True) -> None`.
  - `order_dict(row) -> dict`, `lot_dict(row) -> dict`, `resource_dict(row) -> dict`.

- [ ] **Step 1: Write `_db.py`**

```python
#!/usr/bin/env python
"""SQLite storage layer for the item_flow_tracking module.

A single embedded database file holds four tables:

- ``orders``     — one row per customer order (identified by phone number).
- ``lots``       — parts an order is split into at intake; the unit of tracking.
- ``resources``  — the fixed pool of physical bins/machines/areas, reused
  across orders. Capacity is one lot each; occupancy is derived from
  ``lots.current_resource``.
- ``lot_events`` — append-only audit ledger; every move/redo/count/deliver
  writes a row so a part's history can be reconstructed.

The DB path defaults to ``../data/flow.db`` but can be overridden with the
``ATRIA_FLOW_DB`` environment variable (tests point this at a temp file). The
schema is created on first connect and the default resource pool is seeded so
the module is usable out of the box.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DEFAULT_DB = DATA_DIR / "flow.db"

SCHEMA_VERSION = 1

# Fixed processing pipeline, in order. ``done`` is the terminal state.
STEPS = ["nhan_hang", "giat", "say", "gap", "kiem_dem", "giao_hang", "done"]

STEP_LABELS = {
    "nhan_hang": "Nhận hàng",
    "giat": "Giặt",
    "say": "Sấy",
    "gap": "Gấp",
    "kiem_dem": "Kiểm đếm",
    "giao_hang": "Giao hàng",
    "done": "Xong",
}

# Moving a lot into a machine/area implies the step it is now at. A ``bin`` is
# just a holding location, so it leaves the step unchanged.
RESOURCE_KIND_TO_STEP = {
    "washer": "giat",
    "dryer": "say",
    "fold": "gap",
    "count": "kiem_dem",
}

RESOURCE_KIND_LABELS = {
    "bin": "Bin",
    "washer": "Máy giặt",
    "dryer": "Máy sấy",
    "fold": "Khu gấp",
    "count": "Khu đếm",
}

# Default fixed pool seeded into a fresh DB.
DEFAULT_POOL = {"bin": 15, "washer": 10, "dryer": 10, "fold": 1, "count": 1}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    order_id       TEXT PRIMARY KEY,
    customer_phone TEXT NOT NULL,
    customer_name  TEXT,
    status         TEXT NOT NULL DEFAULT 'active',
    total_items    INTEGER,
    note           TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lots (
    lot_id           TEXT PRIMARY KEY,
    order_id         TEXT NOT NULL,
    label            TEXT NOT NULL,
    step             TEXT NOT NULL,
    current_resource TEXT,
    item_count       INTEGER,
    is_redo          INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'active',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resources (
    resource_id TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    label       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'free'
);

CREATE TABLE IF NOT EXISTS lot_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id        TEXT NOT NULL,
    order_id      TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    from_step     TEXT,
    to_step       TEXT,
    from_resource TEXT,
    to_resource   TEXT,
    item_count    INTEGER,
    timestamp     TEXT NOT NULL,
    notes         TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_order ON lot_events(order_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_lot   ON lot_events(lot_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_lots_order   ON lots(order_id);
"""


def now() -> str:
    """Return the current UTC time as an ISO-8601 ``Z`` timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def db_path() -> Path:
    """Resolve the active DB file (env override wins; else the module default)."""
    override = os.environ.get("ATRIA_FLOW_DB")
    return Path(override) if override else DEFAULT_DB


def connect() -> sqlite3.Connection:
    """Open (creating + bootstrapping if needed) the flow DB."""
    path = db_path()
    fresh = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    if int(conn.execute("PRAGMA user_version").fetchone()[0]) < SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    if fresh and conn.execute("SELECT COUNT(*) FROM resources").fetchone()[0] == 0:
        seed_resources(conn)
    conn.commit()
    return conn


def connect_readonly() -> sqlite3.Connection:
    """Open the DB in read-only mode (used by guarded read commands)."""
    path = db_path()
    if not path.exists():
        connect().close()  # bootstrap the file so a read-only open succeeds
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def seed_resources(conn: sqlite3.Connection) -> int:
    """Populate the fixed resource pool. Safe to call repeatedly (idempotent)."""
    inserted = 0
    for kind, count in DEFAULT_POOL.items():
        for i in range(1, count + 1):
            rid = f"{kind}-{i}"
            label = f"{RESOURCE_KIND_LABELS[kind]} {i}"
            cur = conn.execute(
                "INSERT OR IGNORE INTO resources (resource_id, kind, label, status) "
                "VALUES (?, ?, ?, 'free')",
                (rid, kind, label),
            )
            inserted += cur.rowcount
    conn.commit()
    return inserted


def log_event(
    conn: sqlite3.Connection,
    lot_id: str,
    order_id: str,
    event_type: str,
    *,
    from_step: str | None = None,
    to_step: str | None = None,
    from_resource: str | None = None,
    to_resource: str | None = None,
    item_count: int | None = None,
    notes: str | None = None,
    commit: bool = True,
) -> None:
    """Append a row to the audit ledger. Caller owns the transaction by default."""
    conn.execute(
        "INSERT INTO lot_events "
        "(lot_id, order_id, event_type, from_step, to_step, from_resource, "
        " to_resource, item_count, timestamp, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (lot_id, order_id, event_type, from_step, to_step, from_resource,
         to_resource, item_count, now(), notes),
    )
    if commit:
        conn.commit()


def order_dict(row: sqlite3.Row) -> dict:
    """Normalise an ``orders`` row into the JSON shape the UI/agent expect."""
    return {
        "order_id": row["order_id"],
        "customer_phone": row["customer_phone"],
        "customer_name": row["customer_name"] or "",
        "status": row["status"],
        "total_items": row["total_items"],
        "note": row["note"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def lot_dict(row: sqlite3.Row) -> dict:
    """Normalise a ``lots`` row into JSON shape."""
    return {
        "lot_id": row["lot_id"],
        "order_id": row["order_id"],
        "label": row["label"],
        "step": row["step"],
        "step_label": STEP_LABELS.get(row["step"], row["step"]),
        "current_resource": row["current_resource"],
        "item_count": row["item_count"],
        "is_redo": bool(row["is_redo"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def resource_dict(row: sqlite3.Row) -> dict:
    """Normalise a ``resources`` row into JSON shape."""
    return {
        "resource_id": row["resource_id"],
        "kind": row["kind"],
        "label": row["label"],
        "status": row["status"],
    }
```

- [ ] **Step 2: Write the schema/seed test in `tests/test_item_flow_tracking.py`**

```python
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "modules" / "item_flow_tracking" / "scripts" / "flow.py"


@pytest.fixture()
def env(tmp_path):
    """Point the flow CLI at an isolated, freshly-seeded temp DB."""
    e = os.environ.copy()
    e["ATRIA_FLOW_DB"] = str(tmp_path / "flow.db")
    return e


def run(env, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, check=False, env=env,
    )


def run_json(env, *args: str) -> dict:
    r = run(env, *args, "--json")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# ── schema + seeded resource pool ────────────────────────────────────────────


def test_fresh_db_seeds_resource_pool(env):
    payload = run_json(env, "resource", "list")
    kinds = {}
    for r in payload["resources"]:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    assert kinds == {"bin": 15, "washer": 10, "dryer": 10, "fold": 1, "count": 1}
    assert all(r["status"] == "free" for r in payload["resources"])
```

- [ ] **Step 3: Commit**

```bash
git add modules/item_flow_tracking/scripts/_db.py tests/test_item_flow_tracking.py
git commit -m "feat(item-flow): add SQLite store, schema, and resource pool seed"
```

> Note: the schema/seed test depends on `flow.py` (`resource list`), built in Task 6. It will pass once the full suite runs in Task 10. Do not run pytest yet (see Global Constraints).

---

### Task 2: CLI scaffold + create/list/show orders

**Files:**
- Create: `modules/item_flow_tracking/scripts/flow.py`
- Test: `tests/test_item_flow_tracking.py` (extend)

**Interfaces:**
- Consumes from Task 1: `_db.connect`, `_db.now`, `_db.order_dict`, `_db.lot_dict`, `_db.log_event`.
- Produces:
  - Module helpers: `_err(msg)`, `_emit(obj)`, `_find_order(conn, order_id)`, `_find_lot(conn, lot_id)`, `_find_resource(conn, rid)`, `_gen_order_id(conn) -> str`.
  - Commands: `order new`, `order list`, `order show`.
  - `_build_parser()` and `main(argv)`; `python flow.py order new --phone P --bins N [--name X] [--note T]` prints `{"order": {...}, "lots": [...]}` with `--json`.

- [ ] **Step 1: Write `flow.py` scaffold + order commands**

```python
#!/usr/bin/env python
"""Item flow tracking CLI for the item_flow_tracking module.

Tracks laundry orders (one customer per phone number) split into parts
("lots") that flow through a fixed step pipeline over a shared pool of
physical resources. The live store is a single ``flow.db`` file (see
``_db.py``); every mutation is recorded in the append-only ``lot_events``
ledger.

Subcommands:
  order ..... new, list, show, deliver, cancel
  lot ....... move, count, redo, deliver
  customer .. history
  resource .. list, set, add, retire
  data ...... dashboard, export, reset
"""

from __future__ import annotations

import argparse
import csv
import io
import json as _json
import sqlite3
import sys

import _db


# ── small output helpers ────────────────────────────────────────────────────


def _err(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)


def _emit(obj: object) -> None:
    print(_json.dumps(obj, ensure_ascii=False))


def _find_order(conn: sqlite3.Connection, order_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()


def _find_lot(conn: sqlite3.Connection, lot_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM lots WHERE lot_id = ?", (lot_id,)).fetchone()


def _find_resource(conn: sqlite3.Connection, rid: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM resources WHERE resource_id = ?", (rid,)).fetchone()


def _order_lots(conn: sqlite3.Connection, order_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM lots WHERE order_id = ? ORDER BY label", (order_id,)
    ).fetchall()
    return [_db.lot_dict(r) for r in rows]


def _gen_order_id(conn: sqlite3.Connection) -> str:
    """Generate the next per-day order id: ``DH-YYYYMMDD-NNN``."""
    day = _db.now()[:10].replace("-", "")
    prefix = f"DH-{day}"
    n = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE order_id LIKE ?", (prefix + "-%",)
    ).fetchone()[0]
    return f"{prefix}-{n + 1:03d}"


# ── order commands ──────────────────────────────────────────────────────────


def cmd_order_new(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    if args.bins < 1:
        _err("--bins must be >= 1")
        return 1
    free_bins = conn.execute(
        "SELECT * FROM resources WHERE kind = 'bin' AND status = 'free' ORDER BY rowid"
    ).fetchall()
    if len(free_bins) < args.bins:
        _err(f"not enough free bins: need {args.bins}, have {len(free_bins)}")
        return 1

    ts = _db.now()
    order_id = _gen_order_id(conn)
    conn.execute(
        "INSERT INTO orders (order_id, customer_phone, customer_name, status, "
        "total_items, note, created_at, updated_at) "
        "VALUES (?, ?, ?, 'active', NULL, ?, ?, ?)",
        (order_id, args.phone, args.name, args.note, ts, ts),
    )
    for i in range(1, args.bins + 1):
        bin_row = free_bins[i - 1]
        lot_id = f"{order_id}-P{i}"
        conn.execute(
            "INSERT INTO lots (lot_id, order_id, label, step, current_resource, "
            "item_count, is_redo, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'nhan_hang', ?, NULL, 0, 'active', ?, ?)",
            (lot_id, order_id, f"P{i}", bin_row["resource_id"], ts, ts),
        )
        conn.execute(
            "UPDATE resources SET status = 'busy' WHERE resource_id = ?",
            (bin_row["resource_id"],),
        )
        _db.log_event(conn, lot_id, order_id, "intake",
                      to_step="nhan_hang", to_resource=bin_row["resource_id"], commit=False)
    conn.commit()

    order = _db.order_dict(_find_order(conn, order_id))
    lots = _order_lots(conn, order_id)
    if args.json:
        _emit({"order": order, "lots": lots})
    else:
        print(f"Created {order_id} for {args.phone} — {args.bins} parts "
              f"({', '.join(lot['current_resource'] for lot in lots)})")
    return 0


def cmd_order_list(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    where: list[str] = []
    params: list[object] = []
    if args.status:
        where.append("status = ?")
        params.append(args.status)
    if args.phone:
        where.append("customer_phone LIKE ?")
        params.append(f"%{args.phone}%")
    sql = "SELECT * FROM orders"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC"

    orders = []
    for r in conn.execute(sql, params).fetchall():
        o = _db.order_dict(r)
        o["lots"] = _order_lots(conn, r["order_id"])
        orders.append(o)
    if args.json:
        _emit({"orders": orders})
    else:
        for o in orders:
            print(f"{o['order_id']}  {o['customer_phone']:<12}  {o['status']:<9}  "
                  f"{len(o['lots'])} parts  total={o['total_items']}")
    return 0


def cmd_order_show(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    row = _find_order(conn, args.order)
    if not row:
        _err(f"order not found: {args.order}")
        return 1
    order = _db.order_dict(row)
    order["lots"] = _order_lots(conn, args.order)
    if args.json:
        _emit({"order": order})
    else:
        print(f"{order['order_id']}  {order['customer_phone']}  {order['status']}")
        for lot in order["lots"]:
            print(f"  {lot['label']}  {lot['step_label']:<12}  "
                  f"@ {lot['current_resource'] or '-'}  count={lot['item_count']}")
    return 0


# ── parser + dispatch ───────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Item flow tracking CLI")
    sub = parser.add_subparsers(dest="group", required=True)

    order = sub.add_parser("order", help="order operations").add_subparsers(
        dest="cmd", required=True)

    p = order.add_parser("new", help="create an order split into N bins/parts")
    p.add_argument("--phone", required=True)
    p.add_argument("--name", default=None)
    p.add_argument("--bins", type=int, required=True)
    p.add_argument("--note", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_order_new)

    p = order.add_parser("list", help="list orders")
    p.add_argument("--status", choices=["active", "done", "cancelled"], default=None)
    p.add_argument("--phone", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_order_list)

    p = order.add_parser("show", help="show one order and its parts")
    p.add_argument("--order", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_order_show)

    return parser


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv[1:])
    conn = _db.connect()
    try:
        return args.fn(conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 2: Add order tests to `tests/test_item_flow_tracking.py`**

```python
# ── orders + lots at intake ──────────────────────────────────────────────────


def test_order_new_creates_lots_and_assigns_bins(env):
    payload = run_json(env, "order", "new", "--phone", "0901234567",
                       "--name", "Khach A", "--bins", "3")
    order = payload["order"]
    lots = payload["lots"]
    assert order["order_id"].startswith("DH-")
    assert order["customer_phone"] == "0901234567"
    assert order["status"] == "active"
    assert len(lots) == 3
    assert {lot["label"] for lot in lots} == {"P1", "P2", "P3"}
    assert all(lot["step"] == "nhan_hang" for lot in lots)
    bins = [lot["current_resource"] for lot in lots]
    assert all(b.startswith("bin-") for b in bins)
    assert len(set(bins)) == 3  # distinct bins

    res = run_json(env, "resource", "list", "--status", "busy")
    busy = {r["resource_id"] for r in res["resources"]}
    assert set(bins) <= busy


def test_order_new_rejects_when_not_enough_bins(env):
    r = run(env, "order", "new", "--phone", "0900000000", "--bins", "16", "--json")
    assert r.returncode != 0
    assert "free bins" in r.stderr


def test_order_ids_increment_per_day(env):
    a = run_json(env, "order", "new", "--phone", "0900000001", "--bins", "1")["order"]["order_id"]
    b = run_json(env, "order", "new", "--phone", "0900000002", "--bins", "1")["order"]["order_id"]
    assert a != b
    assert a.endswith("-001") and b.endswith("-002")


def test_order_show_lists_parts(env):
    new = run_json(env, "order", "new", "--phone", "0901112223", "--bins", "2")
    oid = new["order"]["order_id"]
    shown = run_json(env, "order", "show", "--order", oid)
    assert shown["order"]["order_id"] == oid
    assert len(shown["order"]["lots"]) == 2
```

- [ ] **Step 3: Commit**

```bash
git add modules/item_flow_tracking/scripts/flow.py tests/test_item_flow_tracking.py
git commit -m "feat(item-flow): order create/list/show CLI with bin assignment"
```

---

### Task 3: Move a lot between resources (`lot move`)

**Files:**
- Modify: `modules/item_flow_tracking/scripts/flow.py` (add `cmd_lot_move`, register `lot` subparser)
- Test: `tests/test_item_flow_tracking.py` (extend)

**Interfaces:**
- Consumes: `_find_lot`, `_find_resource`, `_db.RESOURCE_KIND_TO_STEP`, `_db.log_event`.
- Produces: `lot move --lot <id> --to <resource_id> [--force] [--json]` → frees the old resource, occupies the target, infers the new step from the target kind (bin keeps step), logs a `move` event, prints `{"lot": {...}}`.

- [ ] **Step 1: Add `cmd_lot_move` to `flow.py`** (place after `cmd_order_show`)

```python
def cmd_lot_move(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    lot = _find_lot(conn, args.lot)
    if not lot:
        _err(f"lot not found: {args.lot}")
        return 1
    if lot["status"] != "active":
        _err(f"lot is not active: {args.lot} ({lot['status']})")
        return 1
    target = _find_resource(conn, args.to)
    if not target:
        _err(f"resource not found: {args.to}")
        return 1

    old = lot["current_resource"]
    if target["status"] == "busy" and target["resource_id"] != old and not args.force:
        _err(f"resource busy: {args.to} (use --force to override)")
        return 1

    new_step = _db.RESOURCE_KIND_TO_STEP.get(target["kind"], lot["step"])
    ts = _db.now()
    if old and old != target["resource_id"]:
        conn.execute("UPDATE resources SET status = 'free' WHERE resource_id = ?", (old,))
    conn.execute("UPDATE resources SET status = 'busy' WHERE resource_id = ?",
                 (target["resource_id"],))
    conn.execute(
        "UPDATE lots SET step = ?, current_resource = ?, updated_at = ? WHERE lot_id = ?",
        (new_step, target["resource_id"], ts, args.lot),
    )
    _db.log_event(conn, args.lot, lot["order_id"], "move",
                  from_step=lot["step"], to_step=new_step,
                  from_resource=old, to_resource=target["resource_id"], commit=False)
    conn.commit()

    if args.json:
        _emit({"lot": _db.lot_dict(_find_lot(conn, args.lot))})
    else:
        print(f"{args.lot} → {target['label']} ({_db.STEP_LABELS.get(new_step, new_step)})")
    return 0
```

- [ ] **Step 2: Register the `lot` subparser group in `_build_parser`** (before `return parser`)

```python
    lot = sub.add_parser("lot", help="lot (part) operations").add_subparsers(
        dest="cmd", required=True)

    p = lot.add_parser("move", help="move a lot into a resource (step inferred)")
    p.add_argument("--lot", required=True)
    p.add_argument("--to", required=True, help="target resource_id, e.g. washer-3 or bin-5")
    p.add_argument("--force", action="store_true", help="override a busy target")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_lot_move)
```

- [ ] **Step 3: Add move tests**

```python
# ── moving lots between resources ────────────────────────────────────────────


def _first_lot(env, phone="0905550000", bins=1):
    payload = run_json(env, "order", "new", "--phone", phone, "--bins", str(bins))
    return payload["lots"][0]


def test_move_into_washer_infers_giat_step(env):
    lot = _first_lot(env)
    moved = run_json(env, "lot", "move", "--lot", lot["lot_id"], "--to", "washer-1")
    assert moved["lot"]["step"] == "giat"
    assert moved["lot"]["current_resource"] == "washer-1"
    # the original bin is freed, the washer is now busy
    res = {r["resource_id"]: r["status"] for r in run_json(env, "resource", "list")["resources"]}
    assert res["washer-1"] == "busy"
    assert res[lot["current_resource"]] == "free"


def test_move_into_bin_keeps_step(env):
    lot = _first_lot(env, phone="0905550001")
    run_json(env, "lot", "move", "--lot", lot["lot_id"], "--to", "washer-2")
    moved = run_json(env, "lot", "move", "--lot", lot["lot_id"], "--to", "bin-2")
    assert moved["lot"]["step"] == "giat"  # bin does not change the step
    assert moved["lot"]["current_resource"] == "bin-2"


def test_move_rejects_busy_target_without_force(env):
    a = _first_lot(env, phone="0905550002")
    b = _first_lot(env, phone="0905550003")
    run_json(env, "lot", "move", "--lot", a["lot_id"], "--to", "washer-5")
    r = run(env, "lot", "move", "--lot", b["lot_id"], "--to", "washer-5", "--json")
    assert r.returncode != 0
    assert "busy" in r.stderr
    ok = run(env, "lot", "move", "--lot", b["lot_id"], "--to", "washer-5", "--force", "--json")
    assert ok.returncode == 0
```

- [ ] **Step 4: Commit**

```bash
git add modules/item_flow_tracking/scripts/flow.py tests/test_item_flow_tracking.py
git commit -m "feat(item-flow): lot move with step inference and resource locking"
```

---

### Task 4: Count + redo (`lot count`, `lot redo`)

**Files:**
- Modify: `modules/item_flow_tracking/scripts/flow.py`
- Test: `tests/test_item_flow_tracking.py` (extend)

**Interfaces:**
- Produces:
  - `lot count --lot <id> --items <n> [--json]` → sets the lot's `item_count`, recomputes the order's `total_items` (sum of counted lots), logs a `count` event.
  - `lot redo --lot <id> [--to <step>] [--notes <s>] [--json]` → sets `is_redo=1`, moves the lot's step back (default `giat`), logs a `redo` event.

- [ ] **Step 1: Add `cmd_lot_count` and `cmd_lot_redo` to `flow.py`**

```python
def _recompute_order_total(conn: sqlite3.Connection, order_id: str) -> int | None:
    row = conn.execute(
        "SELECT COUNT(item_count) AS counted, SUM(item_count) AS total "
        "FROM lots WHERE order_id = ?",
        (order_id,),
    ).fetchone()
    total = row["total"] if row["counted"] else None
    conn.execute(
        "UPDATE orders SET total_items = ?, updated_at = ? WHERE order_id = ?",
        (total, _db.now(), order_id),
    )
    return total


def cmd_lot_count(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    lot = _find_lot(conn, args.lot)
    if not lot:
        _err(f"lot not found: {args.lot}")
        return 1
    if args.items < 0:
        _err("--items must be >= 0")
        return 1
    ts = _db.now()
    conn.execute(
        "UPDATE lots SET item_count = ?, updated_at = ? WHERE lot_id = ?",
        (args.items, ts, args.lot),
    )
    _recompute_order_total(conn, lot["order_id"])
    _db.log_event(conn, args.lot, lot["order_id"], "count",
                  item_count=args.items, commit=False)
    conn.commit()

    if args.json:
        _emit({
            "lot": _db.lot_dict(_find_lot(conn, args.lot)),
            "order": _db.order_dict(_find_order(conn, lot["order_id"])),
        })
    else:
        order = _find_order(conn, lot["order_id"])
        print(f"{args.lot} counted {args.items} — order total = {order['total_items']}")
    return 0


def cmd_lot_redo(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    lot = _find_lot(conn, args.lot)
    if not lot:
        _err(f"lot not found: {args.lot}")
        return 1
    target = args.to or "giat"
    if target not in _db.STEPS:
        _err(f"unknown step: {target}")
        return 1
    ts = _db.now()
    conn.execute(
        "UPDATE lots SET step = ?, is_redo = 1, updated_at = ? WHERE lot_id = ?",
        (target, ts, args.lot),
    )
    _db.log_event(conn, args.lot, lot["order_id"], "redo",
                  from_step=lot["step"], to_step=target, notes=args.notes, commit=False)
    conn.commit()

    if args.json:
        _emit({"lot": _db.lot_dict(_find_lot(conn, args.lot))})
    else:
        print(f"{args.lot} sent back to {_db.STEP_LABELS.get(target, target)} (redo)")
    return 0
```

- [ ] **Step 2: Register `count` and `redo` under the `lot` group** (after the `move` subparser)

```python
    p = lot.add_parser("count", help="record counted item quantity for a lot")
    p.add_argument("--lot", required=True)
    p.add_argument("--items", type=int, required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_lot_count)

    p = lot.add_parser("redo", help="send a lot back to an earlier step (default giat)")
    p.add_argument("--lot", required=True)
    p.add_argument("--to", default=None, choices=_db.STEPS)
    p.add_argument("--notes", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_lot_redo)
```

- [ ] **Step 3: Add count/redo tests**

```python
# ── counting + redo ──────────────────────────────────────────────────────────


def test_count_sums_to_order_total(env):
    new = run_json(env, "order", "new", "--phone", "0906660000", "--bins", "2")
    oid = new["order"]["order_id"]
    p1, p2 = new["lots"][0]["lot_id"], new["lots"][1]["lot_id"]

    first = run_json(env, "lot", "count", "--lot", p1, "--items", "10")
    assert first["order"]["total_items"] == 10
    second = run_json(env, "lot", "count", "--lot", p2, "--items", "15")
    assert second["order"]["total_items"] == 25


def test_redo_sets_flag_and_moves_step_back(env):
    lot = _first_lot(env, phone="0906661111")
    run_json(env, "lot", "move", "--lot", lot["lot_id"], "--to", "dryer-1")  # step say
    redone = run_json(env, "lot", "redo", "--lot", lot["lot_id"], "--notes", "lem ban")
    assert redone["lot"]["is_redo"] is True
    assert redone["lot"]["step"] == "giat"  # default redo target
```

- [ ] **Step 4: Commit**

```bash
git add modules/item_flow_tracking/scripts/flow.py tests/test_item_flow_tracking.py
git commit -m "feat(item-flow): lot count (order total) and redo transitions"
```

---

### Task 5: Deliver + cancel (`order deliver`, `lot deliver`, `order cancel`)

**Files:**
- Modify: `modules/item_flow_tracking/scripts/flow.py`
- Test: `tests/test_item_flow_tracking.py` (extend)

**Interfaces:**
- Produces:
  - `lot deliver --lot <id> [--json]` → marks the lot `done`, frees its resource; if all of the order's lots are `done`, the order becomes `done`.
  - `order deliver --order <id> [--json]` → requires every lot counted (`item_count` not null); marks all lots `done`, frees resources, order `done`.
  - `order cancel --order <id> [--reason <s>] [--json]` → order `cancelled`, all lots `cancelled`, resources freed.

- [ ] **Step 1: Add `cmd_lot_deliver`, `cmd_order_deliver`, `cmd_order_cancel` to `flow.py`**

```python
def _free_lot_resource(conn: sqlite3.Connection, lot: sqlite3.Row) -> None:
    if lot["current_resource"]:
        conn.execute("UPDATE resources SET status = 'free' WHERE resource_id = ?",
                     (lot["current_resource"],))


def _maybe_complete_order(conn: sqlite3.Connection, order_id: str) -> None:
    row = conn.execute(
        "SELECT COUNT(*) AS n, SUM(status = 'done') AS done FROM lots WHERE order_id = ?",
        (order_id,),
    ).fetchone()
    if row["n"] and row["done"] == row["n"]:
        conn.execute("UPDATE orders SET status = 'done', updated_at = ? WHERE order_id = ?",
                     (_db.now(), order_id))


def cmd_lot_deliver(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    lot = _find_lot(conn, args.lot)
    if not lot:
        _err(f"lot not found: {args.lot}")
        return 1
    ts = _db.now()
    _free_lot_resource(conn, lot)
    conn.execute(
        "UPDATE lots SET step = 'done', status = 'done', current_resource = NULL, "
        "updated_at = ? WHERE lot_id = ?",
        (ts, args.lot),
    )
    _db.log_event(conn, args.lot, lot["order_id"], "deliver",
                  from_step=lot["step"], to_step="done",
                  from_resource=lot["current_resource"], commit=False)
    _maybe_complete_order(conn, lot["order_id"])
    conn.commit()
    if args.json:
        _emit({"order": _db.order_dict(_find_order(conn, lot["order_id"]))})
    else:
        print(f"{args.lot} delivered")
    return 0


def cmd_order_deliver(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    order = _find_order(conn, args.order)
    if not order:
        _err(f"order not found: {args.order}")
        return 1
    lots = conn.execute("SELECT * FROM lots WHERE order_id = ?", (args.order,)).fetchall()
    uncounted = [lot["lot_id"] for lot in lots if lot["item_count"] is None]
    if uncounted:
        _err(f"cannot deliver — not all parts counted: {', '.join(uncounted)}")
        return 1
    ts = _db.now()
    for lot in lots:
        _free_lot_resource(conn, lot)
        conn.execute(
            "UPDATE lots SET step = 'done', status = 'done', current_resource = NULL, "
            "updated_at = ? WHERE lot_id = ?",
            (ts, lot["lot_id"]),
        )
        _db.log_event(conn, lot["lot_id"], args.order, "deliver",
                      from_step=lot["step"], to_step="done",
                      from_resource=lot["current_resource"], commit=False)
    conn.execute("UPDATE orders SET status = 'done', updated_at = ? WHERE order_id = ?",
                 (ts, args.order))
    conn.commit()
    if args.json:
        _emit({"order": _db.order_dict(_find_order(conn, args.order))})
    else:
        print(f"{args.order} delivered ({len(lots)} parts)")
    return 0


def cmd_order_cancel(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    order = _find_order(conn, args.order)
    if not order:
        _err(f"order not found: {args.order}")
        return 1
    lots = conn.execute("SELECT * FROM lots WHERE order_id = ?", (args.order,)).fetchall()
    ts = _db.now()
    for lot in lots:
        _free_lot_resource(conn, lot)
        conn.execute(
            "UPDATE lots SET status = 'cancelled', current_resource = NULL, "
            "updated_at = ? WHERE lot_id = ?",
            (ts, lot["lot_id"]),
        )
        _db.log_event(conn, lot["lot_id"], args.order, "cancel", notes=args.reason, commit=False)
    conn.execute("UPDATE orders SET status = 'cancelled', updated_at = ? WHERE order_id = ?",
                 (ts, args.order))
    conn.commit()
    if args.json:
        _emit({"order": _db.order_dict(_find_order(conn, args.order))})
    else:
        print(f"{args.order} cancelled")
    return 0
```

- [ ] **Step 2: Register `order deliver`, `order cancel`, `lot deliver`**

Under the `order` group (after `show`):

```python
    p = order.add_parser("deliver", help="deliver a whole order (all parts must be counted)")
    p.add_argument("--order", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_order_deliver)

    p = order.add_parser("cancel", help="cancel an order and free its resources")
    p.add_argument("--order", required=True)
    p.add_argument("--reason", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_order_cancel)
```

Under the `lot` group (after `redo`):

```python
    p = lot.add_parser("deliver", help="mark a single lot delivered/done")
    p.add_argument("--lot", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_lot_deliver)
```

- [ ] **Step 3: Add deliver/cancel tests**

```python
# ── deliver + cancel ─────────────────────────────────────────────────────────


def test_order_deliver_requires_all_counted(env):
    new = run_json(env, "order", "new", "--phone", "0907770000", "--bins", "2")
    oid = new["order"]["order_id"]
    run_json(env, "lot", "count", "--lot", new["lots"][0]["lot_id"], "--items", "5")
    blocked = run(env, "order", "deliver", "--order", oid, "--json")
    assert blocked.returncode != 0
    assert "counted" in blocked.stderr

    run_json(env, "lot", "count", "--lot", new["lots"][1]["lot_id"], "--items", "7")
    ok = run_json(env, "order", "deliver", "--order", oid)
    assert ok["order"]["status"] == "done"


def test_lot_deliver_completes_order_when_last(env):
    new = run_json(env, "order", "new", "--phone", "0907771111", "--bins", "2")
    oid = new["order"]["order_id"]
    run_json(env, "lot", "deliver", "--lot", new["lots"][0]["lot_id"])
    mid = run_json(env, "order", "show", "--order", oid)
    assert mid["order"]["status"] == "active"
    last = run_json(env, "lot", "deliver", "--lot", new["lots"][1]["lot_id"])
    assert last["order"]["status"] == "done"


def test_cancel_frees_resources(env):
    new = run_json(env, "order", "new", "--phone", "0907772222", "--bins", "2")
    oid = new["order"]["order_id"]
    bins = [lot["current_resource"] for lot in new["lots"]]
    run_json(env, "order", "cancel", "--order", oid, "--reason", "khach huy")
    res = {r["resource_id"]: r["status"] for r in run_json(env, "resource", "list")["resources"]}
    assert all(res[b] == "free" for b in bins)
    assert run_json(env, "order", "show", "--order", oid)["order"]["status"] == "cancelled"
```

- [ ] **Step 4: Commit**

```bash
git add modules/item_flow_tracking/scripts/flow.py tests/test_item_flow_tracking.py
git commit -m "feat(item-flow): order/lot deliver and order cancel"
```

---

### Task 6: Read commands — customer history, resources, dashboard JSON

**Files:**
- Modify: `modules/item_flow_tracking/scripts/flow.py`
- Test: `tests/test_item_flow_tracking.py` (extend)

**Interfaces:**
- Produces:
  - `customer history --phone <p> [--json]` → all orders for a phone, newest first, each with its lots.
  - `resource list [--kind <k>] [--status <s>] [--json]` → resources with an `occupant` (`{lot_id, order_id}` or null).
  - `resource set --resource <id> --status <free|busy|maintenance> [--json]`.
  - `dashboard [--json]` → `{resources: [...with occupant], orders: [active w/ lots], steps: {step: [lots]}}`.

- [ ] **Step 1: Add the read commands to `flow.py`**

```python
def _resource_occupant(conn: sqlite3.Connection, rid: str) -> dict | None:
    row = conn.execute(
        "SELECT lot_id, order_id FROM lots WHERE current_resource = ? AND status = 'active'",
        (rid,),
    ).fetchone()
    return {"lot_id": row["lot_id"], "order_id": row["order_id"]} if row else None


def cmd_customer_history(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    rows = conn.execute(
        "SELECT * FROM orders WHERE customer_phone = ? ORDER BY created_at DESC",
        (args.phone,),
    ).fetchall()
    orders = []
    for r in rows:
        o = _db.order_dict(r)
        o["lots"] = _order_lots(conn, r["order_id"])
        orders.append(o)
    if args.json:
        _emit({"phone": args.phone, "orders": orders})
    else:
        print(f"{args.phone}: {len(orders)} orders")
        for o in orders:
            print(f"  {o['order_id']}  {o['status']:<9}  total={o['total_items']}")
    return 0


def cmd_resource_list(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    where: list[str] = []
    params: list[object] = []
    if args.kind:
        where.append("kind = ?")
        params.append(args.kind)
    if args.status:
        where.append("status = ?")
        params.append(args.status)
    sql = "SELECT * FROM resources"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY rowid"
    resources = []
    for r in conn.execute(sql, params).fetchall():
        d = _db.resource_dict(r)
        d["occupant"] = _resource_occupant(conn, r["resource_id"])
        resources.append(d)
    if args.json:
        _emit({"resources": resources})
    else:
        for d in resources:
            who = d["occupant"]["lot_id"] if d["occupant"] else "-"
            print(f"{d['resource_id']:<10}  {d['status']:<11}  {who}")
    return 0


def cmd_resource_set(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    r = _find_resource(conn, args.resource)
    if not r:
        _err(f"resource not found: {args.resource}")
        return 1
    conn.execute("UPDATE resources SET status = ? WHERE resource_id = ?",
                 (args.status, args.resource))
    conn.commit()
    if args.json:
        _emit({"resource": _db.resource_dict(_find_resource(conn, args.resource))})
    else:
        print(f"{args.resource} -> {args.status}")
    return 0


def cmd_dashboard(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    resources = []
    for r in conn.execute("SELECT * FROM resources ORDER BY rowid").fetchall():
        d = _db.resource_dict(r)
        d["occupant"] = _resource_occupant(conn, r["resource_id"])
        resources.append(d)

    orders = []
    for r in conn.execute(
        "SELECT * FROM orders WHERE status = 'active' ORDER BY created_at DESC"
    ).fetchall():
        o = _db.order_dict(r)
        o["lots"] = _order_lots(conn, r["order_id"])
        orders.append(o)

    steps: dict[str, list[dict]] = {s: [] for s in _db.STEPS}
    for r in conn.execute("SELECT * FROM lots WHERE status = 'active'").fetchall():
        lot = _db.lot_dict(r)
        steps.setdefault(lot["step"], []).append(lot)

    _emit({"resources": resources, "orders": orders, "steps": steps})
    return 0
```

- [ ] **Step 2: Register the read commands**

Add a `customer` group and extend the `resource` group; add `dashboard` at top level. Before `return parser`:

```python
    customer = sub.add_parser("customer", help="customer lookups").add_subparsers(
        dest="cmd", required=True)
    p = customer.add_parser("history", help="all orders for a phone number")
    p.add_argument("--phone", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_customer_history)

    resource = sub.add_parser("resource", help="resource pool operations").add_subparsers(
        dest="cmd", required=True)
    p = resource.add_parser("list", help="list the resource pool")
    p.add_argument("--kind", choices=["bin", "washer", "dryer", "fold", "count"], default=None)
    p.add_argument("--status", choices=["free", "busy", "maintenance"], default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_resource_list)
    p = resource.add_parser("set", help="manually set a resource status")
    p.add_argument("--resource", required=True)
    p.add_argument("--status", required=True, choices=["free", "busy", "maintenance"])
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_resource_set)

    p = sub.add_parser("dashboard", help="emit the full dashboard JSON payload")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_dashboard)
```

> Note: `resource add`/`retire` are added in Task 7 under this same `resource` group.

- [ ] **Step 3: Add read-command tests**

```python
# ── customer history + dashboard ─────────────────────────────────────────────


def test_customer_history_groups_by_phone(env):
    run_json(env, "order", "new", "--phone", "0908880000", "--bins", "1")
    run_json(env, "order", "new", "--phone", "0908880000", "--bins", "1")
    run_json(env, "order", "new", "--phone", "0908889999", "--bins", "1")
    hist = run_json(env, "customer", "history", "--phone", "0908880000")
    assert len(hist["orders"]) == 2


def test_dashboard_payload_shape(env):
    new = run_json(env, "order", "new", "--phone", "0909990000", "--bins", "2")
    run_json(env, "lot", "move", "--lot", new["lots"][0]["lot_id"], "--to", "washer-1")
    dash = run_json(env, "dashboard")
    assert "resources" in dash and "orders" in dash and "steps" in dash
    assert len(dash["resources"]) == 37  # 15+10+10+1+1
    washer1 = next(r for r in dash["resources"] if r["resource_id"] == "washer-1")
    assert washer1["occupant"] is not None
    assert any(lot["lot_id"] == new["lots"][0]["lot_id"] for lot in dash["steps"]["giat"])
```

- [ ] **Step 4: Commit**

```bash
git add modules/item_flow_tracking/scripts/flow.py tests/test_item_flow_tracking.py
git commit -m "feat(item-flow): customer history, resource list/set, dashboard JSON"
```

---

### Task 7: Data management — export, reset, resource add/retire

**Files:**
- Modify: `modules/item_flow_tracking/scripts/flow.py`
- Test: `tests/test_item_flow_tracking.py` (extend)

**Interfaces:**
- Produces:
  - `data export --table <orders|lots|resources|events> [--format csv|json] [--out <path>]`.
  - `data reset [--json]` → wipes `orders`, `lots`, `lot_events`, frees+re-seeds `resources`.
  - `resource add --kind <k> --count <n> [--json]` → append N resources of a kind (ids continue after the current max index for that kind).
  - `resource retire --resource <id> [--json]` → delete a resource (refuses if occupied/busy).

> Scope note: bulk CSV **import** is intentionally out of scope (YAGNI) — orders are created via `order new`, not bulk-loaded. The `data-management` sub-skill documents export/reset/resource config only.

- [ ] **Step 1: Add the data-management commands to `flow.py`**

```python
_EXPORT_TABLES = {"orders": "orders", "lots": "lots",
                  "resources": "resources", "events": "lot_events"}


def cmd_data_export(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    table = _EXPORT_TABLES[args.table]
    rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
    if args.format == "json":
        text = _json.dumps({args.table: rows}, ensure_ascii=False, indent=2)
    else:
        buf = io.StringIO()
        if rows:
            writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        text = buf.getvalue()
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        print(f"Wrote {len(rows)} rows to {args.out}")
    else:
        print(text)
    return 0


def cmd_data_reset(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    conn.execute("DELETE FROM lot_events")
    conn.execute("DELETE FROM lots")
    conn.execute("DELETE FROM orders")
    conn.execute("DELETE FROM resources")
    _db.seed_resources(conn)
    conn.commit()
    if args.json:
        _emit({"ok": True})
    else:
        print("Data reset — resource pool re-seeded.")
    return 0


def cmd_resource_add(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    if args.count < 1:
        _err("--count must be >= 1")
        return 1
    rows = conn.execute(
        "SELECT resource_id FROM resources WHERE kind = ?", (args.kind,)
    ).fetchall()
    max_idx = 0
    for r in rows:
        try:
            max_idx = max(max_idx, int(r["resource_id"].rsplit("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    added = []
    for i in range(max_idx + 1, max_idx + 1 + args.count):
        rid = f"{args.kind}-{i}"
        label = f"{_db.RESOURCE_KIND_LABELS[args.kind]} {i}"
        conn.execute(
            "INSERT INTO resources (resource_id, kind, label, status) VALUES (?, ?, ?, 'free')",
            (rid, args.kind, label),
        )
        added.append(rid)
    conn.commit()
    if args.json:
        _emit({"added": added})
    else:
        print(f"Added {len(added)}: {', '.join(added)}")
    return 0


def cmd_resource_retire(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    r = _find_resource(conn, args.resource)
    if not r:
        _err(f"resource not found: {args.resource}")
        return 1
    if _resource_occupant(conn, args.resource):
        _err(f"resource is occupied: {args.resource}")
        return 1
    conn.execute("DELETE FROM resources WHERE resource_id = ?", (args.resource,))
    conn.commit()
    if args.json:
        _emit({"retired": args.resource})
    else:
        print(f"Retired {args.resource}")
    return 0
```

- [ ] **Step 2: Register the commands**

Add a `data` group and extend the existing `resource` group (place the two `resource` parsers next to `list`/`set` from Task 6). Before `return parser`:

```python
    data = sub.add_parser("data", help="bulk data + lifecycle operations").add_subparsers(
        dest="cmd", required=True)
    p = data.add_parser("export", help="export a table to csv/json")
    p.add_argument("--table", choices=list(_EXPORT_TABLES), default="orders")
    p.add_argument("--format", choices=["csv", "json"], default="json")
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_data_export)
    p = data.add_parser("reset", help="wipe all data and re-seed the resource pool")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_data_reset)

    p = resource.add_parser("add", help="append N resources of a kind")
    p.add_argument("--kind", required=True, choices=["bin", "washer", "dryer", "fold", "count"])
    p.add_argument("--count", type=int, required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_resource_add)
    p = resource.add_parser("retire", help="remove a (free) resource from the pool")
    p.add_argument("--resource", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_resource_retire)
```

- [ ] **Step 3: Add data-management tests**

```python
# ── data management ──────────────────────────────────────────────────────────


def test_resource_add_continues_index(env):
    added = run_json(env, "resource", "add", "--kind", "washer", "--count", "2")["added"]
    assert added == ["washer-11", "washer-12"]


def test_resource_retire_refuses_when_occupied(env):
    lot = run_json(env, "order", "new", "--phone", "0910000000", "--bins", "1")["lots"][0]
    busy_bin = lot["current_resource"]
    blocked = run(env, "resource", "retire", "--resource", busy_bin, "--json")
    assert blocked.returncode != 0
    ok = run(env, "resource", "retire", "--resource", "bin-15", "--json")
    assert ok.returncode == 0


def test_reset_clears_orders_and_reseeds_pool(env):
    run_json(env, "order", "new", "--phone", "0911111111", "--bins", "1")
    run_json(env, "data", "reset")
    assert run_json(env, "order", "list")["orders"] == []
    assert len(run_json(env, "resource", "list")["resources"]) == 37


def test_export_orders_json(env):
    run_json(env, "order", "new", "--phone", "0912222222", "--bins", "1")
    r = run(env, "data", "export", "--table", "orders", "--format", "json")
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    assert len(payload["orders"]) == 1
```

- [ ] **Step 4: Commit**

```bash
git add modules/item_flow_tracking/scripts/flow.py tests/test_item_flow_tracking.py
git commit -m "feat(item-flow): data export/reset and resource add/retire"
```

---

### Task 8: Dashboard (`dashboard.html`)

**Files:**
- Create: `modules/item_flow_tracking/dashboard.html`

**Interfaces:**
- Consumes: `flow.py dashboard --json` via `AtriaDash.json("flow.py", ["dashboard", "--json"])`.
- Uses the host bridge contract observed in `warehouse/dashboard.html`: `AtriaDash.json(script, args)`, `AtriaDash.run(script, args)`, `AtriaDash.resize(h)`, `AtriaDash.setBadge(...)`, `AtriaDash.onChange(cb)`, `AtriaDash.onVisibility(cb)`, `AtriaDash.ready()`, plus `__base.css` and `__bridge.js`.

- [ ] **Step 1: Write `dashboard.html`**

Three sections rendered from the single `dashboard --json` payload: a **resource grid** (bins / washers / dryers / fold / count, colored by status, busy cells show the occupant order), an **active orders** list (phone + per-part step + running total), and a **by-step board** (one column per step, cards = lots at that step). Use the same token bridge and bridge-call style as `warehouse/dashboard.html`.

```html
<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8" />
  <title>Item Flow Tracking</title>
  <link rel="stylesheet" href="__base.css" />
  <style>
    :root {
      --ink: 0 0% 0%; --canvas: 0 0% 100%; --surface-soft: 40 22% 96%;
      --hairline: 0 0% 12%; --hairline-soft: 0 0% 88%; --muted-ink: 0 0% 38%;
      --free: 150 50% 86%; --busy: 8 80% 80%; --maint: 38 60% 86%;
      --ease-out: cubic-bezier(0.22, 1, 0.36, 1);
    }
    * { box-sizing: border-box; }
    html, body { font-family: 'Inter', system-ui, sans-serif; color: hsl(var(--ink));
      background: hsl(var(--canvas)); }
    body { padding: 24px; }
    .wrap { max-width: 1100px; margin: 0 auto; display: flex; flex-direction: column; gap: 24px; }
    h1 { font-size: 24px; margin: 0; } h2 { font-size: 14px; margin: 0 0 10px; }
    .sub { color: hsl(var(--muted-ink)); font-size: 13px; margin-top: 4px; }
    .toolbar { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px;
      border-bottom: 1px solid hsl(var(--hairline)); padding-bottom: 14px; }
    button { font: inherit; cursor: pointer; background: hsl(var(--ink)); color: hsl(var(--canvas));
      border: 0; border-radius: 999px; padding: 8px 16px; font-size: 13px; }
    button:hover { opacity: 0.88; }
    .panel { border: 1px solid hsl(var(--hairline)); border-radius: 12px; padding: 16px; }
    .res-group { margin-bottom: 14px; }
    .res-group .label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
      color: hsl(var(--muted-ink)); margin-bottom: 6px; }
    .res-grid { display: flex; flex-wrap: wrap; gap: 6px; }
    .cell { min-width: 56px; padding: 8px 6px; border-radius: 8px; border: 1px solid hsl(var(--hairline-soft));
      font-size: 11px; text-align: center; }
    .cell.free { background: hsl(var(--free)); }
    .cell.busy { background: hsl(var(--busy)); }
    .cell.maintenance { background: hsl(var(--maint)); }
    .cell .who { display: block; font-size: 9.5px; color: hsl(var(--muted-ink)); margin-top: 2px;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .order { border-bottom: 1px solid hsl(var(--hairline-soft)); padding: 10px 0; }
    .order:last-child { border-bottom: 0; }
    .order .hd { display: flex; justify-content: space-between; font-size: 13px; }
    .order .parts { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
    .pill { font-size: 11px; padding: 3px 8px; border-radius: 999px; background: hsl(var(--surface-soft));
      border: 1px solid hsl(var(--hairline-soft)); }
    .board { display: flex; gap: 10px; overflow-x: auto; }
    .col { flex: 1 0 130px; }
    .col .label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
      color: hsl(var(--muted-ink)); margin-bottom: 6px; }
    .card { font-size: 11px; padding: 6px 8px; border-radius: 8px; border: 1px solid hsl(var(--hairline-soft));
      margin-bottom: 6px; background: hsl(var(--canvas)); }
    .card.redo { border-color: hsl(var(--busy)); }
    .empty { color: hsl(var(--muted-ink)); font-size: 12px; padding: 8px 0; }
    .err { color: hsl(0 70% 45%); font-size: 12px; min-height: 16px; }
  </style>
</head>
<body>
  <div class="wrap" id="root">
    <div class="toolbar">
      <div><h1>Item Flow Tracking</h1><div class="sub">Đơn giặt là · tài nguyên & tiến độ</div></div>
      <button type="button" id="refresh">Làm mới</button>
    </div>
    <div class="err" id="err"></div>
    <section class="panel"><h2>Tài nguyên</h2><div id="resources"></div></section>
    <section class="panel"><h2>Đơn đang xử lý</h2><div id="orders"></div></section>
    <section class="panel"><h2>Theo bước</h2><div class="board" id="board"></div></section>
  </div>
  <script src="__bridge.js"></script>
  <script>
    (function () {
      var STEP_LABELS = { nhan_hang: "Nhận hàng", giat: "Giặt", say: "Sấy", gap: "Gấp",
        kiem_dem: "Kiểm đếm", giao_hang: "Giao hàng", done: "Xong" };
      var STEPS = ["nhan_hang", "giat", "say", "gap", "kiem_dem", "giao_hang", "done"];
      var KIND_LABELS = { bin: "Bins", washer: "Máy giặt", dryer: "Máy sấy", fold: "Khu gấp", count: "Khu đếm" };
      var el = {
        resources: document.getElementById("resources"),
        orders: document.getElementById("orders"),
        board: document.getElementById("board"),
        err: document.getElementById("err"),
        refresh: document.getElementById("refresh"),
      };
      function setErr(m) { el.err.textContent = m || ""; }
      function reportSize() {
        AtriaDash.resize(Math.max(document.body.scrollHeight,
          document.getElementById("root").offsetHeight + 48));
      }
      function renderResources(resources) {
        el.resources.innerHTML = "";
        var byKind = {};
        resources.forEach(function (r) { (byKind[r.kind] = byKind[r.kind] || []).push(r); });
        var busy = 0;
        Object.keys(KIND_LABELS).forEach(function (kind) {
          var list = byKind[kind] || [];
          if (!list.length) return;
          var group = document.createElement("div");
          group.className = "res-group";
          var lab = document.createElement("div");
          lab.className = "label";
          lab.textContent = KIND_LABELS[kind] + " (" + list.length + ")";
          var grid = document.createElement("div");
          grid.className = "res-grid";
          list.forEach(function (r) {
            if (r.status === "busy") busy++;
            var c = document.createElement("div");
            c.className = "cell " + r.status;
            c.textContent = r.resource_id.split("-")[1] || r.resource_id;
            c.title = r.label + " · " + r.status;
            if (r.occupant) {
              var who = document.createElement("span");
              who.className = "who";
              who.textContent = r.occupant.order_id.replace("DH-", "");
              c.appendChild(who);
            }
            grid.appendChild(c);
          });
          group.appendChild(lab); group.appendChild(grid);
          el.resources.appendChild(group);
        });
        AtriaDash.setBadge(busy > 0 ? { count: busy, severity: "info" } : null);
      }
      function renderOrders(orders) {
        el.orders.innerHTML = "";
        if (!orders.length) { el.orders.innerHTML = '<div class="empty">Chưa có đơn nào.</div>'; return; }
        orders.forEach(function (o) {
          var d = document.createElement("div");
          d.className = "order";
          var hd = document.createElement("div");
          hd.className = "hd";
          hd.innerHTML = "<strong>" + o.order_id + "</strong><span>" + o.customer_phone +
            " · total " + (o.total_items == null ? "—" : o.total_items) + "</span>";
          var parts = document.createElement("div");
          parts.className = "parts";
          (o.lots || []).forEach(function (lot) {
            var p = document.createElement("span");
            p.className = "pill";
            p.textContent = lot.label + " · " + (STEP_LABELS[lot.step] || lot.step) +
              (lot.is_redo ? " ⟲" : "") + " @" + (lot.current_resource || "-");
            parts.appendChild(p);
          });
          d.appendChild(hd); d.appendChild(parts);
          el.orders.appendChild(d);
        });
      }
      function renderBoard(steps) {
        el.board.innerHTML = "";
        STEPS.forEach(function (s) {
          var col = document.createElement("div");
          col.className = "col";
          var lab = document.createElement("div");
          lab.className = "label";
          var lots = (steps && steps[s]) || [];
          lab.textContent = STEP_LABELS[s] + " (" + lots.length + ")";
          col.appendChild(lab);
          lots.forEach(function (lot) {
            var c = document.createElement("div");
            c.className = "card" + (lot.is_redo ? " redo" : "");
            c.textContent = lot.order_id.replace("DH-", "") + " " + lot.label +
              " @" + (lot.current_resource || "-");
            col.appendChild(c);
          });
          el.board.appendChild(col);
        });
      }
      function load() {
        AtriaDash.json("flow.py", ["dashboard", "--json"])
          .then(function (data) {
            setErr("");
            renderResources((data && data.resources) || []);
            renderOrders((data && data.orders) || []);
            renderBoard((data && data.steps) || {});
            reportSize();
          })
          .catch(function (e) { setErr("Lỗi tải dashboard: " + (e && e.message ? e.message : e)); });
      }
      el.refresh.addEventListener("click", load);
      AtriaDash.onChange(function () { load(); });
      AtriaDash.onVisibility(function (v) { if (v) load(); });
      if (typeof ResizeObserver !== "undefined") new ResizeObserver(reportSize).observe(document.body);
      load();
      AtriaDash.ready();
    })();
  </script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add modules/item_flow_tracking/dashboard.html
git commit -m "feat(item-flow): dashboard with resource grid, orders, and step board"
```

---

### Task 9: Module metadata — SKILL.md, manifest, icon, sub-skills, gitignore

**Files:**
- Create: `modules/item_flow_tracking/SKILL.md`
- Create: `modules/item_flow_tracking/manifest.json`
- Create: `modules/item_flow_tracking/icon.svg`
- Create: `modules/item_flow_tracking/skills/tracking-ops.md`
- Create: `modules/item_flow_tracking/skills/analytics.md`
- Create: `modules/item_flow_tracking/skills/data-management.md`
- Modify: `.gitignore` (ignore the live DB)

- [ ] **Step 1: Write `SKILL.md`**

```markdown
---
name: item_flow_tracking
description: Theo dõi đơn giặt là — mỗi đơn của một khách (định danh bằng số điện thoại) chia thành nhiều phần ("lot"/Bin) chạy qua chuỗi bước cố định trên pool tài nguyên dùng chung (bin, máy giặt, máy sấy, khu gấp/đếm), backed by SQLite, có dashboard.
---

# item_flow_tracking

Track laundry orders backed by a single embedded **SQLite** database
(`data/flow.db`). Each order belongs to a customer (identified by **phone
number**) and is split at intake into one or more **parts ("lots")** — one per
Bin. Each part moves through a fixed pipeline while occupying shared physical
resources; every move is recorded in an append-only `lot_events` ledger.

## When to use

- The user wants to create/intake a laundry order and split it into bins.
- The user wants to move a part to the next station (wash/dry/fold/count) or
  back it for redo ("làm lại").
- The user wants to record counted quantities, deliver, or cancel an order.
- The user asks where an order or part is, or for a customer's order history.
- The user wants resource status (which bins/machines are busy/free).

## Data model

SQLite DB at `<modules>/item_flow_tracking/data/flow.db`, created automatically
on first use and seeded with the fixed resource pool. Four tables: `orders`
(one per customer order), `lots` (parts; the tracking unit), `resources` (the
fixed pool — default 15 bins, 10 washers, 10 dryers, 1 fold, 1 count), and
`lot_events` (audit ledger). The DB path can be overridden with `ATRIA_FLOW_DB`
(used by tests); the live DB is gitignored.

Fixed steps, in order: `nhan_hang → giat → say → gap → kiem_dem → giao_hang →
done`, plus a `redo` transition. Moving a part into a resource infers its step:
washer→giặt, dryer→sấy, fold→gấp, count→kiểm đếm; a bin is just a holding spot
and keeps the step. At kiểm đếm each part's count is summed into the order
total; an order can only be delivered once all parts are counted.

## How to use

Bash CWD is the chat workspace, not the modules root — use absolute paths.
Replace `<modules>` with the absolute modules root from the "Active Modules"
prompt section. All operations are subcommands of `scripts/flow.py`. Add
`--json` for machine-readable output.

Most common — create an order and list active orders:

```
python <modules>/item_flow_tracking/scripts/flow.py order new --phone 0901234567 --name "Khach A" --bins 3
python <modules>/item_flow_tracking/scripts/flow.py order list
```

## Sub-skills (load on demand)

For anything beyond `order new`/`order list`/`order show`, load the matching
sub-skill with `invoke_skill` — do not guess flags:

- `invoke_skill("item_flow_tracking:tracking-ops")` — `lot move`, `lot count`,
  `lot redo`, `lot deliver`, `order deliver`, `order cancel`.
- `invoke_skill("item_flow_tracking:analytics")` — `order show`,
  `customer history`, `resource list`, and the `dashboard` payload.
- `invoke_skill("item_flow_tracking:data-management")` — `data export`,
  `data reset`, `resource set`, `resource add`, `resource retire`.

## Files

- `SKILL.md` — this overview.
- `skills/*.md` — on-demand sub-skill guides (tracking-ops, analytics, data-management).
- `scripts/_db.py` — SQLite connection, schema, resource-pool seed, ledger helper.
- `scripts/flow.py` — the flow-tracking CLI (orders, lots, resources, dashboard).
- `dashboard.html` — resource grid, active orders, and by-step board.
- `data/flow.db` — live SQLite store (auto-created; gitignored).
```

- [ ] **Step 2: Write `manifest.json`**

```json
{
  "display_name": "Item Flow Tracking",
  "tooltip": "Đơn giặt là · tài nguyên & tiến độ",
  "icon": "icon.svg",
  "dashboard": {
    "title": "Item Flow · Đơn giặt là",
    "default_height": 820,
    "badge_color": "info"
  },
  "activity": {
    "default": { "running": "Đang xử lý đơn…", "done": "Xong" },
    "actions": {
      "new":       { "running": "Đang tạo đơn…",        "done": "Đã tạo đơn" },
      "list":      { "running": "Đang tải đơn…",        "done": "Đã tải đơn" },
      "show":      { "running": "Đang mở đơn…",         "done": "Đã mở đơn" },
      "move":      { "running": "Đang chuyển phần…",    "done": "Đã chuyển" },
      "count":     { "running": "Đang kiểm đếm…",       "done": "Đã đếm" },
      "redo":      { "running": "Đang đánh dấu làm lại…", "done": "Đã đánh dấu làm lại" },
      "deliver":   { "running": "Đang giao hàng…",      "done": "Đã giao" },
      "cancel":    { "running": "Đang hủy đơn…",        "done": "Đã hủy" },
      "history":   { "running": "Đang tra lịch sử…",    "done": "Đã tra xong" },
      "dashboard": { "running": "Đang dựng dashboard…", "done": "Sẵn sàng" },
      "export":    { "running": "Đang xuất dữ liệu…",   "done": "Đã xuất" },
      "reset":     { "running": "Đang reset dữ liệu…",  "done": "Đã reset" }
    }
  }
}
```

- [ ] **Step 3: Write `icon.svg`** (a simple flow/arrow glyph, single-color, currentColor)

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <rect x="3" y="4" width="6" height="6" rx="1"/>
  <rect x="15" y="14" width="6" height="6" rx="1"/>
  <path d="M9 7h6a3 3 0 0 1 3 3v4"/>
  <path d="M15 11l3 3 3-3"/>
</svg>
```

- [ ] **Step 4: Write `skills/tracking-ops.md`**

```markdown
---
name: tracking-ops
description: Move parts through steps and finish orders — lot move, lot count, lot redo, lot deliver, order deliver, order cancel.
---

# item_flow_tracking · tracking-ops

Mutating operations on orders and parts. All are subcommands of
`scripts/flow.py`; use absolute paths (`<modules>` = the modules root from the
"Active Modules" prompt section). Every change is recorded in the `lot_events`
ledger.

## Move a part (step is inferred from the resource)

Moving into a machine/area sets the step automatically (washer→giặt, dryer→sấy,
fold→gấp, count→kiểm đếm); moving into a bin just relocates it and keeps the
step. Fails if the target is busy unless `--force`:

```
python <modules>/item_flow_tracking/scripts/flow.py lot move --lot DH-20260626-001-P1 --to washer-3
python <modules>/item_flow_tracking/scripts/flow.py lot move --lot DH-20260626-001-P1 --to bin-5
```

## Count a part (sums into the order total)

```
python <modules>/item_flow_tracking/scripts/flow.py lot count --lot DH-20260626-001-P1 --items 24
```

## Redo ("làm lại") — send a part back

Defaults back to `giat`; pass `--to` for another step:

```
python <modules>/item_flow_tracking/scripts/flow.py lot redo --lot DH-20260626-001-P1 --notes "còn vết bẩn"
python <modules>/item_flow_tracking/scripts/flow.py lot redo --lot DH-20260626-001-P1 --to say
```

## Deliver / cancel

`order deliver` requires every part to be counted; `lot deliver` finishes one
part (and completes the order when it's the last):

```
python <modules>/item_flow_tracking/scripts/flow.py lot deliver --lot DH-20260626-001-P1
python <modules>/item_flow_tracking/scripts/flow.py order deliver --order DH-20260626-001
python <modules>/item_flow_tracking/scripts/flow.py order cancel --order DH-20260626-001 --reason "khách hủy"
```
```

- [ ] **Step 5: Write `skills/analytics.md`**

```markdown
---
name: analytics
description: Read-only views — order show, customer history by phone, resource status, and the dashboard payload.
---

# item_flow_tracking · analytics

Read-only lookups. All are subcommands of `scripts/flow.py`; use absolute paths
(`<modules>` = the modules root from the "Active Modules" prompt section). Add
`--json` for machine-readable output.

## One order and its parts

```
python <modules>/item_flow_tracking/scripts/flow.py order show --order DH-20260626-001
```

## Customer history (by phone number)

```
python <modules>/item_flow_tracking/scripts/flow.py customer history --phone 0901234567
```

## Resource status

List the pool, optionally filtered; busy resources show their occupant:

```
python <modules>/item_flow_tracking/scripts/flow.py resource list
python <modules>/item_flow_tracking/scripts/flow.py resource list --kind washer --status busy
```

## Full dashboard payload

Returns resources (with occupants), active orders with parts, and parts bucketed
by step (work-in-progress per stage):

```
python <modules>/item_flow_tracking/scripts/flow.py dashboard --json
```
```

- [ ] **Step 6: Write `skills/data-management.md`**

```markdown
---
name: data-management
description: Bulk data + resource pool config — data export, data reset, resource set/add/retire.
---

# item_flow_tracking · data-management

Bulk data and resource-pool lifecycle operations. All are subcommands of
`scripts/flow.py`; use absolute paths (`<modules>` = the modules root from the
"Active Modules" prompt section).

## Export

Dump a table to stdout, or to a file with `--out`. `--table` is one of
`orders` (default), `lots`, `resources`, `events`; `--format` is `json`
(default) or `csv`:

```
python <modules>/item_flow_tracking/scripts/flow.py data export --table lots --format csv --out lots.csv
python <modules>/item_flow_tracking/scripts/flow.py data export --table events --format json
```

## Reset

Empty all orders/lots/events and re-seed the default resource pool
(destructive — confirm with the user first):

```
python <modules>/item_flow_tracking/scripts/flow.py data reset
```

## Configure the resource pool

Mark a resource out of service, or grow/shrink the pool. `resource add` appends
N of a kind (ids continue after the current max); `resource retire` removes a
free resource (refuses if occupied):

```
python <modules>/item_flow_tracking/scripts/flow.py resource set --resource washer-3 --status maintenance
python <modules>/item_flow_tracking/scripts/flow.py resource add --kind bin --count 5
python <modules>/item_flow_tracking/scripts/flow.py resource retire --resource bin-15
```
```

- [ ] **Step 7: Append the live DB to `.gitignore`** (after the warehouse lines ~178-179)

```
modules/item_flow_tracking/data/flow.db
modules/item_flow_tracking/data/flow.db-*
```

- [ ] **Step 8: Commit**

```bash
git add modules/item_flow_tracking/SKILL.md modules/item_flow_tracking/manifest.json \
        modules/item_flow_tracking/icon.svg modules/item_flow_tracking/skills/ .gitignore
git commit -m "feat(item-flow): SKILL.md, manifest, icon, sub-skills, gitignore"
```

---

### Task 10: Verification — unit tests + real end-to-end

**Files:** none (verification only)

**Interfaces:** exercises the whole module via the CLI and the registry.

- [ ] **Step 1: Run the full unit-test suite once**

Run: `make test-file FILE=tests/test_item_flow_tracking.py`
(or `uv run pytest tests/test_item_flow_tracking.py -v`)
Expected: all tests PASS. Fix any failures before continuing.

- [ ] **Step 2: Run lint + typecheck on the new code**

Run: `make check`
Expected: Black clean, Ruff clean, mypy clean. Fix any issues.

- [ ] **Step 3: Real end-to-end run of the CLI** (per project testing rules)

Run, in order, against a throwaway DB:

```bash
export ATRIA_FLOW_DB=/tmp/itemflow_e2e.db
rm -f "$ATRIA_FLOW_DB"
S=modules/item_flow_tracking/scripts/flow.py
python $S order new --phone 0901234567 --name "Khach A" --bins 3 --json
python $S order list
# take the first order id + part ids from `order new` output, then:
python $S lot move --lot DH-<today>-001-P1 --to washer-1
python $S lot move --lot DH-<today>-001-P1 --to dryer-1     # step say
python $S lot redo --lot DH-<today>-001-P1 --notes "test"   # back to giat
python $S lot count --lot DH-<today>-001-P1 --items 10
python $S lot count --lot DH-<today>-001-P2 --items 8
python $S lot count --lot DH-<today>-001-P3 --items 12
python $S order show --order DH-<today>-001 --json          # total_items == 30
python $S order deliver --order DH-<today>-001 --json       # status done
python $S dashboard --json                                  # resources all free again
python $S customer history --phone 0901234567 --json
```

Expected: order total is 30 after counting; `order deliver` succeeds only after
all parts counted and sets status `done`; resources return to `free`; dashboard
payload has `resources`/`orders`/`steps` keys.

- [ ] **Step 4: Verify the module registers and the dashboard loads**

Run: `OPENAI_API_KEY=$OPENAI_API_KEY atria run ui` (per CLAUDE.md, set the key),
open the Item Flow Tracking module from the sidebar, confirm the dashboard
renders the resource grid, create an order from chat ("tạo đơn giặt cho số
0901234567, 3 thùng"), and confirm the dashboard updates. Alternatively confirm
registration headlessly:

```bash
python -c "from atria.core.modules.registry import get_registry; r=get_registry(); r.load_all(); print([m.name for m in r.list()])"
```

Expected: `item_flow_tracking` appears in the module list; the dashboard shows
the seeded 15/10/10/1/1 pool and reflects new orders.

- [ ] **Step 5: Final commit (if any fixes were made)**

```bash
git add -A
git commit -m "test(item-flow): verify module end-to-end"
```

---

## Self-Review

**Spec coverage:**
- §2 domain model (orders, lots, resources, events; phone identity; fixed steps; step↔resource inference; count→order total; deliver gate) → Tasks 1–6. ✓
- §3 data model tables + helpers + env override → Task 1. ✓
- §4 operations (order new/list/show/deliver/cancel; lot move/count/redo/deliver; customer history; resource list/set; dashboard; resource add/retire; export/reset) → Tasks 2–7. ✓
- §5 dashboard three regions → Task 8. ✓
- §6 file structure (SKILL.md, manifest, icon, dashboard, scripts, three sub-skills, data/) → Tasks 1,2,8,9. ✓
- §7 testing (unit + real e2e) → each task's tests + Task 10. ✓
- §8 decisions locked (stable lot id, step inference, per-part count, redo→giặt, pool 15/10/10/1/1) → enforced in Tasks 1–7. ✓
- §9 out of scope (no bin merge/split, no billing, single workshop) → respected; bulk CSV **import** also deferred (noted in Task 7). ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. The `<today>`/`<modules>` tokens in Task 10/sub-skills are runtime values the operator substitutes, not plan gaps.

**Type consistency:** `_db.connect/now/log_event/order_dict/lot_dict/resource_dict/seed_resources/STEPS/STEP_LABELS/RESOURCE_KIND_TO_STEP/RESOURCE_KIND_LABELS/DEFAULT_POOL` defined in Task 1 and used consistently. CLI helpers `_err/_emit/_find_order/_find_lot/_find_resource/_order_lots/_gen_order_id/_recompute_order_total/_free_lot_resource/_maybe_complete_order/_resource_occupant/_EXPORT_TABLES` defined before use. Command function names match their `set_defaults(fn=...)` registrations. Dashboard calls `flow.py dashboard --json` matching `cmd_dashboard`'s payload keys (`resources`/`orders`/`steps`).
