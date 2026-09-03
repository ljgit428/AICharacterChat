"""End-to-end tests for the event-sourced chat system (v0.1.4).

Drives the real HTTP API (REST + streaming) against the project's PostgreSQL
test database, mocking only the LLM network layer. Verifies the full event-
sourcing contract:

- every chat turn writes user/message + assistant/message events
- the Message projection stays byte-identical to what the events derive
- the model-facing prompt is built from the derived event view
- memory extraction consumes the projected messages
- compaction appends a summary event; the UI history stays full while the
  derived model view is compacted
- projection rebuild reproduces the original Message rows
"""
import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from chat.models import (
    Character,
    ChatEvent,
    ChatEventType,
    ChatSession,
    MemoryAuditLog,
    Message,
    MessageAttachment,
    ModelConfiguration,
    ModelRole,
    ModelRoleAssignment,
    UserProfile,
)


def _consume_streaming(response):
    """Consume a StreamingHttpResponse body, handling both sync and async
    iterators (the stream_message view now returns an async generator so
    chunks flow in real time under ASGI)."""
    content = response.streaming_content
    if hasattr(content, '__aiter__'):
        from asgiref.sync import async_to_sync

        async def _collect():
            chunks = []
            async for chunk in content:
                chunks.append(chunk)
            return b''.join(chunks)

        return async_to_sync(_collect)()
    return b''.join(content)


def _consume_streaming_partial(response, max_events):
    """Consume at most ``max_events`` NDJSON lines, then abandon the stream.

    Simulates the client closing the page mid-generation: the async iterator
    is finalized and the underlying sync generator is abandoned exactly where
    it stands — everything persisted up to that point stays written.
    """
    content = response.streaming_content
    if hasattr(content, '__aiter__'):
        from asgiref.sync import async_to_sync

        async def _collect():
            chunks = []
            async for chunk in content:
                chunks.append(chunk)
                if len(chunks) >= max_events:
                    break
            return b''.join(chunks)

        return async_to_sync(_collect)()
    return b''.join(content)


class ModelConfigMixin:
    """Reusable model-config and character setup (mirrors test_api.py)."""

    def create_model_config(self, user=None, **overrides):
        owner = user or self.user
        overrides.pop('is_default', None)
        defaults = {
            'name': 'E2E Test Model',
            'provider': 'openai_compatible',
            'model_name': 'gpt-4.1-mini',
            'api_key': 'e2e-api-key',
            'base_url': 'https://e2e.example.com/v1',
            'context_window': 32000,
        }
        defaults.update(overrides)
        config = ModelConfiguration.objects.create(user=owner, **defaults)
        ModelRoleAssignment.objects.update_or_create(
            user=owner,
            role=ModelRole.TEXT,
            defaults={'model_config': config},
        )
        return config


# ---------------------------------------------------------------------------
#  1.  Full turn through REST send_message
# ---------------------------------------------------------------------------

@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
@override_settings(COMPACTION_ENABLED=False)
@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class ChatTurnE2ETests(ModelConfigMixin, TestCase):
    """One``send_message`` turn: event log, projection, memory extraction."""

    def setUp(self):
        self.user = User.objects.create_user(username='e2e-user', password='x')
        self.character = Character.objects.create(
            created_by=self.user,
            name='E2E Character',
            description='A character for end-to-end tests.',
            scenario='Test',
            tags=['e2e'],
        )
        self.create_model_config()
        # Enable long-term memory for the memory-extraction assertion.
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={'allow_long_term_memory': True},
        )
        self.client.force_login(self.user)

    def _canned_tool_call_response(self, section, description, reason='E2E test'):
        return {
            'choices': [{
                'message': {
                    'role': 'assistant',
                    'content': '',
                    'tool_calls': [{
                        'id': 'call_e2e_1',
                        'type': 'function',
                        'function': {
                            'name': 'create_memory',
                            'arguments': json.dumps({
                                'section': section,
                                'description': description,
                                'reason': reason,
                            }),
                        },
                    }],
                },
            }],
        }

    def test_send_message_writes_events_projection_and_memory(self):
        """A full turn through the non-streaming REST API: event log,
        Message projection, derive_messages, and memory extraction."""
        from chat.tasks import sync_long_term_memory

        # Mock the main reply and the memory-extraction tool-call loop.
        reply_text = '你好，我是 E2E 角色！'
        memory_tool = self._canned_tool_call_response('identity', 'Likes E2E testing.')
        terminal = {'choices': [{'message': {'role': 'assistant', 'content': 'noop', 'tool_calls': []}}]}

        # memory-tool calls: _collect_memory_actions loop uses
        # _request_openai_compatible_completion.  The first call gets the
        # tool-call response, the second gets the terminal.
        main_mock = patch('chat.tasks._generate_text', return_value=reply_text)
        memory_mock = patch(
            'chat.tasks._request_openai_compatible_completion',
            side_effect=[memory_tool, terminal],
        )
        with main_mock, memory_mock:
            response = self.client.post(
                '/api/chat/send_message/',
                data=json.dumps({
                    'character_id': self.character.id,
                    'message': '你好呀！',
                }),
                content_type='application/json',
            )

        # ---- response ----
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('ai_message', payload)
        self.assertIn('user_message', payload)
        self.assertEqual(payload['ai_message']['content'], reply_text)
        self.assertEqual(payload['user_message']['content'], '你好呀！')

        # ---- event log ----
        events = list(ChatEvent.objects.filter(chat_session_id=payload['chat_session_id']).order_by('seq'))
        self.assertEqual(len(events), 3)  # session/created + user/message + assistant/message
        self.assertEqual(events[0].event_type, ChatEventType.SESSION_CREATED)
        self.assertEqual(events[1].event_type, ChatEventType.USER_MESSAGE)
        self.assertEqual(events[2].event_type, ChatEventType.ASSISTANT_MESSAGE)
        self.assertEqual(events[1].data['content'], '你好呀！')
        self.assertEqual(events[2].data['content'], reply_text)
        # seq monotonic
        self.assertEqual(events[0].seq, 1)
        self.assertEqual(events[1].seq, 2)
        self.assertEqual(events[2].seq, 3)

        # ---- Message projection matches events ----
        session = ChatSession.objects.get(id=payload['chat_session_id'])
        messages = list(Message.objects.filter(chat_session=session).order_by('timestamp'))
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].content, '你好呀！')
        self.assertEqual(messages[1].content, reply_text)

        # ---- derive_messages matches ----
        from chat.events.store import EventStore
        derived = EventStore.derive_messages(session, compacted=False)
        self.assertEqual(len(derived), 2)
        self.assertEqual(derived[0].content, '你好呀！')
        self.assertEqual(derived[1].content, reply_text)

        # ---- memory extraction ran ----
        memory_items = list(self.character.memory_items.all())
        self.assertEqual(len(memory_items), 1)
        self.assertEqual(memory_items[0].section, 'identity')
        self.assertEqual(memory_items[0].description, 'Likes E2E testing.')
        self.assertTrue(
            MemoryAuditLog.objects.filter(character=self.character, action='create').exists()
        )

    def test_send_message_second_turn_appends_events_in_order(self):
        """Two turns via the API: seqs continue monotonically."""
        from chat.tasks import sync_long_term_memory

        reply = '回复'
        terminal = {'choices': [{'message': {'role': 'assistant', 'content': 'noop', 'tool_calls': []}}]}
        main_mock = patch('chat.tasks._generate_text', return_value=reply)
        memory_mock = patch(
            'chat.tasks._request_openai_compatible_completion',
            return_value=terminal,
        )
        with main_mock, memory_mock:
            r1 = self.client.post(
                '/api/chat/send_message/',
                data=json.dumps({'character_id': self.character.id, 'message': '第一句'}),
                content_type='application/json',
            )
            r2 = self.client.post(
                '/api/chat/send_message/',
                data=json.dumps({
                    'character_id': self.character.id,
                    'chat_session_id': r1.json()['chat_session_id'],
                    'message': '第二句',
                }),
                content_type='application/json',
            )

        session = ChatSession.objects.get(id=r1.json()['chat_session_id'])
        events = list(ChatEvent.objects.filter(chat_session=session).order_by('seq'))
        # 1 session/created + 2 user + 2 assistant = 5
        self.assertEqual(len(events), 5)
        self.assertEqual(events[1].data['content'], '第一句')
        self.assertEqual(events[3].data['content'], '第二句')
        self.assertEqual(events[1].seq, 2)
        self.assertEqual(events[3].seq, 4)

        from chat.events.store import EventStore
        derived = EventStore.derive_messages(session, compacted=False)
        self.assertEqual(len(derived), 4)
        self.assertEqual(derived[0].content, '第一句')
        self.assertEqual(derived[2].content, '第二句')


# ---------------------------------------------------------------------------
#  2.  Streaming endpoint (stream_message)
# ---------------------------------------------------------------------------

@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
@override_settings(COMPACTION_ENABLED=False)
@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class StreamingE2ETests(ModelConfigMixin, TestCase):
    """The NDJSON streaming endpoint with a fake SSE backend."""

    def setUp(self):
        self.user = User.objects.create_user(username='stream-user', password='x')
        self.character = Character.objects.create(
            created_by=self.user,
            name='Stream Character',
            description='For streaming e2e tests.',
            scenario='Test',
            tags=['e2e-stream'],
        )
        self.create_model_config()
        self.client.force_login(self.user)

    def test_stream_message_writes_events_and_returns_ndjson(self):
        """Streaming endpoint: fake chunks → events + projection + done.

        ``_iter_text_chunks`` is mocked directly because with memory tools the
        openai_compatible path is buffered, not streamed.
        """
        fake_chunks = [
            {'type': 'delta', 'content': '你好'},
            {'type': 'delta', 'content': '世界！'},
            {'type': 'usage', 'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}},
        ]

        with (
            patch('chat.tasks._iter_text_chunks', return_value=iter(fake_chunks)),
            # The eager memory-extraction task inside _finalize_ai_response
            # calls the non-streaming completion; keep it mocked too.
            patch(
                'chat.tasks._request_openai_compatible_completion',
                return_value={'choices': [{'message': {'role': 'assistant', 'content': 'noop', 'tool_calls': []}}]},
            ),
        ):
            response = self.client.post(
                '/api/chat/stream_message/',
                data=json.dumps({
                    'character_id': self.character.id,
                    'message': '测试流式回复',
                }),
                content_type='application/json',
            )

            # StreamingHttpResponse is lazy: the generator body (and thus the
            # mocked backend) runs only while the content is consumed, so the
            # patch must stay active during iteration.
            lines = [
                json.loads(line)
                for line in _consume_streaming(response).decode('utf-8').splitlines()
                if line.strip()
            ]

        self.assertEqual(response.status_code, 200)
        event_types = [line['type'] for line in lines]
        self.assertEqual(event_types, ['session', 'delta', 'delta', 'done'])

        # The done event carries the full aggregated text.
        done = lines[-1]
        self.assertEqual(done['type'], 'done')
        self.assertEqual(done['content'], '你好世界！')

        # ---- event log ----
        session_id = lines[0]['chat_session_id']
        session = ChatSession.objects.get(id=session_id)
        events = list(ChatEvent.objects.filter(chat_session=session).order_by('seq'))
        self.assertEqual(len(events), 3)
        self.assertEqual(events[1].data['content'], '测试流式回复')
        self.assertEqual(events[2].data['content'], '你好世界！')

        # ---- Message projection ----
        messages = list(Message.objects.filter(chat_session=session).order_by('timestamp'))
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[1].content, '你好世界！')

        # ---- derive_messages ----
        from chat.events.store import EventStore
        derived = EventStore.derive_messages(session, compacted=False)
        self.assertEqual(len(derived), 2)
        self.assertEqual(derived[1].content, '你好世界！')

    def test_stream_message_persists_partial_reply_after_page_closes(self):
        """增量落库 e2e：消费端中途断开（模拟关页）后，已生成的工具调用与
        部分正文已经写库，草稿保持 streaming——重开页面能看到已生成内容。"""
        fake_chunks = [
            {'type': 'tool', 'tool': 'web_search', 'arguments': {'query': '今天的天气'}},
            # 无标记的思考必须立即实时透传（旧拆分器要缓冲 1200 字符）。
            {'type': 'thinking', 'content': '先想一下'},
            {'type': 'delta', 'content': '你好'},
            {'type': 'delta', 'content': '世界！'},
            {'type': 'usage', 'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}},
        ]

        with (
            patch('chat.tasks._iter_text_chunks', return_value=iter(fake_chunks)),
            # The eager memory-extraction task inside _finalize_ai_response
            # calls the non-streaming completion; keep it mocked too.
            patch(
                'chat.tasks._request_openai_compatible_completion',
                return_value={'choices': [{'message': {'role': 'assistant', 'content': 'noop', 'tool_calls': []}}]},
            ),
        ):
            response = self.client.post(
                '/api/chat/stream_message/',
                data=json.dumps({
                    'character_id': self.character.id,
                    'message': '测试增量落库',
                }),
                content_type='application/json',
            )
            # 只消费 session + tool + thinking 就"关页"。
            _consume_streaming_partial(response, 3)

        session = self.character.chat_sessions.first()
        messages = list(Message.objects.filter(chat_session=session).order_by('timestamp'))
        self.assertEqual(len(messages), 2)
        reply = messages[1]
        self.assertEqual(reply.role, 'assistant')
        # 已生成部分逐段落库；未到达的 delta 与 done 不写。
        self.assertEqual(reply.content, '')
        self.assertEqual(reply.thinking, '先想一下')
        self.assertEqual(reply.tool_calls, [{'tool': 'web_search', 'arguments': {'query': '今天的天气'}}])
        # 页面关闭 = 流被放弃：没有 done/error 收尾，状态停留在 streaming。
        self.assertEqual(reply.status, 'streaming')

        # 事件日志与投影一致（单一真相来源，重建不丢部分内容）。
        assistant_event = ChatEvent.objects.filter(
            chat_session=session, event_type=ChatEventType.ASSISTANT_MESSAGE,
        ).get()
        self.assertEqual(assistant_event.data['content'], '')
        self.assertEqual(assistant_event.data['thinking'], '先想一下')
        self.assertEqual(assistant_event.data['status'], 'streaming')

    def test_stream_message_marks_interrupted_and_keeps_partial_on_failure(self):
        """生成中途报错：已生成部分保留为 interrupted（含思考/工具），
        前端重开页面能看到部分内容并得到"被中断"标记。"""
        def _chunks_that_fail(*args, **kwargs):
            yield {'type': 'delta', 'content': '前半句'}
            yield {'type': 'delta', 'content': '后半句'}
            raise RuntimeError('model exploded')

        with (
            patch('chat.tasks._iter_text_chunks', _chunks_that_fail),
            patch(
                'chat.tasks._request_openai_compatible_completion',
                return_value={'choices': [{'message': {'role': 'assistant', 'content': 'noop', 'tool_calls': []}}]},
            ),
        ):
            response = self.client.post(
                '/api/chat/stream_message/',
                data=json.dumps({
                    'character_id': self.character.id,
                    'message': '测试失败保留',
                }),
                content_type='application/json',
            )
            lines = [
                json.loads(line)
                for line in _consume_streaming(response).decode('utf-8').splitlines()
                if line.strip()
            ]

        self.assertEqual(response.status_code, 200)
        self.assertEqual([line['type'] for line in lines], ['session', 'delta', 'delta', 'error'])

        session = self.character.chat_sessions.first()
        messages = list(Message.objects.filter(chat_session=session).order_by('timestamp'))
        self.assertEqual(len(messages), 2)
        reply = messages[1]
        self.assertEqual(reply.content, '前半句后半句')
        self.assertEqual(reply.status, 'interrupted')

    def test_stream_message_discards_draft_when_failure_produces_nothing(self):
        """生成瞬间报错且没有任何内容：撤销空草稿，回到旧行为（error 事件兜底）。"""
        def _chunks_fail_immediately(*args, **kwargs):
            raise RuntimeError('model exploded')
            yield  # pragma: no cover — 使该函数成为生成器

        with (
            patch('chat.tasks._iter_text_chunks', _chunks_fail_immediately),
            patch(
                'chat.tasks._request_openai_compatible_completion',
                return_value={'choices': [{'message': {'role': 'assistant', 'content': 'noop', 'tool_calls': []}}]},
            ),
        ):
            response = self.client.post(
                '/api/chat/stream_message/',
                data=json.dumps({
                    'character_id': self.character.id,
                    'message': '测试空失败',
                }),
                content_type='application/json',
            )
            lines = [
                json.loads(line)
                for line in _consume_streaming(response).decode('utf-8').splitlines()
                if line.strip()
            ]

        self.assertEqual([line['type'] for line in lines], ['session', 'error'])

        session = self.character.chat_sessions.first()
        # 事件日志只留 session/created + user/message；投影只有一条用户消息。
        events = list(ChatEvent.objects.filter(chat_session=session).order_by('seq'))
        self.assertEqual(len(events), 2)
        self.assertEqual(Message.objects.filter(chat_session=session).count(), 1)


# ---------------------------------------------------------------------------
#  3.  Compaction end-to-end via long conversation + task
# ---------------------------------------------------------------------------

@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
@override_settings(COMPACTION_ENABLED=True)
@override_settings(COMPACTION_MIN_HISTORY_TOKENS=8000)
@override_settings(COMPACTION_THRESHOLD_RATIO=0.7)
@override_settings(COMPACTION_RETAIN_RATIO=0.3)
@override_settings(COMPACTION_MIN_RETAIN_TOKENS=4000)
@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class CompactionE2ETests(ModelConfigMixin, TestCase):
    """Long conversation → compaction → derived view / UI view / rebuild."""

    def setUp(self):
        self.user = User.objects.create_user(username='compact-e2e', password='x')
        self.character = Character.objects.create(
            created_by=self.user,
            name='Compact E2E',
            description='For compaction e2e tests.',
            scenario='Test',
            tags=['e2e-compact'],
        )
        self.create_model_config(context_window=8000)
        self.client.force_login(self.user)
        # Skip memory-extraction work during the long loop.
        self.mock_collect = patch('chat.tasks._collect_memory_actions', return_value=[])

    def _drive_conversation(self, turns, message_chars=200, reply_text=None):
        """Drive turns via the non-streaming API with a mocked LLM reply.

        Auto-compaction is disabled during the loop (CELERY_TASK_ALWAYS_EAGER
        would otherwise run compaction inline inside ``_finalize_ai_response``);
        the test then triggers compaction explicitly. Messages are padded so
        the history accumulates enough estimated tokens to cross the
        compaction threshold.
        """
        reply_text = reply_text or ('回复' + '字' * message_chars)
        session_id = None
        with (
            override_settings(COMPACTION_ENABLED=False),
            self.mock_collect,
            patch('chat.tasks._generate_text', return_value=reply_text),
        ):
            for i in range(turns):
                data = {
                    'character_id': self.character.id,
                    'message': f'第{i+1}条消息 ' + '字' * message_chars,
                }
                if session_id:
                    data['chat_session_id'] = session_id
                response = self.client.post(
                    '/api/chat/send_message/',
                    data=json.dumps(data),
                    content_type='application/json',
                )
                self.assertEqual(response.status_code, 200)
                if session_id is None:
                    session_id = response.json()['chat_session_id']
        return session_id

    def test_compaction_end_to_end(self):
        """60 turns → compact → verify summary event, derived view, UI view,
        and rebuild."""
        from chat.events.store import EventStore, active_history_tokens, history_tokens
        from chat.events.projection import rebuild_session_messages
        from chat.tasks import compact_session_history

        session_id = self._drive_conversation(60)
        session = ChatSession.objects.get(id=session_id)

        # ---- Before compaction: all events visible ----
        total_events = ChatEvent.objects.filter(chat_session=session).count()
        all_messages = list(Message.objects.filter(chat_session=session).order_by('timestamp'))
        self.assertEqual(len(all_messages), 120)  # 60 turns

        # ---- Run compaction (mocked summary) ----
        summary_text = '这是前 40 轮对话的摘要。'
        with patch('chat.tasks._generate_text', return_value=summary_text):
            result = compact_session_history(session_id)

        self.assertEqual(result['status'], 'compacted')

        # ---- compaction/summary event appended ----
        summary_event = ChatEvent.objects.filter(
            chat_session=session,
            event_type=ChatEventType.COMPACTION_SUMMARY,
        ).order_by('-seq').first()
        self.assertIsNotNone(summary_event)
        data = summary_event.data
        self.assertEqual(data['summary'], summary_text)
        self.assertIn('shadowed_start_seq', data)
        self.assertIn('shadowed_end_seq', data)
        self.assertGreater(data['tokens_freed'], 0)

        # ---- Derived compacted view: summary + retained tail ----
        compacted = EventStore.derive_messages(session, compacted=True)
        self.assertTrue(any(v.is_compacted_summary for v in compacted))
        summary_views = [v for v in compacted if v.is_compacted_summary]
        self.assertEqual(len(summary_views), 1)
        self.assertIn(summary_text, summary_views[0].content)

        # The compacted view has fewer view messages than the full history.
        self.assertLess(len(compacted), 120)

        # ---- UI view (full history) stays intact ----
        full = EventStore.derive_messages(session, compacted=False)
        self.assertEqual(len(full), 120)

        # UI history API also returns all messages.
        self.client.force_login(self.user)
        hist_response = self.client.get(f'/api/messages/?chat_session_id={session_id}')
        self.assertEqual(hist_response.status_code, 200)
        self.assertEqual(len(hist_response.json()), 120)

        # ---- active tokens dropped, no redispatch ----
        self.assertGreater(history_tokens(session), 0)
        self.assertLess(
            active_history_tokens(session),
            history_tokens(session),
        )

        # ---- Projection rebuild reproduces identical rows ----
        before = list(Message.objects.filter(chat_session=session).order_by('timestamp'))
        before_snapshot = [(m.role, m.content, m.thinking) for m in before]
        rebuilt = rebuild_session_messages(session)
        after_snapshot = [(m.role, m.content, m.thinking) for m in rebuilt]
        self.assertEqual(after_snapshot, before_snapshot)