"""md_to_pdf: markdown -> PDF via weasyprint."""

from pathlib import Path

import pytest

from atria.core.context_engineering.tools.implementations.md_to_pdf_tool import MdToPdfTool


def _weasyprint_native_libs_available() -> bool:
    try:
        from weasyprint import HTML

        HTML(string="<p>x</p>").write_pdf()
        return True
    except Exception:
        return False


_WEASYPRINT_OK = _weasyprint_native_libs_available()


@pytest.mark.skipif(not _WEASYPRINT_OK, reason="WeasyPrint native libs (pango/cairo) not installed")
def test_renders_simple_markdown(tmp_path: Path) -> None:
    md = tmp_path / "r.md"
    md.write_text("# Report\n\nHello **world**.\n")
    pdf = tmp_path / "r.pdf"
    result = MdToPdfTool().render(str(md), str(pdf))
    assert result["success"], result.get("error")
    assert pdf.exists()
    assert pdf.read_bytes()[:4] == b"%PDF"


def test_missing_markdown_file_returns_error(tmp_path: Path) -> None:
    result = MdToPdfTool().render(str(tmp_path / "missing.md"), str(tmp_path / "x.pdf"))
    assert not result["success"]
    assert "not found" in (result["error"] or "")
