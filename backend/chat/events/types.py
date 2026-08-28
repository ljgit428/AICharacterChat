"""Event payload builders for the chat event log.

The payload vocabulary mirrors the ``Message`` fields that the projection
reproduces: every value the prompt builders or the UI serializer read must be
recoverable from the event alone (lossless replay).
"""
from __future__ import annotations


def user_message_payload(
    *,
    content: str,
    attachments: list | None = None,
) -> dict:
    """Payload for a ``user/message`` event.

    ``attachments`` is a list of dicts carrying the *persisted* storage name
    (``file_name``) plus display metadata — the actual file bytes live on
    disk and are never duplicated into the log.
    """
    return {
        'content': content or '',
        'attachments': [
            {
                'file_name': (item.get('file_name') or ''),
                'attachment_name': (item.get('attachment_name') or ''),
                'attachment_mime_type': (item.get('attachment_mime_type') or ''),
                'attachment_kind': (item.get('attachment_kind') or ''),
                'attachment_text_content': (item.get('attachment_text_content') or ''),
                'media_analysis': (item.get('media_analysis') or ''),
                'gemini_file_name': (item.get('gemini_file_name') or ''),
                'sort_order': item.get('sort_order', 0),
            }
            for item in (attachments or [])
        ],
    }


def assistant_message_payload(
    *,
    content: str,
    thinking: str = '',
    tool_calls: list | None = None,
    token_usage: dict | None = None,
    research_payload: dict | None = None,
    latency_ms: int | None = None,
) -> dict:
    """Payload for an ``assistant/message`` event — the complete reply."""
    return {
        'content': content or '',
        'thinking': thinking or '',
        'tool_calls': tool_calls or [],
        'token_usage': token_usage or {},
        'research_payload': research_payload or {},
        'latency_ms': latency_ms,
    }


def compaction_summary_payload(
    *,
    summary: str,
    shadowed_start_seq: int,
    shadowed_end_seq: int,
    shadowed_count: int,
    tokens_freed: int,
    provider: str = '',
    model: str = '',
) -> dict:
    """Payload for a ``compaction/summary`` event.

    ``shadowed_start_seq`` / ``shadowed_end_seq`` name the shadowed event
    range (inclusive). The range is a *position* span over the log, so
    ``derive_messages`` can render the summary in place of those events.
    """
    return {
        'summary': summary or '',
        'shadowed_start_seq': int(shadowed_start_seq),
        'shadowed_end_seq': int(shadowed_end_seq),
        'shadowed_count': int(shadowed_count),
        'tokens_freed': int(tokens_freed),
        'provider': provider or '',
        'model': model or '',
    }
