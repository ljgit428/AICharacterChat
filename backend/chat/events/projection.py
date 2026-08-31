"""Materialized projection of the chat event log.

``Message`` and ``MessageAttachment`` rows are a *derived view* of
``ChatEvent`` — the event log is the single source of truth. This module
applies one event to the projection (write-through) and can rebuild a
session's Message rows from scratch. The UI/history serializers keep reading
the projection unchanged; only the model-facing prompt switches to the
event-derived view (see ``events.store.derive_messages``).
"""
from __future__ import annotations

from django.db import transaction

from ..models import ChatEvent, ChatEventType, Message, MessageAttachment


def project_event(event: ChatEvent) -> Message | None:
    """Apply one event to the Message projection.

    Returns the created ``Message`` for message-producing events and ``None``
    for bookkeeping events (``session/created``, ``compaction/summary``),
    which produce no Message row.
    """
    if event.event_type == ChatEventType.USER_MESSAGE:
        return _project_user_message(event)
    if event.event_type == ChatEventType.ASSISTANT_MESSAGE:
        return _project_assistant_message(event)
    return None


def _project_user_message(event: ChatEvent) -> Message:
    data = event.data or {}
    message = Message.objects.create(
        chat_session=event.chat_session,
        role='user',
        content=data.get('content') or '',
        character=event.character,
    )
    _align_timestamp(message, event)

    created_attachments = []
    for index, payload in enumerate(data.get('attachments') or []):
        created_attachments.append(
            MessageAttachment.objects.create(
                message=message,
                file=payload.get('file_name') or '',
                attachment_name=payload.get('attachment_name') or '',
                attachment_mime_type=payload.get('attachment_mime_type') or '',
                attachment_kind=payload.get('attachment_kind') or '',
                attachment_text_content=payload.get('attachment_text_content') or '',
                media_analysis=payload.get('media_analysis') or '',
                gemini_file_name=payload.get('gemini_file_name') or '',
                sort_order=payload.get('sort_order', index),
            )
        )
    if created_attachments:
        primary = created_attachments[0]
        # Legacy single-file denormalization so old serializers/prompt paths
        # keep working unchanged.
        Message.objects.filter(pk=message.pk).update(
            attachment=primary.file.name,
            attachment_name=primary.attachment_name,
            attachment_mime_type=primary.attachment_mime_type,
            attachment_kind=primary.attachment_kind,
            attachment_text_content=primary.attachment_text_content,
        )
    message.refresh_from_db()
    return message


def _project_assistant_message(event: ChatEvent) -> Message:
    data = event.data or {}
    message = Message.objects.create(
        chat_session=event.chat_session,
        role='assistant',
        content=data.get('content') or '',
        character=event.character,
        research_payload=data.get('research_payload') or {},
        thinking=data.get('thinking') or '',
        raw_reasoning=data.get('raw_reasoning') or '',
        tool_calls=data.get('tool_calls') or [],
        token_usage=data.get('token_usage') or {},
    )
    _align_timestamp(message, event)
    message.refresh_from_db()
    return message


def _align_timestamp(message: Message, event: ChatEvent) -> None:
    """Message.timestamp is ``auto_now_add``; force it to the event's time so
    a rebuild reproduces the original timeline exactly."""
    Message.objects.filter(pk=message.pk).update(timestamp=event.created_at)


def rebuild_session_messages(chat_session) -> list[Message]:
    """Delete a session's Message rows and recreate them from its event log.

    Returns the recreated ``Message`` objects. MessageAttachment rows are
    deleted by CASCADE and recreated from the event payloads.
    """
    with transaction.atomic():
        Message.objects.filter(chat_session=chat_session).delete()
        created: list[Message] = []
        events = (
            ChatEvent.objects.filter(chat_session=chat_session)
            .select_related('chat_session', 'character')
            .order_by('seq')
        )
        for event in events:
            message = project_event(event)
            if message is not None:
                created.append(message)
    return created
