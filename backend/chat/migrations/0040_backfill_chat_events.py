"""Data migration: backfill existing Message rows into the ChatEvent event log.

For each existing ChatSession, this creates:
- one ``session/created`` event
- one ``user/message`` or ``assistant/message`` event per ``Message`` row
  (with attachment metadata copied from ``MessageAttachment`` rows)

The event seq is assigned by message timestamp order per session, and
``ChatEvent.created_at`` is set to the original ``Message.timestamp`` so the
timeline is preserved exactly. After this migration, the event log is the
authoritative source of truth and the ``Message`` table is a materialized
projection.

Run ``python manage.py rebuild_message_projection`` afterward to verify
consistency (the projection should produce identical Message rows).
"""
from __future__ import annotations

from django.db import migrations


def backfill_chat_events(apps, schema_editor):
    ChatEvent = apps.get_model('chat', 'ChatEvent')
    ChatSession = apps.get_model('chat', 'ChatSession')
    Message = apps.get_model('chat', 'Message')
    MessageAttachment = apps.get_model('chat', 'MessageAttachment')

    sessions = ChatSession.objects.order_by('created_at').iterator()
    for session in sessions:
        event_seq = 1

        # session/created
        ChatEvent.objects.create(
            chat_session=session,
            seq=event_seq,
            event_type='session/created',
            data={'origin': session.origin, 'title': session.title},
            created_at=session.created_at,
        )
        event_seq += 1

        # user/message and assistant/message events
        messages = (
            Message.objects.filter(chat_session=session)
            .order_by('timestamp')
            .select_related('character')
            .iterator()
        )
        for message in messages:
            if message.role not in ('user', 'assistant'):
                continue

            if message.role == 'user':
                attachment_payloads = []
                for attachment in MessageAttachment.objects.filter(message=message).order_by('sort_order', 'id'):
                    attachment_payloads.append({
                        'file_name': attachment.file.name,
                        'attachment_name': attachment.attachment_name or '',
                        'attachment_mime_type': attachment.attachment_mime_type or '',
                        'attachment_kind': attachment.attachment_kind or '',
                        'attachment_text_content': attachment.attachment_text_content or '',
                        'media_analysis': attachment.media_analysis or '',
                        'gemini_file_name': attachment.gemini_file_name or '',
                        'sort_order': attachment.sort_order,
                    })
                # Legacy single-file fallback (pre-0017 attachments stored on Message)
                if not attachment_payloads and message.attachment:
                    attachment_payloads.append({
                        'file_name': message.attachment.name,
                        'attachment_name': message.attachment_name or '',
                        'attachment_mime_type': message.attachment_mime_type or '',
                        'attachment_kind': message.attachment_kind or '',
                        'attachment_text_content': message.attachment_text_content or '',
                        'media_analysis': '',
                        'gemini_file_name': '',
                        'sort_order': 0,
                    })

                data = {
                    'content': message.content or '',
                    'attachments': attachment_payloads,
                }
                event_type = 'user/message'
            else:
                data = {
                    'content': message.content or '',
                    'thinking': message.thinking or '',
                    'tool_calls': message.tool_calls or [],
                    'token_usage': message.token_usage or {},
                    'research_payload': message.research_payload or {},
                }
                event_type = 'assistant/message'

            ChatEvent.objects.create(
                chat_session=session,
                character=message.character,
                seq=event_seq,
                event_type=event_type,
                data=data,
                created_at=message.timestamp,
            )
            event_seq += 1


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0039_chatevent'),
    ]

    operations = [
        migrations.RunPython(backfill_chat_events, reverse_code=migrations.RunPython.noop),
    ]