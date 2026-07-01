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
    UserProfile,
    WebSearchConfiguration,
)
from chat.search import search_web
from chat.attachments import (
    MAX_IMAGE_ATTACHMENT_BYTES,
    MAX_TEXT_ATTACHMENT_BYTES,
    MAX_VIDEO_ATTACHMENT_BYTES,
    _format_size_limit,
    validate_attachment_size,
)
from chat.soul import (
    build_character_system_prompt_preview,
    build_character_setup_markdown,
    list_memory_explorer_path,
    read_memory_explorer_file,
)
from chat.tasks import (
    _build_memory_tool_specs,
    _build_provider_messages,
    _build_search_query,
    _build_stream_memory_prefetch,
    _build_system_prompt,
    _generate_openai_compatible_response,
    build_research_context,
)


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class AuthorizationRegressionTests(TestCase):
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

    def create_model_config(self, user=None, **overrides):
        owner = user or self.user
        defaults = {
            'name': 'Default User Model',
            'provider': 'openai_compatible',
            'model_name': 'gpt-4.1-mini',
            'api_key': 'user-api-key',
            'base_url': 'https://example.com/v1',
            'is_default': True,
        }
        defaults.update(overrides)
        return ModelConfiguration.objects.create(user=owner, **defaults)

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

    def test_rest_delete_character_blocks_when_chat_sessions_exist(self):
        self.client.force_login(self.user)

        response = self.client.delete(f'/api/characters/{self.own_character.id}/')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['error'],
            'Cannot delete a character with existing chat sessions',
        )
        self.assertTrue(Character.objects.filter(id=self.own_character.id).exists())
        self.assertTrue(ChatSession.objects.filter(id=self.own_session.id).exists())

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
        # be truncated in the error message so the AICharacterDraft
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
            for line in b''.join(response.streaming_content).decode('utf-8').splitlines()
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
        self.assertIn('Interpret relative time words such as today, tonight, and tomorrow in the user\'s local timezone.', prompt)
        self.assertIn('Location Hint (City level): Boston, MA', prompt)
        self.assertIn('Do not guess current conditions.', prompt)

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
            is_default=True,
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
            is_default=True,
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

    @patch('chat.tasks._request_openai_compatible_completion')
    def test_openai_tool_loop_reads_memory_files_before_final_answer(self, mock_request_openai_completion):
        mock_request_openai_completion.side_effect = [
            {
                'choices': [{
                    'message': {
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
                }],
            },
            {
                'choices': [{
                    'message': {
                        'role': 'assistant',
                        'content': 'I still call you Gatewalker.',
                    },
                }],
            },
        ]

        result = _generate_openai_compatible_response(
            model_name='gpt-4.1-mini',
            api_key='secret',
            messages=[{'role': 'system', 'content': 'Use memory tools.'}],
            base_url='https://example.com/v1',
            tools=_build_memory_tool_specs(),
            character=self.character,
        )

        self.assertEqual(result, 'I still call you Gatewalker.')
        self.assertEqual(mock_request_openai_completion.call_count, 2)

        second_call_messages = mock_request_openai_completion.call_args_list[1].kwargs['messages']
        tool_messages = [message for message in second_call_messages if message.get('role') == 'tool']
        self.assertEqual(len(tool_messages), 1)
        self.assertIn('Gatewalker', tool_messages[0]['content'])

    @patch('chat.tasks._request_openai_compatible_completion')
    def test_openai_tool_loop_falls_back_when_backend_rejects_tools(self, mock_request_openai_completion):
        mock_request_openai_completion.side_effect = [
            requests.HTTPError('Unsupported parameter: tools'),
            {
                'choices': [{
                    'message': {
                        'role': 'assistant',
                        'content': 'Fallback answer without tools.',
                    },
                }],
            },
        ]

        result = _generate_openai_compatible_response(
            model_name='gpt-4.1-mini',
            api_key='secret',
            messages=[{'role': 'system', 'content': 'Use memory tools if available.'}],
            base_url='https://example.com/v1',
            tools=_build_memory_tool_specs(),
            character=self.character,
        )

        self.assertEqual(result, 'Fallback answer without tools.')
        self.assertEqual(mock_request_openai_completion.call_count, 2)
        self.assertNotIn('tools', mock_request_openai_completion.call_args_list[1].kwargs)


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class ChatAttachmentTests(TestCase):
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
            is_default=True,
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
            for line in b''.join(response.streaming_content).decode('utf-8').splitlines()
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
            for line in b''.join(response.streaming_content).decode('utf-8').splitlines()
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
            is_default=True,
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

    def test_openai_compatible_qwen36_plus_uses_native_image_and_video_blocks(self):
        ModelConfiguration.objects.create(
            user=self.user,
            name='Qwen 3.6 Plus',
            provider='openai_compatible',
            model_name='qwen3.6-plus',
            api_key='secret',
            base_url='https://dashscope-intl.aliyuncs.com/compatible-mode/v1',
            is_default=True,
        )

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
        image_content = formatted_history[-1]['content']
        self.assertIsInstance(image_content, list)
        self.assertEqual(image_content[0]['type'], 'text')
        self.assertEqual(image_content[1]['type'], 'image_url')
        self.assertTrue(image_content[1]['image_url']['url'].startswith('data:image/png;base64,'))
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

        _, formatted_history, _ = _build_provider_messages(
            chat_session=self.session,
            character=self.character,
            generate_greeting=False,
            research_context=None,
        )

        video_content = formatted_history[-1]['content']
        self.assertIsInstance(video_content, list)
        self.assertEqual(video_content[0]['type'], 'text')
        self.assertEqual(video_content[1]['type'], 'video_url')
        self.assertTrue(video_content[1]['video_url']['url'].startswith('data:video/mp4;base64,'))
        self.assertEqual(video_content[1]['fps'], 2.0)
        self.assertEqual(video_message.attachment_kind, 'video')

    def test_openai_compatible_qwen_vl_ocr_stays_image_only(self):
        ModelConfiguration.objects.create(
            user=self.user,
            name='Qwen OCR',
            provider='openai_compatible',
            model_name='qwen-vl-ocr',
            api_key='secret',
            base_url='https://dashscope-intl.aliyuncs.com/compatible-mode/v1',
            is_default=True,
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
class CharacterBackgroundUploadTests(TestCase):
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
            is_default=True,
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

        _, prompt = mock_generate_text.call_args[0]
        self.assertIn('Keep the core concept grounded.', prompt)
        self.assertIn('Name: Mira', prompt)
        self.assertIn('Mira always answers with calm precision.', prompt)
        self.assertNotIn('portrait.png', prompt)

    def test_create_character_imports_background_text_into_memory_explorer(self):
        background_url = self._write_uploaded_text(
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
                    backgroundFileUrl=background_url,
                    backgroundFileName='legacy-dialogue.txt',
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('errors', payload)
        self.assertEqual(payload['data']['createCharacter']['backgroundFileName'], 'legacy-dialogue.txt')

        character = Character.objects.get(id=payload['data']['createCharacter']['id'])
        self.assertTrue(character.file.name.startswith('character_files/'))
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
        replacement_url = self._write_uploaded_text(
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
                    backgroundFileUrl=replacement_url,
                    backgroundFileName='replacement.txt',
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
        dialogue_url = self._write_uploaded_text(
            'dialogue.txt',
            'User: Stay with me.\nCharacter: Always.',
        )
        image_url = self._write_uploaded_binary(
            'portrait.png',
            b'\x89PNG\r\n\x1a\n',
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
                        {'uploadedUrl': dialogue_url, 'fileName': 'dialogue.txt'},
                        {'uploadedUrl': image_url, 'fileName': 'portrait.png'},
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

    def test_provider_messages_include_character_reference_images_for_vision_models(self):
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
        CharacterKnowledgeAsset.objects.create(
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
            name='Vision Default',
            provider='openai_compatible',
            model_name='gpt-4o',
            api_key='secret',
            base_url='https://example.com/v1',
            is_default=True,
        )
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
        self.assertEqual(formatted_history[1]['role'], 'user')
        self.assertIsInstance(formatted_history[1]['content'], list)
        self.assertEqual(len(formatted_history[1]['content']), 1)
        self.assertEqual(formatted_history[1]['content'][0]['type'], 'image_url')
        self.assertTrue(formatted_history[1]['content'][0]['image_url']['url'].startswith('data:image/png;base64,'))
