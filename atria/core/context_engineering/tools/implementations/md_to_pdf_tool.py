"""markdown_to_pdf tool — convert .md to a styled PDF via WeasyPrint."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import markdown as md_lib

try:
    from weasyprint import HTML, CSS

    WEASYPRINT_AVAILABLE = True
    _WEASYPRINT_IMPORT_ERROR: str | None = None
except (OSError, ImportError) as e:
    HTML = None  # type: ignore[assignment,misc]
    CSS = None  # type: ignore[assignment,misc]
    WEASYPRINT_AVAILABLE = False
    _WEASYPRINT_IMPORT_ERROR = (
        f"WeasyPrint native dependencies missing ({e}). "
        "On macOS: `brew install pango`. On Debian/Ubuntu: "
        "`apt-get install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0`."
    )


_DEFAULT_CSS = Path(__file__).parent / "assets" / "report.css"


def _fail(msg: str) -> dict[str, Any]:
    return {"success": False, "output": None, "error": msg}


def _ok(output: dict[str, Any]) -> dict[str, Any]:
    return {"success": True, "output": output, "error": None}


class MarkdownToPdfHandler:
    """Converts a markdown file to a styled PDF using WeasyPrint."""

    def convert(self, args: dict[str, Any], context: Any) -> dict[str, Any]:
        md_path = (args.get("md_path") or "").strip()
        pdf_path = (args.get("pdf_path") or "").strip()
        css_path = (args.get("css_path") or "").strip() or None

        if not md_path:
            return _fail("'md_path' is required")
        if not pdf_path:
            return _fail("'pdf_path' is required")
        if not pdf_path.lower().endswith(".pdf"):
            return _fail("'pdf_path' must end with .pdf")

        src = Path(md_path)
        if not src.exists():
            return _fail(f"Markdown file not found: {md_path}")

        out = Path(pdf_path)
        if not out.parent.exists():
            return _fail(f"Output directory does not exist: {out.parent}")

        if not WEASYPRINT_AVAILABLE:
            return _fail(_WEASYPRINT_IMPORT_ERROR or "WeasyPrint unavailable")

        css_file = Path(css_path) if css_path else _DEFAULT_CSS
        if css_path and not css_file.exists():
            return _fail(f"CSS file not found: {css_path}")

        try:
            text = src.read_text(encoding="utf-8")
            html_body = md_lib.markdown(
                text,
                extensions=["extra", "tables", "fenced_code", "toc"],
            )
            html_doc = (
                "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
                f"<body>{html_body}</body></html>"
            )
            html = HTML(string=html_doc, base_url=str(src.parent))
            css = CSS(filename=str(css_file)) if css_file.exists() else None
            stylesheets = [css] if css else []
            doc = html.render(stylesheets=stylesheets)
            doc.write_pdf(str(out))
        except Exception as e:
            return _fail(f"PDF generation failed: {e}")

        return _ok(
            {
                "path": str(out),
                "bytes": out.stat().st_size,
                "pages": len(doc.pages),
            }
        )


_CSS = """
@page { size: A4; margin: 1.5cm; }
body { font-family: -apple-system, "Segoe UI", Arial, sans-serif; line-height: 1.45; }
h1 { font-size: 22pt; margin-bottom: 0.4em; }
h2 { font-size: 16pt; margin-top: 1.2em; }
img { max-width: 100%; }
code, pre { background: #f5f5f5; padding: 2px 4px; border-radius: 3px; }
"""


class MdToPdfTool:
    """Render a markdown file to a PDF (simple API used by the report phase)."""

    def render(self, md_path: str, pdf_path: str) -> dict[str, Any]:
        src = Path(md_path)
        if not src.exists():
            return {
                "success": False,
                "output": None,
                "error": f"markdown not found: {md_path}",
            }
        if not WEASYPRINT_AVAILABLE:
            return {
                "success": False,
                "output": None,
                "error": _WEASYPRINT_IMPORT_ERROR or "WeasyPrint unavailable",
            }
        html_body = md_lib.markdown(
            src.read_text(encoding="utf-8"),
            extensions=["fenced_code", "tables"],
        )
        html_doc = f"<html><head><style>{_CSS}</style></head><body>{html_body}</body></html>"
        try:
            HTML(string=html_doc, base_url=str(src.parent)).write_pdf(pdf_path)
        except Exception as e:
            return {
                "success": False,
                "output": None,
                "error": f"weasyprint failed: {e}",
            }
        return {
            "success": True,
            "output": {"pdf_path": pdf_path, "pages": None},
            "error": None,
        }
