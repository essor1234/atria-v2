"""Telegram channel adapter (long-polling).

Implements the Telegram Bot API via **getUpdates long-polling** — chosen so setup
needs no public URL / HTTPS / webhook. Each adapter instance serves ONE bot token and
registers under a unique channel key (``telegram:<connection-id>``) so multiple bots
coexist under one MessageRouter.

Key Telegram constraint: ``getUpdates`` is single-consumer per token — a second poller
gets HTTP 409, and polling is mutually exclusive with any webhook. So we ``deleteWebhook``
once before polling and surface 409 as a clear status instead of dying silently.

Authorization: only chat ids in the connection's allowlist may drive the agent. Unknown
senders are recorded as *pending contacts* and told their id (so the owner can add them).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Iterable, Optional

import httpx

from atria.core.channels.base import ChannelAdapter, InboundMessage, OutboundMessage

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org"


class TelegramAdapter(ChannelAdapter):
    """Long-polling Telegram Bot adapter for one bot token."""

    def __init__(
        self,
        bot_token: str,
        *,
        channel_name: str = "telegram",
        router: Optional[Any] = None,
        allowed_chat_ids: Optional[Iterable[str]] = None,
        poll_timeout: int = 50,
    ) -> None:
        self.channel_name = channel_name
        self._token = bot_token
        self._router = router  # MessageRouter (set before start())
        self._allowed: set[str] = {str(c) for c in (allowed_chat_ids or [])}
        self._poll_timeout = poll_timeout

        self._client: Optional[httpx.AsyncClient] = None
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._offset: Optional[int] = None

        # Observable status for the Connect UI.
        self.status: str = "stopped"  # stopped|running|conflict|error
        self.last_error: Optional[str] = None
        self.bot_username: Optional[str] = None
        # chat_id -> display name, captured from messages by non-allowlisted users.
        self.pending_contacts: dict[str, str] = {}

    # ---- config -------------------------------------------------------------

    def update_allowlist(self, chat_ids: Iterable[str]) -> None:
        """Replace the allowlist (called when recipients change in the UI)."""
        self._allowed = {str(c) for c in chat_ids}
        for cid in list(self.pending_contacts):
            if cid in self._allowed:
                self.pending_contacts.pop(cid, None)

    # ---- low-level API ------------------------------------------------------

    async def _api(self, method: str, **params: Any) -> dict:
        """Call a Bot API method; always returns Telegram's parsed JSON envelope."""
        assert self._client is not None
        url = f"{_TELEGRAM_API}/bot{self._token}/{method}"
        body = {k: v for k, v in params.items() if v is not None}
        resp = await self._client.post(url, json=body)
        try:
            return resp.json()
        except Exception:
            return {"ok": False, "error_code": resp.status_code, "description": resp.text[:200]}

    async def get_me(self) -> dict:
        """Validate the token (used by the /test endpoint)."""
        owns_client = self._client is None
        if owns_client:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(20.0))
        try:
            data = await self._api("getMe")
            if data.get("ok"):
                self.bot_username = data["result"].get("username")
            return data
        finally:
            if owns_client and self._client is not None:
                await self._client.aclose()
                self._client = None

    # ---- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Open the client, drop any webhook, and launch the poll loop."""
        self._stop.clear()
        # Read timeout must exceed the long-poll timeout.
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._poll_timeout + 15.0, connect=15.0)
        )
        me = await self._api("getMe")
        if not me.get("ok"):
            self.status = "error"
            self.last_error = me.get("description", "getMe failed")
            logger.error("Telegram %s getMe failed: %s", self.channel_name, self.last_error)
            return
        self.bot_username = me["result"].get("username")
        # Polling is mutually exclusive with a webhook — clear it first.
        await self._api("deleteWebhook")
        self._task = asyncio.create_task(self._poll_loop(), name=f"poll-{self.channel_name}")
        logger.info("Telegram adapter started: %s (@%s)", self.channel_name, self.bot_username)

    async def _poll_loop(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                data = await self._api(
                    "getUpdates",
                    offset=self._offset,
                    timeout=self._poll_timeout,
                    allowed_updates=["message"],
                )
                if not data.get("ok"):
                    code = data.get("error_code")
                    self.last_error = data.get("description", "getUpdates failed")
                    if code == 409:
                        # Another poller holds this token (e.g. a duplicate process
                        # or a --reload leftover). Surface clearly; back off.
                        self.status = "conflict"
                        logger.warning("Telegram %s 409 conflict: %s", self.channel_name,
                                       self.last_error)
                    else:
                        self.status = "error"
                        logger.warning("Telegram %s getUpdates error: %s", self.channel_name,
                                       self.last_error)
                    await self._sleep(min(backoff, 30))
                    backoff = min(backoff * 2, 30)
                    continue

                self.status = "running"
                self.last_error = None
                backoff = 1.0
                for upd in data.get("result", []):
                    self._offset = upd["update_id"] + 1
                    try:
                        await self._handle_update(upd)
                    except Exception:  # one bad update must not kill the loop
                        logger.exception("Telegram %s update handler error", self.channel_name)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.status = "error"
                self.last_error = str(exc)
                logger.warning("Telegram %s poll error: %s", self.channel_name, exc)
                await self._sleep(min(backoff, 30))
                backoff = min(backoff * 2, 30)
        self.status = "stopped"

    async def _sleep(self, seconds: float) -> None:
        """Interruptible sleep that wakes promptly on stop()."""
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def _handle_update(self, update: dict) -> None:
        msg = update.get("message")
        if not msg or "text" not in msg:
            return
        chat = msg.get("chat", {})
        chat_id = str(chat.get("id"))
        text = msg["text"]
        name = (
            chat.get("username")
            or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
            or chat_id
        )

        # Authorization gate.
        if chat_id not in self._allowed:
            self.pending_contacts[chat_id] = name
            await self.send(
                {"chat_id": chat_id},
                OutboundMessage(
                    text=(
                        "You're not authorized yet. Your Telegram ID is "
                        f"`{chat_id}` — ask the owner to add you in Connect."
                    ),
                    parse_mode="markdown",
                ),
            )
            logger.info("Telegram %s pending contact: %s (%s)", self.channel_name, chat_id, name)
            return

        # /start is an onboarding tap, not an agent query.
        if text.strip() == "/start":
            await self.send(
                {"chat_id": chat_id},
                OutboundMessage(text=f"Hi {name} — you're connected. Send me a message."),
            )
            return

        if self._router is None:
            return
        inbound = InboundMessage(
            channel=self.channel_name,
            user_id=chat_id,
            text=text,
            chat_type="group" if chat.get("type") in ("group", "supergroup") else "direct",
            reply_to_message_id=str(msg.get("message_id")) if msg.get("message_id") else None,
            metadata={"chat_id": chat_id},
            raw=update,
        )
        await self._router.handle_inbound(inbound)

    async def send(self, delivery_context: dict[str, Any], message: OutboundMessage) -> None:
        """Send an outbound message to a chat (delivery_context carries chat_id)."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(20.0))
        chat_id = delivery_context.get("chat_id") or delivery_context.get("user_id")
        if chat_id is None:
            logger.error("Telegram %s send: no chat_id in delivery_context", self.channel_name)
            return
        params: dict[str, Any] = {"chat_id": chat_id, "text": message.text}
        if message.parse_mode == "markdown":
            params["parse_mode"] = "Markdown"
        elif message.parse_mode == "html":
            params["parse_mode"] = "HTML"
        if message.disable_preview:
            params["disable_web_page_preview"] = True
        # Inline keyboard (Confirm/Reject buttons) via OutboundMessage.metadata["buttons"]:
        #   [[{"text": "Confirm", "callback_data": "ok"}], [...]]
        buttons = (message.metadata or {}).get("buttons")
        if buttons:
            params["reply_markup"] = json.dumps({"inline_keyboard": buttons})
        data = await self._api("sendMessage", **params)
        if not data.get("ok"):
            logger.error("Telegram %s sendMessage failed: %s", self.channel_name,
                         data.get("description"))

    async def stop(self) -> None:
        """Stop the poll loop and close the client (no exceptions escape)."""
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None
        self.status = "stopped"
