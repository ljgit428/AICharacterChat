"""Rebuild the Message projection from the ChatEvent event log.

The event log is the single source of truth for a session's conversation;
``Message`` rows are a materialized projection. Run this command to verify or
repair the projection for one session or the whole database:

    python manage.py rebuild_message_projection --session 12
    python manage.py rebuild_message_projection --all

For each target session the command deletes its Message/MessageAttachment
rows and recreates them from ``ChatEvent``, then reports how many messages
were rebuilt (``--check`` performs a dry run that only reports drift).
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from chat.events.projection import rebuild_session_messages
from chat.events.store import EventStore
from chat.models import ChatEvent, ChatSession, Message


class Command(BaseCommand):
    help = 'Rebuild Message rows (the projection) from the ChatEvent event log.'

    def add_arguments(self, parser):
        parser.add_argument('--session', type=int, default=None, help='Rebuild one session by id.')
        parser.add_argument('--all', action='store_true', help='Rebuild every session that has events.')
        parser.add_argument(
            '--check',
            action='store_true',
            help='Dry run: report drift between the event log and the projection without writing.',
        )

    def handle(self, *args, **options):
        session_id = options['session']
        rebuild_all = options['all']
        check_only = options['check']
        if not session_id and not rebuild_all:
            raise CommandError('Pass --session <id> or --all.')

        if session_id:
            try:
                sessions = [ChatSession.objects.get(id=session_id)]
            except ChatSession.DoesNotExist:
                raise CommandError(f'Chat session {session_id} not found.')
        else:
            sessions = ChatSession.objects.filter(events__isnull=False).distinct().order_by('id')

        rebuilt_total = 0
        for session in sessions:
            event_count = ChatEvent.objects.filter(chat_session=session).count()
            message_count = Message.objects.filter(chat_session=session).count()
            if check_only:
                if event_count != message_count + 1:
                    self.stdout.write(
                        self.style.WARNING(
                            f'session {session.id}: {message_count} messages vs {event_count} events (drift)'
                        )
                    )
                else:
                    self.stdout.write(f'session {session.id}: consistent ({message_count} messages)')
                continue
            created = rebuild_session_messages(session)
            rebuilt_total += len(created)
            self.stdout.write(
                self.style.SUCCESS(
                    f'session {session.id}: rebuilt {len(created)} messages from {event_count} events'
                )
            )

        if not check_only:
            self.stdout.write(self.style.SUCCESS(f'Rebuilt {rebuilt_total} messages total.'))

        # Sanity: derived views should render the same roles/contents.
        for session in sessions:
            views = EventStore.derive_messages(session, compacted=False)
            if views:
                self.stdout.write(f'session {session.id}: derive_messages -> {len(views)} views')
