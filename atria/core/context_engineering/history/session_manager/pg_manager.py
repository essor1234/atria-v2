"""PostgreSQL-backed session manager."""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atria.db.connection import get_sessionmaker
from atria.db.models import Message
from atria.db.provisioner import provision
from atria.db.repositories.conversation_repo import ConversationRepository
from atria.db.repositories.message_repo import MessageRepository
from atria.models.message import ChatMessage
from atria.models.session import Session, SessionMetadata

logger = logging.getLogger(__name__)


class PgSessionManager:
    """Async session manager backed by PostgreSQL.

    Satisfies the (async) SessionManagerInterface protocol.
    The sessionmaker is initialised lazily on first async call so that the
    manager can be constructed in a sync context (e.g. get_state()) without
    touching asyncio — the underlying AsyncEngine is always created on the
    live event loop.
    """

    def __init__(
        self,
        sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None,
        working_directory: Optional[str] = None,
    ) -> None:
        self._sm: Optional[async_sessionmaker[AsyncSession]] = sessionmaker
        self._working_directory = working_directory
        self._conv_repo: Optional[ConversationRepository] = None
        self._msg_repo: Optional[MessageRepository] = None
        self.current_session: Optional[Session] = None
        self.turn_count: int = 0
        self._user_id: Optional[int] = None
        self._project_id: Optional[int] = None

    async def _get_repos(self) -> tuple[ConversationRepository, MessageRepository]:
        """Return repos, creating the sessionmaker and repos on first call."""
        if self._sm is None or self._conv_repo is None:
            self._sm = await get_sessionmaker()
            self._conv_repo = ConversationRepository(self._sm)
            self._msg_repo = MessageRepository(self._sm)
        return self._conv_repo, self._msg_repo  # type: ignore[return-value]

    async def _ensure_provisioned(self, working_directory: Optional[str] = None) -> tuple[int, int]:
        """Provision default user/project if not yet done and cache ids."""
        if self._user_id is None or self._project_id is None:
            sm = await get_sessionmaker()
            wd = working_directory or self._working_directory
            self._user_id, self._project_id = await provision(sm, wd)
        return self._user_id, self._project_id

    async def create_session(
        self,
        working_directory: Optional[str] = None,
        channel: str = "cli",
        channel_user_id: str = "",
        chat_type: str = "direct",
        thread_id: Optional[str] = None,
        delivery_context: Optional[dict] = None,
        workspace_confirmed: bool = True,
        owner_id: Optional[str] = None,
        project_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> Session:
        if project_id is not None and user_id is not None:
            p_user_id, p_project_id = user_id, project_id
        elif user_id is not None and project_id is None:
            # Personal session: no project, store user_id directly
            p_user_id, p_project_id = user_id, None
        else:
            p_user_id, p_project_id = await self._ensure_provisioned(working_directory)

        conv_repo, _ = await self._get_repos()
        conv_id = await conv_repo.create(
            project_id=p_project_id,
            user_id=p_user_id,
            title=None,
            mode=channel[:10],
            working_directory=working_directory,
        )
        session = Session(
            id=str(conv_id),
            working_directory=working_directory or self._working_directory,
            channel=channel,
            channel_user_id=channel_user_id,
            chat_type=chat_type,
            thread_id=thread_id,
            delivery_context=delivery_context or {},
            workspace_confirmed=workspace_confirmed,
            owner_id=owner_id,
        )
        self.current_session = session
        self.turn_count = 0
        return session

    async def load_session(self, session_id: str, owner_id: Optional[str] = None) -> Session:
        try:
            conv_id = int(session_id)
        except ValueError:
            raise FileNotFoundError(f"Session {session_id} not found")

        conv_repo, msg_repo = await self._get_repos()
        owner_user_id: Optional[int] = None
        if owner_id:
            try:
                owner_user_id = int(owner_id)
            except (TypeError, ValueError):
                owner_user_id = None
        row = await conv_repo.get_by_id(conv_id, user_id=owner_user_id)
        if row is None:
            raise FileNotFoundError(f"Session {session_id} not found")

        messages = await msg_repo.list_by_conversation(conv_id)
        row_user_id = row["user_id"]
        _meta: dict = {"title": row["title"]} if row["title"] else {}
        session = Session(
            id=str(row["id"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"] or row["created_at"],
            messages=messages,
            channel=row["mode"],
            metadata=_meta,
            working_directory=row["working_directory"],
            owner_id=str(row_user_id) if row_user_id is not None else None,
        )
        if row["is_deleted"]:
            session.archive()

        if owner_id and session.owner_id != owner_id:
            raise FileNotFoundError(f"Session {session_id} not found")

        self.current_session = session
        self.turn_count = len(messages)
        return session

    async def save_session(
        self,
        session: Optional[Session] = None,
        force: bool = False,
        **_kwargs: object,
    ) -> None:
        session = session or self.current_session
        if not session:
            return
        if not force and not session.messages:
            return

        try:
            conv_id = int(session.id)
        except ValueError:
            return

        title = session.metadata.get("title")
        if not title and session.messages:
            for m in session.messages:
                if m.role.value == "user" and m.content:
                    title = m.content[:50].split(".")[0].strip()
                    break

        conv_repo, msg_repo = await self._get_repos()
        await conv_repo.update(conv_id, title=title)

        # Only insert messages that aren't yet persisted (track by count)
        sm = await get_sessionmaker()
        async with sm() as db:
            result = await db.execute(
                select(func.count(Message.id)).where(
                    Message.conversation_id == conv_id,
                    Message.is_deleted.is_(False),
                )
            )
            existing_count = int(result.scalar_one() or 0)

        mode = session.metadata.get("mode", "normal")
        for i, msg in enumerate(session.messages):
            if i >= existing_count:
                await msg_repo.insert(
                    conversation_id=conv_id,
                    message=msg,
                    mode=mode,
                )

    async def add_message(self, message: ChatMessage, auto_save_interval: int = 5) -> None:
        if not self.current_session:
            raise ValueError("No active session")
        added = self.current_session.add_message(message)
        if not added:
            return
        self.turn_count += 1
        if auto_save_interval > 0 and self.turn_count % auto_save_interval == 0:
            await self.save_session()

    async def list_sessions(
        self,
        owner_id: Optional[str] = None,
        include_archived: bool = False,
    ) -> list[SessionMetadata]:
        conv_repo, _ = await self._get_repos()
        owner_user_id: Optional[int] = None
        if owner_id:
            try:
                owner_user_id = int(owner_id)
            except (TypeError, ValueError):
                owner_user_id = None
        rows = await conv_repo.list_all(user_id=owner_user_id)
        result = []
        for row in rows:
            if not include_archived and row["is_deleted"]:
                continue
            result.append(
                SessionMetadata(
                    id=str(row["id"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"] or row["created_at"],
                    message_count=0,
                    total_tokens=0,
                    title=row["title"],
                    channel=row["mode"],
                    working_directory=None,
                    channel_user_id="",
                    thread_id=None,
                )
            )
        return result

    async def list_all_sessions(
        self,
        include_archived: bool = False,
        owner_id: Optional[str] = None,
        include_unowned: bool = True,
    ) -> list[SessionMetadata]:
        return await self.list_sessions(owner_id=owner_id, include_archived=include_archived)

    async def delete_turn(self, session_id: str, turn_index: int) -> list[ChatMessage]:
        """Soft-delete the contiguous slice [turn_index, next_user_index).

        Raises:
            FileNotFoundError: session unknown
            IndexError: turn_index out of range
            ValueError: turn_index does not point to a USER message
        """
        from atria.models.message import Role

        try:
            conv_id = int(session_id)
        except ValueError:
            raise FileNotFoundError(session_id)

        _, msg_repo = await self._get_repos()
        messages = await msg_repo.list_by_conversation(conv_id)

        if turn_index < 0 or turn_index >= len(messages):
            raise IndexError(f"turn_index {turn_index} out of range (len={len(messages)})")
        if messages[turn_index].role != Role.USER:
            raise ValueError(f"turn_index {turn_index} is not a USER message")

        end = turn_index + 1
        while end < len(messages) and messages[end].role != Role.USER:
            end += 1

        ids = await msg_repo.list_ids_by_conversation(conv_id)
        # ids is the same length & order as messages (both filtered to is_deleted=False)
        ids_to_delete = ids[turn_index:end]
        await msg_repo.soft_delete_by_ids(ids_to_delete)

        # Keep in-memory current_session in sync if it matches.
        if self.current_session and self.current_session.id == session_id:
            self.current_session.messages = (
                self.current_session.messages[:turn_index] + self.current_session.messages[end:]
            )
            remaining = self.current_session.messages
        else:
            remaining = messages[:turn_index] + messages[end:]

        return remaining

    async def delete_session(self, session_id: str) -> None:
        try:
            conv_id = int(session_id)
        except ValueError:
            return
        conv_repo, _ = await self._get_repos()
        await conv_repo.soft_delete(conv_id)
        if self.current_session and self.current_session.id == session_id:
            self.current_session = None

    async def get_current_session(self) -> Optional[Session]:
        return self.current_session

    async def get_session_by_id(self, session_id: str, owner_id: Optional[str] = None) -> Session:
        return await self.load_session(session_id, owner_id=owner_id)

    async def set_title(self, session_id: str, title: str) -> None:
        try:
            conv_id = int(session_id)
        except ValueError:
            return
        conv_repo, _ = await self._get_repos()
        await conv_repo.update(conv_id, title=title[:255])
        if self.current_session and self.current_session.id == session_id:
            self.current_session.metadata["title"] = title

    async def load_latest_session(self, working_directory: object = None) -> Optional[Session]:
        sessions = await self.list_sessions()
        if not sessions:
            return None
        return await self.load_session(sessions[0].id)

    async def find_latest_session(
        self, working_directory: object = None
    ) -> Optional[SessionMetadata]:
        sessions = await self.list_sessions()
        return sessions[0] if sessions else None

    async def fork_session(self, message_index: Optional[int] = None) -> Optional[Session]:
        current = self.current_session
        if current is None:
            return None
        messages = (
            current.messages[: message_index + 1]
            if message_index is not None
            else list(current.messages)
        )
        user_id, project_id = await self._ensure_provisioned()
        conv_id = await self._conv_repo.create(
            project_id=project_id,
            user_id=user_id,
            title=f"Fork of {current.metadata.get('title', current.id)}",
            mode=current.channel[:10],
        )
        new_session = Session(
            id=str(conv_id),
            messages=messages,
            working_directory=current.working_directory,
            metadata={**current.metadata, "forked_from": current.id},
            parent_id=current.id,
            channel=current.channel,
        )
        self.current_session = new_session
        self.turn_count = len(messages)
        await self.save_session(new_session, force=True)
        return new_session

    async def load_transcript(self, session_id: str) -> list[ChatMessage]:
        session = await self.load_session(session_id)
        return session.messages

    async def find_session_by_channel_user(
        self, channel: str, user_id: str, thread_id: Optional[str] = None
    ) -> Optional[SessionMetadata]:
        return None

    async def list_user_workspaces(self) -> list[str]:
        return []
