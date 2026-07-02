"""Parse maintenance documents into structured Document records.

A source file starts with a ``---``-delimited front-matter block declaring
``doc_type``, ``title``, ``revision``, ``effective_date``, and ``ata_chapter``,
followed by the document body. Only ``.md`` / ``.txt`` are handled in the pilot.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
_REQUIRED = ("doc_type", "title", "revision", "effective_date", "ata_chapter")


@dataclass(frozen=True)
class Document:
    """A parsed maintenance document: front-matter metadata plus body text."""

    doc_type: str
    title: str
    revision: str
    effective_date: str
    ata_chapter: str
    path: str
    text: str


def _split_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    """Return (metadata, body). Front-matter is a leading ``---`` ... ``---`` block."""
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, raw
    meta: dict[str, str] = {}
    body_start = len(lines)
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            body_start = i + 1
            break
        key, sep, value = lines[i].partition(":")
        if sep:
            meta[key.strip()] = value.strip().strip('"').strip("'")
    body = "\n".join(lines[body_start:]).lstrip("\n")
    return meta, body


def parse_document(path: str) -> Document:
    """Parse a single ``.md``/``.txt`` file into a :class:`Document`.

    Args:
        path: Filesystem path to the document.

    Returns:
        The parsed document.

    Raises:
        ValueError: If a required front-matter key is missing.
    """
    raw = Path(path).read_text(encoding="utf-8")
    meta, body = _split_frontmatter(raw)
    for key in _REQUIRED:
        if key not in meta:
            raise ValueError(f"{path}: missing front-matter key {key!r}")
    return Document(
        doc_type=meta["doc_type"],
        title=meta["title"],
        revision=meta["revision"],
        effective_date=meta["effective_date"],
        ata_chapter=str(meta["ata_chapter"]),
        path=path,
        text=body,
    )


def load_corpus(root: str) -> list[Document]:
    """Parse every ``.md``/``.txt`` directly under ``root``, sorted by filename."""
    paths = sorted(
        p for p in Path(root).iterdir()
        if p.suffix in (".md", ".txt") and p.is_file()
    )
    return [parse_document(str(p)) for p in paths]
