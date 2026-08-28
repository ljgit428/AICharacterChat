"""Append-only event log service for chat sessions.

The event log (``ChatEvent`` table) is the single source of truth for a
session's conversation. ``Message`` rows are a materialized projection
maintained via ``events.projection.project_event`` — write-through on every
append, and rebuildable from scratch.

Message history *for the model* is *derived* here from the event log
(``derive_messages``). Compaction shadows old events with a summary; the
derived view renders the summary and skips the shadowed range, while the
projection (and thus the UI) keeps the full log visible.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ..models import ChatEvent, ChatEventType, ChatSession
from . import projection


# ---------------------------------------------------------------------------
#  Duck-typed views that the prompt builders consume
# ---------------------------------------------------------------------------


class _StorageFileView:
    """Minimal file handle exposing ``.name`` and ``.path``.

    Lets the existing media builders (``_build_data_url``,
    ``_read_media_base64``, ``_get_or_upload_generativeai_file``) consume
    event-derived attachments exactly like Django ``FieldFile``.
    """

    def __init__(self, name: str) -> None:
        self.name = name or ''

    @property
    def path(self) -> str:
        return os.path.join(settings.MEDIA_ROOT, self.name)


@dataclass
class AttachmentView:
    """Duck-typed replacement for ``MessageAttachment`` rows.

    ``get_message_attachments`` only reads attributes; it never calls ORM
    methods on the members, so a plain list of these works as a drop-in.
    """

    file_name: str = ''
    attachment_name: str = ''
    attachment_mime_type: str = ''
    attachment_kind: str = ''
    attachment_text_content: str = ''
    media_analysis: str = ''
    sort_order: int = 0

    def __post_init__(self) -> None:
        self.file = _StorageFileView(self.file_name)


@dataclass
class MessageView:
    """Duck-typed replacement for ``Message`` rows in prompt-building code.

    ``get_message_attachments`` memoises on ``message._cached_attachments``
    (checked first), so we set it in ``__post_init__``. All other prompt
    helpers read plain attributes accessible via ``getattr``.
    """

    role: str
    content: str
    timestamp: datetime
    event_seq: int
    chat_session_id: int | None = None
    character_id: int | None = None
    thinking: str = ''
    tool_calls: list = field(default_factory=list)
    token_usage: dict = field(default_factory=dict)
    research_payload: dict = field(default_factory=dict)
    attachments: list = field(default_factory=list)
    is_compacted_summary: bool = False

    def __post_init__(self) -> None:
        self._cached_attachments = self.attachments


# ---------------------------------------------------------------------------
#  EventStore
# ---------------------------------------------------------------------------


class EventStore:
    """Service for appending to, loading from, and deriving from a session's
    event log."""

    @staticmethod
    def append(
        chat_session: ChatSession,
        event_type: str,
        data: dict | None = None,
        *,
        character=None,
        created_at: datetime | None = None,
    ) -> tuple[ChatEvent, Any | None]:
        """Append one event and apply the write-through projection.

        Seq is allocated monotonically inside a transaction with a
        ``select_for_update`` row lock on the session so concurrent appends
        stay gap-free. Returns ``(event, projected_message)`` where the
        second element is ``None`` for bookkeeping events.
        """
        data = data or {}
        with transaction.atomic():
            ChatSession.objects.select_for_update().get(pk=chat_session.pk)
            last_seq = (
                ChatEvent.objects.filter(chat_session=chat_session)
                .order_by('-seq')
                .values_list('seq', flat=True)
                .first()
            )
            event = ChatEvent.objects.create(
                chat_session=chat_session,
                character=character,
                seq=(last_seq or 0) + 1,
                event_type=event_type,
                data=data,
                created_at=created_at or timezone.now(),
            )
            message = projection.project_event(event)
        return event, message

    # ------------------------------------------------------------------
    #  load

    @staticmethod
    def load(
        chat_session: ChatSession,
        *,
        after_seq: int = 0,
    ) -> list[ChatEvent]:
        """Return events in seq order, optionally from a given seq onward."""
        return list(
            ChatEvent.objects.filter(
                chat_session=chat_session,
                seq__gt=after_seq,
            ).order_by('seq')
        )

    # ------------------------------------------------------------------
    #  derive_messages

    @staticmethod
    def derive_messages(
        chat_session: ChatSession,
        *,
        compacted: bool = False,
        merge_adjacent_same_role: bool | None = None,
        filter_legacy_bootstrap: bool = True,
    ) -> list[MessageView]:
        """Derive the message list from the event log.

        Parameters
        ----------
        compacted:
            When ``True``, compaction summaries replace the shadowed message
            range; when ``False``, every real message is included verbatim.
        merge_adjacent_same_role:
            Merge consecutive same-role messages so the summary pseudo-message
            cannot create role-adjacency conflicts on providers with strict
            alternation.  Defaults to the value of ``compacted``.
        filter_legacy_bootstrap:
            Skip legacy ``=== CHARACTER IDENTITY ===`` bootstrap messages that
            were once injected as user messages.
        """
        events = list(
            ChatEvent.objects.filter(chat_session=chat_session).order_by('seq')
        )
        if merge_adjacent_same_role is None:
            merge_adjacent_same_role = compacted

        # Collect the compaction shadow ranges and their summary views.
        shadow_ranges: list[tuple[int, int]] = []
        summaries: list[tuple[int, int, MessageView]] = []  # (start, end, view)
        for event in events:
            if event.event_type == ChatEventType.COMPACTION_SUMMARY:
                data = event.data or {}
                start = data.get('shadowed_start_seq')
                end = data.get('shadowed_end_seq')
                if start is not None and end is not None:
                    start, end = int(start), int(end)
                    shadow_ranges.append((start, end))
                    if compacted:
                        summary = (data.get('summary') or '').strip()
                        if summary:
                            summaries.append((start, end, _summary_view(event, summary)))

        # Build the base list of retained (non-shadowed) message views.
        views: list[MessageView] = []
        range_index = 0
        for event in events:
            while (
                range_index < len(shadow_ranges)
                and shadow_ranges[range_index][1] < event.seq
            ):
                range_index += 1

            if event.event_type == ChatEventType.COMPACTION_SUMMARY:
                continue  # compaction events never appear in the derived view

            # Only the compacted (model-facing) view hides shadowed events;
            # the full view keeps every real message (like the UI projection).
            if compacted:
                in_shadow = (
                    range_index < len(shadow_ranges)
                    and shadow_ranges[range_index][0] <= event.seq <= shadow_ranges[range_index][1]
                )
                if in_shadow:
                    continue

            if event.event_type == ChatEventType.USER_MESSAGE:
                view = _user_view(event)
            elif event.event_type == ChatEventType.ASSISTANT_MESSAGE:
                view = _assistant_view(event)
            else:
                continue  # session/created and future bookkeeping events

            if filter_legacy_bootstrap and _is_legacy_bootstrap_content(view.content):
                continue
            views.append(view)

        if compacted:
            # Insert each summary right where its shadowed range began — before
            # the first retained message after the range. Ranges are disjoint
            # and ordered, so inserting in start order keeps summaries oldest
            # first, each landing before the retained tail that follows it.
            summaries.sort(key=lambda item: item[0])
            for _start, end, summary_view in summaries:
                insert_at = 0
                while insert_at < len(views) and views[insert_at].event_seq <= end:
                    insert_at += 1
                views.insert(insert_at, summary_view)

        if merge_adjacent_same_role:
            views = _merge_adjacent_same_role(views)
        return views


# ---------------------------------------------------------------------------
#  Helper factories
# ---------------------------------------------------------------------------


def _user_view(event: ChatEvent) -> MessageView:
    """Turn a ``user/message`` event into a ``MessageView``."""
    data = event.data or {}
    attachments = [
        AttachmentView(
            file_name=p.get('file_name') or '',
            attachment_name=p.get('attachment_name') or '',
            attachment_mime_type=p.get('attachment_mime_type') or '',
            attachment_kind=p.get('attachment_kind') or '',
            attachment_text_content=p.get('attachment_text_content') or '',
            media_analysis=p.get('media_analysis') or '',
            sort_order=p.get('sort_order', index),
        )
        for index, p in enumerate(data.get('attachments') or [])
    ]
    return MessageView(
        role='user',
        content=data.get('content') or '',
        timestamp=event.created_at,
        event_seq=event.seq,
        chat_session_id=event.chat_session_id,
        character_id=event.character_id,
        attachments=attachments,
    )


def _assistant_view(event: ChatEvent) -> MessageView:
    """Turn an ``assistant/message`` event into a ``MessageView``."""
    data = event.data or {}
    return MessageView(
        role='assistant',
        content=data.get('content') or '',
        timestamp=event.created_at,
        event_seq=event.seq,
        chat_session_id=event.chat_session_id,
        character_id=event.character_id,
        thinking=data.get('thinking') or '',
        tool_calls=data.get('tool_calls') or [],
        token_usage=data.get('token_usage') or {},
        research_payload=data.get('research_payload') or {},
    )


def _summary_view(event: ChatEvent, summary: str) -> MessageView:
    """Turn the summary part of a compaction event into a pseudo-message that
    the model sees in place of the shadowed events."""
    return MessageView(
        role='user',
        content=f'<compacted-summary>\n{summary}\n</compacted-summary>',
        timestamp=event.created_at,
        event_seq=event.seq,
        chat_session_id=event.chat_session_id,
        character_id=event.character_id,
        is_compacted_summary=True,
    )


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _is_legacy_bootstrap_content(content: str) -> bool:
    """Detect old ``=== CHARACTER IDENTITY ===`` user messages that the prompt
    builder must skip (replicates ``tasks._is_legacy_bootstrap_message`` on
    raw text)."""
    content = (content or '').strip()
    return (
        content.startswith('=== CHARACTER IDENTITY ===')
        and 'Please provide your initial greeting based on your character settings.' in content
    )


def _merge_adjacent_same_role(views: list[MessageView]) -> list[MessageView]:
    """Merge consecutive messages whose role is the same, keeping the derived
    list compatible with strict-alternation providers."""
    if not views:
        return views
    merged: list[MessageView] = [views[0]]
    for view in views[1:]:
        if merged[-1].role == view.role:
            prev = merged[-1]
            prev.content = f"{prev.content}\n\n{view.content}".strip()
        else:
            merged.append(view)
    return merged


# ---------------------------------------------------------------------------
#  Token estimation
# ---------------------------------------------------------------------------


def estimate_str_tokens(text: str | None) -> int:
    """Heuristic token count for CJK-prone text (~1.7 chars per token)."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 1.7))


def estimate_attachment_tokens(attachment_payload: dict) -> int:
    """Estimated token count for one attachment payload."""
    return estimate_str_tokens(attachment_payload.get('attachment_text_content'))


def estimate_event_tokens(event: ChatEvent) -> int:
    """Estimated token count for one message event (content + thinking +
    attachment text)."""
    data = event.data or {}
    total = estimate_str_tokens(data.get('content') or '')
    total += estimate_str_tokens(data.get('thinking') or '')
    for attachment in data.get('attachments') or []:
        total += estimate_attachment_tokens(attachment)
    return total


def history_tokens(chat_session: ChatSession) -> int:
    """Sum of estimated tokens for all message events in a session."""
    events = ChatEvent.objects.filter(
        chat_session=chat_session,
        event_type__in=[ChatEventType.USER_MESSAGE, ChatEventType.ASSISTANT_MESSAGE],
    ).order_by('seq')
    return sum(estimate_event_tokens(e) for e in events.iterator())
