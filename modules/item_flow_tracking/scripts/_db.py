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

SCHEMA_VERSION = 2

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
    declared_total INTEGER,
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

CREATE TABLE IF NOT EXISTS order_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id     TEXT NOT NULL,
    item_type    TEXT NOT NULL COLLATE NOCASE,
    declared_qty INTEGER NOT NULL,
    counted_qty  INTEGER,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    UNIQUE (order_id, item_type)
);

CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
"""


def now() -> str:
    """Return the current UTC time as an ISO-8601 ``Z`` timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def db_path() -> Path:
    """Resolve the active DB file (env override wins; else the module default)."""
    override = os.environ.get("ATRIA_FLOW_DB")
    return Path(override) if override else DEFAULT_DB


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns missing from pre-v2 databases (idempotent)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(orders)").fetchall()}
    if "declared_total" not in cols:
        conn.execute("ALTER TABLE orders ADD COLUMN declared_total INTEGER")


def connect() -> sqlite3.Connection:
    """Open (creating + bootstrapping if needed) the flow DB."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    if int(conn.execute("PRAGMA user_version").fetchone()[0]) < SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    _migrate(conn)
    if conn.execute("SELECT COUNT(*) FROM resources").fetchone()[0] == 0:
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
        "declared_total": row["declared_total"],
        "note": row["note"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def recompute_order_totals(conn: sqlite3.Connection, order_id: str) -> None:
    """Recompute an order's declared_total and total_items from its item lines."""
    row = conn.execute(
        "SELECT SUM(declared_qty) AS dq, COUNT(counted_qty) AS cc, "
        "SUM(counted_qty) AS cq FROM order_items WHERE order_id = ?",
        (order_id,),
    ).fetchone()
    declared = row["dq"]
    total = row["cq"] if row["cc"] else None
    conn.execute(
        "UPDATE orders SET declared_total = ?, total_items = ?, updated_at = ? "
        "WHERE order_id = ?",
        (declared, total, now(), order_id),
    )


def order_item_dict(row: sqlite3.Row) -> dict:
    """Normalise an ``order_items`` row into JSON shape (with declared/counted diff)."""
    declared = int(row["declared_qty"])
    counted = row["counted_qty"]
    return {
        "item_type": row["item_type"],
        "declared_qty": declared,
        "counted_qty": (int(counted) if counted is not None else None),
        "diff": (int(counted) - declared if counted is not None else None),
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
