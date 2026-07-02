"""Tests for editable-dataset read/write: round-trip, backup, validation."""

from __future__ import annotations

import pytest

from atria.core.modules import store


def _seed(tmp_path):
    store.create_module(tmp_path, "demo", template="data")
    store.write_data_files(tmp_path, "demo", [("wc.csv", b"Year,Winner\n2018,France\n2022,Argentina\n")])
    return tmp_path


def test_read_dataset_shape(tmp_path):
    _seed(tmp_path)
    data = store.read_dataset(tmp_path, "demo", "wc.csv")
    assert data["file"] == "data/wc.csv"
    assert [c["name"] for c in data["columns"]] == ["Year", "Winner"]
    assert data["rows"] == [
        {"Year": "2018", "Winner": "France"},
        {"Year": "2022", "Winner": "Argentina"},
    ]


def test_write_dataset_round_trips_and_preserves_header_order(tmp_path):
    _seed(tmp_path)
    new_rows = [
        {"Year": "2018", "Winner": "France"},
        {"Year": "2026", "Winner": "TBD"},  # edited + added
    ]
    res = store.write_dataset(
        tmp_path, "demo", "wc.csv", [{"name": "Year"}, {"name": "Winner"}], new_rows
    )
    assert res["written"] == "data/wc.csv"
    assert res["rows"] == 2
    back = store.read_dataset(tmp_path, "demo", "wc.csv")
    assert [c["name"] for c in back["columns"]] == ["Year", "Winner"]
    assert back["rows"] == new_rows


def test_write_dataset_accepts_plain_string_columns(tmp_path):
    _seed(tmp_path)
    store.write_dataset(tmp_path, "demo", "wc.csv", ["Year", "Winner"], [{"Year": "1", "Winner": "x"}])
    back = store.read_dataset(tmp_path, "demo", "wc.csv")
    assert back["rows"] == [{"Year": "1", "Winner": "x"}]


def test_write_dataset_tolerates_data_prefix(tmp_path):
    # source.file from read_dataset is "data/wc.csv"; writing it back must resolve
    # to the SAME file, never data/data/wc.csv (the sync bug).
    _seed(tmp_path)
    store.write_dataset(tmp_path, "demo", "data/wc.csv", ["Year", "Winner"], [{"Year": "1", "Winner": "x"}])
    assert (tmp_path / "demo" / "data" / "wc.csv").is_file()
    assert not (tmp_path / "demo" / "data" / "data").exists()
    assert store.read_dataset(tmp_path, "demo", "data/wc.csv")["rows"] == [{"Year": "1", "Winner": "x"}]


def test_write_dataset_creates_backup(tmp_path):
    _seed(tmp_path)
    store.write_dataset(tmp_path, "demo", "wc.csv", ["Year", "Winner"], [{"Year": "9", "Winner": "z"}])
    assert (tmp_path / "demo" / "data" / "wc.csv.bak").is_file()


def test_write_dataset_rejects_traversal(tmp_path):
    _seed(tmp_path)
    with pytest.raises(ValueError):
        store.write_dataset(tmp_path, "demo", "../escape.csv", ["a"], [{"a": "1"}])


def test_write_dataset_rejects_non_csv(tmp_path):
    _seed(tmp_path)
    with pytest.raises(ValueError):
        store.write_dataset(tmp_path, "demo", "notes.txt", ["a"], [{"a": "1"}])


def test_write_dataset_rejects_too_many_rows(tmp_path):
    _seed(tmp_path)
    too_many = [{"a": "1"}] * (store._MAX_DATA_ROWS + 1)
    with pytest.raises(ValueError):
        store.write_dataset(tmp_path, "demo", "wc.csv", ["a"], too_many)


def test_read_dataset_missing_file_raises(tmp_path):
    _seed(tmp_path)
    with pytest.raises(FileNotFoundError):
        store.read_dataset(tmp_path, "demo", "nope.csv")


def test_send_editable_table_builds_payload(tmp_path, monkeypatch):
    _seed(tmp_path)
    from atria.core.modules import registry
    from atria.core.context_engineering.tools.implementations.send_editable_table_tool import (
        SendEditableTableHandler,
    )

    reg = registry.ModuleRegistry(tmp_path)
    reg.load_all()
    monkeypatch.setattr(registry, "get_registry", lambda: reg)

    captured = {}

    class FakeUI:
        def on_data(self, payload):
            captured["payload"] = payload

    class Ctx:
        ui_callback = FakeUI()

    res = SendEditableTableHandler().send(
        {"module": "demo", "file": "wc.csv", "title": "World Cups"}, Ctx()
    )
    assert res["success"] is True
    payload = captured["payload"]
    assert payload["editable"] is True
    # source.file is data/-relative so the frontend can round-trip it back to the
    # read/write routes without re-prefixing into data/data/...
    assert payload["source"] == {"module": "demo", "file": "wc.csv"}
    assert all(c["editable"] is True for c in payload["columns"])
    assert res["data_payload"]["editable"] is True


def test_send_editable_table_respects_editable_columns_whitelist(tmp_path, monkeypatch):
    _seed(tmp_path)
    from atria.core.modules import registry
    from atria.core.context_engineering.tools.implementations.send_editable_table_tool import (
        SendEditableTableHandler,
    )

    reg = registry.ModuleRegistry(tmp_path)
    reg.load_all()
    monkeypatch.setattr(registry, "get_registry", lambda: reg)

    captured = {}

    class FakeUI:
        def on_data(self, payload):
            captured["payload"] = payload

    class Ctx:
        ui_callback = FakeUI()

    SendEditableTableHandler().send(
        {"module": "demo", "file": "wc.csv", "title": "WC", "editable_columns": ["Winner"]},
        Ctx(),
    )
    cols = {c["name"]: c["editable"] for c in captured["payload"]["columns"]}
    assert cols == {"Year": False, "Winner": True}


def test_send_editable_table_missing_dataset_errors(tmp_path, monkeypatch):
    _seed(tmp_path)
    from atria.core.modules import registry
    from atria.core.context_engineering.tools.implementations.send_editable_table_tool import (
        SendEditableTableHandler,
    )

    reg = registry.ModuleRegistry(tmp_path)
    reg.load_all()
    monkeypatch.setattr(registry, "get_registry", lambda: reg)

    class Ctx:
        ui_callback = type("U", (), {"on_data": staticmethod(lambda p: None)})()

    res = SendEditableTableHandler().send(
        {"module": "demo", "file": "missing.csv", "title": "X"}, Ctx()
    )
    assert res["success"] is False
