import json
import os
import requests
import shutil
import tempfile
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from chat.models import (
    AttachmentKind,
    Character,
    CharacterKnowledgeAsset,
    ChatSession,
    Message,
    MessageAttachment,
    ModelConfiguration,
    ModelRole,
    ModelRoleAssignment,
    UserProfile,
    WebSearchConfiguration,
)
from chat.search import search_web
from chat.attachments import (
    MAX_AUDIO_ATTACHMENT_BYTES,
    MAX_IMAGE_ATTACHMENT_BYTES,
    MAX_TEXT_ATTACHMENT_BYTES,
    MAX_VIDEO_ATTACHMENT_BYTES,
    _format_size_limit,
    guess_attachment_kind,
    validate_attachment_size,
)
from chat.memory.filesystem import CharacterMemoryFilesystem, StagedUploadMemoryFilesystem
from chat.soul import (
    build_character_prompt_context,
    build_character_system_prompt_preview,
    build_character_setup_markdown,
    list_memory_explorer_path,
    read_memory_explorer_file,
)
from chat.tasks import (
    MEDIA_ANALYSIS_MAX_BYTES,
    _build_memory_tool_specs,
    _build_provider_messages,
    _build_search_query,
    _build_stream_memory_prefetch,
    _build_system_prompt,
    _build_anthropic_request_messages,
    _convert_tools_to_anthropic,
    _DualThinkingSplitter,
    _generate_anthropic_response,
    _generate_openai_compatible_response,
    _get_or_upload_generativeai_file,
    _prepare_generation,
    build_research_context,
    stream_ai_response,
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


class ModelConfigTestMixin:
    """模型配置 + 角色槽位的测试辅助，供多个 TestCase 复用（要求 self.user 存在）。"""

    def create_model_config(self, user=None, **overrides):
        owner = user or self.user
        overrides.pop('is_default', None)
        defaults = {
            'name': 'Default User Model',
            'provider': 'openai_compatible',
            'model_name': 'gpt-4.1-mini',
            'api_key': 'user-api-key',
            'base_url': 'https://example.com/v1',
        }
        defaults.update(overrides)
        config = ModelConfiguration.objects.create(user=owner, **defaults)
        ModelRoleAssignment.objects.update_or_create(
            user=owner,
            role=ModelRole.TEXT,
            defaults={'model_config': config},
        )
        return config

    def create_media_model_config(self, role, user=None, **overrides):
        owner = user or self.user
        overrides.pop('is_default', None)
        defaults = {
            'name': f'{role.title()} Role Model',
            'provider': 'openai_compatible',
            'model_name': f'{role}-role-model',
            'api_key': 'role-api-key',
            'base_url': 'https://role.example.com/v1',
        }
        defaults.update(overrides)
        config = ModelConfiguration.objects.create(user=owner, **defaults)
        ModelRoleAssignment.objects.update_or_create(
            user=owner,
            role=role,
            defaults={'model_config': config},
        )
        return config


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class AuthorizationRegressionTests(ModelConfigTestMixin, TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='owner', password='password123')
        self.other_user = User.objects.create_user(username='other', password='password123')

        self.own_character = Character.objects.create(
            created_by=self.user,
            name='Owner Character',
            avatar_url='',
            description='Owned by the current user.',
            personality='Calm',
            appearance='Blue jacket',
            scenario='Library',
            example_dialogue='',
            affiliation='Team A',
            tags=['owner'],
        )
        self.other_character = Character.objects.create(
            created_by=self.other_user,
            name='Other Character',
            avatar_url='',
            description='Owned by another user.',
            personality='Serious',
            appearance='Black coat',
            scenario='Street',
            example_dialogue='',
            affiliation='Team B',
            tags=['other'],
        )

        self.own_session = ChatSession.objects.create(
            user=self.user,
            character=self.own_character,
            title='Owner Session',
        )
        self.other_session = ChatSession.objects.create(
            user=self.other_user,
            character=self.other_character,
            title='Other Session',
        )

    def create_web_search_config(self, user=None, **overrides):
        owner = user or self.user
        defaults = {
            'provider': 'tavily',
            'api_key': 'tavily-secret',
            'max_results': 5,
        }
        defaults.update(overrides)
        return WebSearchConfiguration.objects.create(user=owner, **defaults)

    def graphql(self, query, variables=None, user=None):
        if user:
            self.client.force_login(user)

        response = self.client.post(
            '/api/graphql/',
            data=json.dumps({
                'query': query,
                'variables': variables or {},
            }),
            content_type='application/json',
        )
        return response

    def test_rest_character_list_only_returns_authenticated_users_characters(self):
        self.client.force_login(self.user)

        response = self.client.get('/api/characters/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]['id'], self.own_character.id)

    def test_graphql_characters_query_only_returns_authenticated_users_characters(self):
        response = self.graphql(
            """
            query {
              characters {
                id
                name
              }
            }
            """,
            user=self.user,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('errors', payload)
        self.assertEqual(payload['data']['characters'], [
            {'id': str(self.own_character.id), 'name': self.own_character.name}
        ])

    def test_graphql_chat_sessions_query_only_returns_authenticated_users_sessions(self):
        response = self.graphql(
            """
            query {
              chatSessions {
                id
                title
              }
            }
            """,
            user=self.user,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('errors', payload)
        self.assertEqual(payload['data']['chatSessions'], [
            {'id': str(self.own_session.id), 'title': self.own_session.title}
        ])

    def test_graphql_update_character_rejects_cross_user_access(self):
        response = self.graphql(
            """
            mutation UpdateCharacter($id: ID!, $input: CharacterInput!) {
              updateCharacter(id: $id, input: $input) {
                id
                name
              }
            }
            """,
            variables={
                'id': str(self.other_character.id),
                'input': {
                    'name': self.other_character.name,
                    'avatarUrl': self.other_character.avatar_url or '',
                    'description': self.other_character.description,
                    'personality': self.other_character.personality or '',
                    'appearance': self.other_character.appearance or '',
                    'scenario': self.other_character.scenario,
                    'exampleDialogue': self.other_character.example_dialogue,
                    'affiliation': self.other_character.affiliation,
                    'tags': self.other_character.tags,
                },
            },
            user=self.user,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('errors', payload)
        self.other_character.refresh_from_db()
        self.assertEqual(self.other_character.name, 'Other Character')

    def test_graphql_update_character_allows_owner_to_edit_character(self):
        response = self.graphql(
            """
            mutation UpdateCharacter($id: ID!, $input: CharacterInput!) {
              updateCharacter(id: $id, input: $input) {
                id
                name
              }
            }
            """,
            variables={
                'id': str(self.own_character.id),
                'input': {
                    'name': 'Updated Owner Character',
                    'avatarUrl': self.own_character.avatar_url or '',
                    'description': self.own_character.description,
                    'personality': self.own_character.personality or '',
                    'appearance': self.own_character.appearance or '',
                    'responseGuidelines': 'Stay focused.',
                    'scenario': 'Updated library',
                    'exampleDialogue': self.own_character.example_dialogue,
                    'affiliation': self.own_character.affiliation,
                    'tags': self.own_character.tags,
                },
            },
            user=self.user,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('errors', payload)
        self.assertEqual(payload['data']['updateCharacter']['name'], 'Updated Owner Character')

        self.own_character.refresh_from_db()
        self.assertEqual(self.own_character.name, 'Updated Owner Character')
        self.assertEqual(self.own_character.scenario, 'Updated library')

    def test_rest_delete_character_deletes_character_with_chat_sessions(self):
        self.client.force_login(self.user)

        response = self.client.delete(f'/api/characters/{self.own_character.id}/')

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Character.objects.filter(id=self.own_character.id).exists())
        self.assertFalse(ChatSession.objects.filter(id=self.own_session.id).exists())

    def test_rest_delete_character_allows_delete_without_chat_sessions(self):
        self.client.force_login(self.user)
        deletable_character = Character.objects.create(
            created_by=self.user,
            name='Disposable Character',
            avatar_url='',
            description='No chat history yet.',
            personality='Quiet',
            appearance='Grey sweater',
            scenario='Cafe',
            example_dialogue='',
            affiliation='Team C',
            tags=['disposable'],
        )

        response = self.client.delete(f'/api/characters/{deletable_character.id}/')

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Character.objects.filter(id=deletable_character.id).exists())

    def test_graphql_requires_authentication(self):
        response = self.graphql(
            """
            query {
              characters {
                id
              }
            }
            """
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('errors', payload)

    @patch('chat.graphql.schema._generate_text')
    def test_generate_character_draft_uses_default_user_model_configuration(self, mock_generate_text):
        self.create_model_config(name='Default Draft Model')
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={'interface_language': 'en-US'},
        )
        mock_generate_text.return_value = json.dumps({
            'name': 'Drafted Character',
            'description': 'A detailed background in three sentences. Second sentence. Third sentence.',
            'affiliation': 'Lab',
            'tags': ['lab', 'research', 'calm'],
        })

        response = self.graphql(
            """
            mutation GenerateDraft($textContext: String) {
              generateCharacterDraft(textContext: $textContext) {
                name
                description
                affiliation
                tags
              }
            }
            """,
            variables={'textContext': 'Character concept from the user.'},
            user=self.user,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('errors', payload)
        self.assertEqual(payload['data']['generateCharacterDraft']['name'], 'Drafted Character')

        runtime_config, prompt = mock_generate_text.call_args[0]
        self.assertEqual(runtime_config, {
            'provider': 'openai_compatible',
            'model_name': 'gpt-4.1-mini',
            'api_key': 'user-api-key',
            'base_url': 'https://example.com/v1',
        })
        self.assertIn('Character concept from the user.', prompt)
        self.assertIn('do NOT invent lore, appearance, scenario, or opening lines', prompt)

    @patch('chat.graphql.schema._generate_text')
    def test_generate_character_draft_recovers_from_fenced_json_response(self, mock_generate_text):
        self.create_model_config(name='Default Draft Model')
        mock_generate_text.return_value = (
            '```json\n'
            '{"name": "Fenced Character", "description": "Three sentences here. Second one. Third one.",'
            ' "affiliation": "Lab", "tags": ["fenced", "recovered"]}\n'
            '```'
        )

        response = self.graphql(
            """
            mutation GenerateDraft($textContext: String) {
              generateCharacterDraft(textContext: $textContext) {
                name
                affiliation
                tags
              }
            }
            """,
            variables={'textContext': 'Character concept from the user.'},
            user=self.user,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('errors', payload)
        self.assertEqual(payload['data']['generateCharacterDraft']['name'], 'Fenced Character')
        self.assertEqual(payload['data']['generateCharacterDraft']['affiliation'], 'Lab')
        self.assertEqual(payload['data']['generateCharacterDraft']['tags'], ['fenced', 'recovered'])

    @patch('chat.graphql.schema._generate_text')
    def test_generate_character_draft_recovers_from_prose_wrapped_json(self, mock_generate_text):
        self.create_model_config(name='Default Draft Model')
        mock_generate_text.return_value = (
            'Sure, here is the draft you asked for:\n'
            '{"name": "Prose Character", "description": "A.", "affiliation": "Crew", "tags": []}\n'
            'Let me know if you want changes!'
        )

        response = self.graphql(
            """
            mutation GenerateDraft($textContext: String) {
              generateCharacterDraft(textContext: $textContext) {
                name
                affiliation
              }
            }
            """,
            variables={'textContext': 'Character concept from the user.'},
            user=self.user,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('errors', payload)
        self.assertEqual(payload['data']['generateCharacterDraft']['name'], 'Prose Character')
        self.assertEqual(payload['data']['generateCharacterDraft']['affiliation'], 'Crew')

    @patch('chat.graphql.schema._generate_text')
    def test_generate_character_draft_hard_fails_with_raw_preview_when_model_returns_non_json(
        self, mock_generate_text,
    ):
        # A chat-tuned model that ignores the "return ONLY raw JSON"
        # instruction, or a misconfigured proxy that returns a debug
        # message, is a contract violation. The mutation must hard-fail
        # (name='Generation Failed', not silently fill the form) AND
        # embed a preview of the raw model response in the error
        # message so the user can see what went wrong without checking
        # /tmp.
        self.create_model_config(name='Default Draft Model')
        mock_generate_text.return_value = (
            '[mock from empty-key glm-5.2] hi, no Authorization header reached me at http://localhost:8800.'
        )

        response = self.graphql(
            """
            mutation GenerateDraft($textContext: String) {
              generateCharacterDraft(textContext: $textContext) {
                name
                description
                affiliation
                personality
                tags
                exampleDialogue
              }
            }
            """,
            variables={'textContext': 'Character concept from the user.'},
            user=self.user,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('errors', payload)
        draft = payload['data']['generateCharacterDraft']
        self.assertEqual(draft['name'], 'Generation Failed')
        self.assertIn('Model did not return a valid JSON object', draft['description'])
        self.assertIn('Raw model response preview', draft['description'])
        self.assertIn(
            '[mock from empty-key glm-5.2] hi, no Authorization header reached me at http://localhost:8800.',
            draft['description'],
        )
        # The rest of the fields must be empty so the user does not get
        # a half-populated form they might mistake for success.
        self.assertEqual(draft['affiliation'], '')
        self.assertEqual(draft['personality'], '')
        self.assertEqual(draft['exampleDialogue'], '')
        self.assertEqual(draft['tags'], [])

    @patch('chat.graphql.schema._generate_text')
    def test_generate_character_draft_hard_fails_when_model_returns_empty_string(
        self, mock_generate_text,
    ):
        # An empty model response is also a contract violation; the user
        # should see the (empty response) marker in the error message
        # rather than a silently successful draft.
        self.create_model_config(name='Default Draft Model')
        mock_generate_text.return_value = ''

        response = self.graphql(
            """
            mutation GenerateDraft($textContext: String) {
              generateCharacterDraft(textContext: $textContext) {
                name
                description
                tags
              }
            }
            """,
            variables={'textContext': 'Character concept from the user.'},
            user=self.user,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('errors', payload)
        draft = payload['data']['generateCharacterDraft']
        self.assertEqual(draft['name'], 'Generation Failed')
        self.assertIn('(empty response)', draft['description'])
        self.assertEqual(draft['tags'], [])

    @patch('chat.graphql.schema._generate_text')
    def test_generate_character_draft_error_message_truncates_very_long_raw_response(
        self, mock_generate_text,
    ):
        # A 5_000-char model response (e.g. a verbose prose reply) must
        # be truncated in the error message so the PrisMateDraft
        # description does not blow up; the truncation marker must
        # point at the /tmp dump where the full text lives.
        self.create_model_config(name='Default Draft Model')
        long_raw = 'x' * 5_000
        mock_generate_text.return_value = long_raw

        response = self.graphql(
            """
            mutation GenerateDraft($textContext: String) {
              generateCharacterDraft(textContext: $textContext) {
                name
                description
              }
            }
            """,
            variables={'textContext': 'Character concept from the user.'},
            user=self.user,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        draft = payload['data']['generateCharacterDraft']
        self.assertEqual(draft['name'], 'Generation Failed')
        self.assertIn('[truncated; full response was 5000 chars', draft['description'])
        self.assertIn('see the backend log for the parser dump file path', draft['description'])
        self.assertNotIn('/tmp/ai_draft_raw_', draft['description'])
        self.assertLess(len(draft['description']), 2_000)

    @patch('chat.graphql.schema._generate_text')
    def test_generate_character_draft_uses_simplified_chinese_prompt_when_requested(self, mock_generate_text):
        self.create_model_config(name='Default Draft Model')
        mock_generate_text.return_value = json.dumps({
            'name': '草稿角色',
            'description': '第一句。第二句。第三句。',
            'affiliation': '研究所',
            'tags': ['冷静', '研究', '档案'],
        })

        response = self.graphql(
            """
            mutation GenerateDraft($textContext: String, $locale: String) {
              generateCharacterDraft(textContext: $textContext, locale: $locale) {
                name
                description
              }
            }
            """,
            variables={'textContext': '角色概念来自用户。', 'locale': 'zh-CN'},
            user=self.user,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('errors', payload)
        self.assertEqual(payload['data']['generateCharacterDraft']['name'], '草稿角色')

        _, prompt = mock_generate_text.call_args[0]
        self.assertIn('你是一名专业的角色设计师。', prompt)
        self.assertIn('[用户输入上下文]', prompt)
        self.assertIn('角色概念来自用户。', prompt)

    def test_generate_character_draft_fails_without_user_model_configuration(self):
        response = self.graphql(
            """
            mutation GenerateDraft($textContext: String) {
              generateCharacterDraft(textContext: $textContext) {
                name
                description
              }
            }
            """,
            variables={'textContext': 'Character concept from the user.'},
            user=self.user,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('errors', payload)
        self.assertEqual(payload['data']['generateCharacterDraft']['name'], 'Generation Failed')
        self.assertIn(
            'Please configure your own model API before using this feature.',
            payload['data']['generateCharacterDraft']['description'],
        )

    def test_stream_message_requires_user_model_configuration(self):
        self.client.force_login(self.user)

        response = self.client.post(
            '/api/chat/stream_message/',
            data=json.dumps({
                'character_id': self.own_character.id,
                'start_conversation': True,
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'Please configure your own model API in Project Settings before starting a chat.',
            response.json()['error'],
        )

    def test_user_profile_me_endpoint_creates_and_updates_profile(self):
        self.client.force_login(self.user)

        get_response = self.client.get('/api/user-profile/me/')
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()['timezone'], 'UTC')

        patch_response = self.client.patch(
            '/api/user-profile/me/',
            data=json.dumps({
                'preferred_name': 'Owner Alias',
                'default_enable_web_search': True,
                'interface_language': 'en-US',
                'share_location': True,
                'location_precision': 'city',
                'location_label': 'Boston, MA',
                'allow_long_term_memory': False,
            }),
            content_type='application/json',
        )

        self.assertEqual(patch_response.status_code, 200)
        payload = patch_response.json()
        self.assertEqual(payload['preferred_name'], 'Owner Alias')
        self.assertTrue(payload['default_enable_web_search'])
        self.assertEqual(payload['interface_language'], 'en-US')
        self.assertTrue(payload['share_location'])
        self.assertEqual(payload['location_label'], 'Boston, MA')
        self.assertFalse(payload['allow_long_term_memory'])

    def test_user_profile_rejects_invalid_timezone(self):
        self.client.force_login(self.user)

        response = self.client.patch(
            '/api/user-profile/me/',
            data=json.dumps({
                'timezone': 'Mars/Olympus',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('timezone', response.json())

    def test_user_profile_requires_location_hint_before_enabling_weather(self):
        self.client.force_login(self.user)

        # 新资料默认开启位置分享；先关掉再重新开启，模拟「显式开启」路径。
        disable_response = self.client.patch(
            '/api/user-profile/me/',
            data=json.dumps({'share_location': False}),
            content_type='application/json',
        )
        self.assertEqual(disable_response.status_code, 200)

        response = self.client.patch(
            '/api/user-profile/me/',
            data=json.dumps({
                'share_location': True,
                'share_weather': True,
                'location_label': '',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('location_label', response.json())

    def test_user_profile_allows_pending_location_hint_on_fresh_profile(self):
        """默认开启分享的新资料：提示暂空时仍可局部更新其他字段。"""
        self.client.force_login(self.user)

        response = self.client.patch(
            '/api/user-profile/me/',
            data=json.dumps({'preferred_name': 'Owner Alias'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['preferred_name'], 'Owner Alias')
        self.assertEqual(response.json()['location_label'], '')

    def test_user_profile_persists_detected_coordinates_and_clears_on_opt_out(self):
        self.client.force_login(self.user)

        save_response = self.client.patch(
            '/api/user-profile/me/',
            data=json.dumps({
                'share_location': True,
                'location_precision': 'exact',
                'location_label': '中国 · 上海',
                'location_latitude': 31.2304,
                'location_longitude': 121.4737,
            }),
            content_type='application/json',
        )

        self.assertEqual(save_response.status_code, 200)
        payload = save_response.json()
        self.assertAlmostEqual(payload['location_latitude'], 31.2304)
        self.assertAlmostEqual(payload['location_longitude'], 121.4737)

        opt_out_response = self.client.patch(
            '/api/user-profile/me/',
            data=json.dumps({'share_location': False}),
            content_type='application/json',
        )

        self.assertEqual(opt_out_response.status_code, 200)
        payload = opt_out_response.json()
        self.assertIsNone(payload['location_latitude'])
        self.assertIsNone(payload['location_longitude'])

    def test_user_profile_auto_sync_flags_have_defaults_and_persist(self):
        self.client.force_login(self.user)

        get_response = self.client.get('/api/user-profile/me/')
        self.assertEqual(get_response.status_code, 200)
        payload = get_response.json()
        self.assertTrue(payload['share_local_time'])
        self.assertTrue(payload['share_location'])
        self.assertTrue(payload['share_weather'])
        self.assertTrue(payload['auto_sync_timezone'])
        self.assertTrue(payload['auto_sync_location'])

        patch_response = self.client.patch(
            '/api/user-profile/me/',
            data=json.dumps({
                'auto_sync_timezone': False,
                'auto_sync_location': False,
            }),
            content_type='application/json',
        )

        self.assertEqual(patch_response.status_code, 200)
        payload = patch_response.json()
        self.assertFalse(payload['auto_sync_timezone'])
        self.assertFalse(payload['auto_sync_location'])

    def test_detect_location_forwards_provider_result(self):
        self.client.force_login(self.user)
        detected = {
            'ok': True,
            'source': 'ipwho.is',
            'country': '中国',
            'region': '上海',
            'city': '上海',
            'timezone': 'Asia/Shanghai',
            'latitude': 31.22,
            'longitude': 121.45,
        }

        with patch('chat.views.detect_location_from_request', return_value=detected) as mock_detect:
            response = self.client.get('/api/user-profile/detect-location/', data={'lang': 'zh-CN'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), detected)
        self.assertEqual(mock_detect.call_args.kwargs['lang'], 'zh-CN')

    def test_detect_location_ignores_lang_for_non_chinese_locales(self):
        self.client.force_login(self.user)

        with patch('chat.views.detect_location_from_request', return_value={'ok': False, 'reason': 'unavailable'}) as mock_detect:
            self.client.get('/api/user-profile/detect-location/')

        self.assertEqual(mock_detect.call_args.kwargs['lang'], 'en')

    def test_web_search_config_me_endpoint_returns_default_shape_when_missing(self):
        self.client.force_login(self.user)

        response = self.client.get('/api/web-search-config/me/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['provider'], 'tavily')
        self.assertEqual(payload['api_key'], '')
        self.assertEqual(payload['max_results'], 5)

    def test_web_search_config_me_endpoint_creates_and_updates_config(self):
        self.client.force_login(self.user)

        response = self.client.patch(
            '/api/web-search-config/me/',
            data=json.dumps({
                'provider': 'tavily',
                'api_key': 'fresh-key',
                'max_results': 7,
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['provider'], 'tavily')
        self.assertEqual(payload['api_key'], 'fresh-key')
        self.assertEqual(payload['max_results'], 7)

        config = WebSearchConfiguration.objects.get(user=self.user)
        self.assertEqual(config.api_key, 'fresh-key')
        self.assertEqual(config.max_results, 7)

    def test_web_search_config_me_endpoint_rejects_invalid_values(self):
        self.client.force_login(self.user)

        response = self.client.patch(
            '/api/web-search-config/me/',
            data=json.dumps({
                'provider': 'other',
                'api_key': '',
                'max_results': 99,
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn('provider', payload)

    @patch('chat.search.requests.post')
    def test_web_search_test_endpoint_returns_standardized_results(self, mock_post):
        self.client.force_login(self.user)
        self.create_web_search_config(api_key='configured-key', max_results=3)
        mock_post.return_value.json.return_value = {
            'results': [{
                'title': 'Archive Notes',
                'url': 'https://example.com/archive',
                'content': 'sealed archive oath',
            }],
        }
        mock_post.return_value.raise_for_status.return_value = None

        response = self.client.post(
            '/api/web-search-config/test/',
            data=json.dumps({'query': 'sealed archive oath'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['provider'], 'tavily')
        self.assertEqual(payload['error'], '')
        self.assertEqual(len(payload['items']), 1)
        self.assertEqual(payload['items'][0]['title'], 'Archive Notes')

    def test_web_search_test_endpoint_reports_missing_configuration(self):
        self.client.force_login(self.user)

        response = self.client.post(
            '/api/web-search-config/test/',
            data=json.dumps({'query': 'latest weather'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['items'], [])
        self.assertIn('not configured', payload['error'])

    def test_create_session_succeeds_when_user_profile_has_web_search_default(self):
        self.client.force_login(self.user)
        self.create_model_config()
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={'default_enable_web_search': True},
        )

        response = self.client.post(
            '/api/sessions/',
            data=json.dumps({
                'character': self.own_character.id,
                'title': 'Profile Default Search Session',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['title'], 'Profile Default Search Session')

    @patch('chat.views.stream_ai_response')
    def test_stream_message_starts_with_proactive_greeting_without_fake_user_message(self, mock_stream_ai_response):
        self.client.force_login(self.user)
        self.create_model_config()
        mock_stream_ai_response.return_value = iter([
            {'type': 'delta', 'content': 'Hello'},
            {
                'type': 'done',
                'message_id': 999,
                'content': 'Hello there',
                'timestamp': '2026-01-01T00:00:00+00:00',
                'latency_ms': 120,
            },
        ])

        response = self.client.post(
            '/api/chat/stream_message/',
            data=json.dumps({
                'character_id': self.own_character.id,
                'start_conversation': True,
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        payload_lines = [
            json.loads(line)
            for line in _consume_streaming(response).decode('utf-8').splitlines()
            if line.strip()
        ]

        self.assertEqual(payload_lines[0]['type'], 'session')
        self.assertTrue(payload_lines[0]['is_greeting'])
        self.assertIsNone(payload_lines[0]['user_message'])
        self.assertEqual(payload_lines[1]['type'], 'delta')
        self.assertEqual(payload_lines[1]['content'], 'Hello')
        self.assertEqual(payload_lines[2]['type'], 'done')

        created_session = ChatSession.objects.get(id=payload_lines[0]['chat_session_id'])
        self.assertEqual(created_session.user, self.user)
        self.assertEqual(Message.objects.filter(chat_session=created_session, role='user').count(), 0)


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class SoulMemoryExplorerTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()

        self.user = User.objects.create_user(username='soul-owner', password='password123')
        self.other_user = User.objects.create_user(username='soul-other', password='password123')
        self.client.force_login(self.user)
        self.character = Character.objects.create(
            created_by=self.user,
            name='Soul Character',
            avatar_url='',
            description='A character used for memory explorer tests.',
            user_address='Archivist',
            personality='Reflective',
            appearance='Silver coat',
            scenario='Archive room',
            example_dialogue='',
            affiliation='Archive',
            tags=['soul'],
            response_guidelines='Stay precise.',
        )

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    def test_character_setup_markdown_uses_current_schema_preview(self):
        markdown = build_character_setup_markdown(self.character)

        self.assertIn('## Identity', markdown)
        self.assertIn('Name: Soul Character', markdown)
        self.assertIn('Calls the user "Archivist".', markdown)
        self.assertIn('## Appearance', markdown)
        self.assertIn('Silver coat', markdown)
        self.assertIn('## Reference Files', markdown)
        self.assertIn('No uploaded reference files yet.', markdown)

    def test_memory_explorer_lists_schema_raw_and_wiki_layers(self):
        root_listing = list_memory_explorer_path(self.character)

        self.assertEqual(root_listing['error'], '')
        self.assertEqual(
            [entry['path'] for entry in root_listing['entries']],
            ['raw', 'schema', 'wiki'],
        )

        schema_listing = list_memory_explorer_path(self.character, path_prefix='schema', recursive=True)
        self.assertEqual(
            [entry['path'] for entry in schema_listing['entries'] if entry['entry_type'] == 'file'],
            ['schema/soul.md'],
        )

    def test_memory_explorer_reads_chat_transcript_and_search_payload(self):
        Message.objects.create(
            chat_session=ChatSession.objects.create(
                user=self.user,
                character=self.character,
                title='Explorer Session',
            ),
            role='user',
            content='Do you remember the sealed record?',
        )
        assistant_message = Message.objects.create(
            chat_session=self.character.chat_sessions.get(title='Explorer Session'),
            role='assistant',
            content='I remember the seal and the oath.',
            character=self.character,
            research_payload={
                'query': 'sealed archive oath',
                'provider': 'tavily',
                'items': [{
                    'title': 'Archive Notes',
                    'url': 'https://example.com/archive',
                    'snippet': 'The oath is written beside the seal.',
                    'domain': 'example.com',
                }],
            },
        )

        raw_listing = list_memory_explorer_path(self.character, path_prefix='raw', recursive=True)
        raw_paths = {entry['path'] for entry in raw_listing['entries']}
        transcript_path = f'raw/chat_sessions/session_{assistant_message.chat_session_id}/transcript.md'
        search_path = f'raw/chat_sessions/session_{assistant_message.chat_session_id}/web_search/turn_{assistant_message.id}.md'

        self.assertIn(transcript_path, raw_paths)
        self.assertIn(search_path, raw_paths)

        transcript = read_memory_explorer_file(self.character, transcript_path)
        self.assertIn('Do you remember the sealed record?', transcript['content'])
        self.assertIn('I remember the seal and the oath.', transcript['content'])

        search_result = read_memory_explorer_file(self.character, search_path)
        self.assertIn('sealed archive oath', search_result['content'])
        self.assertIn('Archive Notes', search_result['content'])

    def test_memory_explorer_reads_uploaded_setup_files(self):
        CharacterKnowledgeAsset.objects.create(
            character=self.character,
            file=SimpleUploadedFile(
                'notes.txt',
                b'Keep the archive index hidden.',
                content_type='text/plain',
            ),
            attachment_name='notes.txt',
            attachment_mime_type='text/plain',
            attachment_kind='text',
            attachment_text_content='Keep the archive index hidden.',
            sort_order=0,
        )

        raw_listing = list_memory_explorer_path(self.character, path_prefix='raw', recursive=True)
        raw_paths = {entry['path'] for entry in raw_listing['entries']}

        self.assertIn('raw/character_setup/uploads/notes.txt', raw_paths)

        upload_doc = read_memory_explorer_file(self.character, 'raw/character_setup/uploads/notes.txt')
        self.assertEqual(upload_doc['path'], 'raw/character_setup/uploads/notes.txt')
        self.assertIn('Keep the archive index hidden.', upload_doc['content'])

    def test_memory_explorer_marks_reference_assets_as_manageable(self):
        asset = CharacterKnowledgeAsset.objects.create(
            character=self.character,
            file=SimpleUploadedFile(
                'notes.txt',
                b'Keep the archive index hidden.',
                content_type='text/plain',
            ),
            attachment_name='notes.txt',
            attachment_mime_type='text/plain',
            attachment_kind='text',
            attachment_text_content='Keep the archive index hidden.',
            sort_order=0,
        )

        raw_listing = list_memory_explorer_path(self.character, path_prefix='raw', recursive=True)
        upload_entry = next(
            entry for entry in raw_listing['entries']
            if entry['path'] == 'raw/character_setup/uploads/notes.txt'
        )

        self.assertTrue(upload_entry['manageable'])
        self.assertEqual(upload_entry['asset_id'], asset.id)
        self.assertEqual(upload_entry['preview_kind'], 'text')

        schema_doc = read_memory_explorer_file(self.character, 'schema/soul.md')
        self.assertFalse(schema_doc['manageable'])
        self.assertEqual(schema_doc['preview_kind'], 'text')

    def test_rest_upload_knowledge_assets_adds_manageable_files(self):
        response = self.client.post(
            f'/api/characters/{self.character.id}/knowledge_assets/',
            data={'files': SimpleUploadedFile('upload.txt', b'Archive lock combination.', content_type='text/plain')},
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(len(payload['assets']), 1)
        asset_id = payload['assets'][0]['id']
        self.assertEqual(CharacterKnowledgeAsset.objects.filter(character=self.character).count(), 1)

        listing = self.client.get(
            f'/api/characters/{self.character.id}/soul_files/',
            {'path_prefix': 'raw', 'recursive': 'true'},
        )
        self.assertEqual(listing.status_code, 200)
        entry = next(
            item for item in listing.json()['entries']
            if item['path'] == 'raw/character_setup/uploads/upload.txt'
        )
        self.assertTrue(entry['manageable'])
        self.assertEqual(entry['asset_id'], asset_id)

        file_response = self.client.get(
            f'/api/characters/{self.character.id}/soul_file/',
            {'path': 'raw/character_setup/uploads/upload.txt'},
        )
        self.assertEqual(file_response.status_code, 200)
        file_payload = file_response.json()
        self.assertTrue(file_payload['manageable'])
        self.assertEqual(file_payload['asset_id'], asset_id)
        self.assertIn('Archive lock combination.', file_payload['content'])

    def test_rest_delete_knowledge_asset_removes_file_and_storage(self):
        asset = CharacterKnowledgeAsset.objects.create(
            character=self.character,
            file=SimpleUploadedFile(
                'notes.txt',
                b'Keep the archive index hidden.',
                content_type='text/plain',
            ),
            attachment_name='notes.txt',
            attachment_mime_type='text/plain',
            attachment_kind='text',
            attachment_text_content='Keep the archive index hidden.',
            sort_order=0,
        )
        asset_path = asset.file.path

        response = self.client.delete(f'/api/characters/{self.character.id}/knowledge_assets/{asset.id}/')

        self.assertEqual(response.status_code, 204)
        self.assertFalse(CharacterKnowledgeAsset.objects.filter(pk=asset.id).exists())
        self.assertFalse(os.path.exists(asset_path))

        raw_listing = list_memory_explorer_path(self.character, path_prefix='raw', recursive=True)
        raw_paths = {entry['path'] for entry in raw_listing['entries']}
        self.assertNotIn('raw/character_setup/uploads/notes.txt', raw_paths)

    def test_rest_delete_knowledge_asset_rejects_missing_or_unowned_assets(self):
        foreign_character = Character.objects.create(
            created_by=self.other_user,
            name='Foreign Character',
            avatar_url='',
            description='Other owner character.',
            user_address='Scout',
            personality='Alert',
            appearance='Brown cloak',
            scenario='Road',
            example_dialogue='',
            affiliation='Watch',
            tags=['foreign'],
        )
        foreign_asset = CharacterKnowledgeAsset.objects.create(
            character=foreign_character,
            file=SimpleUploadedFile(
                'foreign.txt',
                b'Foreign content',
                content_type='text/plain',
            ),
            attachment_name='foreign.txt',
            attachment_mime_type='text/plain',
            attachment_kind='text',
            attachment_text_content='Foreign content',
            sort_order=0,
        )

        missing_response = self.client.delete(f'/api/characters/{self.character.id}/knowledge_assets/999999/')
        self.assertEqual(missing_response.status_code, 400)

        unowned_response = self.client.delete(f'/api/characters/{foreign_character.id}/knowledge_assets/{foreign_asset.id}/')
        self.assertEqual(unowned_response.status_code, 404)


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class PromptMemoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='prompt-owner', password='password123')
        self.character = Character.objects.create(
            created_by=self.user,
            name='Prompt Character',
            avatar_url='',
            description='A character used for prompt composition tests.',
            user_address='Gatewalker',
            personality='Watchful',
            appearance='White gloves',
            scenario='Vault',
            example_dialogue='',
            affiliation='Keepers',
            tags=['prompt'],
        )
        self.session = ChatSession.objects.create(
            user=self.user,
            character=self.character,
            title='Prompt Session',
        )

    def create_web_search_config(self, **overrides):
        defaults = {
            'provider': 'tavily',
            'api_key': 'tavily-secret',
            'max_results': 5,
        }
        defaults.update(overrides)
        return WebSearchConfiguration.objects.create(user=self.user, **defaults)

    def test_system_prompt_uses_role_specific_memory_not_global_user_profile_identity(self):
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={
                'preferred_name': 'Global Alias',
                'pronouns': 'they/them',
                'bio': 'This should stay out of the character prompt.',
                'preferred_relationship_style': 'protective',
                'blocked_topics': 'taxes',
            },
        )

        prompt = _build_system_prompt(self.character, self.session)

        self.assertNotIn('[USER MODEL]', prompt)
        self.assertNotIn('Navigator', prompt)
        self.assertNotIn('trusted co-conspirator', prompt)
        self.assertNotIn('Preferred Name: Global Alias', prompt)
        self.assertNotIn('Preferred Relationship Style: protective', prompt)
        self.assertIn('[ACCOUNT BOUNDARIES]', prompt)
        self.assertIn('Blocked Topics: taxes', prompt)

    def test_system_prompt_includes_seeded_user_address_before_conversation(self):
        prompt = _build_system_prompt(self.character, self.session)

        self.assertIn('Gatewalker', prompt)
        self.assertNotIn('[USER MODEL]', prompt)

    def test_system_prompt_omits_legacy_static_opening_and_lore_sections(self):
        prompt = _build_system_prompt(self.character, self.session)

        self.assertIn('[CHARACTER SETUP]', prompt)
        self.assertIn('## Appearance', prompt)
        self.assertIn('White gloves', prompt)
        self.assertIn('## Scenario', prompt)
        self.assertIn('Vault', prompt)
        self.assertNotIn('[OPENING STYLE]', prompt)
        self.assertNotIn('[KNOWLEDGE BASE]', prompt)
        self.assertNotIn('Vault protocol.', prompt)
        self.assertNotIn('## Default Scenario', prompt)

    def test_system_prompt_uses_character_setup_preview_when_present(self):
        self.character.system_prompt_preview = "\n".join([
            "## Identity",
            "Name: Prompt Character",
            "",
            "## Scenario",
            "Vault",
            "",
            "## Appearance",
            "White gloves",
        ])
        self.character.save(update_fields=['system_prompt_preview'])

        prompt = _build_system_prompt(self.character, self.session)

        self.assertIn('[CHARACTER SETUP]', prompt)
        self.assertIn('## Scenario', prompt)
        self.assertIn('White gloves', prompt)
        self.assertNotIn('[CONSTITUTION]', prompt)
        self.assertNotIn('[PERSONA]', prompt)
        self.assertNotIn('[CHARACTER BACKSTORY]', prompt)
        self.assertNotIn('[EXAMPLE DIALOGUE]', prompt)
        self.assertIn('[USER UPLOADS]', prompt)

    def test_uploaded_background_text_stays_within_prompt_budget(self):
        for index, letter in enumerate(['a', 'b', 'c']):
            CharacterKnowledgeAsset.objects.create(
                character=self.character,
                file=SimpleUploadedFile(
                    f'lore-{letter}.txt',
                    letter.encode(),
                    content_type='text/plain',
                ),
                attachment_name=f'lore-{letter}.txt',
                attachment_mime_type='text/plain',
                attachment_kind='text',
                attachment_text_content=letter.upper() * 25000,
                sort_order=index,
            )

        background = build_character_prompt_context(self.character)['uploaded_background']

        self.assertIn('## lore-a.txt', background)
        self.assertIn('## lore-b.txt', background)
        self.assertNotIn('## lore-c.txt', background)
        self.assertIn('1 more uploaded file(s) exist but were omitted', background)

    def test_uploaded_background_text_keeps_first_asset_even_when_over_budget(self):
        CharacterKnowledgeAsset.objects.create(
            character=self.character,
            file=SimpleUploadedFile('huge-lore.txt', b'x', content_type='text/plain'),
            attachment_name='huge-lore.txt',
            attachment_mime_type='text/plain',
            attachment_kind='text',
            attachment_text_content='X' * 80000,
            sort_order=0,
        )

        background = build_character_prompt_context(self.character)['uploaded_background']

        self.assertIn('## huge-lore.txt', background)
        self.assertNotIn('omitted', background)

    def test_character_setup_preview_uses_simplified_chinese_when_profile_prefers_it(self):
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={'interface_language': 'zh-CN'},
        )

        preview = build_character_system_prompt_preview(self.character)

        self.assertIn('## 身份', preview)
        self.assertIn('名字: Prompt Character', preview)
        self.assertIn('## 核心简介', preview)

    def test_system_prompt_omits_character_tags_from_prompt_context(self):
        prompt = _build_system_prompt(self.character, self.session)

        self.assertNotIn('## Tags', prompt)
        self.assertNotIn('## Tags\nprompt', prompt)

    def test_system_prompt_bootstraps_user_model_from_profile_when_role_memory_is_empty(self):
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={
                'preferred_name': 'Global Alias',
                'pronouns': 'they/them',
                'bio': 'Knows the hidden routes.',
                'preferred_relationship_style': 'protective',
            },
        )

        prompt = _build_system_prompt(self.character, self.session)

        self.assertNotIn('[USER MODEL]', prompt)
        self.assertNotIn('Global Alias', prompt)
        self.assertNotIn("they/them", prompt)
        self.assertNotIn('Knows the hidden routes.', prompt)
        self.assertNotIn('protective.', prompt)

    def test_system_prompt_falls_back_to_profile_when_role_memory_is_cleared(self):
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={
                'preferred_name': 'Global Alias',
                'bio': 'Returns even after memories are wiped.',
            },
        )

        prompt = _build_system_prompt(self.character, self.session)

        self.assertNotIn('Global Alias', prompt)
        self.assertNotIn('Returns even after memories are wiped.', prompt)

    def test_system_prompt_includes_local_time_and_weather_guidance(self):
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={
                'timezone': 'America/New_York',
                'share_local_time': True,
                'share_location': True,
                'location_precision': 'city',
                'location_label': 'Boston, MA',
                'share_weather': True,
            },
        )

        prompt = _build_system_prompt(self.character, self.session)

        self.assertIn('User Local Time:', prompt)
        self.assertIn('User Local Daypart:', prompt)
        self.assertIn("Interpret relative time words such as today, tonight, and tomorrow in the user's local timezone.", prompt)
        self.assertIn('Location Hint (City level): Boston, MA', prompt)
        self.assertIn('Do not guess current conditions.', prompt)
        # 城市级不应暴露坐标；时间行应包含 UTC 偏移与时区名，避免 CST 之类歧义。
        self.assertNotIn('approx. latitude', prompt)
        self.assertIn('(UTC-', prompt)
        self.assertIn('America/New_York', prompt)

    def test_system_prompt_includes_coordinates_only_at_exact_precision(self):
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={
                'share_location': True,
                'location_precision': 'exact',
                'location_label': '中国 · 上海',
                'location_latitude': 31.2304,
                'location_longitude': 121.4737,
            },
        )

        exact_prompt = _build_system_prompt(self.character, self.session)
        self.assertIn('Location Hint (Exact level): 中国 · 上海 (approx. latitude 31.23, longitude 121.47)', exact_prompt)

        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={'location_precision': 'city'},
        )

        city_prompt = _build_system_prompt(self.character, self.session)
        self.assertIn('Location Hint (City level): 中国 · 上海', city_prompt)
        self.assertNotIn('approx. latitude', city_prompt)

    def test_system_prompt_tool_mode_uses_memory_filesystem_index_without_loading_memory_bodies(self):
        CharacterKnowledgeAsset.objects.create(
            character=self.character,
            file=SimpleUploadedFile(
                'backstory.txt',
                b'Raised under the seventh archive.',
                content_type='text/plain',
            ),
            attachment_name='backstory.txt',
            attachment_mime_type='text/plain',
            attachment_kind='text',
            attachment_text_content='Raised under the seventh archive.',
            sort_order=0,
        )
        Message.objects.create(
            chat_session=self.session,
            role='user',
            content='Do you remember the eclipse oath?',
        )

        prompt = _build_system_prompt(self.character, self.session, use_memory_tools=True)

        self.assertIn('[MEMORY TOOLING]', prompt)
        self.assertIn('[MEMORY FILESYSTEM]', prompt)
        self.assertIn('schema/soul.md', prompt)
        self.assertIn(f'raw/chat_sessions/session_{self.session.id}/transcript.md', prompt)
        self.assertIn('raw/character_setup/uploads/backstory.txt', prompt)
        self.assertNotIn('Shared the eclipse oath.', prompt)
        self.assertNotIn('Raised under the seventh archive.', prompt)

    def test_memory_explorer_lists_and_reads_virtual_paths(self):
        CharacterKnowledgeAsset.objects.create(
            character=self.character,
            file=SimpleUploadedFile(
                'notes.txt',
                b'Gate records are kept below the vault.',
                content_type='text/plain',
            ),
            attachment_name='notes.txt',
            attachment_mime_type='text/plain',
            attachment_kind='text',
            attachment_text_content='Gate records are kept below the vault.',
            sort_order=0,
        )
        Message.objects.create(
            chat_session=self.session,
            role='user',
            content='Do you remember the eclipse oath?',
        )
        Message.objects.create(
            chat_session=self.session,
            role='assistant',
            content='I remember every word of it.',
            character=self.character,
        )

        root_listing = list_memory_explorer_path(self.character)
        self.assertEqual(root_listing['error'], '')
        self.assertEqual(
            [entry['path'] for entry in root_listing['entries']],
            ['raw', 'schema', 'wiki'],
        )

        schema_doc = read_memory_explorer_file(self.character, 'schema/soul.md')
        self.assertEqual(schema_doc['path'], 'schema/soul.md')
        self.assertIn('Gatewalker', schema_doc['content'])

        raw_listing = list_memory_explorer_path(self.character, path_prefix='raw', recursive=True)
        raw_paths = {entry['path'] for entry in raw_listing['entries']}
        session_path = f'raw/chat_sessions/session_{self.session.id}/transcript.md'
        self.assertIn(session_path, raw_paths)
        self.assertIn('raw/character_setup/uploads/notes.txt', raw_paths)

        session_transcript = read_memory_explorer_file(self.character, session_path)
        self.assertEqual(session_transcript['path'], session_path)
        self.assertIn('Do you remember the eclipse oath?', session_transcript['content'])
        self.assertIn('I remember every word of it.', session_transcript['content'])

    def test_system_prompt_prefetch_mode_injects_compact_retrieved_memory(self):
        retrieved_memory = _build_stream_memory_prefetch(self.character, self.session, generate_greeting=True)
        prompt = _build_system_prompt(
            self.character,
            self.session,
            use_memory_tools=False,
            retrieved_memory=retrieved_memory,
        )

        self.assertIn('[RETRIEVED MEMORY]', prompt)
        self.assertIn('A character used for prompt composition tests.', prompt)
        self.assertNotIn('[USER MODEL]', prompt)

    def test_provider_messages_can_disable_memory_tool_mode_for_streaming(self):
        ModelConfiguration.objects.create(
            user=self.user,
            name='Prompt Default',
            provider='openai_compatible',
            model_name='gpt-4.1-mini',
            api_key='secret',
            base_url='https://example.com/v1',
        )

        runtime_config, formatted_history, tools = _build_provider_messages(
            chat_session=self.session,
            character=self.character,
            generate_greeting=False,
            research_context=None,
            allow_memory_tools=False,
            retrieved_memory='[RETRIEVED MEMORY]\n# Memory Summary\n- Shared the eclipse oath.',
        )

        self.assertEqual(runtime_config['provider'], 'openai_compatible')
        self.assertEqual(tools, [])
        self.assertIn('[RETRIEVED MEMORY]', formatted_history[0]['content'])
        self.assertNotIn('[MEMORY TOOLING]', formatted_history[0]['content'])

    def test_search_query_uses_local_location_and_local_date_for_weather(self):
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={
                'timezone': 'America/New_York',
                'share_local_time': True,
                'share_location': True,
                'location_precision': 'city',
                'location_label': 'Boston, MA',
                'share_weather': True,
            },
        )

        user_message = Message.objects.create(
            chat_session=self.session,
            role='user',
            content='今天天气怎么样？',
        )

        query = _build_search_query(self.session, user_message=user_message)
        expected_date = datetime.now(ZoneInfo('America/New_York')).date().isoformat()

        self.assertIn('Boston, MA', query)
        self.assertIn(expected_date, query)

    def test_search_web_uses_user_owned_configuration_instead_of_global_settings(self):
        self.create_web_search_config(api_key='owner-search-key', max_results=4)

        with override_settings(TAVILY_API_KEY='legacy-key', WEB_SEARCH_PROVIDER='tavily'):
            with patch('chat.search.requests.post') as mock_post:
                mock_post.return_value.json.return_value = {'results': []}
                mock_post.return_value.raise_for_status.return_value = None

                payload = search_web('sealed archive oath', user=self.user)

        self.assertEqual(payload['provider'], 'tavily')
        self.assertEqual(payload['error'], '')
        self.assertEqual(
            mock_post.call_args.kwargs['json']['api_key'],
            'owner-search-key',
        )
        self.assertEqual(mock_post.call_args.kwargs['json']['max_results'], 4)

    def test_build_research_context_returns_error_when_user_enabled_search_without_api_config(self):
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={'default_enable_web_search': True},
        )
        user_message = Message.objects.create(
            chat_session=self.session,
            role='user',
            content='What is the latest weather in Boston?',
        )

        payload = build_research_context(self.session, user_message=user_message)

        self.assertEqual(payload['items'], [])
        self.assertIn('not configured', payload['error'])

    @patch('chat.search.requests.post')
    def test_build_research_context_uses_saved_web_search_config(self, mock_post):
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={'default_enable_web_search': True},
        )
        self.create_web_search_config(api_key='saved-search-key', max_results=6)
        mock_post.return_value.json.return_value = {
            'results': [{
                'title': 'Archive Notes',
                'url': 'https://example.com/archive',
                'content': 'sealed archive oath',
            }],
        }
        mock_post.return_value.raise_for_status.return_value = None

        user_message = Message.objects.create(
            chat_session=self.session,
            role='user',
            content='Tell me about the sealed archive oath.',
        )

        payload = build_research_context(self.session, user_message=user_message)

        self.assertEqual(payload['provider'], 'tavily')
        self.assertEqual(payload['error'], '')
        self.assertEqual(len(payload['items']), 1)
        self.assertEqual(mock_post.call_args.kwargs['json']['api_key'], 'saved-search-key')

    def test_provider_messages_do_not_add_gemini_native_search_tool(self):
        model_config = ModelConfiguration.objects.create(
            user=self.user,
            name='Gemini Default',
            provider='gemini',
            model_name='gemini-2.0-flash',
            api_key='secret',
            base_url='',
        )
        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={'default_enable_web_search': True},
        )

        runtime_config, _, tools = _build_provider_messages(
            chat_session=self.session,
            character=self.character,
            generate_greeting=False,
            research_context={
                'query': 'latest weather Boston',
                'provider': 'tavily',
                'items': [],
                'error': '',
            },
            allow_memory_tools=False,
        )

        self.assertEqual(model_config.provider, 'gemini')
        self.assertEqual(runtime_config['provider'], 'gemini')
        self.assertEqual(tools, [])

    @patch('chat.tasks._stream_openai_compatible_round')
    def test_openai_tool_loop_reads_memory_files_before_final_answer(self, mock_round):
        def round_one(**kwargs):
            yield {
                'type': 'round_finished',
                'assistant_message': {
                    'role': 'assistant',
                    'content': '',
                    'tool_calls': [{
                        'id': 'call_1',
                        'type': 'function',
                        'function': {
                            'name': 'read_memory_file',
                            'arguments': json.dumps({'path': 'schema/soul.md'}),
                        },
                    }],
                },
                'usage': None,
            }

        def round_two(**kwargs):
            yield {
                'type': 'round_finished',
                'assistant_message': {'role': 'assistant', 'content': 'I still call you Gatewalker.'},
                'usage': None,
            }

        def _round_factory(**kwargs):
            calls = _round_factory.calls
            _round_factory.calls += 1
            return (round_one if calls == 0 else round_two)(**kwargs)
        _round_factory.calls = 0
        mock_round.side_effect = _round_factory

        result = ''.join(
            e.get('content') or '' for e in _generate_openai_compatible_response(
                model_name='gpt-4.1-mini',
                api_key='secret',
                messages=[{'role': 'system', 'content': 'Use memory tools.'}],
                base_url='https://example.com/v1',
                tools=_build_memory_tool_specs(),
                filesystem=CharacterMemoryFilesystem(self.character),
            )
            if e.get('type') == 'final_text'
        )

        self.assertEqual(result, 'I still call you Gatewalker.')
        self.assertEqual(mock_round.call_count, 2)

        second_call_messages = mock_round.call_args_list[1].kwargs['messages']
        tool_messages = [message for message in second_call_messages if message.get('role') == 'tool']
        self.assertEqual(len(tool_messages), 1)
        self.assertIn('Gatewalker', tool_messages[0]['content'])

    @patch('chat.tasks._request_openai_compatible_completion')
    @patch('chat.tasks._stream_openai_compatible_round')
    def test_openai_tool_loop_falls_back_when_backend_rejects_tools(self, mock_round, mock_request_openai_completion):
        def _round_rejects_tools(**kwargs):
            raise requests.HTTPError('Unsupported parameter: tools')

        mock_round.side_effect = _round_rejects_tools
        mock_request_openai_completion.return_value = {
            'choices': [{'message': {'role': 'assistant', 'content': 'Fallback answer without tools.'}}],
        }

        result = ''.join(
            e.get('content') or '' for e in _generate_openai_compatible_response(
                model_name='gpt-4.1-mini',
                api_key='secret',
                messages=[{'role': 'system', 'content': 'Use memory tools if available.'}],
                base_url='https://example.com/v1',
                tools=_build_memory_tool_specs(),
                filesystem=CharacterMemoryFilesystem(self.character),
            )
            if e.get('type') == 'final_text'
        )

        self.assertEqual(result, 'Fallback answer without tools.')
        self.assertEqual(mock_request_openai_completion.call_count, 1)
        self.assertNotIn('tools', mock_request_openai_completion.call_args_list[0].kwargs)


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class ChatAttachmentTests(ModelConfigTestMixin, TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()

        self.user = User.objects.create_user(username='attachment-owner', password='password123')
        self.client.force_login(self.user)
        self.character = Character.objects.create(
            created_by=self.user,
            name='Attachment Character',
            avatar_url='',
            description='Handles attachment chat tests.',
            personality='Observant',
            appearance='Grey coat',
            scenario='Studio',
            example_dialogue='',
            affiliation='Lab',
            tags=['attachment'],
        )
        self.model_config = ModelConfiguration.objects.create(
            user=self.user,
            name='Attachment Default',
            provider='openai_compatible',
            model_name='gpt-4.1-mini',
            api_key='secret',
            base_url='https://example.com/v1',
        )
        self.session = ChatSession.objects.create(
            user=self.user,
            character=self.character,
            title='Attachment Session',
        )
        Message.objects.create(
            chat_session=self.session,
            role='assistant',
            content='Ready when you are.',
            character=self.character,
        )

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    @patch('chat.views.stream_ai_response')
    def test_stream_message_accepts_text_attachment_without_text_body(self, mock_stream_ai_response):
        mock_stream_ai_response.return_value = iter([
            {'type': 'delta', 'content': 'I read it.'},
            {
                'type': 'done',
                'message_id': 999,
                'content': 'I read it.',
                'timestamp': '2026-01-01T00:00:00+00:00',
                'latency_ms': 90,
            },
        ])

        response = self.client.post(
            '/api/chat/stream_message/',
            data={
                'character_id': str(self.character.id),
                'chat_session_id': str(self.session.id),
                'message': '',
                'attachment': SimpleUploadedFile(
                    'notes.txt',
                    b'alpha\nbeta\ngamma',
                    content_type='text/plain',
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        payload_lines = [
            json.loads(line)
            for line in _consume_streaming(response).decode('utf-8').splitlines()
            if line.strip()
        ]

        self.assertEqual(payload_lines[0]['type'], 'session')
        self.assertEqual(payload_lines[0]['user_message']['file_name'], 'notes.txt')
        self.assertEqual(payload_lines[0]['user_message']['file_type'], 'text')

        user_message = Message.objects.filter(chat_session=self.session, role='user').latest('timestamp')
        self.assertEqual(user_message.attachment_kind, 'text')
        self.assertIn('alpha', user_message.attachment_text_content)

    @patch('chat.views.stream_ai_response')
    def test_stream_message_accepts_multiple_attachments_and_preserves_order(self, mock_stream_ai_response):
        mock_stream_ai_response.return_value = iter([
            {'type': 'delta', 'content': 'I checked both.'},
            {
                'type': 'done',
                'message_id': 1001,
                'content': 'I checked both.',
                'timestamp': '2026-01-01T00:00:00+00:00',
                'latency_ms': 95,
            },
        ])

        response = self.client.post(
            '/api/chat/stream_message/',
            data={
                'character_id': str(self.character.id),
                'chat_session_id': str(self.session.id),
                'message': 'Compare these.',
                'attachments': [
                    SimpleUploadedFile(
                        'scene.png',
                        b'\x89PNG\r\n\x1a\n',
                        content_type='image/png',
                    ),
                    SimpleUploadedFile(
                        'clip.mp4',
                        b'\x00\x00\x00\x18ftypmp42',
                        content_type='video/mp4',
                    ),
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload_lines = [
            json.loads(line)
            for line in _consume_streaming(response).decode('utf-8').splitlines()
            if line.strip()
        ]

        session_event = payload_lines[0]
        self.assertEqual(session_event['type'], 'session')
        self.assertEqual(session_event['user_message']['file_name'], 'scene.png')
        self.assertEqual(
            [attachment['file_name'] for attachment in session_event['user_message']['attachments']],
            ['scene.png', 'clip.mp4'],
        )
        self.assertEqual(
            [attachment['file_type'] for attachment in session_event['user_message']['attachments']],
            ['image', 'video'],
        )

        user_message = Message.objects.filter(chat_session=self.session, role='user').latest('timestamp')
        attachments = list(user_message.attachments.order_by('sort_order'))
        self.assertEqual(len(attachments), 2)
        self.assertEqual([attachment.attachment_name for attachment in attachments], ['scene.png', 'clip.mp4'])
        self.assertEqual([attachment.attachment_kind for attachment in attachments], ['image', 'video'])
        self.assertEqual(user_message.attachment_name, 'scene.png')

    def test_message_serializer_returns_multiple_attachments_with_legacy_primary_fields(self):
        user_message = Message.objects.create(
            chat_session=self.session,
            role='user',
            content='Two files attached.',
            character=self.character,
            attachment_name='scene.png',
            attachment_kind='image',
            attachment_mime_type='image/png',
        )
        first_attachment = MessageAttachment.objects.create(
            message=user_message,
            file=SimpleUploadedFile(
                'scene.png',
                b'\x89PNG\r\n\x1a\n',
                content_type='image/png',
            ),
            attachment_name='scene.png',
            attachment_mime_type='image/png',
            attachment_kind='image',
            sort_order=0,
        )
        MessageAttachment.objects.create(
            message=user_message,
            file=SimpleUploadedFile(
                'clip.mp4',
                b'\x00\x00\x00\x18ftypmp42',
                content_type='video/mp4',
            ),
            attachment_name='clip.mp4',
            attachment_mime_type='video/mp4',
            attachment_kind='video',
            sort_order=1,
        )
        Message.objects.filter(pk=user_message.pk).update(attachment=first_attachment.file.name)
        user_message.refresh_from_db()

        response = self.client.get(f'/api/messages/?chat_session_id={self.session.id}')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        serialized_message = next(item for item in payload if item['id'] == user_message.id)
        self.assertEqual(serialized_message['file_name'], 'scene.png')
        self.assertEqual(serialized_message['file_type'], 'image')
        self.assertEqual(
          [attachment['file_name'] for attachment in serialized_message['attachments']],
          ['scene.png', 'clip.mp4'],
        )
        self.assertEqual(
          [attachment['file_type'] for attachment in serialized_message['attachments']],
          ['image', 'video'],
        )

    def test_message_history_endpoint_preserves_legacy_single_attachment_records(self):
        legacy_message = Message.objects.create(
            chat_session=self.session,
            role='user',
            content='Old attachment record.',
            character=self.character,
            attachment=SimpleUploadedFile(
                'legacy-notes.txt',
                b'legacy\nattachment',
                content_type='text/plain',
            ),
            attachment_name='legacy-notes.txt',
            attachment_mime_type='text/plain',
            attachment_kind='text',
            attachment_text_content='legacy\nattachment',
        )

        response = self.client.get(f'/api/messages/?chat_session_id={self.session.id}')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        serialized_message = next(item for item in payload if item['id'] == legacy_message.id)
        self.assertEqual(serialized_message['file_name'], 'legacy-notes.txt')
        self.assertEqual(serialized_message['file_type'], 'text')
        self.assertEqual(len(serialized_message['attachments']), 1)
        self.assertEqual(serialized_message['attachments'][0]['file_name'], 'legacy-notes.txt')
        self.assertEqual(serialized_message['attachments'][0]['file_type'], 'text')

    def test_openai_compatible_text_only_model_falls_back_for_image_attachment(self):
        ModelConfiguration.objects.create(
            user=self.user,
            name='Text Only',
            provider='openai_compatible',
            model_name='plain-text-model',
            api_key='secret',
        )

        image_message = Message.objects.create(
            chat_session=self.session,
            role='user',
            content='What is in this image?',
            character=self.character,
            attachment=SimpleUploadedFile(
                'scene.png',
                b'\x89PNG\r\n\x1a\n',
                content_type='image/png',
            ),
            attachment_name='scene.png',
            attachment_mime_type='image/png',
            attachment_kind='image',
        )

        runtime_config, formatted_history, _ = _build_provider_messages(
            chat_session=self.session,
            character=self.character,
            generate_greeting=False,
            research_context=None,
        )

        self.assertEqual(runtime_config['provider'], 'openai_compatible')
        self.assertIn('cannot directly inspect images', formatted_history[-1]['content'])
        self.assertEqual(image_message.attachment_kind, 'image')

    @patch('chat.tasks._request_openai_media_analysis', return_value='A red umbrella in the rain.')
    def test_media_role_slots_analyze_attachments_for_text_only_chat_model(self, mock_analysis):
        ModelConfiguration.objects.create(
            user=self.user,
            name='Text Only',
            provider='openai_compatible',
            model_name='plain-text-model',
            api_key='secret',
        )
        self.create_media_model_config(ModelRole.IMAGE, name='Image Role', model_name='qwen3.6-vl-plus')
        self.create_media_model_config(ModelRole.VIDEO, name='Video Role', model_name='qwen3.6-vl-plus')

        image_message = Message.objects.create(
            chat_session=self.session,
            role='user',
            content='Describe this image.',
            character=self.character,
            attachment=SimpleUploadedFile(
                'scene.png',
                b'\x89PNG\r\n\x1a\n',
                content_type='image/png',
            ),
            attachment_name='scene.png',
            attachment_mime_type='image/png',
            attachment_kind='image',
        )

        runtime_config, formatted_history, _ = _build_provider_messages(
            chat_session=self.session,
            character=self.character,
            generate_greeting=False,
            research_context=None,
        )

        self.assertEqual(runtime_config['provider'], 'openai_compatible')
        self.assertEqual(mock_analysis.call_count, 1)
        image_content = formatted_history[-1]['content']
        self.assertIsInstance(image_content, str)
        self.assertIn('[Media analysis by image model]', image_content)
        self.assertIn('A red umbrella in the rain.', image_content)
        self.assertEqual(image_message.attachment_kind, 'image')

        video_message = Message.objects.create(
            chat_session=self.session,
            role='user',
            content='Summarize this clip.',
            character=self.character,
            attachment=SimpleUploadedFile(
                'clip.mp4',
                b'\x00\x00\x00\x18ftypmp42',
                content_type='video/mp4',
            ),
            attachment_name='clip.mp4',
            attachment_mime_type='video/mp4',
            attachment_kind='video',
        )

        mock_analysis.return_value = 'A timelapse of a city at dusk.'
        _, formatted_history, _ = _build_provider_messages(
            chat_session=self.session,
            character=self.character,
            generate_greeting=False,
            research_context=None,
        )

        video_content = formatted_history[-1]['content']
        self.assertIsInstance(video_content, str)
        self.assertIn('[Media analysis by video model]', video_content)
        self.assertIn('A timelapse of a city at dusk.', video_content)
        self.assertEqual(video_message.attachment_kind, 'video')

    @patch('chat.tasks._upload_generativeai_file')
    @patch('chat.tasks.genai.get_file')
    def test_cached_gemini_file_skips_reupload(self, mock_get_file, mock_upload):
        message = Message.objects.create(
            chat_session=self.session,
            role='user',
            content='Describe this image.',
            character=self.character,
        )
        attachment = MessageAttachment.objects.create(
            message=message,
            file=SimpleUploadedFile('scene.png', b'png', content_type='image/png'),
            attachment_name='scene.png',
            attachment_mime_type='image/png',
            attachment_kind='image',
            gemini_file_name='files/cached-123',
        )

        result = _get_or_upload_generativeai_file(attachment, attachment.file.path, 'scene.png', 'key')

        self.assertIs(result, mock_get_file.return_value)
        mock_upload.assert_not_called()

    @patch('chat.tasks._upload_generativeai_file')
    @patch('chat.tasks.genai.get_file', side_effect=RuntimeError('file not found'))
    def test_stale_gemini_file_cache_triggers_reupload(self, mock_get_file, mock_upload):
        class UploadedFileStub:
            name = 'files/fresh-456'

        mock_upload.return_value = UploadedFileStub()

        message = Message.objects.create(
            chat_session=self.session,
            role='user',
            content='Describe this image.',
            character=self.character,
        )
        attachment = MessageAttachment.objects.create(
            message=message,
            file=SimpleUploadedFile('scene.png', b'png', content_type='image/png'),
            attachment_name='scene.png',
            attachment_mime_type='image/png',
            attachment_kind='image',
            gemini_file_name='files/stale-1',
        )

        result = _get_or_upload_generativeai_file(attachment, attachment.file.path, 'scene.png', 'key')

        self.assertIs(result, mock_upload.return_value)
        mock_get_file.assert_called_once_with('files/stale-1')
        attachment.refresh_from_db()
        self.assertEqual(attachment.gemini_file_name, 'files/fresh-456')

    @patch('chat.tasks._request_gemini_media_analysis', return_value='A street market at dusk.')
    def test_gemini_video_slot_analyzes_files_over_inline_limit(self, mock_analysis):
        ModelConfiguration.objects.create(
            user=self.user,
            name='Text Only',
            provider='openai_compatible',
            model_name='plain-text-model',
            api_key='secret',
        )
        self.create_media_model_config(
            ModelRole.VIDEO,
            provider='gemini',
            model_name='gemini-2.5-flash',
            api_key='gemini-key',
            base_url='',
        )

        Message.objects.create(
            chat_session=self.session,
            role='user',
            content='Summarize this video.',
            character=self.character,
            attachment=SimpleUploadedFile(
                'long.mp4',
                b'x' * (MEDIA_ANALYSIS_MAX_BYTES + 1),
                content_type='video/mp4',
            ),
            attachment_name='long.mp4',
            attachment_mime_type='video/mp4',
            attachment_kind='video',
        )

        _runtime_config, formatted_history, _ = _build_provider_messages(
            chat_session=self.session,
            character=self.character,
            generate_greeting=False,
            research_context=None,
        )

        mock_analysis.assert_called_once()
        self.assertIn('A street market at dusk.', formatted_history[-1]['content'])

    @patch('chat.tasks._request_openai_media_analysis')
    def test_media_analysis_cache_prevents_repeat_calls(self, mock_analysis):
        mock_analysis.return_value = 'A red umbrella in the rain.'
        ModelConfiguration.objects.create(
            user=self.user,
            name='Text Only',
            provider='openai_compatible',
            model_name='plain-text-model',
            api_key='secret',
        )
        self.create_media_model_config(ModelRole.IMAGE, name='Image Role')

        user_message = Message.objects.create(
            chat_session=self.session,
            role='user',
            content='Describe this image.',
            character=self.character,
        )
        MessageAttachment.objects.create(
            message=user_message,
            file=SimpleUploadedFile(
                'scene.png',
                b'\x89PNG\r\n\x1a\n',
                content_type='image/png',
            ),
            attachment_name='scene.png',
            attachment_mime_type='image/png',
            attachment_kind='image',
            sort_order=0,
        )

        for _ in range(2):
            _build_provider_messages(
                chat_session=self.session,
                character=self.character,
                generate_greeting=False,
                research_context=None,
            )

        self.assertEqual(mock_analysis.call_count, 1)

    @patch('chat.tasks._upload_generativeai_file')
    def test_gemini_text_model_sends_native_media_without_slots(self, mock_upload):
        mock_upload.side_effect = lambda path, display_name, api_key: {
            'path': path,
            'display_name': display_name,
        }
        self.create_model_config(
            name='Gemini Text',
            provider='gemini',
            model_name='gemini-2.0-flash',
            api_key='secret',
            base_url='',
        )

        Message.objects.create(
            chat_session=self.session,
            role='user',
            content='Describe this image.',
            character=self.character,
            attachment=SimpleUploadedFile(
                'scene.png',
                b'\x89PNG\r\n\x1a\n',
                content_type='image/png',
            ),
            attachment_name='scene.png',
            attachment_mime_type='image/png',
            attachment_kind='image',
        )

        runtime_config, formatted_history, _ = _build_provider_messages(
            chat_session=self.session,
            character=self.character,
            generate_greeting=False,
            research_context=None,
        )

        self.assertEqual(runtime_config['provider'], 'gemini')
        self.assertEqual(mock_upload.call_count, 1)
        last_entry = formatted_history[-1]
        self.assertEqual(last_entry['role'], 'user')
        self.assertEqual(last_entry['parts'][0], 'Describe this image.')
        self.assertEqual(last_entry['parts'][1], {'path': mock_upload.call_args[0][0], 'display_name': 'scene.png'})

    def test_openai_compatible_text_only_model_limits_video_attachment_without_slot(self):
        ModelConfiguration.objects.create(
            user=self.user,
            name='Text Only',
            provider='openai_compatible',
            model_name='plain-text-model',
            api_key='secret',
        )

        video_message = Message.objects.create(
            chat_session=self.session,
            role='user',
            content='Read this video.',
            character=self.character,
            attachment=SimpleUploadedFile(
                'ocr.mp4',
                b'\x00\x00\x00\x18ftypmp42',
                content_type='video/mp4',
            ),
            attachment_name='ocr.mp4',
            attachment_mime_type='video/mp4',
            attachment_kind='video',
        )

        runtime_config, formatted_history, _ = _build_provider_messages(
            chat_session=self.session,
            character=self.character,
            generate_greeting=False,
            research_context=None,
        )

        self.assertEqual(runtime_config['provider'], 'openai_compatible')
        self.assertIsInstance(formatted_history[-1]['content'], str)
        self.assertIn('cannot directly inspect videos', formatted_history[-1]['content'])
        self.assertEqual(video_message.attachment_kind, 'video')


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class AttachmentSizeValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='size-owner', password='password123')

    def test_format_size_limit_renders_known_byte_counts(self):
        # Locks in the human-readable format used by the validator's
        # user-facing error message. Whole-number MB and KB limits must
        # not carry a trailing decimal, and sub-KB values fall back to
        # raw bytes.
        self.assertEqual(_format_size_limit(2 * 1024 * 1024), '2 MB')
        self.assertEqual(_format_size_limit(MAX_IMAGE_ATTACHMENT_BYTES), '20 MB')
        self.assertEqual(_format_size_limit(MAX_VIDEO_ATTACHMENT_BYTES), '100 MB')
        self.assertEqual(_format_size_limit(512 * 1024), '512 KB')
        self.assertEqual(_format_size_limit(1024), '1 KB')
        self.assertEqual(_format_size_limit(500), '500 B')

    def test_validate_attachment_size_reports_actual_limit_not_rounded_mb(self):
        # Regression: previously the error message used
        # `max_size // (1024 * 1024)`, which rounds 524288 bytes (512 KB)
        # down to 0, producing the misleading error "Text files larger
        # than 0 MB are not supported". The validator now reports the
        # real limit (2 MB) and the text limit itself is 2 MB so typical
        # character reference documents can be uploaded.
        self.assertEqual(MAX_TEXT_ATTACHMENT_BYTES, 2 * 1024 * 1024)

        small_text = SimpleUploadedFile('small.txt', b'small content', content_type='text/plain')
        # Under-limit files must pass cleanly.
        validate_attachment_size(small_text, AttachmentKind.TEXT)

        over_limit = SimpleUploadedFile(
            'over.txt',
            b'x' * (MAX_TEXT_ATTACHMENT_BYTES + 1),
            content_type='text/plain',
        )
        with self.assertRaises(ValueError) as ctx:
            validate_attachment_size(over_limit, AttachmentKind.TEXT)
        message = str(ctx.exception)
        self.assertIn('Text files larger than 2 MB are not supported', message)
        self.assertNotIn('0 MB', message)

    def test_validate_attachment_size_image_and_video_limits_format_mb(self):
        # Image and video limits are already in the MB range, so the
        # regression guard for "0 MB" cannot trigger for them — but
        # confirm the message format is still clean and includes the
        # correct, current limit so a future bump is easy to spot.
        # The over-limit file is just 1 byte over each limit so the
        # test stays cheap; we are validating the message format, not
        # the validator's ability to handle large byte buffers.
        for kind, expected, limit in (
            (AttachmentKind.IMAGE, '20 MB', MAX_IMAGE_ATTACHMENT_BYTES),
            (AttachmentKind.VIDEO, '100 MB', MAX_VIDEO_ATTACHMENT_BYTES),
        ):
            over_limit = SimpleUploadedFile(
                'over.bin',
                b'x' * (limit + 1),
                content_type='application/octet-stream',
            )
            with self.assertRaises(ValueError) as ctx:
                validate_attachment_size(over_limit, kind)
            self.assertIn(f'larger than {expected} are not supported', str(ctx.exception))


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class CharacterBackgroundUploadTests(ModelConfigTestMixin, TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()

        self.user = User.objects.create_user(username='background-owner', password='password123')
        self.client.force_login(self.user)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    def graphql(self, query, variables=None):
        return self.client.post(
            '/api/graphql/',
            data=json.dumps({
                'query': query,
                'variables': variables or {},
            }),
            content_type='application/json',
        )

    def _write_uploaded_text(self, filename, content):
        uploads_dir = os.path.join(self.media_root, 'uploads')
        os.makedirs(uploads_dir, exist_ok=True)
        with open(os.path.join(uploads_dir, filename), 'w', encoding='utf-8') as uploaded_file:
            uploaded_file.write(content)
        return f'http://testserver/media/uploads/{filename}'

    def _stage_upload(self, filename, content, *, binary=False):
        """Create an ``asset/uploaded`` event via AssetStore; returns upload_id.

        Replaces the old bare-file staging writes: the upload endpoint and the
        GraphQL create/update now flow through the AssetEvent log, so tests
        must stage through AssetStore.upload to get an upload_id.
        """
        from chat.assets.store import AssetStore

        if binary:
            file_obj = SimpleUploadedFile(
                filename,
                content if isinstance(content, bytes) else content.encode('utf-8'),
                content_type='image/png',
            )
        else:
            file_obj = SimpleUploadedFile(
                filename,
                content.encode('utf-8'),
                content_type='text/plain',
            )
        event, _metadata = AssetStore.upload(self.user, file_obj, filename)
        return event.id

    def _build_character_input(self, **overrides):
        payload = {
            'name': 'Imported Character',
            'avatarUrl': '',
            'description': 'A character seeded from imported background text.',
            'userAddress': 'Archivist',
            'personality': 'Reflective',
            'appearance': 'Silver coat',
            'responseGuidelines': 'Stay precise.',
            'scenario': 'Archive room',
            'exampleDialogue': '',
            'affiliation': 'Archive',
            'tags': ['archive', 'memory'],
            'backgroundFileUrl': '',
            'backgroundFileName': '',
        }
        payload.update(overrides)
        return payload

    def _write_uploaded_binary(self, filename, content):
        uploads_dir = os.path.join(self.media_root, 'uploads')
        os.makedirs(uploads_dir, exist_ok=True)
        with open(os.path.join(uploads_dir, filename), 'wb') as uploaded_file:
            uploaded_file.write(content)
        return f'http://testserver/media/uploads/{filename}'

    @patch('chat.graphql.schema._generate_text')
    def test_generate_character_draft_reads_uploaded_text_files_from_file_urls(self, mock_generate_text):
        ModelConfiguration.objects.create(
            user=self.user,
            name='Draft Model',
            provider='openai_compatible',
            model_name='gpt-4.1-mini',
            api_key='user-api-key',
            base_url='https://example.com/v1',
        )
        first_url = self._write_uploaded_text(
            'profile.txt',
            'Name: Mira\nRole: Research lead.',
        )
        second_url = self._write_uploaded_text(
            'dialogue.md',
            'Mira always answers with calm precision.',
        )
        image_url = self._write_uploaded_binary(
            'portrait.png',
            b'\x89PNG\r\n\x1a\n',
        )
        mock_generate_text.return_value = json.dumps({
            'name': 'Mira',
            'description': 'A detailed background in three sentences. Second sentence. Third sentence.',
            'affiliation': 'Lab',
            'tags': ['lab', 'calm', 'precise'],
        })

        response = self.graphql(
            """
            mutation GenerateDraft($fileUrls: [String!], $textContext: String) {
              generateCharacterDraft(fileUrls: $fileUrls, textContext: $textContext) {
                name
                description
              }
            }
            """,
            variables={
                'fileUrls': [first_url, second_url, image_url],
                'textContext': 'Keep the core concept grounded.',
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('errors', payload)
        self.assertEqual(payload['data']['generateCharacterDraft']['name'], 'Mira')

        # The draft must route through the Memory Tools, not inline the file bodies.
        runtime_config, messages = mock_generate_text.call_args[0]
        self.assertEqual(runtime_config['provider'], 'openai_compatible')
        self.assertTrue(mock_generate_text.call_args.kwargs['tools'])
        filesystem = mock_generate_text.call_args.kwargs['filesystem']
        self.assertIsInstance(filesystem, StagedUploadMemoryFilesystem)

        prompt_text = '\n'.join(
            message['content']
            for message in messages
            if isinstance(message.get('content'), str)
        )
        self.assertIn('Keep the core concept grounded.', prompt_text)
        # File bodies must NOT be injected into the prompt.
        self.assertNotIn('Name: Mira', prompt_text)
        self.assertNotIn('Mira always answers with calm precision.', prompt_text)

        # The files are queryable through the filesystem instead.
        listing = filesystem.list_memory_files(path_prefix='raw/character_setup/uploads')
        entries_by_title = {entry['title']: entry for entry in listing['entries']}
        self.assertIn('profile.txt', entries_by_title)
        self.assertIn('dialogue.md', entries_by_title)
        self.assertIn('portrait.png', entries_by_title)
        self.assertEqual(entries_by_title['portrait.png']['kind'], 'image')

        profile_doc = filesystem.read_memory_file('raw/character_setup/uploads/profile.txt')
        self.assertIn('Name: Mira', profile_doc['content'])

        portrait_doc = filesystem.read_memory_file('raw/character_setup/uploads/portrait.png')
        self.assertEqual(portrait_doc['kind'], 'image')
        self.assertEqual(portrait_doc['content'], '')

    def test_create_character_imports_background_text_into_memory_explorer(self):
        upload_id = self._stage_upload(
            'legacy-dialogue.txt',
            'User: Do you still remember me?\nCharacter: I never forgot.',
        )

        response = self.graphql(
            """
            mutation CreateCharacter($input: CharacterInput!) {
              createCharacter(input: $input) {
                id
                name
                backgroundFileName
              }
            }
            """,
            variables={
                'input': self._build_character_input(
                    backgroundFiles=[
                        {'uploadId': str(upload_id), 'fileName': 'legacy-dialogue.txt'},
                    ],
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('errors', payload)
        self.assertEqual(payload['data']['createCharacter']['backgroundFileName'], 'legacy-dialogue.txt')

        character = Character.objects.get(id=payload['data']['createCharacter']['id'])
        # Character files live in exactly one place: CharacterKnowledgeAsset.
        # The legacy `Character.file` mirror is no longer written.
        self.assertFalse(character.file)
        self.assertEqual(CharacterKnowledgeAsset.objects.filter(character=character).count(), 1)

        uploaded_doc = read_memory_explorer_file(
            character,
            'raw/character_setup/uploads/legacy-dialogue.txt',
        )
        self.assertEqual(uploaded_doc['path'], 'raw/character_setup/uploads/legacy-dialogue.txt')
        self.assertIn('I never forgot.', uploaded_doc['content'])

        session = ChatSession.objects.create(
            user=self.user,
            character=character,
            title='Imported Prompt Session',
        )
        prompt = _build_system_prompt(character, session)
        self.assertIn('USER UPLOADS', prompt)
        self.assertIn('Do you still remember me?', prompt)
        self.assertNotIn('## Tags', prompt)
        self.assertNotIn('archive, memory', prompt)

    def test_update_character_replaces_imported_background_text(self):
        character = Character.objects.create(
            created_by=self.user,
            name='Mutable Character',
            avatar_url='',
            description='Initial description.',
            user_address='Archivist',
            personality='Calm',
            appearance='Grey robe',
            response_guidelines='Stay calm.',
            scenario='Library',
            example_dialogue='',
            affiliation='Stacks',
            tags=['mutable'],
            file=SimpleUploadedFile(
                'original.txt',
                b'User: Original line\nCharacter: Original reply',
                content_type='text/plain',
            ),
        )
        replacement_upload_id = self._stage_upload(
            'replacement.txt',
            'User: New line\nCharacter: New reply',
        )

        response = self.graphql(
            """
            mutation UpdateCharacter($id: ID!, $input: CharacterInput!) {
              updateCharacter(id: $id, input: $input) {
                id
                backgroundFileName
              }
            }
            """,
            variables={
                'id': str(character.id),
                'input': self._build_character_input(
                    name=character.name,
                    description=character.description,
                    userAddress=character.user_address,
                    personality=character.personality,
                    appearance=character.appearance,
                    responseGuidelines=character.response_guidelines,
                    scenario=character.scenario,
                    exampleDialogue=character.example_dialogue,
                    affiliation=character.affiliation,
                    tags=character.tags,
                    backgroundFiles=[
                        {'uploadId': str(replacement_upload_id), 'fileName': 'replacement.txt'},
                    ],
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('errors', payload)
        self.assertEqual(payload['data']['updateCharacter']['backgroundFileName'], 'replacement.txt')

        character.refresh_from_db()
        uploaded_doc = read_memory_explorer_file(
            character,
            'raw/character_setup/uploads/replacement.txt',
        )
        self.assertIn('New reply', uploaded_doc['content'])
        self.assertNotIn('Original reply', uploaded_doc['content'])

    def test_create_character_accepts_multiple_text_and_image_reference_files(self):
        dialogue_upload_id = self._stage_upload(
            'dialogue.txt',
            'User: Stay with me.\nCharacter: Always.',
        )
        image_upload_id = self._stage_upload(
            'portrait.png',
            b'\x89PNG\r\n\x1a\n',
            binary=True,
        )

        response = self.graphql(
            """
            mutation CreateCharacter($input: CharacterInput!) {
              createCharacter(input: $input) {
                id
                knowledgeAssets {
                  fileName
                  fileType
                }
              }
            }
            """,
            variables={
                'input': self._build_character_input(
                    backgroundFiles=[
                        {'uploadId': str(dialogue_upload_id), 'fileName': 'dialogue.txt'},
                        {'uploadId': str(image_upload_id), 'fileName': 'portrait.png'},
                    ],
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('errors', payload)
        returned_assets = payload['data']['createCharacter']['knowledgeAssets']
        self.assertEqual(len(returned_assets), 2)
        self.assertEqual([asset['fileType'] for asset in returned_assets], ['text', 'image'])

        character = Character.objects.get(id=payload['data']['createCharacter']['id'])
        self.assertEqual(CharacterKnowledgeAsset.objects.filter(character=character).count(), 2)

        visual_doc = read_memory_explorer_file(
            character,
            'raw/character_setup/uploads/portrait.png',
        )
        self.assertIn('portrait.png', visual_doc['content'])

        background_doc = read_memory_explorer_file(
            character,
            'raw/character_setup/uploads/dialogue.txt',
        )
        self.assertIn('Stay with me.', background_doc['content'])

    @patch('chat.graphql.schema._generate_text')
    def test_generate_draft_routes_many_files_through_single_shot(self, mock_generate_text):
        """12+ 个文本文件且指定目标角色 → 预筛 + 单次 LLM 请求直达出卡。"""
        ModelConfiguration.objects.create(
            user=self.user,
            name='Draft Model',
            provider='openai_compatible',
            model_name='gpt-4.1-mini',
            api_key='user-api-key',
            base_url='https://example.com/v1',
        )

        urls = []
        for i in range(13):
            body = f'圣亚: 这是第 {i} 段的台词\n老师: 明白'
            urls.append(self._write_uploaded_text(f'episode_{i}.txt', body))

        def fake_generate_text(runtime_config, messages, *args, **kwargs):
            if isinstance(messages, str):
                # 单请求主链路：内联 prompt（含预筛片段）→ 直接返回角色卡 JSON。
                assert '圣亚' in messages
                return json.dumps({
                    'name': '圣亚',
                    'description': '三句话背景。第二句。第三句。',
                    'affiliation': '三一学园',
                    'personality': '温和而礼貌。',
                    'tags': ['温和', '三一'],
                    'example_dialogue': (
                        'User: 今天过得如何？\nCharacter: 平静的一天。\n\n'
                        'User: 那件事你怎么看？\nCharacter: 老师知道这件事吗？还不确定。'
                    ),
                })
            raise AssertionError('single-shot path must issue exactly one plain-prompt call')

        mock_generate_text.side_effect = fake_generate_text

        response = self.graphql(
            """
            mutation GenerateDraft($fileUrls: [String!], $textContext: String) {
              generateCharacterDraft(fileUrls: $fileUrls, textContext: $textContext) {
                name
                description
                personality
                affiliation
                tags
                exampleDialogue
              }
            }
            """,
            variables={
                'fileUrls': urls,
                'textContext': '目标角色名: 圣亚\n[角色简述]: 分析她',
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('errors', payload)
        draft = payload['data']['generateCharacterDraft']
        self.assertEqual(draft['name'], '圣亚')
        self.assertEqual(draft['personality'], '温和而礼貌。')
        self.assertEqual(draft['affiliation'], '三一学园')
        self.assertEqual(draft['tags'], ['温和', '三一'])
        self.assertIn('今天过得如何？', draft['exampleDialogue'])
        self.assertIn('Character: 老师知道这件事吗？', draft['exampleDialogue'])

        # 单请求主链路：恰好 1 次模型调用，prompt 里带预筛出的台词片段。
        self.assertEqual(mock_generate_text.call_count, 1)
        sent_prompt = mock_generate_text.call_args[0][1]
        self.assertIn('圣亚: 这是第 0 段的台词', sent_prompt)

    @patch('chat.tasks._request_openai_media_analysis', return_value='A young man with a silver pocket watch.')
    def test_provider_messages_include_character_reference_images_via_image_role(self, mock_analysis):
        character = Character.objects.create(
            created_by=self.user,
            name='Vision Character',
            avatar_url='',
            description='Uses visual references.',
            user_address='Traveler',
            personality='Focused',
            appearance='White scarf',
            response_guidelines='Stay visual.',
            scenario='Studio',
            example_dialogue='',
            affiliation='Gallery',
            tags=['vision'],
        )
        image_asset = CharacterKnowledgeAsset.objects.create(
            character=character,
            file=SimpleUploadedFile(
                'portrait.png',
                b'\x89PNG\r\n\x1a\n',
                content_type='image/png',
            ),
            attachment_name='portrait.png',
            attachment_mime_type='image/png',
            attachment_kind='image',
            sort_order=0,
        )
        CharacterKnowledgeAsset.objects.create(
            character=character,
            file=SimpleUploadedFile(
                'notes.txt',
                b'He keeps a silver pocket watch.',
                content_type='text/plain',
            ),
            attachment_name='notes.txt',
            attachment_mime_type='text/plain',
            attachment_kind='text',
            attachment_text_content='He keeps a silver pocket watch.',
            sort_order=1,
        )
        ModelConfiguration.objects.create(
            user=self.user,
            name='Text Only',
            provider='openai_compatible',
            model_name='plain-text-model',
            api_key='secret',
        )
        self.create_media_model_config(ModelRole.IMAGE, name='Image Role')

        session = ChatSession.objects.create(
            user=self.user,
            character=character,
            title='Vision Session',
        )

        runtime_config, formatted_history, _ = _build_provider_messages(
            chat_session=session,
            character=character,
            generate_greeting=False,
            research_context=None,
        )

        self.assertEqual(runtime_config['provider'], 'openai_compatible')
        self.assertEqual(mock_analysis.call_count, 1)
        reference_message = formatted_history[1]
        self.assertEqual(reference_message['role'], 'user')
        self.assertIsInstance(reference_message['content'], str)
        self.assertIn('[Character reference image analysis by image model]', reference_message['content'])
        self.assertIn('A young man with a silver pocket watch.', reference_message['content'])

        image_asset.refresh_from_db()
        self.assertEqual(image_asset.media_analysis, 'A young man with a silver pocket watch.')


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class ModelRoleAssignmentApiTests(ModelConfigTestMixin, TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='role-owner', password='password123')
        self.other_user = User.objects.create_user(username='role-other', password='password123')

    def test_list_returns_all_roles_with_none_defaults(self):
        self.client.force_login(self.user)
        response = self.client.get('/api/model-roles/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(set(payload.keys()), {'text', 'image', 'audio', 'video'})
        self.assertTrue(all(value is None for value in payload.values()))

    def test_put_assigns_roles_and_allows_config_reuse(self):
        config = self.create_model_config(name='Shared Model')
        self.client.force_login(self.user)

        response = self.client.put(
            '/api/model-roles/',
            data=json.dumps({'text': config.id, 'image': config.id, 'audio': None}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['text']['id'], config.id)
        self.assertEqual(payload['image']['id'], config.id)
        self.assertIsNone(payload['audio'])
        self.assertIsNone(payload['video'])
        self.assertEqual(
            ModelRoleAssignment.objects.filter(user=self.user, model_config=config).count(),
            2,
        )

    def test_put_rejects_empty_text_role(self):
        config = self.create_model_config(name='Text Model')
        self.client.force_login(self.user)

        response = self.client.put(
            '/api/model-roles/',
            data=json.dumps({'text': None}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('text model is required', response.json()['error'])
        self.assertTrue(
            ModelRoleAssignment.objects.filter(user=self.user, role=ModelRole.TEXT, model_config=config).exists()
        )

    def test_put_rejects_other_users_config(self):
        foreign_config = self.create_model_config(name='Foreign Model', user=self.other_user)
        self.create_model_config(name='Own Model')
        self.client.force_login(self.user)

        response = self.client.put(
            '/api/model-roles/',
            data=json.dumps({'text': foreign_config.id}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)

    def test_put_keeps_unmentioned_roles(self):
        first = self.create_model_config(name='First')
        self.client.force_login(self.user)
        self.client.put(
            '/api/model-roles/',
            data=json.dumps({'text': first.id}),
            content_type='application/json',
        )
        second = ModelConfiguration.objects.create(
            user=self.user,
            name='Second',
            provider='openai_compatible',
            model_name='other-model',
            api_key='key',
        )

        response = self.client.put(
            '/api/model-roles/',
            data=json.dumps({'image': second.id}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['text']['id'], first.id)
        self.assertEqual(payload['image']['id'], second.id)

    def test_delete_refuses_text_role_config_and_clears_media_role(self):
        text_config = self.create_model_config(name='Text Guard')
        media_config = self.create_media_model_config(ModelRole.IMAGE, name='Image Guard')
        self.client.force_login(self.user)

        refused = self.client.delete(f'/api/model-configs/{text_config.id}/')
        self.assertEqual(refused.status_code, 400)
        self.assertIn('text role', refused.json()['error'])

        allowed = self.client.delete(f'/api/model-configs/{media_config.id}/')
        self.assertEqual(allowed.status_code, 204)
        self.assertFalse(
            ModelRoleAssignment.objects.filter(user=self.user, role=ModelRole.IMAGE).exists()
        )
        self.assertTrue(
            ModelRoleAssignment.objects.filter(user=self.user, role=ModelRole.TEXT).exists()
        )

    def test_put_rejects_media_roles_without_any_text_assignment(self):
        config = ModelConfiguration.objects.create(
            user=self.user,
            name='Lonely Model',
            provider='openai_compatible',
            model_name='some-model',
            api_key='key',
        )
        self.client.force_login(self.user)

        response = self.client.put(
            '/api/model-roles/',
            data=json.dumps({'image': config.id}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('text model is required', response.json()['error'])
        self.assertFalse(
            ModelRoleAssignment.objects.filter(user=self.user, role=ModelRole.IMAGE).exists()
        )

    def test_first_created_config_auto_assigns_text_role(self):
        self.client.force_login(self.user)

        response = self.client.post(
            '/api/model-configs/',
            data=json.dumps({
                'name': 'First Config',
                'provider': 'openai_compatible',
                'model_name': 'gpt-4.1-mini',
                'api_key': 'secret',
                'base_url': 'https://example.com/v1',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        config = ModelConfiguration.objects.get(user=self.user, name='First Config')
        self.assertTrue(
            ModelRoleAssignment.objects.filter(
                user=self.user, role=ModelRole.TEXT, model_config=config
            ).exists()
        )

    def test_requires_authentication(self):
        response = self.client.get('/api/model-roles/')
        self.assertEqual(response.status_code, 401)

        put = self.client.put(
            '/api/model-roles/',
            data=json.dumps({'text': 1}),
            content_type='application/json',
        )
        self.assertEqual(put.status_code, 401)


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class ModelCatalogProbeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='probe-owner', password='password123')

    def test_probe_requires_authentication(self):
        response = self.client.post('/api/model-catalog/probe/')
        self.assertEqual(response.status_code, 401)

    def test_probe_rejects_unknown_provider(self):
        self.client.force_login(self.user)
        response = self.client.post(
            '/api/model-catalog/probe/',
            data=json.dumps({'provider': 'unknown'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('Unsupported provider', response.json()['error'])

    @patch('chat.model_catalog.requests.get')
    def test_probe_openai_compatible_lists_models(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'data': [{'id': 'model-b'}, {'id': 'model-a'}, {'id': 'model-a'}],
        }
        self.client.force_login(self.user)

        response = self.client.post(
            '/api/model-catalog/probe/',
            data=json.dumps({'provider': 'openai_compatible', 'base_url': 'https://example.com/v1', 'api_key': 'secret'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['models'], ['model-a', 'model-b'])
        request_url = mock_get.call_args[0][0]
        self.assertEqual(request_url, 'https://example.com/v1/models')
        self.assertEqual(mock_get.call_args[1]['headers']['Authorization'], 'Bearer secret')

    @patch('chat.model_catalog.requests.get')
    def test_probe_gemini_filters_generate_content_models(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'models': [
                {'name': 'models/gemini-2.0-flash', 'supportedGenerationMethods': ['generateContent']},
                {'name': 'models/text-embedding-004', 'supportedGenerationMethods': ['embedContent']},
            ],
        }
        self.client.force_login(self.user)

        response = self.client.post(
            '/api/model-catalog/probe/',
            data=json.dumps({'provider': 'gemini', 'api_key': 'secret'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['models'], ['gemini-2.0-flash'])

    @patch('chat.model_catalog.requests.get')
    def test_probe_gemini_requires_api_key(self, mock_get):
        self.client.force_login(self.user)
        response = self.client.post(
            '/api/model-catalog/probe/',
            data=json.dumps({'provider': 'gemini'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        mock_get.assert_not_called()

    @patch('chat.model_catalog.requests.get')
    def test_probe_anthropic_uses_api_key_header(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {'data': [{'id': 'claude-sonnet-4-5'}]}
        self.client.force_login(self.user)

        response = self.client.post(
            '/api/model-catalog/probe/',
            data=json.dumps({'provider': 'anthropic', 'api_key': 'secret'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['models'], ['claude-sonnet-4-5'])
        request_url = mock_get.call_args[0][0]
        self.assertEqual(request_url, 'https://api.anthropic.com/v1/models')
        self.assertEqual(mock_get.call_args[1]['headers']['x-api-key'], 'secret')


class AudioAttachmentRecognitionTests(TestCase):
    def test_guess_kind_recognizes_audio_by_mime_and_extension(self):
        mp3 = SimpleUploadedFile('voice.mp3', b'ID3', content_type='audio/mpeg')
        self.assertEqual(guess_attachment_kind(mp3), (AttachmentKind.AUDIO, 'audio/mpeg'))

        wav_by_extension = SimpleUploadedFile(
            'voice.wav', b'RIFF', content_type='application/octet-stream'
        )
        kind, mime = guess_attachment_kind(wav_by_extension)
        self.assertEqual(kind, AttachmentKind.AUDIO)
        self.assertTrue(mime.startswith('audio/'))

        ogg = SimpleUploadedFile('voice.ogg', b'OggS', content_type='audio/ogg')
        self.assertEqual(guess_attachment_kind(ogg)[0], AttachmentKind.AUDIO)

    def test_audio_attachment_size_limit(self):
        oversized = SimpleUploadedFile(
            'voice.mp3', b'x' * (MAX_AUDIO_ATTACHMENT_BYTES + 1), content_type='audio/mpeg'
        )
        with self.assertRaises(ValueError) as ctx:
            validate_attachment_size(oversized, AttachmentKind.AUDIO)
        self.assertIn('20 MB', str(ctx.exception))

        within = SimpleUploadedFile('voice.mp3', b'x' * 1024, content_type='audio/mpeg')
        validate_attachment_size(within, AttachmentKind.AUDIO)


class AnthropicMessageConversionTests(TestCase):
    def test_system_messages_are_extracted(self):
        system, messages = _build_anthropic_request_messages([
            {'role': 'system', 'content': 'You are Mira.'},
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Hi!'},
            {'role': 'user', 'content': 'Bye'},
        ])

        self.assertEqual(system, 'You are Mira.')
        self.assertEqual(
            messages,
            [
                {'role': 'user', 'content': 'Hello'},
                {'role': 'assistant', 'content': 'Hi!'},
                {'role': 'user', 'content': 'Bye'},
            ],
        )

    def test_image_url_blocks_are_converted_to_base64_sources(self):
        data_url = 'data:image/png;base64,QUJD'
        system, messages = _build_anthropic_request_messages([
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': [
                {'type': 'text', 'text': 'look'},
                {'type': 'image_url', 'image_url': {'url': data_url}},
                {'type': 'image_url', 'image_url': {'url': 'data:image/tiff;base64,AAA'}},
            ]},
        ])

        self.assertEqual(messages[0]['content'], [
            {'type': 'text', 'text': 'look'},
            {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'QUJD'}},
            {'type': 'text', 'text': '[Attached image skipped: image/tiff images are not supported by this provider]'},
        ])

    def test_tools_are_converted_to_anthropic_schema(self):
        converted = _convert_tools_to_anthropic(_build_memory_tool_specs())

        self.assertEqual(len(converted), 2)
        list_tool = converted[0]
        self.assertEqual(list_tool['name'], 'list_memory_files')
        self.assertIn('path_prefix', list_tool['input_schema']['properties'])
        self.assertNotIn('function', list_tool)

    def test_tool_blocks_survive_round_trip(self):
        tool_use = {'type': 'tool_use', 'id': 'toolu_1', 'name': 'list_memory_files', 'input': {'path_prefix': 'wiki'}}
        tool_result = {'type': 'tool_result', 'tool_use_id': 'toolu_1', 'content': '{"entries": []}'}

        _system, messages = _build_anthropic_request_messages([
            {'role': 'user', 'content': 'read memory'},
            {'role': 'assistant', 'content': [tool_use]},
            {'role': 'user', 'content': [tool_result]},
        ])

        self.assertEqual(messages[1]['content'], [tool_use])
        self.assertEqual(messages[2]['content'], [tool_result])

    def test_native_image_blocks_pass_through(self):
        image_block = {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'QUJD'}}

        _system, messages = _build_anthropic_request_messages([
            {'role': 'user', 'content': [{'type': 'text', 'text': 'ref'}, image_block]},
        ])

        self.assertEqual(messages[0]['content'], [{'type': 'text', 'text': 'ref'}, image_block])

    def test_consecutive_same_role_messages_are_merged(self):
        _system, messages = _build_anthropic_request_messages([
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': '[Character reference image analysis]'},
            {'role': 'user', 'content': 'Hello'},
        ])

        self.assertEqual([message['role'] for message in messages], ['user'])
        self.assertEqual(len(messages[0]['content']), 2)

    def test_empty_content_messages_are_skipped(self):
        _system, messages = _build_anthropic_request_messages([
            {'role': 'user', 'content': ''},
            {'role': 'assistant', 'content': 'Hi'},
        ])

        self.assertEqual(messages, [{'role': 'assistant', 'content': 'Hi'}])

    @patch('chat.tasks._execute_local_memory_tool', return_value={'entries': []})
    @patch('chat.tasks.requests.post')
    def test_tool_loop_preserves_tool_use_pairing(self, mock_post, _mock_tool):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.side_effect = [
            {'content': [
                {'type': 'text', 'text': 'checking memory'},
                {'type': 'tool_use', 'id': 'toolu_1', 'name': 'list_memory_files', 'input': {}},
            ]},
            {'content': [{'type': 'text', 'text': 'All clear.'}]},
        ]

        result = _generate_anthropic_response(
            model_name='claude-sonnet-4-5',
            api_key='secret',
            messages=[{'role': 'user', 'content': 'hi'}],
            base_url='',
            tools=_build_memory_tool_specs(),
            filesystem=object(),
        )

        self.assertEqual(result, 'All clear.')
        self.assertEqual(mock_post.call_count, 2)
        final_messages = mock_post.call_args_list[1][1]['json']['messages']
        self.assertTrue(any(
            block.get('type') == 'tool_use' and block.get('id') == 'toolu_1'
            for block in final_messages[-2]['content']
        ))
        self.assertTrue(any(
            block.get('type') == 'tool_result' and block.get('tool_use_id') == 'toolu_1'
            for block in final_messages[-1]['content']
        ))
        for message in final_messages:
            blocks = message['content']
            if isinstance(blocks, str):
                self.assertTrue(blocks)
                continue
            for block in blocks:
                if block.get('type') == 'text':
                    self.assertTrue(block['text'])


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class StreamingToolAndThinkingEventTests(ModelConfigTestMixin, TestCase):
    """Tool lines and native reasoning surfaced through the stream protocol."""

    def setUp(self):
        self.user = User.objects.create_user(username='stream-tools', password='password123')
        self.client.force_login(self.user)
        self.character = Character.objects.create(
            created_by=self.user,
            name='Stream Character',
            avatar_url='',
            description='A character for stream event tests.',
            personality='Curious',
            appearance='Green scarf',
            scenario='Garden',
            example_dialogue='',
            affiliation='Team S',
            tags=['stream'],
        )
        self.session = ChatSession.objects.create(
            user=self.user,
            character=self.character,
            title='Stream Tools Session',
        )

    def _profile(self, **overrides):
        profile = UserProfile.get_or_create_for_user(self.user)
        for key, value in overrides.items():
            setattr(profile, key, value)
        profile.save()
        return profile

    @patch('chat.tasks._build_provider_messages')
    @patch('chat.tasks._get_runtime_model_config')
    @patch('chat.tasks._iter_text_chunks')
    @patch('chat.tasks.build_research_context')
    @patch('chat.tasks._get_user_profile')
    @patch('chat.tasks._refine_steps_with_character_osis')
    @patch('chat.tasks._collect_memory_actions', return_value=[])
    def test_stream_ai_response_surfaces_tool_and_thinking_events_and_persists(
        self, mock_memory_actions, mock_refine, mock_profile, mock_research, mock_chunks, mock_config, mock_build
    ):
        mock_profile.return_value = self._profile(default_enable_web_search=False)
        mock_research.return_value = {'query': '', 'items': [], 'provider': '', 'error': ''}
        mock_chunks.return_value = iter([
            {'type': 'tool', 'tool': 'read_memory_file', 'arguments': {'path': 'raw/chat_sessions/session_1/transcript.md'}},
            # 双段思考协议：CHARACTER_OS 标记之后的内容才实时透传为 thinking 事件
            # （不带标记的模型推理会被拆分器缓冲，只有 done 时给出）。
            {'type': 'thinking', 'content': '<<<CHARACTER_OS>>>Let me check what happened last time...'},
            {'type': 'delta', 'content': 'Hello'},
            {'type': 'delta', 'content': ' there'},
        ])
        mock_config.return_value = {
            'provider': 'openai_compatible',
            'model_name': 'deepseek-r1',
            'api_key': 'k',
            'base_url': '',
        }
        mock_build.return_value = (mock_config.return_value, [], [])

        events = list(stream_ai_response(self.session, self.character))

        self.assertEqual(events[0]['type'], 'tool')
        self.assertEqual(events[0]['tool'], 'read_memory_file')
        self.assertEqual(events[0]['arguments']['path'], 'raw/chat_sessions/session_1/transcript.md')

        thinking_event = next(event for event in events if event['type'] == 'thinking')
        self.assertEqual(thinking_event['content'], 'Let me check what happened last time...')

        delta_text = ''.join(event['content'] for event in events if event['type'] == 'delta')
        self.assertEqual(delta_text, 'Hello there')

        done_event = next(event for event in events if event['type'] == 'done')
        self.assertEqual(done_event['thinking'], 'Let me check what happened last time...')
        self.assertEqual(done_event['tool_calls'], [
            {'tool': 'read_memory_file', 'arguments': {'path': 'raw/chat_sessions/session_1/transcript.md'}},
        ])

        ai_message = Message.objects.get(id=done_event['message_id'])
        self.assertEqual(ai_message.thinking, 'Let me check what happened last time...')
        self.assertEqual(ai_message.tool_calls, [
            {'tool': 'read_memory_file', 'arguments': {'path': 'raw/chat_sessions/session_1/transcript.md'}},
        ])

    @patch('chat.tasks._build_provider_messages')
    @patch('chat.tasks._get_runtime_model_config')
    @patch('chat.tasks._iter_text_chunks')
    @patch('chat.tasks.build_research_context')
    @patch('chat.tasks._build_search_query')
    @patch('chat.tasks._get_user_profile')
    @patch('chat.tasks._refine_steps_with_character_osis')
    @patch('chat.tasks._collect_memory_actions', return_value=[])
    def test_stream_ai_response_emits_web_search_tool_event(
        self, mock_memory_actions, mock_refine, mock_profile, mock_query, mock_research, mock_chunks, mock_config, mock_build
    ):
        mock_profile.return_value = self._profile(default_enable_web_search=True)
        mock_query.return_value = 'best ramen in tokyo'
        mock_research.return_value = {
            'query': 'best ramen in tokyo',
            'items': [{'title': 'x', 'url': 'https://x', 'snippet': 'y'}],
            'provider': 'tavily',
            'error': '',
        }
        mock_chunks.return_value = iter([{'type': 'delta', 'content': 'Try Ichiran.'}])
        mock_config.return_value = {
            'provider': 'openai_compatible',
            'model_name': 'm',
            'api_key': 'k',
            'base_url': '',
        }
        mock_build.return_value = (mock_config.return_value, [], [])

        events = list(stream_ai_response(self.session, self.character))

        self.assertEqual(events[0]['type'], 'tool')
        self.assertEqual(events[0]['tool'], 'web_search')
        self.assertEqual(events[0]['arguments']['query'], 'best ramen in tokyo')
        done_event = next(event for event in events if event['type'] == 'done')
        self.assertEqual(done_event['tool_calls'][0]['tool'], 'web_search')

    @patch('chat.tasks._execute_local_memory_tool', return_value={'entries': []})
    @patch('chat.tasks.requests.post')
    def test_openai_tool_loop_emits_tool_and_thinking_events(self, mock_post, _mock_tool):
        """工具循环已流式化（v0.1.6）：思考增量在轮内实时流出，
        工具调用分片累积，轮末产出最终文本。"""

        def _sse_response(chunks):
            class FakeResponse:
                status_code = 200

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def raise_for_status(self):
                    pass

                def close(self):
                    pass

                def iter_lines(self, decode_unicode=True):
                    for chunk in chunks:
                        yield 'data: ' + json.dumps(chunk)

            return FakeResponse()

        round1 = [
            {'choices': [{'delta': {'role': 'assistant', 'reasoning_content': '先看看记忆里有什么'}, 'finish_reason': None}]},
            {'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'call_1', 'type': 'function', 'function': {'name': 'list_memory_files', 'arguments': ''}}]}, 'finish_reason': None}]},
            {'choices': [{'delta': {'tool_calls': [{'index': 0, 'function': {'arguments': '{"path_prefix": "wiki"}'}}]}, 'finish_reason': 'tool_calls'}]},
        ]
        round2 = [
            {'choices': [{'delta': {'reasoning_content': '那现在直接回答'}, 'finish_reason': None}]},
            # 模型把双段协议/think 标签写进正文：final_text 必须已被清洗。
            {'choices': [{'delta': {'content': '<<<RAW_REASONING>>>提炼一下…<think>All set.</think>'}, 'finish_reason': 'stop'}]},
        ]
        mock_post.side_effect = [_sse_response(round1), _sse_response(round2)]

        result = _generate_openai_compatible_response(
            model_name='deepseek-r1',
            api_key='k',
            messages=[{'role': 'user', 'content': 'hi'}],
            base_url='https://example.com/v1',
            tools=_build_memory_tool_specs(),
            filesystem=object(),
        )
        # The function is a generator: collect final_text + tool/thinking events.
        events = list(result)
        final_text = ''.join(e.get('content') or '' for e in events if e.get('type') == 'final_text')
        tool_events = [e for e in events if e.get('type') in ('tool', 'thinking')]

        self.assertEqual(final_text, 'All set.')
        # 思考按轮实时流（每段一个事件、标注轮次），工具调用紧随其后，
        # 前端按"思考→工具→思考"顺序渲染。
        self.assertEqual(tool_events, [
            {'type': 'thinking', 'content': '先看看记忆里有什么', 'round': 1},
            {'type': 'tool', 'tool': 'list_memory_files', 'arguments': {'path_prefix': 'wiki'}, 'round': 1},
            {'type': 'thinking', 'content': '那现在直接回答', 'round': 2},
        ])

    @patch('chat.views.stream_ai_response')
    def test_stream_message_passes_tool_and_thinking_events_through(self, mock_stream_ai_response):
        self.create_model_config()
        mock_stream_ai_response.return_value = iter([
            {'type': 'tool', 'tool': 'web_search', 'arguments': {'query': 'x'}},
            {'type': 'thinking', 'content': 'hmm'},
            {'type': 'delta', 'content': 'Hello'},
            {
                'type': 'done',
                'message_id': 999,
                'content': 'Hello',
                'timestamp': '2026-01-01T00:00:00+00:00',
                'latency_ms': 10,
                'thinking': 'hmm',
                'tool_calls': [{'tool': 'web_search', 'arguments': {'query': 'x'}}],
            },
        ])

        response = self.client.post(
            '/api/chat/stream_message/',
            data=json.dumps({
                'character_id': self.character.id,
                'chat_session_id': self.session.id,
                'message': 'hi',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        payload_lines = [
            json.loads(line)
            for line in _consume_streaming(response).decode('utf-8').splitlines()
            if line.strip()
        ]
        event_types = [line['type'] for line in payload_lines]
        self.assertEqual(event_types, ['session', 'tool', 'thinking', 'delta', 'done'])
        self.assertEqual(payload_lines[1]['tool'], 'web_search')
        self.assertEqual(payload_lines[2]['content'], 'hmm')
        self.assertEqual(payload_lines[4]['thinking'], 'hmm')


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class DualThinkingSplitterTests(TestCase):
    """思考流的实时可见性：无标记推理必须立即实时透传（v0.1.6 修复）。"""

    def test_unmarked_reasoning_streams_live_and_lands_in_thinking(self):
        splitter = _DualThinkingSplitter()

        first_events = splitter.feed('这段推理立刻可见')
        self.assertEqual(first_events, [{'type': 'thinking', 'content': '这段推理立刻可见'}])
        # 后续增量也要持续透传（旧实现只透传一次，之后又恢复静默）。
        second_events = splitter.feed('第二段也实时')
        self.assertEqual(second_events, [{'type': 'thinking', 'content': '第二段也实时'}])

        self.assertFalse(splitter.saw_marker)
        # 无标记回退 = "思考过程"而非原始推理（raw 只收 RAW 标记之后的内容）。
        os_text, raw_text = splitter.finalize()
        self.assertEqual(os_text, '这段推理立刻可见第二段也实时')
        self.assertEqual(raw_text, '')

    def test_incomplete_marker_prefix_waits_for_next_chunk(self):
        splitter = _DualThinkingSplitter()

        # '<<<CHAR' 可能是残缺标记前缀：按住不透传。
        self.assertEqual(splitter.feed('<<<CHAR'), [])
        # 下一 chunk 补齐标记：标记后的文本作为角色心声实时透传。
        events = splitter.feed('ACTER_OS>>>我的独白')
        self.assertEqual(events, [{'type': 'thinking', 'content': '我的独白'}])
        self.assertTrue(splitter.saw_marker)
        os_text, raw_text = splitter.finalize()
        self.assertEqual(os_text, '我的独白')
        self.assertEqual(raw_text, '')

    def test_raw_reasoning_after_marker_stays_quiet_until_done(self):
        splitter = _DualThinkingSplitter()

        splitter.feed('<<<CHARACTER_OS>>>心声')
        # RAW 标记后的内容按双段协议静默缓存（原始推理只在 done 提供）。
        self.assertEqual(splitter.feed('<<<RAW_REASONING>>>硬核推理'), [])
        self.assertTrue(splitter.saw_marker)
        os_text, raw_text = splitter.finalize()
        self.assertEqual(os_text, '心声')
        self.assertEqual(raw_text, '硬核推理')

    def test_multiround_raw_reasoning_only_collects_raw_marker_sections(self):
        """工具循环每轮重复协议标记：raw_reasoning 只收 RAW 标记之后的内容，
        第二轮的角色心声不得混入原始推理（v0.1.6 用户实测）。"""
        splitter = _DualThinkingSplitter()

        splitter.feed('<<<CHARACTER_OS>>>第一轮心声')
        splitter.feed('<<<RAW_REASONING>>>第一轮硬核')
        # 第二轮再次回到心声协议：旧实现在这里会把"第二轮心声"错误归入 raw。
        self.assertEqual(splitter.feed('<<<CHARACTER_OS>>>第二轮心声'),
                         [{'type': 'thinking', 'content': '第二轮心声'}])
        splitter.feed('<<<RAW_REASONING>>>第二轮硬核')

        os_text, raw_text = splitter.finalize()
        self.assertEqual(os_text, '第一轮心声第二轮心声')
        self.assertEqual(raw_text, '第一轮硬核第二轮硬核')

    def test_prefix_before_first_raw_marker_is_not_raw(self):
        """未出现过心声标记时，RAW 标记之前的前奏不得计入 raw_reasoning。"""
        splitter = _DualThinkingSplitter()

        splitter.feed('前奏文字')
        splitter.feed('<<<RAW_REASONING>>>真正的原始推理')

        os_text, raw_text = splitter.finalize()
        self.assertEqual(raw_text, '真正的原始推理')

    def test_extract_real_reply_text_strips_protocol_pollution(self):
        """deepseek-v4-flash 实测会把双段协议与 <think> 标签写进正文：清洗后
        只剩真正的回复（v0.1.6）。"""
        from chat.tasks import _extract_real_reply_text

        polluted = (
            '<<<CHARACTER_OS>>>\n\n'
            '哇，是老师了！这是角色心声段落……\n\n'
            '<<<RAW_REASONING>>>\n\n'
            '用户用简单的中文打招呼……直接以活泼的语气回应即可。\n'
            '<think>真正的回答来了！</think>'
        )
        self.assertEqual(_extract_real_reply_text(polluted), '真正的回答来了！')

    def test_extract_real_reply_text_keeps_normal_replies(self):
        from chat.tasks import _extract_real_reply_text

        normal = '你好呀，老师！今天也要元气满满唷～'
        self.assertEqual(_extract_real_reply_text(normal), normal)

    def test_extract_real_reply_text_trims_self_instruction_prefix(self):
        """模型把查询计划+自我指令写进正文（无标记）：只保留正式回复
        （v0.1.6 用户实测"系统思考混入角色输出"）。"""
        from chat.tasks import _extract_real_reply_text

        polluted = (
            '用户问爱丽丝什么时候获得阿比舒机甲套装。\n\n'
            '- 阿比舒机甲是在最终决战前夕获得的（资料确认）\n\n'
            '回答时用爱丽丝的游戏玩家口吻，讲述获得机甲的故事。\n\n'
            '咦，老师还记得阿比舒的事呀！'
        )
        self.assertEqual(_extract_real_reply_text(polluted), '咦，老师还记得阿比舒的事呀！')

    def test_extract_real_reply_text_trims_fused_single_line_plan(self):
        """计划段被模型用单换行熔成一整段（无 \n\n 段落边界）时，
        按句子粒度仍能切到正确的"自我指令"句。"""
        from chat.tasks import _extract_real_reply_text

        polluted = (
            '用户问爱丽丝何时获得阿比舒机甲。'
            '已检索记忆文件确认相关信息：阿比舒是最终章前由莉央会长给予的机甲装备。'
            '回复需以游戏术语、第三人称、拟声词，保持天真活泼又带点认真回忆的口吻。'
            '核心要点：大战前夕获得、来自莉央会长、训练摔伤被背回、对机甲有怜惜之情。'
            '\n\n嗯，想好了。'
            '爱丽丝要用"读档回忆"的方式来回答老师，把阿比舒那天的故事讲得又认真又温暖。'
            '\n\n确认回复方案：以爱丽丝视角叙述获得阿比舒的时间点。'
            '\n\n保持角色语气，第三人称+拟声词，游戏术语包装。'
            '\n\n最终回复：组织语言，以游戏存档比喻开场，讲述阿比舒获得经历，语气真挚活泼。'
            '\n\n哇，老师还记得阿比舒呀！'
            '爱丽丝好高兴唷！'
        )
        self.assertEqual(
            _extract_real_reply_text(polluted),
            '哇，老师还记得阿比舒呀！爱丽丝好高兴唷！',
        )


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class SharedGenerationConfigTests(TestCase):
    """Streaming and non-streaming paths share one generation configuration."""

    def setUp(self):
        self.user = User.objects.create_user(username='shared-config', password='password123')
        self.character = Character.objects.create(
            created_by=self.user,
            name='Shared Config Character',
            avatar_url='',
            description='A character for shared generation config tests.',
            personality='Even-keeled',
            appearance='Beige sweater',
            scenario='Office',
            example_dialogue='',
            affiliation='Team C',
            tags=['shared'],
        )
        self.session = ChatSession.objects.create(
            user=self.user,
            character=self.character,
            title='Shared Config Session',
        )

    @patch('chat.tasks._build_provider_messages')
    @patch('chat.tasks._build_stream_memory_prefetch', return_value='PREFETCHED MEMORY')
    @patch('chat.tasks._supports_memory_tool_mode')
    @patch('chat.tasks._get_runtime_model_config')
    def test_prepare_generation_uses_prefetch_when_tools_unsupported(
        self, mock_config, mock_supports, mock_prefetch, mock_build
    ):
        mock_config.return_value = {
            'provider': 'gemini',
            'model_name': 'gemini-2.5-flash',
            'api_key': 'k',
            'base_url': '',
        }
        mock_supports.return_value = False
        mock_build.return_value = (mock_config.return_value, [], [])

        _prepare_generation(self.session, self.character)

        mock_prefetch.assert_called_once()
        mock_build.assert_called_once_with(
            chat_session=self.session,
            character=self.character,
            generate_greeting=False,
            research_context=None,
            allow_memory_tools=False,
            retrieved_memory='PREFETCHED MEMORY',
        )

    @patch('chat.tasks._build_provider_messages')
    @patch('chat.tasks._build_stream_memory_prefetch')
    @patch('chat.tasks._supports_memory_tool_mode')
    @patch('chat.tasks._get_runtime_model_config')
    def test_prepare_generation_uses_tools_when_supported_and_skips_prefetch(
        self, mock_config, mock_supports, mock_prefetch, mock_build
    ):
        mock_config.return_value = {
            'provider': 'openai_compatible',
            'model_name': 'gpt-4.1',
            'api_key': 'k',
            'base_url': '',
        }
        mock_supports.return_value = True
        mock_build.return_value = (mock_config.return_value, [], [])

        _prepare_generation(self.session, self.character)

        mock_prefetch.assert_not_called()
        mock_build.assert_called_once_with(
            chat_session=self.session,
            character=self.character,
            generate_greeting=False,
            research_context=None,
            allow_memory_tools=True,
            retrieved_memory='',
        )


class GeoDetectionTests(TestCase):
    """chat.geo.detect_location 的 provider 链路与归一化。"""

    def test_private_addresses_trigger_egress_fallback_with_mocks(self):
        from chat.geo import detect_location

        with patch('chat.geo.requests.get') as mock_get:
            mock_get.return_value.json.return_value = {
                'success': True,
                'country': 'United States',
                'region': 'California',
                'city': 'San Francisco',
                'timezone': 'America/Los_Angeles',
                'latitude': 37.77,
                'longitude': -122.41,
            }
            mock_get.return_value.raise_for_status.return_value = None
            result = detect_location('192.168.1.10')

        self.assertTrue(result['ok'])
        self.assertTrue(result['fallback_egress'])
        # 回退时不应把内网 IP 传给查询服务。
        self.assertNotIn('ip', mock_get.call_args_list[0].kwargs['params'])

    def test_normalizes_ipwho_payload_with_localized_names(self):
        from chat.geo import detect_location

        ipwho_payload = {
            'success': True,
            'country': '中国',
            'region': '上海',
            'city': '上海',
            'timezone': {'id': 'Asia/Shanghai', 'abbr': 'CST'},
            'latitude': 31.22,
            'longitude': 121.45,
        }

        with patch('chat.geo.requests.get') as mock_get:
            mock_get.return_value.json.return_value = ipwho_payload
            mock_get.return_value.raise_for_status.return_value = None
            result = detect_location('66.165.242.131', lang='zh-CN')

        self.assertTrue(result['ok'])
        self.assertEqual(result['source'], 'ipwho.is')
        self.assertEqual(result['country'], '中国')
        self.assertEqual(result['timezone'], 'Asia/Shanghai')
        first_call = mock_get.call_args_list[0]
        self.assertEqual(first_call.args[0], 'https://ipwho.is/')
        self.assertEqual(first_call.kwargs['params'], {'ip': '66.165.242.131', 'lang': 'zh-CN'})

    def test_falls_back_to_ipapi_when_ipwho_fails(self):
        from chat.geo import detect_location

        ipapi_payload = {
            'country_name': 'United States',
            'region': 'California',
            'city': 'San Francisco',
            'timezone': 'America/Los_Angeles',
            'latitude': 37.77,
            'longitude': -122.41,
        }

        with patch('chat.geo.requests.get') as mock_get:
            mock_get.return_value.json.side_effect = [
                {'success': False, 'message': 'blocked'},
                ipapi_payload,
            ]
            mock_get.return_value.raise_for_status.return_value = None
            result = detect_location('66.165.242.131')

        self.assertTrue(result['ok'])
        self.assertEqual(result['source'], 'ipapi.co')
        self.assertEqual(result['country'], 'United States')
        self.assertEqual(result['region'], 'California')
        self.assertEqual(result['city'], 'San Francisco')
        self.assertEqual(result['timezone'], 'America/Los_Angeles')

    def test_reports_unavailable_when_all_providers_fail(self):
        from chat.geo import detect_location

        with patch('chat.geo.requests.get') as mock_get:
            mock_get.return_value.json.side_effect = [
                {'success': False, 'message': 'blocked'},
                {'country_name': '', 'region': '', 'city': ''},
            ]
            mock_get.return_value.raise_for_status.return_value = None
            result = detect_location('66.165.242.131')

        self.assertEqual(result, {'ok': False, 'reason': 'unavailable'})


class GeoDetectionEgressFallbackTests(TestCase):
    """内网/本机客户端应回退到服务器出口 IP 检测。"""

    IPWHO_PAYLOAD = {
        'success': True,
        'ip': '203.0.113.7',
        'country': '中国',
        'region': '上海',
        'city': '上海',
        'timezone': {'id': 'Asia/Shanghai'},
        'latitude': 31.22,
        'longitude': 121.45,
    }

    def setUp(self):
        self.user = User.objects.create_user(username='geo-owner', password='password123')

    def test_detect_location_falls_back_to_server_egress_for_loopback_client(self):
        self.client.force_login(self.user)

        with patch('chat.geo.requests.get') as mock_get:
            mock_get.return_value.json.return_value = dict(self.IPWHO_PAYLOAD)
            mock_get.return_value.raise_for_status.return_value = None
            response = self.client.get('/api/user-profile/detect-location/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertTrue(payload['fallback_egress'])
        self.assertEqual(payload['country'], '中国')
        self.assertEqual(payload['latitude'], 31.22)
        first_call = mock_get.call_args_list[0]
        self.assertEqual(first_call.args[0], 'https://ipwho.is/')
        self.assertEqual(first_call.kwargs['params'], {'lang': 'en'})

    def test_detect_location_still_uses_client_ip_when_public(self):
        from chat.geo import detect_location

        with patch('chat.geo.requests.get') as mock_get:
            mock_get.return_value.json.return_value = dict(self.IPWHO_PAYLOAD)
            mock_get.return_value.raise_for_status.return_value = None
            result = detect_location('66.165.242.131')

        self.assertTrue(result['ok'])
        self.assertFalse(result['fallback_egress'])
        first_call = mock_get.call_args_list[0]
        self.assertEqual(first_call.kwargs['params']['ip'], '66.165.242.131')
