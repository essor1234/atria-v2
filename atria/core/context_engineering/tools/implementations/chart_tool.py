"""render_chart tool — deterministic matplotlib renderer for the analyze skill."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless, no display server
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import seaborn as sns  # noqa: E402

_MAX_BYTES = 10 * 1024 * 1024
_MAX_ROWS = 100_000
_CHART_TYPES = {"bar", "line", "scatter", "hist", "pie"}
_AGGS = {"sum", "mean", "count", "none", None}
_FIGSIZE = (10.0, 6.0)
_DPI = 150


def _fail(msg: str) -> dict[str, Any]:
    return {"success": False, "output": None, "error": msg}


def _ok(output: dict[str, Any]) -> dict[str, Any]:
    return {"success": True, "output": output, "error": None}


class RenderChartHandler:
    """Renders a single chart to a PNG file from a tabular dataset."""

    def render(self, args: dict[str, Any], context: Any) -> dict[str, Any]:
        data_path = (args.get("data_path") or "").strip()
        chart_type = (args.get("chart_type") or "").strip()
        x = (args.get("x") or "").strip()
        y = args.get("y")
        title = (args.get("title") or "").strip()
        out_path = (args.get("out_path") or "").strip()
        agg = args.get("agg")

        if not data_path:
            return _fail("'data_path' is required")
        if chart_type not in _CHART_TYPES:
            return _fail(f"'chart_type' must be one of {sorted(_CHART_TYPES)}, got {chart_type!r}")
        if not title:
            return _fail("'title' is required")
        if not out_path:
            return _fail("'out_path' is required")
        if not out_path.lower().endswith(".png"):
            return _fail("'out_path' must end with .png")
        if not isinstance(y, list) or not y or not all(isinstance(c, str) for c in y):
            return _fail("'y' must be a non-empty list of column names")
        if agg not in _AGGS:
            return _fail(f"'agg' must be one of sum|mean|count|none, got {agg!r}")
        if chart_type != "hist" and not x:
            return _fail("'x' is required for chart_type != 'hist'")

        src = Path(data_path)
        if not src.exists():
            return _fail(f"Data file not found: {data_path}")
        if src.stat().st_size > _MAX_BYTES:
            return _fail(f"Data file exceeds 10 MB cap (size={src.stat().st_size})")

        out = Path(out_path)
        if not out.parent.exists():
            return _fail(f"Output directory does not exist: {out.parent}")

        try:
            df = self._read(src)
        except Exception as e:
            return _fail(f"Failed to read dataset: {e}")

        if len(df) > _MAX_ROWS:
            return _fail(f"Dataset exceeds {_MAX_ROWS:,} row cap (rows={len(df)})")

        missing = [
            c for c in ([x] if chart_type != "hist" else []) + list(y) if c and c not in df.columns
        ]
        if missing:
            available = ", ".join(df.columns)
            return _fail(f"Column(s) not found: {missing}. Available: {available}")

        for col in y:
            if not pd.api.types.is_numeric_dtype(df[col]):
                return _fail(f"Column {col!r} must be numeric for chart_type={chart_type!r}")

        try:
            rows_plotted = self._plot(df, chart_type, x, y, title, agg, out)
        except Exception as e:
            plt.close("all")
            return _fail(f"Render failed: {e}")

        return _ok(
            {
                "path": str(out),
                "width": int(_FIGSIZE[0] * _DPI),
                "height": int(_FIGSIZE[1] * _DPI),
                "rows_plotted": rows_plotted,
            }
        )

    def _read(self, src: Path) -> "pd.DataFrame":
        suffix = src.suffix.lower()
        if suffix in (".xlsx", ".xls"):
            return pd.read_excel(src)
        return pd.read_csv(src)

    def _plot(
        self,
        df: "pd.DataFrame",
        chart_type: str,
        x: str,
        y: list[str],
        title: str,
        agg: str | None,
        out: Path,
    ) -> int:
        fig, ax = plt.subplots(figsize=_FIGSIZE, dpi=_DPI)
        try:
            if chart_type == "hist":
                df[y[0]].plot(kind="hist", ax=ax, bins=20)
                rows = int(df[y[0]].dropna().shape[0])
            elif chart_type == "pie":
                grouped = self._aggregate(df, x, y[:1], agg or "sum")
                grouped[y[0]].plot(kind="pie", ax=ax, labels=grouped.index, autopct="%1.1f%%")
                ax.set_ylabel("")
                rows = int(grouped.shape[0])
            elif chart_type == "scatter":
                df.plot.scatter(x=x, y=y[0], ax=ax)
                rows = int(df[[x, y[0]]].dropna().shape[0])
            elif chart_type == "line":
                grouped = self._aggregate(df, x, y, agg or "sum")
                grouped.plot(kind="line", ax=ax, marker="o")
                rows = int(grouped.shape[0])
            else:  # bar
                grouped = self._aggregate(df, x, y, agg or "sum")
                grouped.plot(kind="bar", ax=ax)
                rows = int(grouped.shape[0])

            ax.set_title(title)
            fig.tight_layout()
            fig.savefig(out, dpi=_DPI, format="png")
        finally:
            plt.close(fig)
        return rows

    def _aggregate(self, df: "pd.DataFrame", x: str, y: list[str], agg: str) -> "pd.DataFrame":
        if agg == "none":
            return df.set_index(x)[y]
        grouped = df.groupby(x)[y]
        if agg == "sum":
            return grouped.sum()
        if agg == "mean":
            return grouped.mean()
        if agg == "count":
            return grouped.count()
        return grouped.sum()


_ALLOWED_TYPES = {"bar", "line", "scatter", "hist", "pie"}
_ALLOWED_AGGS = {None, "sum", "mean", "count"}
_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ChartTool:
    """Render a SQLite table to a PNG. Returns the standard tool envelope."""

    def render(
        self,
        db_path: str,
        source_table: str,
        chart_type: str,
        x: str,
        y: list[str],
        title: str,
        out_path: str,
        agg: str | None = None,
    ) -> dict[str, Any]:
        if chart_type not in _ALLOWED_TYPES:
            return {
                "success": False,
                "output": None,
                "error": f"unknown chart_type {chart_type!r}",
            }
        if agg not in _ALLOWED_AGGS:
            return {
                "success": False,
                "output": None,
                "error": f"unknown agg {agg!r}",
            }
        if not _TABLE_NAME_RE.match(source_table):
            return {
                "success": False,
                "output": None,
                "error": f"invalid source_table {source_table!r}",
            }
        try:
            with sqlite3.connect(db_path) as cx:
                # Try source_table as-is first, then with t_ prefix as fallback
                candidates = [source_table]
                if not source_table.startswith("t_"):
                    candidates.append(f"t_{source_table}")
                df = None
                last_err: Exception | None = None
                for tbl in candidates:
                    try:
                        df = pd.read_sql_query(f"SELECT * FROM {tbl}", cx)
                        break
                    except Exception as e:
                        last_err = e
                if df is None:
                    raise last_err  # type: ignore[misc]
        except Exception as e:
            return {
                "success": False,
                "output": None,
                "error": f"sql read failed: {e}",
            }

        if agg and chart_type not in {"hist", "pie"}:
            df = df.groupby(x, as_index=False).agg({col: agg for col in y})

        sns.set_theme(style="whitegrid")
        fig, ax = plt.subplots(figsize=(8, 5), dpi=120)
        try:
            if chart_type == "bar":
                df.plot(kind="bar", x=x, y=y, ax=ax, legend=len(y) > 1)
            elif chart_type == "line":
                df.plot(kind="line", x=x, y=y, ax=ax, marker="o", legend=len(y) > 1)
            elif chart_type == "scatter":
                ax.scatter(df[x], df[y[0]])
                ax.set_xlabel(x)
                ax.set_ylabel(y[0])
            elif chart_type == "hist":
                ax.hist(df[y[0]].dropna(), bins=20)
                ax.set_xlabel(y[0])
            elif chart_type == "pie":
                ax.pie(df[y[0]], labels=df[x].astype(str), autopct="%1.1f%%")
            ax.set_title(title)
            fig.tight_layout()
            fig.savefig(out_path)
            width = int(fig.get_figwidth() * fig.dpi)
            height = int(fig.get_figheight() * fig.dpi)
        finally:
            plt.close(fig)

        return {
            "success": True,
            "output": {
                "path": out_path,
                "width": width,
                "height": height,
                "rows_plotted": int(len(df)),
            },
            "error": None,
        }
