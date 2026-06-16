"""Tests for the 'data' module template: binary writes, xlsx→csv, scaffolding."""

from __future__ import annotations

import io

import pytest

from atria.core.modules import store
from atria.core.modules.xlsx_convert import xlsx_to_csvs


def _make_xlsx(sheets: dict[str, list[list]]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_create_data_module_scaffolds_tile_files(tmp_path):
    m = store.create_module(tmp_path, "demo", template="data", summary="x")
    assert "dashboard.html" in m.files  # makes it show as a tile
    assert "scripts/data.py" in m.files
    assert "manifest.json" in m.files
    assert (tmp_path / "demo" / "data").is_dir()


def test_xlsx_to_csvs_multisheet():
    xlsx = _make_xlsx(
        {
            "Cups": [["Year", "Winner"], [2018, "France"]],
            "Players": [["Name"], ["Mbappe"]],
        }
    )
    out = xlsx_to_csvs(xlsx, "wc")
    names = sorted(n for n, _ in out)
    assert names == ["wc__cups.csv", "wc__players.csv"]


def test_xlsx_to_csvs_single_sheet():
    xlsx = _make_xlsx({"Only": [["a", "b"], [1, 2]]})
    out = xlsx_to_csvs(xlsx, "single")
    assert [n for n, _ in out] == ["single.csv"]


def test_write_data_files_writes_under_data_and_regenerates_skill(tmp_path):
    store.create_module(tmp_path, "demo", template="data")
    written = store.write_data_files(
        tmp_path, "demo", [("Sub Folder/a.csv", b"x,y\n1,2\n")]
    )
    assert written == ["data/Sub Folder/a.csv"]
    assert (tmp_path / "demo" / "data" / "Sub Folder" / "a.csv").is_file()
    store.regenerate_data_skill(tmp_path, "demo")
    skill = (tmp_path / "demo" / "SKILL.md").read_text(encoding="utf-8")
    assert "### Datasets" in skill and "a.csv" in skill


def test_write_data_files_rejects_traversal(tmp_path):
    store.create_module(tmp_path, "demo", template="data")
    with pytest.raises(ValueError):
        store.write_data_files(tmp_path, "demo", [("../escape.txt", b"x")])


def test_write_data_files_enforces_depth(tmp_path):
    store.create_module(tmp_path, "demo", template="data")
    # data/ + 4 nested dirs + file exceeds _MAX_DEPTH
    deep = "/".join(["d"] * (store._MAX_DEPTH + 1)) + "/f.csv"
    with pytest.raises(ValueError):
        store.write_data_files(tmp_path, "demo", [(deep, b"x")])
