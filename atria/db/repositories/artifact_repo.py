"""CRUD for the artifacts table."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from atria.db.models import Artifact
from atria.db.repositories.base import BaseRepository


def _flatten(model_instance) -> dict:
    return {c.name: getattr(model_instance, c.name) for c in model_instance.__table__.columns}


class ArtifactRepository(BaseRepository):

    async def create(
        self,
        project_id: Optional[int],
        type: str,
        conversation_id: Optional[int] = None,
        title: Optional[str] = None,
        payload_ref: Optional[str] = None,
        preview: Optional[Any] = None,
        source_mode: Optional[str] = None,
        pinned: bool = False,
        scope: Optional[str] = None,
        local_path: Optional[str] = None,
    ) -> int:
        async with self._sessionmaker() as session:
            stmt = (
                pg_insert(Artifact)
                .values(
                    is_deleted=False,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    type=type[:20],
                    source_mode=source_mode,
                    title=title,
                    pinned=pinned,
                    payload_ref=payload_ref,
                    preview=preview,
                    scope=scope[:20] if scope else None,
                    local_path=local_path[:512] if local_path else None,
                )
                .returning(Artifact.id)
            )
            result = await session.execute(stmt)
            new_id = int(result.scalar_one())
            await session.commit()
            return new_id

    async def get_by_id(self, artifact_id: int) -> Optional[dict]:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(Artifact).where(Artifact.id == artifact_id, Artifact.is_deleted.is_(False))
            )
            obj = result.scalars().first()
            return _flatten(obj) if obj else None

    async def list_by_conversation(self, conversation_id: int) -> list[dict]:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(Artifact)
                .where(
                    Artifact.conversation_id == conversation_id,
                    Artifact.is_deleted.is_(False),
                )
                .order_by(Artifact.pinned.desc(), Artifact.created_at.desc())
            )
            return [_flatten(obj) for obj in result.scalars().all()]

    async def list_by_project(self, project_id: int) -> list[dict]:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(Artifact)
                .where(
                    Artifact.project_id == project_id,
                    Artifact.is_deleted.is_(False),
                )
                .order_by(Artifact.pinned.desc(), Artifact.created_at.desc())
            )
            return [_flatten(obj) for obj in result.scalars().all()]

    async def list_by_conversation_and_scope(self, conversation_id: int, scope: str) -> list[dict]:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(Artifact)
                .where(
                    Artifact.conversation_id == conversation_id,
                    Artifact.scope == scope,
                    Artifact.is_deleted.is_(False),
                )
                .order_by(Artifact.pinned.desc(), Artifact.created_at.desc())
            )
            return [_flatten(obj) for obj in result.scalars().all()]

    async def list_by_project_and_scope(self, project_id: int, scope: str) -> list[dict]:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(Artifact)
                .where(
                    Artifact.project_id == project_id,
                    Artifact.scope == scope,
                    Artifact.is_deleted.is_(False),
                )
                .order_by(Artifact.pinned.desc(), Artifact.created_at.desc())
            )
            return [_flatten(obj) for obj in result.scalars().all()]

    async def update(
        self,
        artifact_id: int,
        title: Optional[str] = None,
        pinned: Optional[bool] = None,
        payload_ref: Optional[str] = None,
    ) -> None:
        values: dict = {"updated_at": func.now()}
        if title is not None:
            values["title"] = title
        if pinned is not None:
            values["pinned"] = pinned
        if payload_ref is not None:
            values["payload_ref"] = payload_ref
        async with self._sessionmaker() as session:
            await session.execute(
                update(Artifact).where(Artifact.id == artifact_id).values(**values)
            )
            await session.commit()

    async def soft_delete(self, artifact_id: int) -> bool:
        async with self._sessionmaker() as session:
            stmt = (
                update(Artifact)
                .where(Artifact.id == artifact_id, Artifact.is_deleted.is_(False))
                .values(is_deleted=True, updated_at=func.now())
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

    async def hard_delete(self, artifact_id: int) -> bool:
        """Permanently delete artifact from database.

        Args:
            artifact_id: The artifact ID to delete.

        Returns:
            True if artifact was deleted, False if not found or already deleted.
        """
        async with self._sessionmaker() as session:
            stmt = delete(Artifact).where(Artifact.id == artifact_id)
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

    async def upsert_by_ref(
        self,
        project_id: Optional[int],
        conversation_id: int,
        payload_ref: str,
        type: str,
        title: Optional[str] = None,
        source_mode: str = "auto",
        scope: Optional[str] = None,
        local_path: Optional[str] = None,
    ) -> int:
        async with self._sessionmaker() as session:
            existing = await session.execute(
                select(Artifact.id).where(
                    Artifact.conversation_id == conversation_id,
                    Artifact.payload_ref == payload_ref,
                    Artifact.is_deleted.is_(False),
                )
            )
            row = existing.first()
            if row is not None:
                return int(row.id)
            stmt = (
                pg_insert(Artifact)
                .values(
                    is_deleted=False,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    type=type[:20],
                    source_mode=source_mode,
                    title=title or payload_ref.split("/")[-1],
                    pinned=False,
                    payload_ref=payload_ref,
                    scope=scope[:20] if scope else None,
                    local_path=local_path[:512] if local_path else None,
                )
                .returning(Artifact.id)
            )
            result = await session.execute(stmt)
            new_id = int(result.scalar_one())
            await session.commit()
            return new_id
