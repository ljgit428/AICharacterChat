"""文件组（folder-group）上传 → 记忆文本链路的回归测试。

覆盖：relative_path 上传落盘、StagedUploadMemoryFilesystem 的嵌套路径/去重/
目录项、草稿工具提示词中的上传文件目录索引，以及 Memory Explorer 中知识资产
的目录层级保留。
"""
import json
import os
import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from chat.file_views import sanitize_relative_path
from chat.memory.filesystem import StagedUploadMemoryFilesystem
from chat.graphql.schema import _build_character_draft_tool_prompt
from chat.models import AttachmentKind, Character, CharacterKnowledgeAsset, ModelConfiguration
from chat.soul import list_memory_explorer_path, read_memory_explorer_file


class SanitizeRelativePathTests(TestCase):
    def test_keeps_folder_hierarchy_and_drops_traversal(self):
        self.assertEqual(
            sanitize_relative_path('Momotalk/玛丽_10105/../scene 1.txt'),
            'Momotalk/玛丽_10105/scene 1.txt',
        )

    def test_normalizes_backslashes_and_leading_slashes(self):
        self.assertEqual(
            sanitize_relative_path('\\Group\\sub\\file.txt'),
            'Group/sub/file.txt',
        )

    def test_caps_segment_count(self):
        deep = '/'.join(f'dir{i}' for i in range(20)) + '/file.txt'
        result = sanitize_relative_path(deep)
        self.assertEqual(len(result.split('/')), 12)

    def test_empty_input_returns_empty_string(self):
        self.assertEqual(sanitize_relative_path(''), '')
        self.assertEqual(sanitize_relative_path('../../..'), '')


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class UploadFileViewRelativePathTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(lambda: shutil.rmtree(self.media_root, ignore_errors=True))
        self.user = User.objects.create_user(username='upload-owner', password='x')
        self.client.force_login(self.user)

    def test_upload_with_relative_path_stores_nested_file(self):
        from chat.models import AssetEvent

        upload = SimpleUploadedFile('scene.txt', b'scene body', content_type='text/plain')
        response = self.client.post('/api/files/upload/', {
            'file': upload,
            'relative_path': 'Momotalk/mari_10105/玛丽_Momotalk_1.txt',
        })

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertIn('upload_id', payload)
        self.assertEqual(payload['relative_path'], 'Momotalk/mari_10105/玛丽_Momotalk_1.txt')

        # The file is staged under the per-user pending dir, keyed by the
        # asset/uploaded event.
        event = AssetEvent.objects.get(id=payload['upload_id'])
        self.assertIn('uploads/pending/', event.data['file_path'])
        stored = os.path.join(self.media_root, event.data['file_path'])
        self.assertTrue(os.path.exists(stored))
        with open(stored, 'rb') as stored_file:
            self.assertEqual(stored_file.read(), b'scene body')

    def test_upload_rejects_traversal_in_relative_path(self):
        from chat.models import AssetEvent

        upload = SimpleUploadedFile('evil.txt', b'x', content_type='text/plain')
        response = self.client.post('/api/files/upload/', {
            'file': upload,
            'relative_path': '../../../../etc/evil.txt',
        })

        # '..' segments are dropped in the display name; the storage path is
        # always inside the per-user pending dir, never outside the media root.
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['relative_path'], 'etc/evil.txt')
        event = AssetEvent.objects.get(id=payload['upload_id'])
        self.assertIn('uploads/pending/', event.data['file_path'])
        stored = os.path.join(self.media_root, event.data['file_path'])
        self.assertTrue(os.path.exists(stored))
        self.assertFalse(os.path.exists(os.path.join(self.media_root, 'etc')))
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.media_root), 'etc')))

    def test_upload_requires_authentication(self):
        from django.contrib.auth.models import AnonymousUser

        self.client.logout()
        upload = SimpleUploadedFile('anon.txt', b'x', content_type='text/plain')
        response = self.client.post('/api/files/upload/', {'file': upload})
        self.assertIn(response.status_code, (401, 403))


class StagedUploadFilesystemTests(TestCase):
    def _filesystem(self):
        uploads = [
            {
                'name': 'Momotalk/mari_10105/scene_1.txt',
                'relative_path': 'Momotalk/mari_10105/scene_1.txt',
                'kind': AttachmentKind.TEXT,
                'mime_type': 'text/plain',
                'content': 'scene one body',
                'file_url': 'http://testserver/media/uploads/a.txt',
            },
            {
                'name': 'Momotalk/mari_23008/scene_1.txt',
                'relative_path': 'Momotalk/mari_23008/scene_1.txt',
                'kind': AttachmentKind.TEXT,
                'mime_type': 'text/plain',
                'content': 'scene one of another version',
                'file_url': 'http://testserver/media/uploads/b.txt',
            },
            {
                'name': 'Scenario/main.txt',
                'relative_path': 'Scenario/main.txt',
                'kind': AttachmentKind.TEXT,
                'mime_type': 'text/plain',
                'content': 'main scenario',
                'file_url': 'http://testserver/media/uploads/c.txt',
            },
        ]
        return StagedUploadMemoryFilesystem(uploads)

    def test_same_basename_files_keep_distinct_paths(self):
        filesystem = self._filesystem()
        first = filesystem.read_memory_file('raw/character_setup/uploads/Momotalk/mari_10105/scene_1.txt')
        second = filesystem.read_memory_file('raw/character_setup/uploads/Momotalk/mari_23008/scene_1.txt')
        self.assertIn('scene one body', first['content'])
        self.assertIn('another version', second['content'])

    def test_list_synthesizes_directories_and_supports_browsing(self):
        filesystem = self._filesystem()

        root_listing = filesystem.list_memory_files()
        root_dirs = {entry['path'] for entry in root_listing['entries'] if entry['entry_type'] == 'directory'}
        self.assertIn('raw/character_setup/uploads/Momotalk', root_dirs)
        self.assertIn('raw/character_setup/uploads/Scenario', root_dirs)

        momotalk_listing = filesystem.list_memory_files(path_prefix='raw/character_setup/uploads/Momotalk')
        paths = [entry['path'] for entry in momotalk_listing['entries']]
        # Non-recursive listing shows only the direct children (two folders).
        self.assertEqual(
            paths,
            [
                'raw/character_setup/uploads/Momotalk/mari_10105',
                'raw/character_setup/uploads/Momotalk/mari_23008',
            ],
        )

        recursive_listing = filesystem.list_memory_files(
            path_prefix='raw/character_setup/uploads', recursive=True
        )
        recursive_paths = {entry['path'] for entry in recursive_listing['entries']}
        self.assertIn('raw/character_setup/uploads/Momotalk/mari_23008/scene_1.txt', recursive_paths)

    def test_directory_index_lists_every_file_path(self):
        index = self._filesystem().build_directory_index()
        self.assertIn('raw/character_setup/uploads/Momotalk/mari_10105/scene_1.txt', index)
        self.assertIn('raw/character_setup/uploads/Momotalk/mari_23008/scene_1.txt', index)
        self.assertIn('raw/character_setup/uploads/Scenario/main.txt', index)

    def test_read_unknown_path_reports_error(self):
        filesystem = self._filesystem()
        result = filesystem.read_memory_file('raw/character_setup/uploads/missing.txt')
        self.assertIn('error', result)


class DraftToolPromptIndexTests(TestCase):
    def _index(self):
        return (
            '- raw/character_setup/uploads/Momotalk/mari_10105/scene_1.txt (15 chars)\n'
            '- raw/character_setup/uploads/Scenario/main.txt (13 chars)'
        )

    def test_chinese_prompt_embeds_directory_index_and_binds_paths(self):
        messages = _build_character_draft_tool_prompt('zh-CN', None, 2, directory_index=self._index())
        system_prompt = messages[0]['content']
        self.assertIn('[上传文件目录索引]', system_prompt)
        self.assertIn('raw/character_setup/uploads/Momotalk/mari_10105/scene_1.txt', system_prompt)
        self.assertIn('read_memory_file', system_prompt)
        # 用户消息不再内联文件正文
        self.assertNotIn('scene one body', messages[1]['content'])

    def test_english_prompt_embeds_directory_index(self):
        messages = _build_character_draft_tool_prompt('en-US', None, 2, directory_index=self._index())
        system_prompt = messages[0]['content']
        self.assertIn('[Uploaded File Directory Index]', system_prompt)
        self.assertIn('verbatim', system_prompt)


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class ExplorerNestedUploadPathTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(lambda: shutil.rmtree(self.media_root, ignore_errors=True))

        self.user = User.objects.create_user(username='group-owner', password='password123')
        self.character = Character.objects.create(
            name='Group Character',
            description='probe',
            scenario='',
            example_dialogue='',
            created_by=self.user,
        )
        CharacterKnowledgeAsset.objects.create(
            character=self.character,
            file=SimpleUploadedFile('Momotalk/mari_10105/scene_1.txt', b'nested scene body', content_type='text/plain'),
            attachment_name='Momotalk/mari_10105/scene_1.txt',
            attachment_mime_type='text/plain',
            attachment_kind=AttachmentKind.TEXT,
            attachment_text_content='nested scene body',
            sort_order=1,
        )

    def test_explorer_preserves_folder_hierarchy_of_assets(self):
        listing = list_memory_explorer_path(self.character, path_prefix='raw/character_setup/uploads', recursive=True)
        paths = {entry['path'] for entry in listing['entries']}
        self.assertIn('raw/character_setup/uploads/Momotalk/mari_10105/scene_1.txt', paths)
        # 目录项被合成出来，模型可以逐层浏览
        non_recursive = list_memory_explorer_path(self.character, path_prefix='raw/character_setup/uploads')
        titles = {(entry['entry_type'], entry['title']) for entry in non_recursive['entries']}
        self.assertIn(('directory', 'Momotalk'), titles)

    def test_explorer_reads_nested_asset_content(self):
        doc = read_memory_explorer_file(self.character, 'raw/character_setup/uploads/Momotalk/mari_10105/scene_1.txt')
        self.assertIn('nested scene body', doc.get('content', ''))


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class SoulFileOffsetReadTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(lambda: shutil.rmtree(self.media_root, ignore_errors=True))

        self.user = User.objects.create_user(username='offset-owner', password='password123')
        self.client.force_login(self.user)
        self.character = Character.objects.create(
            name='Offset Character',
            description='probe',
            scenario='',
            example_dialogue='',
            created_by=self.user,
        )
        # 1000 chars so two windows of 600 are needed.
        self.long_body = ''.join(chr(ord('A') + i % 26) for i in range(1000))
        CharacterKnowledgeAsset.objects.create(
            character=self.character,
            file=SimpleUploadedFile('long.txt', self.long_body.encode(), content_type='text/plain'),
            attachment_name='long.txt',
            attachment_mime_type='text/plain',
            attachment_kind=AttachmentKind.TEXT,
            attachment_text_content=self.long_body,
            sort_order=1,
        )

    def test_offset_windows_concatenate_to_full_content(self):
        first = read_memory_explorer_file(self.character, 'raw/character_setup/uploads/long.txt', max_chars=600)
        self.assertEqual(first['offset'], 0)
        self.assertEqual(first['total_chars'], 1000)
        self.assertTrue(first['has_more'])
        self.assertEqual(first['next_offset'], 600)
        self.assertEqual(len(first['content']), 600)

        second = read_memory_explorer_file(
            self.character, 'raw/character_setup/uploads/long.txt', max_chars=600, offset=first['next_offset']
        )
        self.assertFalse(second['has_more'])
        self.assertIsNone(second['next_offset'])
        self.assertEqual(len(second['content']), 400)
        self.assertEqual(first['content'] + second['content'], self.long_body)

    def test_offset_beyond_end_returns_empty_window(self):
        doc = read_memory_explorer_file(
            self.character, 'raw/character_setup/uploads/long.txt', max_chars=600, offset=9999
        )
        self.assertEqual(doc['content'], '')
        self.assertFalse(doc['has_more'])

    def test_rest_soul_file_passes_offset(self):
        response = self.client.get(
            f"/api/characters/{self.character.id}/soul_file/",
            {'path': 'raw/character_setup/uploads/long.txt', 'max_chars': '200', 'offset': '800'},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        # 800 + 200 exactly reaches the end of the 1000-char file.
        self.assertEqual(payload['offset'], 800)
        self.assertEqual(payload['total_chars'], 1000)
        self.assertFalse(payload['has_more'])
        self.assertIsNone(payload['next_offset'])
        self.assertEqual(len(payload['content']), 200)

    def test_rest_soul_file_mid_file_reports_more(self):
        response = self.client.get(
            f"/api/characters/{self.character.id}/soul_file/",
            {'path': 'raw/character_setup/uploads/long.txt', 'max_chars': '200', 'offset': '500'},
        )
        payload = response.json()
        self.assertTrue(payload['has_more'])
        self.assertEqual(payload['next_offset'], 700)


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class KnowledgeAssetCollectionTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(lambda: shutil.rmtree(self.media_root, ignore_errors=True))

        self.user = User.objects.create_user(username='asset-owner', password='password123')
        self.client.force_login(self.user)
        self.character = Character.objects.create(
            name='Asset Character',
            description='probe',
            scenario='',
            example_dialogue='',
            created_by=self.user,
        )

    def test_upload_with_relative_paths_nests_into_vfs(self):
        upload = SimpleUploadedFile('scene_1.txt', b'grouped scene body', content_type='text/plain')
        response = self.client.post(
            f"/api/characters/{self.character.id}/knowledge_assets/",
            {
                'files': upload,
                'relative_paths': json.dumps(['Momotalk/mari_10105/scene_1.txt']),
                'format': 'multipart',
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, 201, response.content[:300])
        asset = self.character.knowledge_assets.get()
        self.assertEqual(asset.attachment_name, 'Momotalk/mari_10105/scene_1.txt')

        listing = list_memory_explorer_path(self.character, path_prefix='raw/character_setup/uploads', recursive=True)
        paths = {entry['path'] for entry in listing['entries'] if entry['entry_type'] == 'file'}
        self.assertIn('raw/character_setup/uploads/Momotalk/mari_10105/scene_1.txt', paths)

    def test_list_knowledge_assets_returns_collection(self):
        CharacterKnowledgeAsset.objects.create(
            character=self.character,
            file=SimpleUploadedFile('a.txt', b'A', content_type='text/plain'),
            attachment_name='Group/a.txt',
            attachment_mime_type='text/plain',
            attachment_kind=AttachmentKind.TEXT,
            attachment_text_content='A',
            sort_order=1,
        )
        response = self.client.get(f"/api/characters/{self.character.id}/knowledge_assets/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload['assets']), 1)
        self.assertEqual(payload['assets'][0]['file_name'], 'Group/a.txt')

    def test_upload_rejects_mismatched_relative_paths_length(self):
        upload = SimpleUploadedFile('solo.txt', b'solo', content_type='text/plain')
        response = self.client.post(
            f"/api/characters/{self.character.id}/knowledge_assets/",
            {
                'files': upload,
                'relative_paths': json.dumps(['one.txt', 'two.txt']),
                'format': 'multipart',
            },
            format='multipart',
        )
        self.assertEqual(response.status_code, 400)


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class DraftMutationPassesFileNamesTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(lambda: shutil.rmtree(self.media_root, ignore_errors=True))

        self.user = User.objects.create_user(username='draft-owner', password='password123')
        self.client.force_login(self.user)
        ModelConfiguration.objects.create(
            user=self.user,
            name='Draft Model',
            provider='openai_compatible',
            model_name='gpt-4.1-mini',
            api_key='user-api-key',
            base_url='https://example.com/v1',
        )
        uploads_dir = os.path.join(self.media_root, 'uploads', 'Momotalk', 'mari_10105')
        os.makedirs(uploads_dir, exist_ok=True)
        with open(os.path.join(uploads_dir, 'scene_1.txt'), 'w', encoding='utf-8') as f:
            f.write('Name: Mari\nRole: Sister.')
        self.file_url = 'http://testserver/media/uploads/Momotalk/mari_10105/scene_1.txt'

    @patch('chat.graphql.schema._generate_text')
    def test_draft_prompt_shows_directory_index_from_filenamess(self, mock_generate_text):
        mock_generate_text.return_value = json.dumps({
            'name': 'Mari',
            'description': 'A detailed background in three sentences. Second sentence. Third sentence.',
            'affiliation': 'Sisterhood',
            'tags': ['calm'],
        })

        response = self.client.post(
            '/api/graphql/',
            data=json.dumps({
                'query': '''
                    mutation GenerateDraft($fileUrls: [String!], $fileNames: [String!]) {
                      generateCharacterDraft(fileUrls: $fileUrls, fileNames: $fileNames) {
                        name
                        description
                      }
                    }
                ''',
                'variables': {
                    'fileUrls': [self.file_url],
                    'fileNames': ['Momotalk/mari_10105/scene_1.txt'],
                },
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('errors', payload)

        _runtime_config, messages = mock_generate_text.call_args[0]
        system_prompt = messages[0]['content']
        self.assertIn('[Uploaded File Directory Index]', system_prompt.replace('[上传文件目录索引]', '[Uploaded File Directory Index]'))
        self.assertTrue(
            '[上传文件目录索引]' in system_prompt or '[Uploaded File Directory Index]' in system_prompt,
            'draft prompt must embed the uploaded file directory index',
        )
        self.assertIn(
            'raw/character_setup/uploads/Momotalk/mari_10105/scene_1.txt',
            system_prompt,
        )

        filesystem = mock_generate_text.call_args.kwargs['filesystem']
        doc = filesystem.read_memory_file('raw/character_setup/uploads/Momotalk/mari_10105/scene_1.txt')
        self.assertIn('Name: Mari', doc['content'])
