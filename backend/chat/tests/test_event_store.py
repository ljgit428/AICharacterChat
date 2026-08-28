"""Event-store tests: append-only log, derived views, and the projection.

Follows ``test_memory.py``'s SQLite-in-memory pattern so the suite stays
runnable without a local PostgreSQL.
"""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from .test_memory import SQLITE_TEST_DATABASES


@override_settings(DATABASES=SQLITE_TEST_DATABASES)
@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class EventStoreBaseTests(TestCase):
    def setUp(self):
        from chat.models import Character, ChatSession

        self.user = User.objects.create_user(username='event-owner', password='password123')
        self.character = Character.objects.create(
            created_by=self.user,
            name='Event Character',
            avatar_url='',
            description='A character for event-store tests.',
            personality='Calm',
            appearance='Grey coat',
            scenario='Archive',
            example_dialogue='',
            affiliation='Lab',
            tags=['events'],
        )
        self.session = ChatSession.objects.create(
            user=self.user,
            character=self.character,
            title='Event Test Session',
            origin='topic',
        )


class EventStoreAppendTests(EventStoreBaseTests):
    def test_append_allocates_monotonic_seq(self):
        from chat.events.store import EventStore
        from chat.models import ChatEventType

        _, _ = EventStore.append(self.session, ChatEventType.SESSION_CREATED, {'origin': 'topic'})
        event, _ = EventStore.append(
            self.session, ChatEventType.USER_MESSAGE, {'content': 'hi'}
        )
        assert event.seq == 2
        event2, _ = EventStore.append(
            self.session, ChatEventType.ASSISTANT_MESSAGE, {'content': 'hello'}
        )
        assert event2.seq == 3
        # Assert seqs are monotonic.
        from chat.models import ChatEvent
        seqs = list(ChatEvent.objects.filter(chat_session=self.session).values_list('seq', flat=True).order_by('seq'))
        assert seqs == [1, 2, 3]

    def test_append_projects_user_message_row(self):
        from chat.events.store import EventStore
        from chat.models import ChatEventType, Message

        event, message = EventStore.append(
            self.session,
            ChatEventType.USER_MESSAGE,
            {'content': '你好'},
            character=self.character,
        )
        assert message is not None
        assert message.role == 'user'
        assert message.content == '你好'
        assert message.character_id == self.character.id
        assert message.timestamp == event.created_at
        assert Message.objects.filter(chat_session=self.session).count() == 1

    def test_append_projects_attachments_and_legacy_fields(self):
        from chat.events.store import EventStore
        from chat.models import ChatEventType, MessageAttachment

        _, message = EventStore.append(
            self.session,
            ChatEventType.USER_MESSAGE,
            {
                'content': '看图',
                'attachments': [
                    {
                        'file_name': 'chat_attachments/pic.png',
                        'attachment_name': 'pic.png',
                        'attachment_mime_type': 'image/png',
                        'attachment_kind': 'image',
                        'attachment_text_content': '',
                        'media_analysis': '',
                        'gemini_file_name': '',
                        'sort_order': 0,
                    }
                ],
            },
            character=self.character,
        )
        attachments = list(MessageAttachment.objects.filter(message=message).order_by('sort_order'))
        assert len(attachments) == 1
        assert attachments[0].file.name == 'chat_attachments/pic.png'
        # Legacy single-file denormalization on the Message row.
        message.refresh_from_db()
        assert message.attachment.name == 'chat_attachments/pic.png'
        assert message.attachment_kind == 'image'

    def test_append_projects_assistant_message_fields(self):
        from chat.events.store import EventStore
        from chat.models import ChatEventType

        _, message = EventStore.append(
            self.session,
            ChatEventType.ASSISTANT_MESSAGE,
            {
                'content': '回复',
                'thinking': '思考',
                'tool_calls': [{'tool': 'create_memory', 'arguments': {'x': 1}}],
                'token_usage': {'total_tokens': 42},
                'research_payload': {'query': 'q'},
            },
            character=self.character,
        )
        assert message.thinking == '思考'
        assert message.tool_calls[0]['tool'] == 'create_memory'
        assert message.token_usage['total_tokens'] == 42
        assert message.research_payload['query'] == 'q'

    def test_bookkeeping_events_produce_no_message(self):
        from chat.events.store import EventStore
        from chat.models import ChatEventType, Message

        event, message = EventStore.append(self.session, ChatEventType.SESSION_CREATED, {'origin': 'topic'})
        assert message is None
        event, message = EventStore.append(
            self.session, ChatEventType.COMPACTION_SUMMARY, {'summary': 's'}
        )
        assert message is None
        assert Message.objects.filter(chat_session=self.session).count() == 0


class EventStoreDeriveTests(EventStoreBaseTests):
    def _seed(self):
        from chat.events.store import EventStore
        from chat.models import ChatEventType

        EventStore.append(self.session, ChatEventType.SESSION_CREATED, {'origin': 'topic'})
        EventStore.append(self.session, ChatEventType.USER_MESSAGE, {'content': '第一句'}, character=self.character)
        EventStore.append(self.session, ChatEventType.ASSISTANT_MESSAGE, {'content': '回应一'}, character=self.character)
        EventStore.append(self.session, ChatEventType.USER_MESSAGE, {'content': '第二句'}, character=self.character)
        EventStore.append(self.session, ChatEventType.ASSISTANT_MESSAGE, {'content': '回应二'}, character=self.character)

    def test_derive_full_returns_all_messages(self):
        from chat.events.store import EventStore

        self._seed()
        views = EventStore.derive_messages(self.session, compacted=False)
        assert [v.role for v in views] == ['user', 'assistant', 'user', 'assistant']
        assert [v.content for v in views] == ['第一句', '回应一', '第二句', '回应二']
        assert all(not v.is_compacted_summary for v in views)

    def test_derive_filters_legacy_bootstrap(self):
        from chat.events.store import EventStore
        from chat.models import ChatEventType

        EventStore.append(
            self.session,
            ChatEventType.USER_MESSAGE,
            {
                'content': (
                    '=== CHARACTER IDENTITY ===\n'
                    'Please provide your initial greeting based on your character settings.'
                )
            },
            character=self.character,
        )
        EventStore.append(self.session, ChatEventType.USER_MESSAGE, {'content': '正常消息'}, character=self.character)
        views = EventStore.derive_messages(self.session, compacted=False)
        assert len(views) == 1
        assert views[0].content == '正常消息'

    def test_derive_compacted_renders_summary_and_skips_shadowed(self):
        from chat.events.store import EventStore
        from chat.models import ChatEventType

        self._seed()
        # seqs: 1 session/created, 2-5 messages. Shadow 2..4.
        EventStore.append(
            self.session,
            ChatEventType.COMPACTION_SUMMARY,
            {
                'summary': '前情提要',
                'shadowed_start_seq': 2,
                'shadowed_end_seq': 4,
                'shadowed_count': 3,
                'tokens_freed': 100,
            },
        )
        full = EventStore.derive_messages(self.session, compacted=False)
        assert len(full) == 4  # UI side never loses history

        compacted = EventStore.derive_messages(self.session, compacted=True)
        assert len(compacted) == 2  # summary + last assistant message
        assert compacted[0].is_compacted_summary
        assert '<compacted-summary>' in compacted[0].content
        assert '前情提要' in compacted[0].content
        assert compacted[1].content == '回应二'

    def test_derive_compacted_merges_adjacent_user_roles(self):
        from chat.events.store import EventStore
        from chat.models import ChatEventType

        self._seed()
        # Shadow seqs 2..3 (user+assistant), leaving the last user (seq 4) and
        # assistant (seq 5) as the retained tail.
        EventStore.append(
            self.session,
            ChatEventType.COMPACTION_SUMMARY,
            {
                'summary': '全部摘要',
                'shadowed_start_seq': 2,
                'shadowed_end_seq': 3,
                'shadowed_count': 2,
                'tokens_freed': 100,
            },
        )
        views = EventStore.derive_messages(self.session, compacted=True)
        # merge_adjacent_same_role defaults to True for compacted views, so
        # the summary(user) + retained user message fold into one view.
        assert len(views) == 2
        assert views[0].role == 'user'
        assert '全部摘要' in views[0].content
        assert '第二句' in views[0].content
        assert views[1].role == 'assistant'
        assert views[1].content == '回应二'


class EventStoreProjectionRebuildTests(EventStoreBaseTests):
    def test_rebuild_reproduces_identical_messages(self):
        from chat.events.store import EventStore
        from chat.models import ChatEventType, Message

        EventStore.append(self.session, ChatEventType.SESSION_CREATED, {'origin': 'topic'})
        EventStore.append(
            self.session,
            ChatEventType.USER_MESSAGE,
            {
                'content': '带附件',
                'attachments': [
                    {
                        'file_name': 'chat_attachments/doc.txt',
                        'attachment_name': 'doc.txt',
                        'attachment_mime_type': 'text/plain',
                        'attachment_kind': 'text',
                        'attachment_text_content': '文件内容',
                        'media_analysis': '',
                        'gemini_file_name': '',
                        'sort_order': 0,
                    }
                ],
            },
            character=self.character,
        )
        EventStore.append(
            self.session,
            ChatEventType.ASSISTANT_MESSAGE,
            {'content': '回应', 'thinking': '想', 'token_usage': {'total_tokens': 10}},
            character=self.character,
        )

        before = list(Message.objects.filter(chat_session=self.session).order_by('timestamp'))
        before_snapshot = [
            {
                'role': m.role,
                'content': m.content,
                'thinking': m.thinking,
                'token_usage': m.token_usage,
                'timestamp': m.timestamp,
                'attachments': [
                    (a.file.name, a.attachment_name, a.attachment_text_content)
                    for a in m.attachments.all().order_by('sort_order')
                ],
            }
            for m in before
        ]

        from chat.events.projection import rebuild_session_messages

        rebuilt = rebuild_session_messages(self.session)
        assert len(rebuilt) == 2
        after_snapshot = [
            {
                'role': m.role,
                'content': m.content,
                'thinking': m.thinking,
                'token_usage': m.token_usage,
                'timestamp': m.timestamp,
                'attachments': [
                    (a.file.name, a.attachment_name, a.attachment_text_content)
                    for a in m.attachments.all().order_by('sort_order')
                ],
            }
            for m in rebuilt
        ]
        assert after_snapshot == before_snapshot

    def test_history_tokens_sums_events(self):
        from chat.events.store import EventStore, history_tokens
        from chat.models import ChatEventType

        EventStore.append(self.session, ChatEventType.USER_MESSAGE, {'content': '甲' * 170}, character=self.character)
        EventStore.append(
            self.session,
            ChatEventType.ASSISTANT_MESSAGE,
            {'content': '乙' * 170, 'thinking': '丙' * 170},
            character=self.character,
        )
        total = history_tokens(self.session)
        # 3 × ceil(170/1.7) = 3 × 100
        assert total == 300
