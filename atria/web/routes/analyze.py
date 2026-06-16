"""Analyze job data endpoints."""

from __future__ import annotations

import base64
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query

from atria.web.dependencies.auth import require_authenticated_user

router = APIRouter(
    prefix="/api/analyze",
    tags=["analyze"],
    dependencies=[Depends(require_authenticated_user)],
)

_SAFE_TABLE_RE = re.compile(r"^[A-Za-z0-9_]+$")
_MAX_ROWS = 50_000


def _validate_db_path(db_path: str) -> Path:
    p = Path(db_path).resolve()
    if p.name != "data.db":
        raise HTTPException(status_code=400, detail="invalid db path")
    if not p.exists():
        raise HTTPException(status_code=404, detail="database not found")
    atria_root = (Path.home() / ".atria").resolve()
    try:
        p.relative_to(atria_root)
        return p
    except ValueError:
        pass
    # Also allow working-directory-relative paths (any parent analyze dir)
    # by checking the path contains "analyze" segment as a safety heuristic.
    parts = p.parts
    if "analyze" not in parts:
        raise HTTPException(status_code=403, detail="path not allowed")
    return p


@router.get("/table-data")
async def get_table_data(
    db_path: str = Query(...),
    table: str = Query(...),
    limit: int = Query(default=_MAX_ROWS, le=_MAX_ROWS),
) -> Dict[str, Any]:
    if not _SAFE_TABLE_RE.match(table):
        raise HTTPException(status_code=400, detail="invalid table name")

    path = _validate_db_path(db_path)

    try:
        with sqlite3.connect(str(path)) as conn:
            cur = conn.execute(f"SELECT * FROM {table} LIMIT {limit}")  # noqa: S608
            col_names = [d[0] for d in cur.description] if cur.description else []
            rows_raw = cur.fetchall()
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=404, detail=f"table query failed: {e}") from e

    rows: List[Dict[str, Any]] = [dict(zip(col_names, r)) for r in rows_raw]
    columns: List[Dict[str, str]] = []
    for col in col_names:
        values = [r.get(col) for r in rows]
        non_null = [v for v in values if v is not None]
        col_type = (
            "number"
            if non_null and all(isinstance(v, (int, float)) for v in non_null)
            else "string"
        )
        columns.append({"name": col, "type": col_type})

    return {"columns": columns, "rows": rows}


def _validate_png_path(png_path: str) -> Path:
    p = Path(png_path).resolve()
    if p.suffix.lower() != ".png":
        raise HTTPException(status_code=400, detail="only .png files allowed")
    if not p.exists():
        raise HTTPException(status_code=404, detail="chart image not found")
    atria_root = (Path.home() / ".atria").resolve()
    try:
        p.relative_to(atria_root)
        return p
    except ValueError:
        pass
    parts = p.parts
    if "analyze" not in parts or "charts" not in parts:
        raise HTTPException(status_code=403, detail="path not allowed")
    return p


@router.get("/chart-image")
async def get_chart_image(path: str = Query(...)) -> Dict[str, Any]:
    """Return a rendered chart PNG as a base64 data-URL."""
    p = _validate_png_path(path)
    data = p.read_bytes()
    src = f"data:image/png;base64,{base64.b64encode(data).decode()}"
    return {"src": src}
