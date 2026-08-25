"""音色库（TtsVoiceModel）与用户级 TTS 引擎设置端点测试。

覆盖：设置页 CRUD 与用户隔离、角色 tts_config 经 voice_model_id 引用音色
库的合成解析优先级、v2pr→v2pro 别名归一化、上传转换任务投递与进度轮询
（Genie 侧全部 mock，不进真实转换路径）。
"""

import json
import shutil
import tempfile
from pathlib import PurePath
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from chat.models import Character, TtsServiceSettings, TtsVoiceModel


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class TtsServiceSettingsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tts_settings_user', password='pw')
        self.client.force_login(self.user)

    def test_me_returns_defaults_when_unset(self):
        response = self.client.get('/api/tts-settings/me/')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['default_provider'], '')
        self.assertEqual(body['genie_url'], '')

    def test_patch_persists_and_normalizes_url(self):
        response = self.client.patch(
            '/api/tts-settings/me/',
            data=json.dumps({'default_provider': 'GENIE', 'genie_url': 'http://127.0.0.1:8050/'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        row = TtsServiceSettings.get_for_user(self.user)
        self.assertEqual(row.default_provider, 'genie')
        self.assertEqual(row.genie_url, 'http://127.0.0.1:8050')

    def test_user_scoped_isolation(self):
        other = User.objects.create_user(username='tts_other_user', password='pw')
        TtsServiceSettings.objects.create(user=other, genie_url='http://10.0.0.9:8050')
        body = self.client.get('/api/tts-settings/me/').json()
        self.assertEqual(body['genie_url'], '')

    def test_overrides_take_precedence_over_env_config(self):
        from chat import tts as chat_tts

        TtsServiceSettings.objects.create(
            user=self.user,
            default_provider='gptsovits',
            genie_url='http://127.0.0.9:9999',
        )
        overrides = chat_tts.service_overrides_for_user(self.user)
        config = chat_tts.get_tts_config(overrides)
        self.assertEqual(config['provider'], 'gptsovits')
        self.assertEqual(config['genie_url'], 'http://127.0.0.9:9999')
        # 未设置的字段回落环境变量默认值。
        self.assertTrue(config['indextts_text_field'])

        self.assertIsNone(chat_tts.service_overrides_for_user(None))


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class TtsVoiceModelCrudTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='voice_user', password='pw')
        self.client.force_login(self.user)

    def test_create_list_delete_scoped_to_owner(self):
        create = self.client.post(
            '/api/tts-voice-models/',
            data=json.dumps({
                'name': 'seia', 'engine': 'genie', 'model_version': 'v2proplus',
                'language': 'zh', 'onnx_model_dir': 'D:/models/seia_onnx',
            }),
            content_type='application/json',
        )
        self.assertEqual(create.status_code, 201, create.content[:300])
        voice_id = create.json()['id']

        other = User.objects.create_user(username='voice_other', password='pw')
        self.client.force_login(other)
        self.assertEqual(self.client.get('/api/tts-voice-models/').json(), [])
        self.assertIn(
            self.client.get(f'/api/tts-voice-models/{voice_id}/').status_code,
            (404, 403),
        )

        self.client.force_login(self.user)
        delete = self.client.delete(f'/api/tts-voice-models/{voice_id}/')
        self.assertIn(delete.status_code, (200, 204))

    def test_model_version_alias_normalized(self):
        create = self.client.post(
            '/api/tts-voice-models/',
            data=json.dumps({'name': 'ryuko', 'engine': 'gptsovits', 'model_version': 'V2PR'}),
            content_type='application/json',
        )
        self.assertEqual(create.status_code, 201)
        self.assertEqual(create.json()['model_version'], 'v2pro')

    def test_unknown_engine_rejected(self):
        create = self.client.post(
            '/api/tts-voice-models/',
            data=json.dumps({'name': 'x', 'engine': 'nope'}),
            content_type='application/json',
        )
        self.assertEqual(create.status_code, 400)


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class VoiceLibrarySynthesisResolutionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='resolve_user', password='pw')
        self.character = Character.objects.create(
            name='Resolver', description='', scenario='', example_dialogue='',
            created_by=self.user,
        )
        self.voice = TtsVoiceModel.objects.create(
            user=self.user,
            name='seia-lib',
            engine='genie',
            model_version='v2proplus',
            language='zh',
            onnx_model_dir='D:/models/seia_lib_onnx',
        )

    def _resolve(self):
        from chat import tts as chat_tts

        return chat_tts.resolve_provider_and_voice(None, self.character.tts_config, user=self.user)

    def test_character_referencing_voice_library_resolves_fields(self):
        self.character.tts_config = {'voice_model_id': str(self.voice.pk)}
        self.character.save(update_fields=['tts_config'])
        provider, voice = self._resolve()
        self.assertEqual(provider, 'genie')
        self.assertEqual(voice['onnx_model_dir'], 'D:/models/seia_lib_onnx')
        self.assertEqual(voice['name'], 'seia-lib')
        self.assertEqual(voice['language'], 'zh')

    def test_character_explicit_field_overrides_library(self):
        self.character.tts_config = {
            'voice_model_id': str(self.voice.pk),
            'ref_audio_path': 'F:/voice/seia/main.wav',
            'ref_audio_text': '参考台词',
        }
        self.character.save(update_fields=['tts_config'])
        _, voice = self._resolve()
        self.assertEqual(voice['ref_audio_path'], 'F:/voice/seia/main.wav')
        self.assertEqual(voice['ref_audio_text'], '参考台词')

    def test_missing_voice_id_reports_actionable_error(self):
        from chat import tts as chat_tts

        self.character.tts_config = {}
        with self.assertRaises(chat_tts.TtsUnavailableError):
            chat_tts.build_genie_voice({}, user=self.user)

    def test_legacy_direct_fields_still_work_without_library(self):
        from chat import tts as chat_tts

        provider, voice = chat_tts.resolve_provider_and_voice(
            None,
            {'provider': 'genie', 'model_version': 'v2proplus',
             'onnx_model_dir': 'D:/m/old_onnx'},
            user=self.user,
        )
        self.assertEqual(provider, 'genie')
        self.assertEqual(voice['onnx_model_dir'], 'D:/m/old_onnx')
        # 旧写法 v2pr 归一化为 v2pro 后不被 genie 支持，必须拒绝而不是静默加载。
        with self.assertRaises(chat_tts.TtsUnavailableError) as ctx:
            chat_tts.resolve_provider_and_voice(
                None,
                {'provider': 'genie', 'model_version': 'v2pr',
                 'onnx_model_dir': 'D:/m/x_onnx'},
                user=self.user,
            )
        self.assertIn('gptsovits', str(ctx.exception))

    def test_relative_ref_audio_path_resolves_against_media_root(self):
        from django.conf import settings as dj_settings
        from chat import tts as chat_tts

        fields = chat_tts.merged_voice_fields(
            {'ref_audio_path': 'tts/ref_audio/a.wav'}, user=None,
        )
        expected_tail = PurePath('tts/ref_audio/a.wav')
        self.assertTrue(fields['ref_audio_path'].replace('\\', '/').endswith(expected_tail.as_posix()))
        self.assertTrue(fields['ref_audio_path'].startswith(str(dj_settings.MEDIA_ROOT)))


@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class UploadConvertFlowTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(lambda: shutil.rmtree(self.media_root, ignore_errors=True))

        self.user = User.objects.create_user(username='convert_user', password='pw')
        self.client.force_login(self.user)

    def _upload(self, genie_post):
        return self.client.post('/api/tts-voice-models/upload_convert/', {
            'ckpt': SimpleUploadedFile('seia-e15.ckpt', b'CKPT', content_type='application/octet-stream'),
            'pth': SimpleUploadedFile('seia_e8_s240.pth', b'PTH', content_type='application/octet-stream'),
            'name': 'Seia ONNX',
            'language': 'zh',
            'model_version': 'v2proplus',
            'ref_audio': SimpleUploadedFile('ref.wav', b'WAV', content_type='audio/wav'),
            'ref_audio_text': '参考台词',
        })

    def test_upload_posts_job_and_marks_converting(self):
        with patch('chat.views.requests.post') as mock_post:
            mock_post.return_value.json.return_value = {'job_id': 'job-1'}
            mock_post.return_value.raise_for_status = lambda: None
            response = self._upload(mock_post)

        self.assertEqual(response.status_code, 201, response.content[:300])
        body = response.json()
        voice = TtsVoiceModel.objects.get(id=body['id'])
        self.assertEqual(voice.conversion_status, TtsVoiceModel.ConversionStatus.CONVERTING)
        self.assertEqual(voice.conversion_job_id, 'job-1')
        self.assertEqual(voice.engine, 'genie')
        self.assertEqual(voice.model_version, 'v2proplus')
        self.assertTrue(voice.source_ckpt_path.endswith('seia-e15.ckpt'))
        self.assertTrue(voice.ref_audio_path.endswith('ref.wav'))

        job_payload = mock_post.call_args.kwargs['json']
        self.assertIn('torch_ckpt_path', job_payload)
        self.assertTrue(job_payload['output_dir'].endswith('seia-onnx_onnx'))

    def test_conversion_status_poll_writes_terminal_state(self):
        with patch('chat.views.requests.post') as mock_post:
            mock_post.return_value.json.return_value = {'job_id': 'job-2'}
            mock_post.return_value.raise_for_status = lambda: None
            voice_id = self._upload(mock_post).json()['id']

        with patch('chat.views.requests.get') as mock_get:
            mock_get.return_value.raise_for_status = lambda: None
            mock_get.return_value.json.return_value = {'status': 'done'}
            response = self.client.get(f'/api/tts-voice-models/{voice_id}/conversion_status/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['conversion_status'], 'ready')
        voice = TtsVoiceModel.objects.get(id=voice_id)
        self.assertEqual(voice.conversion_error, '')

    def test_conversion_error_payload_surfaces_to_record(self):
        with patch('chat.views.requests.post') as mock_post:
            mock_post.return_value.json.return_value = {'job_id': 'job-3'}
            mock_post.return_value.raise_for_status = lambda: None
            response = self.client.post('/api/tts-voice-models/upload_convert/', {
                'ckpt': SimpleUploadedFile('a.ckpt', b'A'),
                'pth': SimpleUploadedFile('b.pth', b'B'),
                'name': 'fail-case',
            })
        failed_id = response.json()['id']

        with patch('chat.views.requests.get') as mock_get:
            mock_get.return_value.raise_for_status = lambda: None
            mock_get.return_value.json.return_value = {'status': 'error', 'error': 'boom'}
            response = self.client.get(f'/api/tts-voice-models/{failed_id}/conversion_status/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['conversion_status'], 'failed')
        self.assertEqual(response.json()['conversion_error'], 'boom')

    def test_unreachable_genie_marks_failed_but_returns_record(self):
        import requests as requests_lib

        with patch('chat.views.requests.post', side_effect=requests_lib.exceptions.ConnectionError('down')):
            response = self._upload(None)
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['conversion_status'], 'failed')
        self.assertIn('无法连接 Genie-TTS 转换服务', body['conversion_error'])

    def test_missing_weights_rejected(self):
        response = self.client.post('/api/tts-voice-models/upload_convert/', {
            'pth': SimpleUploadedFile('b.pth', b'B'),
        })
        self.assertEqual(response.status_code, 400)
