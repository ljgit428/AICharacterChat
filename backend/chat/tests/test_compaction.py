"""Compaction engine tests: range selection, derived rendering, and the
Celery task pipeline (with a mocked summarization call)."""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from .test_memory import SQLITE_TEST_DATABASES


@override_settings(DATABASES=SQLITE_TEST_DATABASES)
@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
@override_settings(COMPACTION_ENABLED=True)
class CompactionBaseTests(TestCase):
    def setUp(self):
        from chat.models import Character, ChatSession, ModelConfiguration, ModelRoleAssignment

        self.user = User.objects.create_user(username='compact-owner', password='password123')
        self.character = Character.objects.create(
            created_by=self.user,
            name='Compact Character',
            avatar_url='',
            description='A character for compaction tests.',
            personality='Calm',
            appearance='Grey coat',
            scenario='Archive',
            example_dialogue='',
            affiliation='Lab',
            tags=['compaction'],
        )
        self.session = ChatSession.objects.create(
            user=self.user,
            character=self.character,
            title='Compact Test Session',
            origin='topic',
        )
        self.model_config = ModelConfiguration.objects.create(
            user=self.user,
            name='test-model',
            provider='openai_compatible',
            model_name='test-model',
            api_key='k',
            base_url='http://localhost',
            context_window=8000,
        )
        ModelRoleAssignment.objects.create(
            user=self.user,
            role='text',
            model_config=self.model_config,
        )

    def _append_turns(self, turns, *, chars=170):
        """Append ``turns`` user/assistant pairs, each message ~100 tokens."""
        from chat.events.store import EventStore
        from chat.models import ChatEventType

        EventStore.append(self.session, ChatEventType.SESSION_CREATED, {'origin': 'topic'})
        for index in range(turns):
            EventStore.append(
                self.session,
                ChatEventType.USER_MESSAGE,
                {'content': f'u{index} ' + '字' * chars},
                character=self.character,
            )
            EventStore.append(
                self.session,
                ChatEventType.ASSISTANT_MESSAGE,
                {'content': f'a{index} ' + '字' * chars},
                character=self.character,
            )


class SelectShadowRangeTests(CompactionBaseTests):
    def test_below_threshold_returns_none(self):
        from chat.events.compaction import select_shadow_range
        from chat.events.store import EventStore

        self._append_turns(2)  # ~400 tokens
        selected = select_shadow_range(
            EventStore.load(self.session),
            context_window=8000,
            threshold_ratio=0.7,
            retain_ratio=0.3,
            min_history_tokens=8000,
            min_retain_tokens=4000,
        )
        assert selected is None

    def test_above_threshold_selects_range_and_retains_tail(self):
        from chat.events.compaction import select_shadow_range
        from chat.events.store import EventStore

        self._append_turns(60)  # ~12000 tokens > 0.7 × 16000? no: threshold = 22400
        selected = select_shadow_range(
            EventStore.load(self.session),
            context_window=8000,
            threshold_ratio=0.7,
            retain_ratio=0.3,
            min_history_tokens=8000,
            min_retain_tokens=4000,
        )
        assert selected is not None
        start, end = selected
        assert start == 2  # first user message event
        # The retained tail must start with an assistant message (the summary
        # is a user-role message; user+user would collide).
        from chat.models import ChatEventType

        retained_seq = end + 1
        retained_roles = [
            e.event_type for e in EventStore.load(self.session)
            if e.seq >= retained_seq and e.event_type in (
                ChatEventType.USER_MESSAGE, ChatEventType.ASSISTANT_MESSAGE,
            )
        ]
        assert retained_roles
        assert retained_roles[0] == ChatEventType.ASSISTANT_MESSAGE

    def test_second_compaction_does_not_reshadow(self):
        from chat.events.compaction import select_shadow_range
        from chat.events.store import EventStore
        from chat.models import ChatEventType

        self._append_turns(60)
        first = select_shadow_range(
            EventStore.load(self.session),
            context_window=8000,
            threshold_ratio=0.7,
            retain_ratio=0.3,
            min_history_tokens=8000,
            min_retain_tokens=4000,
        )
        assert first is not None
        EventStore.append(
            self.session,
            ChatEventType.COMPACTION_SUMMARY,
            {
                'summary': '第一段摘要',
                'shadowed_start_seq': first[0],
                'shadowed_end_seq': first[1],
                'shadowed_count': 100,
                'tokens_freed': 9000,
            },
        )
        # Remaining history is ~3000 tokens < threshold, so no second range.
        second = select_shadow_range(
            EventStore.load(self.session),
            context_window=8000,
            threshold_ratio=0.7,
            retain_ratio=0.3,
            min_history_tokens=8000,
            min_retain_tokens=4000,
        )
        assert second is None


class CompactionTaskTests(CompactionBaseTests):
    def test_task_skips_below_threshold(self):
        from chat.tasks import compact_session_history

        self._append_turns(2)
        result = compact_session_history(self.session.id)
        assert result['status'] == 'skipped'

    def test_task_appends_summary_event_and_derive_renders_it(self):
        from chat.events.store import EventStore
        from chat.models import ChatEvent, ChatEventType
        from chat.tasks import compact_session_history

        self._append_turns(60)
        with patch('chat.tasks._generate_text', return_value='压缩后的摘要文本') as mock_generate:
            result = compact_session_history(self.session.id)
        assert result['status'] == 'compacted'
        mock_generate.assert_called_once()

        summary_event = ChatEvent.objects.filter(
            chat_session=self.session,
            event_type=ChatEventType.COMPACTION_SUMMARY,
        ).order_by('-seq').first()
        assert summary_event is not None
        data = summary_event.data
        assert data['summary'] == '压缩后的摘要文本'
        assert data['shadowed_start_seq'] == result['shadowed_start_seq']
        assert data['shadowed_end_seq'] == result['shadowed_end_seq']
        assert data['tokens_freed'] > 0

        # Derived compacted view shows the summary; full view keeps everything.
        compacted = EventStore.derive_messages(self.session, compacted=True)
        assert any(v.is_compacted_summary for v in compacted)
        full = EventStore.derive_messages(self.session, compacted=False)
        assert len(full) == 120  # 60 turns, none lost

    def test_task_survives_summary_failure(self):
        from chat.events.store import EventStore
        from chat.models import ChatEvent, ChatEventType
        from chat.tasks import compact_session_history

        self._append_turns(60)
        with patch('chat.tasks._generate_text', side_effect=RuntimeError('boom')):
            result = compact_session_history(self.session.id)
        assert result['status'] == 'error'
        assert not ChatEvent.objects.filter(
            chat_session=self.session,
            event_type=ChatEventType.COMPACTION_SUMMARY,
        ).exists()

    def test_maybe_dispatch_respects_enabled_flag(self):
        from chat.tasks import _maybe_dispatch_compaction

        self._append_turns(60)
        runtime_config = {'provider': 'openai_compatible', 'model_name': 'm', 'context_window': 8000}
        with patch('chat.tasks.compact_session_history.delay') as mock_delay:
            with override_settings(COMPACTION_ENABLED=False):
                _maybe_dispatch_compaction(self.session, runtime_config)
            mock_delay.assert_not_called()
            with override_settings(COMPACTION_ENABLED=True, COMPACTION_MIN_HISTORY_TOKENS=8000):
                _maybe_dispatch_compaction(self.session, runtime_config)
            mock_delay.assert_called_once()
