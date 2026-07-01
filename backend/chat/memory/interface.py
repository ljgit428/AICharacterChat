"""LongTermMemoryInterface — Python facade mirroring SonettoHeres namesake.

SonettoHer's ``LongTermMemoryInterface`` is the orchestrator class that owns
the asyncio.Queue, the consumer coroutine, and the WebSocket callback. Our
counterpart is the Celery task (``tasks.sync_long_term_memory``); this
``LongTermMemoryInterface`` is the thin Python-side entry point so synchronous
callers (REST views, force-sync buttons, tests) can talk to the same pipeline.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction

from ..models import (
    Character,
    CharacterMemoryItem,
    ChatSession,
    MemoryAuditAction,
    MemoryAuditLog,
    Message,
)
from .manager import MemoryManager


class LongTermMemoryInterface:
    """Synchronous facade. The async/Celery path is handled by the
    ``sync_long_term_memory`` task; this class is the entry point for
    code paths that need to enqueue, snapshot, or render."""

    @staticmethod
    def enqueue(chat_session: ChatSession, message: Message):
        """Dispatch the Celery task that drives one memory write for this turn."""
        from ..tasks import sync_long_term_memory  # local import to avoid circulars

        return sync_long_term_memory.delay(
            message_id=message.id,
            chat_session_id=chat_session.id,
            character_id=chat_session.character_id,
        )

    @staticmethod
    def get_narrative(character: Character) -> str:
        """Render the narration blob injected into the system prompt."""
        return MemoryManager(character).render_narrative()

    @staticmethod
    def render_wiki_markdown(character: Character) -> str:
        """Render ``wiki/memory.md`` as it shows up in the MemoryExplorer."""
        return MemoryManager(character).render_wiki_markdown()

    @staticmethod
    def snapshot(character: Character) -> dict[str, Any]:
        """Return grouped sections for the /memory page (mirrors
        SonettoHer's ``MemoryManager.get_memories_grouped``)."""
        return MemoryManager(character).grouped()

    @staticmethod
    def wipe(character: Character) -> int:
        """Delete all memory items for a character. Returns the count deleted.
        Used by ``DELETE /api/characters/{id}/memory``.
        """
        with transaction.atomic():
            count = CharacterMemoryItem.objects.filter(character=character).count()
            MemoryAuditLog.objects.create(
                character=character,
                chat_session=None,
                message=None,
                action=MemoryAuditAction.DELETE,
                entry_short_id="*",
                before_description=f"{count} entries",
                after_description="",
                reason="Manual wipe via /memory page.",
            )
            CharacterMemoryItem.objects.filter(character=character).delete()
        return count
