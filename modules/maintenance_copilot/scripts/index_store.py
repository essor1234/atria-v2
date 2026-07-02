# modules/maintenance_copilot/scripts/index_store.py
"""Qdrant-backed vector index for manual chunks.

Embeds chunk text with an injected ``embed_fn`` (production: TEI via the
``index_embed`` role) and stores one point per chunk with its full metadata
payload. Queries are version-aware: by default only the latest indexed revision
per ``doc_type`` is searched.
"""

from __future__ import annotations

import re
import uuid
from typing import Callable, Dict, List, Optional

from qdrant_client import QdrantClient, models

COLLECTION = "manual_chunks"

# Fixed namespace so uuid5(citation) is stable across processes → idempotent re-index.
_POINT_NS = uuid.UUID("6f6b1e2a-1c1a-4f2b-9a3e-2b0c7c9d4e11")

EmbedFn = Callable[[List[str]], List[List[float]]]


def _revision_key(revision: str) -> tuple[int, str]:
    """Sort key for revision strings: numeric suffix first, then the raw string.

    Extracts the last run of digits (e.g. 'Rev-42' -> 42) so 'Rev-42' > 'Rev-9'.
    Falls back to (-1, revision) when no digits are present.
    """
    matches = re.findall(r"\d+", revision)
    return (int(matches[-1]) if matches else -1, revision)


class IndexStore:
    """Create/populate/query the ``manual_chunks`` collection."""

    def __init__(self, qdrant: QdrantClient, embed_fn: EmbedFn, collection: str = COLLECTION):
        self._q = qdrant
        self._embed = embed_fn
        self._collection = collection

    def ensure_collection(self, dim: int) -> None:
        """Create the collection with cosine distance if it does not exist."""
        if self._q.collection_exists(self._collection):
            return
        self._q.create_collection(
            collection_name=self._collection,
            vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
        )

    def upsert_chunks(self, records: List[object]) -> int:
        """Embed and upsert one point per record. Returns the number stored.

        Point ids are a stable ``uuid5`` of the citation, so re-indexing the
        same chunk (even in a new process) updates in place rather than
        duplicating.

        ``records`` must be ``ChunkRecord`` instances; the parameter is typed
        ``List[object]`` to avoid a sibling-module import at the package boundary.
        """
        if not records:
            return 0
        vectors = self._embed([r.text for r in records])  # type: ignore[attr-defined]
        points = [
            models.PointStruct(
                id=str(uuid.uuid5(_POINT_NS, rec.citation)),  # type: ignore[attr-defined]
                vector=vec,
                payload={
                    "chunk_id": rec.chunk_id,          # type: ignore[attr-defined]
                    "text": rec.text,                  # type: ignore[attr-defined]
                    "doc_type": rec.doc_type,          # type: ignore[attr-defined]
                    "title": rec.title,                # type: ignore[attr-defined]
                    "revision": rec.revision,          # type: ignore[attr-defined]
                    "ata_chapter": rec.ata_chapter,    # type: ignore[attr-defined]
                    "source_path": rec.source_path,    # type: ignore[attr-defined]
                    "citation": rec.citation,          # type: ignore[attr-defined]
                },
            )
            for rec, vec in zip(records, vectors)
        ]
        self._q.upsert(collection_name=self._collection, points=points, wait=True)
        return len(points)

    def _latest_revision_by_doctype(self) -> Dict[str, str]:
        """Scan payloads to find the max revision string per doc_type."""
        latest: Dict[str, str] = {}
        offset = None
        while True:
            recs, offset = self._q.scroll(
                collection_name=self._collection, with_payload=True, limit=256, offset=offset
            )
            for r in recs:
                dt = r.payload["doc_type"]
                rev = r.payload["revision"]
                if dt not in latest or _revision_key(rev) > _revision_key(latest[dt]):
                    latest[dt] = rev
            if offset is None:
                break
        return latest

    def query(
        self,
        text: str,
        k: int = 5,
        ata_chapter: Optional[str] = None,
        revision: Optional[str] = "current",
    ) -> List[Dict]:
        """Embed ``text`` and return the top-``k`` filtered hits.

        Args:
            text: The query text.
            k: Max hits to return.
            ata_chapter: If set, restrict to this ATA chapter.
            revision: ``"current"`` (latest per doc_type), a specific revision
                string, or ``None`` for no revision filter.

        Returns:
            Hit dicts with score, citation, text, and metadata.
        """
        must: List[models.FieldCondition] = []
        if ata_chapter is not None:
            must.append(
                models.FieldCondition(
                    key="ata_chapter", match=models.MatchValue(value=ata_chapter)
                )
            )
        should_current = revision == "current"
        if revision is not None and not should_current:
            must.append(
                models.FieldCondition(key="revision", match=models.MatchValue(value=revision))
            )
        vector = self._embed([text])[0]
        result = self._q.query_points(
            collection_name=self._collection,
            query=vector,
            limit=k if not should_current else k * 4,  # over-fetch so post-filtering superseded hits can still yield k
            query_filter=models.Filter(must=must) if must else None,
        )
        latest = self._latest_revision_by_doctype() if should_current else {}
        hits: List[Dict] = []
        for point in result.points:
            p = point.payload
            if should_current and p["revision"] != latest.get(p["doc_type"]):
                continue
            hits.append(
                {
                    "score": point.score,
                    "citation": p["citation"],
                    "text": p["text"],
                    "doc_type": p["doc_type"],
                    "revision": p["revision"],
                    "ata_chapter": p["ata_chapter"],
                    "chunk_id": p["chunk_id"],
                }
            )
            if len(hits) >= k:
                break
        return hits

    def list_indexed(self) -> Dict:
        """Return the point count and the latest revision per doc_type."""
        count = self._q.count(collection_name=self._collection).count
        return {"count": count, "latest_revision": self._latest_revision_by_doctype()}

    def reset(self) -> None:
        """Delete the collection if it exists."""
        if self._q.collection_exists(self._collection):
            self._q.delete_collection(self._collection)
