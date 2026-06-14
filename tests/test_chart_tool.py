"""chart_tool: render a SQLite table to a PNG."""

import sqlite3
from pathlib import Path

from atria.core.context_engineering.tools.implementations.chart_tool import ChartTool


def _seed_db(db: Path) -> None:
    with sqlite3.connect(db) as cx:
        cx.execute("CREATE TABLE t AS SELECT 'NA' AS region, 100 AS r")
        cx.execute("INSERT INTO t VALUES ('EU', 80)")
        cx.execute("INSERT INTO t VALUES ('APAC', 200)")


def test_renders_bar_chart_png(tmp_path: Path) -> None:
    db = tmp_path / "data.db"
    _seed_db(db)
    out = tmp_path / "out.png"
    tool = ChartTool()
    result = tool.render(
        db_path=str(db),
        source_table="t",
        chart_type="bar",
        x="region",
        y=["r"],
        title="Revenue",
        out_path=str(out),
        agg=None,
    )
    assert result["success"]
    assert out.exists() and out.stat().st_size > 200
    assert result["output"]["rows_plotted"] == 3


def test_unknown_chart_type_returns_error(tmp_path: Path) -> None:
    db = tmp_path / "data.db"
    _seed_db(db)
    tool = ChartTool()
    result = tool.render(
        db_path=str(db),
        source_table="t",
        chart_type="rainbow",  # invalid
        x="region",
        y=["r"],
        title="x",
        out_path=str(tmp_path / "x.png"),
        agg=None,
    )
    assert not result["success"]
    assert "chart_type" in (result["error"] or "")


def test_rejects_malicious_table_name(tmp_path: Path) -> None:
    db = tmp_path / "data.db"
    _seed_db(db)
    tool = ChartTool()
    result = tool.render(
        db_path=str(db),
        source_table="t; DROP TABLE raw; --",
        chart_type="bar",
        x="region",
        y=["r"],
        title="x",
        out_path=str(tmp_path / "x.png"),
        agg=None,
    )
    assert not result["success"]
    assert "invalid source_table" in (result["error"] or "")
