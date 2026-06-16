"""Unit tests for the send_data tool."""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from atria.core.context_engineering.tools.implementations.send_data_tool import (
    SendDataHandler,
)


FIXTURES = Path(__file__).parent / "fixtures" / "data"
CSV_PATH = FIXTURES / "sales.csv"
XLSX_PATH = FIXTURES / "sales.xlsx"


class FakeUICallback:
    """Captures on_data payloads for assertions."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def on_data(self, payload: dict[str, Any]) -> None:
        self.payloads.append(payload)


@pytest.fixture(scope="module", autouse=True)
def _ensure_xlsx_fixture() -> None:
    """Generate the XLSX fixture once per test session if absent."""
    if XLSX_PATH.exists():
        return
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["month", "revenue", "units", "in_stock"])
    ws.append(["Jan", 1000.5, 10, True])
    ws.append(["Feb", 1500, 20, True])
    ws.append(["Mar", 2000.25, 15, False])
    ws.append(["Apr", 1750, 18, True])
    ws.append(["May", 2200, 22, False])
    wb.save(XLSX_PATH)
    wb.close()


def _ctx_with_callback() -> tuple[Any, FakeUICallback]:
    cb = FakeUICallback()
    return SimpleNamespace(ui_callback=cb), cb


def _default_suggestion() -> list[dict[str, Any]]:
    return [{"chart_type": "bar", "x": "month", "y": ["revenue"], "title": "Rev by month"}]


def test_happy_path_csv() -> None:
    handler = SendDataHandler()
    ctx, cb = _ctx_with_callback()
    result = handler.send(
        {
            "path": str(CSV_PATH),
            "title": "Sales",
            "suggestions": _default_suggestion(),
        },
        ctx,
    )

    assert result["success"] is True, result
    assert len(cb.payloads) == 1
    payload = cb.payloads[0]
    assert payload["title"] == "Sales"
    assert len(payload["rows"]) == 5
    names = {c["name"]: c["type"] for c in payload["columns"]}
    assert names["month"] == "string"
    assert names["revenue"] == "number"
    assert names["units"] == "number"
    assert names["in_stock"] == "bool"
    first = payload["rows"][0]
    assert first["month"] == "Jan"
    assert first["revenue"] == 1000.5
    assert first["units"] == 10.0
    assert first["in_stock"] is True
    assert "warning" not in payload


def test_happy_path_xlsx() -> None:
    handler = SendDataHandler()
    ctx, cb = _ctx_with_callback()
    result = handler.send(
        {
            "path": str(XLSX_PATH),
            "title": "Sales XLSX",
            "suggestions": _default_suggestion(),
        },
        ctx,
    )
    assert result["success"] is True, result
    assert len(cb.payloads) == 1
    payload = cb.payloads[0]
    assert len(payload["rows"]) == 5
    names = {c["name"]: c["type"] for c in payload["columns"]}
    assert names["revenue"] == "number"
    assert names["in_stock"] == "bool"


def test_both_path_and_url_errors() -> None:
    handler = SendDataHandler()
    ctx, _ = _ctx_with_callback()
    result = handler.send(
        {
            "path": str(CSV_PATH),
            "url": "https://example.com/x.csv",
            "title": "x",
            "suggestions": _default_suggestion(),
        },
        ctx,
    )
    assert result["success"] is False
    assert "exactly one" in result["error"]


def test_neither_path_nor_url_errors() -> None:
    handler = SendDataHandler()
    ctx, _ = _ctx_with_callback()
    result = handler.send(
        {"title": "x", "suggestions": _default_suggestion()},
        ctx,
    )
    assert result["success"] is False
    assert "exactly one" in result["error"]


def test_path_not_absolute_errors() -> None:
    handler = SendDataHandler()
    ctx, _ = _ctx_with_callback()
    result = handler.send(
        {"path": "relative/sales.csv", "title": "x", "suggestions": _default_suggestion()},
        ctx,
    )
    assert result["success"] is False
    assert "absolute" in result["error"].lower()


def test_missing_file_errors(tmp_path: Path) -> None:
    handler = SendDataHandler()
    ctx, _ = _ctx_with_callback()
    bogus = tmp_path / "missing.csv"
    result = handler.send(
        {"path": str(bogus), "title": "x", "suggestions": _default_suggestion()}, ctx
    )
    assert result["success"] is False
    assert "not found" in result["error"].lower()


def test_url_non_http_errors() -> None:
    handler = SendDataHandler()
    ctx, _ = _ctx_with_callback()
    result = handler.send(
        {"url": "ftp://example.com/x.csv", "title": "x", "suggestions": _default_suggestion()},
        ctx,
    )
    assert result["success"] is False
    assert "http" in result["error"].lower()


def test_bad_extension_errors(tmp_path: Path) -> None:
    handler = SendDataHandler()
    ctx, _ = _ctx_with_callback()
    p = tmp_path / "data.txt"
    p.write_text("a,b\n1,2\n")
    result = handler.send({"path": str(p), "title": "x", "suggestions": _default_suggestion()}, ctx)
    assert result["success"] is False
    assert "extension" in result["error"].lower() or "unsupported" in result["error"].lower()


def test_zero_row_file_errors(tmp_path: Path) -> None:
    handler = SendDataHandler()
    ctx, _ = _ctx_with_callback()
    p = tmp_path / "empty.csv"
    p.write_text("a,b\n")
    result = handler.send(
        {
            "path": str(p),
            "title": "x",
            "suggestions": [{"chart_type": "bar", "x": "a", "y": ["b"]}],
        },
        ctx,
    )
    assert result["success"] is False


def test_suggestion_unknown_column_errors() -> None:
    handler = SendDataHandler()
    ctx, _ = _ctx_with_callback()
    result = handler.send(
        {
            "path": str(CSV_PATH),
            "title": "Sales",
            "suggestions": [{"chart_type": "bar", "x": "month", "y": ["nonexistent"]}],
        },
        ctx,
    )
    assert result["success"] is False
    assert "unknown column" in result["error"].lower()


def test_missing_ui_callback_errors() -> None:
    handler = SendDataHandler()
    ctx = SimpleNamespace(ui_callback=None)
    result = handler.send(
        {"path": str(CSV_PATH), "title": "x", "suggestions": _default_suggestion()}, ctx
    )
    assert result["success"] is False
    assert "callback" in result["error"].lower()


def test_row_count_exceeded_truncates(tmp_path: Path) -> None:
    handler = SendDataHandler()
    ctx, cb = _ctx_with_callback()
    p = tmp_path / "big.csv"
    lines = ["a,b"]
    for i in range(10_005):
        lines.append(f"x{i},{i}")
    p.write_text("\n".join(lines) + "\n")

    result = handler.send(
        {
            "path": str(p),
            "title": "Big",
            "suggestions": [{"chart_type": "bar", "x": "a", "y": ["b"]}],
        },
        ctx,
    )
    assert result["success"] is True
    assert "warning" in result
    assert len(cb.payloads[0]["rows"]) == 10_000
    assert "Row count" in cb.payloads[0]["warning"]


def test_col_count_exceeded_truncates(tmp_path: Path) -> None:
    handler = SendDataHandler()
    ctx, cb = _ctx_with_callback()
    p = tmp_path / "wide.csv"
    n = 55
    header = ",".join(f"c{i}" for i in range(n))
    row = ",".join(str(i) for i in range(n))
    p.write_text(f"{header}\n{row}\n{row}\n")

    result = handler.send(
        {
            "path": str(p),
            "title": "Wide",
            "suggestions": [{"chart_type": "bar", "x": "c0", "y": ["c1"]}],
        },
        ctx,
    )
    assert result["success"] is True
    assert "warning" in result
    assert len(cb.payloads[0]["columns"]) == 50
    assert "Column count" in cb.payloads[0]["warning"]


def test_type_inference_all_types(tmp_path: Path) -> None:
    handler = SendDataHandler()
    ctx, cb = _ctx_with_callback()
    p = tmp_path / "types.csv"
    p.write_text(
        "name,score,when,active\n"
        "alice,1.5,2024-01-01,true\n"
        "bob,2,2024-02-15,false\n"
        "carol,3.25,2024-03-30,1\n"
    )
    result = handler.send(
        {
            "path": str(p),
            "title": "Types",
            "suggestions": [{"chart_type": "bar", "x": "name", "y": ["score"]}],
        },
        ctx,
    )
    assert result["success"] is True
    cols = {c["name"]: c["type"] for c in cb.payloads[0]["columns"]}
    assert cols["name"] == "string"
    assert cols["score"] == "number"
    assert cols["when"] == "date"
    assert cols["active"] == "bool"
    rows = cb.payloads[0]["rows"]
    assert rows[0]["score"] == 1.5
    assert rows[0]["when"] == "2024-01-01"
    assert rows[0]["active"] is True
    assert rows[2]["active"] is True  # "1" -> True


# ---------------- URL tests ----------------


def _httpx_mock(data: bytes, content_type: str = "text/csv"):
    """Patch ``send_data_tool.httpx.stream`` so the response body is ``data``."""
    import httpx

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": content_type}, content=data)

    transport = httpx.MockTransport(_handler)

    def _patched_stream(method: str, url: str, **kwargs: Any):
        kwargs.pop("follow_redirects", None)
        timeout = kwargs.pop("timeout", None)
        client = httpx.Client(transport=transport, timeout=timeout)
        return client.stream(method, url, **kwargs)

    return patch(
        "atria.core.context_engineering.tools.implementations.send_data_tool.httpx.stream",
        side_effect=_patched_stream,
    )


def test_url_happy_path_csv() -> None:
    handler = SendDataHandler()
    ctx, cb = _ctx_with_callback()
    csv_bytes = CSV_PATH.read_bytes()

    with _httpx_mock(csv_bytes, "text/csv"):
        result = handler.send(
            {
                "url": "https://example.com/sales.csv",
                "title": "Remote",
                "suggestions": _default_suggestion(),
            },
            ctx,
        )

    assert result["success"] is True, result
    assert len(cb.payloads) == 1
    assert len(cb.payloads[0]["rows"]) == 5


def test_url_size_limit_aborts() -> None:
    handler = SendDataHandler()
    ctx, _ = _ctx_with_callback()
    # 11 MB of CSV-looking bytes
    big = b"a,b\n" + (b"x,1\n" * (3 * 1024 * 1024))
    assert len(big) > 10 * 1024 * 1024

    with _httpx_mock(big, "text/csv"):
        result = handler.send(
            {
                "url": "https://example.com/big.csv",
                "title": "Big",
                "suggestions": [{"chart_type": "bar", "x": "a", "y": ["b"]}],
            },
            ctx,
        )
    assert result["success"] is False
    assert "exceed" in result["error"].lower()
