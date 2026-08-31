"""音频输出（TtsAudioOutput）浏览页的端点与落盘行为测试。

覆盖：/chat/tts 合成成功后自动登记一条音频输出；浏览列表按用户隔离、
支持角色过滤；删除时清掉磁盘文件；合成失败不落盘。
"""

import json
import shutil
import tempfile

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from chat.models import Character, TtsAudioOutput


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class TtsAudioOutputPersistenceTests(TestCase):
    """/chat/tts 成功合成 → 落盘一条 TtsAudioOutput（浏览页数据源）。"""

    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(lambda: shutil.rmtree(self.media_root, ignore_errors=True))

        self.user = User.objects.create_user(username='audio_out_user', password='pw')
        self.client.force_login(self.user)
        self.character = Character.objects.create(
            created_by=self.user,
            name='圣亚',
            description='测试角色',
        )

    def _synth_result(self, provider='genie', emotion='默认'):
        return {
            'audio': b'RIFF....WAVEfmt ',
            'content_type': 'audio/wav',
            'provider': provider,
            'processing_ms': 830,
            'first_byte_ms': 410,
        }

    def _post_tts(self, payload):
        return self.client.post('/api/chat/tts/', payload, content_type='application/json')

    def test_success_persists_audio_output(self):
        from unittest.mock import patch

        with patch('chat.tts.synthesize_speech', return_value=self._synth_result()) as mock_synth:
            response = self._post_tts({
                'text': '今晚的月色真美。',
                'character_id': str(self.character.id),
                'emotion': '默认',
            })

        self.assertEqual(response.status_code, 200)
        outputs = TtsAudioOutput.objects.filter(user=self.user)
        self.assertEqual(outputs.count(), 1)
        output = outputs.get()
        self.assertEqual(output.character_id, self.character.id)
        self.assertEqual(output.text, '今晚的月色真美。')
        self.assertEqual(output.emotion, '默认')
        self.assertEqual(output.provider, 'genie')
        self.assertEqual(output.processing_ms, 830)
        self.assertTrue(output.audio.name.startswith('tts_outputs/'))
        self.assertTrue(output.audio.size > 0)
        mock_synth.assert_called_once()

    def test_success_without_character_keeps_null(self):
        from unittest.mock import patch

        with patch('chat.tts.synthesize_speech', return_value=self._synth_result()):
            response = self._post_tts({'text': '你好'})

        self.assertEqual(response.status_code, 200)
        output = TtsAudioOutput.objects.get(user=self.user)
        self.assertIsNone(output.character_id)

    def test_failure_does_not_persist(self):
        # provider=none（无效 provider）→ 合成失败（501/503 取决于全局配置），
        # 失败路径不应留下任何记录
        response = self._post_tts({'text': '你好', 'provider': 'none'})
        self.assertIn(response.status_code, (501, 503))
        self.assertEqual(TtsAudioOutput.objects.filter(user=self.user).count(), 0)

    def test_missing_text_does_not_persist(self):
        response = self._post_tts({'text': ''})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(TtsAudioOutput.objects.filter(user=self.user).count(), 0)


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class TtsAudioOutputBrowseApiTests(TestCase):
    """浏览页 API：列表隔离、角色过滤、删除清理文件。"""

    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(lambda: shutil.rmtree(self.media_root, ignore_errors=True))

        self.user = User.objects.create_user(username='audio_browse_user', password='pw')
        self.other = User.objects.create_user(username='audio_other_user', password='pw')
        self.client.force_login(self.user)
        self.character = Character.objects.create(
            created_by=self.user,
            name='圣亚',
            description='测试角色',
        )

    def _create_output(self, user, character=None, text='台词', emotion='默认', provider='genie'):
        from django.core.files.base import ContentFile

        output = TtsAudioOutput(
            user=user,
            character=character,
            text=text,
            emotion=emotion,
            provider=provider,
            processing_ms=100,
            first_byte_ms=50,
        )
        output.audio.save('test.wav', ContentFile(b'RIFF....WAVEfmt '), save=True)
        return output

    def test_list_requires_authentication(self):
        self.client.logout()
        response = self.client.get('/api/tts-audio-outputs/')
        self.assertEqual(response.status_code, 401)

    def test_list_is_user_scoped(self):
        self._create_output(self.user, self.character, text='我的台词')
        self._create_output(self.other, text='别人的台词')
        response = self.client.get('/api/tts-audio-outputs/')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['text'], '我的台词')
        self.assertEqual(body[0]['character_id'], self.character.id)
        self.assertEqual(body[0]['character_name'], '圣亚')
        self.assertEqual(body[0]['provider'], 'genie')
        self.assertTrue(body[0]['audio_url'])

    def test_filter_by_character(self):
        other_char = Character.objects.create(created_by=self.user, name='另一个', description='x')
        self._create_output(self.user, self.character, text='A')
        self._create_output(self.user, other_char, text='B')
        response = self.client.get(f'/api/tts-audio-outputs/?character_id={self.character.id}')
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['text'], 'A')

    def test_delete_removes_row_and_file(self):
        output = self._create_output(self.user, self.character, text='待删')
        file_name = output.audio.name

        response = self.client.delete(f'/api/tts-audio-outputs/{output.id}/')
        self.assertEqual(response.status_code, 204)
        self.assertFalse(TtsAudioOutput.objects.filter(id=output.id).exists())
        from django.core.files.storage import default_storage
        self.assertFalse(default_storage.exists(file_name))

    def test_cannot_delete_other_users_output(self):
        output = self._create_output(self.other, text='别人的')
        response = self.client.delete(f'/api/tts-audio-outputs/{output.id}/')
        self.assertEqual(response.status_code, 404)
        self.assertTrue(TtsAudioOutput.objects.filter(id=output.id).exists())

    def test_serializer_exposes_latency_fields(self):
        output = self._create_output(self.user, self.character, text='含延迟')
        output.processing_ms = 830
        output.first_byte_ms = 410
        output.save(update_fields=['processing_ms', 'first_byte_ms'])
        response = self.client.get('/api/tts-audio-outputs/')
        body = response.json()[0]
        self.assertEqual(body['processing_ms'], 830)
        self.assertEqual(body['first_byte_ms'], 410)
