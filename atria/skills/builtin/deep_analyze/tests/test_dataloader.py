"""Dataloader phase: file -> SQLite + schema profile."""

import sqlite3
from pathlib import Path

import pytest

from atria.skills.builtin.deep_analyze.dataloader import load_to_sqlite, profile_schema
from atria.skills.builtin.deep_analyze.validation import AnalyzeValidationError


@pytest.fixture
def sales_csv(tmp_path: Path) -> Path:
    p = tmp_path / "sales.csv"
    p.write_text(
        "order_date,region,revenue\n"
        "2025-01-04,NA,120.5\n"
        "2025-01-04,EU,80.0\n"
        "2025-01-05,APAC,200.0\n"
    )
    return p


def test_load_csv_into_raw_table(sales_csv: Path, tmp_path: Path) -> None:
    db = tmp_path / "data.db"
    rows = load_to_sqlite(sales_csv, db)
    assert rows == 3
    with sqlite3.connect(db) as cx:
        n = cx.execute("SELECT COUNT(*) FROM raw").fetchone()[0]
    assert n == 3


def test_rejects_too_many_rows(tmp_path: Path) -> None:
    p = tmp_path / "huge.csv"
    p.write_text("a\n" + "1\n" * 100_001)
    with pytest.raises(AnalyzeValidationError, match="row"):
        load_to_sqlite(p, tmp_path / "data.db")


def test_profile_schema_extracts_dtypes_and_samples(sales_csv: Path, tmp_path: Path) -> None:
    db = tmp_path / "data.db"
    load_to_sqlite(sales_csv, db)
    profile = profile_schema(db, file_name=sales_csv.name)
    assert profile["file_name"] == "sales.csv"
    assert profile["row_count"] == 3
    col_names = [c["name"] for c in profile["columns"]]
    assert col_names == ["order_date", "region", "revenue"]
    revenue = next(c for c in profile["columns"] if c["name"] == "revenue")
    assert revenue["dtype"] in {"float", "int"}
    assert "min" in revenue and "max" in revenue
