"""实时模式端点测试：ASR 转写、就绪提示、TTS 合成与角色级语音配置。

全部走 mock provider——真实 faster-whisper / Genie-TTS 不进测试路径；
延迟字段的形状在这里锁定，供前端角标与 docs/latency 记录消费。
"""

from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from chat.models import Character


class AsrEndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='asr_user', password='pw')
        self.client.force_login(self.user)
        self.url = '/api/chat/asr/'

    def _post_audio(self, content=b'fake-bytes', name='clip.webm', mime='audio/webm'):
        return self.client.post(self.url, {'audio': SimpleUploadedFile(name, content, content_type=mime)})

    def test_requires_authentication(self):
        # 开发环境的自动登录中间件会兜底认证，这里显式关掉再验证权限。
        self.client.logout()
        with override_settings(DEV_AUTO_LOGIN_ENABLED=False):
            response = self._post_audio()
        self.assertIn(response.status_code, (401, 403))

    def test_missing_audio_returns_400(self):
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, 400)

    def test_unsupported_mime_returns_400(self):
        response = self._post_audio(mime='audio/flac', name='clip.flac')
        self.assertEqual(response.status_code, 400)
        self.assertIn('unsupported audio type', response.json()['error'])

    def test_oversized_audio_returns_400(self):
        with patch('chat.asr.MAX_ASR_AUDIO_BYTES', 8):
            response = self._post_audio(content=b'x' * 16)
        self.assertEqual(response.status_code, 400)

    def test_unavailable_returns_503_with_hint(self):
        with patch('chat.asr.asr_available', return_value=False):
            response = self._post_audio()
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertTrue(body['error'])
        self.assertIn('available', body['readiness'])

    def test_success_returns_text_and_latency_fields(self):
        fake = {
            'text': '你好呀',
            'language': 'zh',
            'processing_ms': 912,
            'model_load_ms': 0,
        }
        with patch('chat.asr.asr_available', return_value=True), \
                patch('chat.asr.transcribe_bytes', return_value=fake) as mock_transcribe:
            response = self._post_audio()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['text'], '你好呀')
        self.assertEqual(body['language'], 'zh')
        # 延迟字段是契约：缺失会直接破坏前端实时角标与延迟记录表。
        self.assertIn('processing_ms', body)
        self.assertIn('model_load_ms', body)
        self.assertEqual(mock_transcribe.call_args.kwargs['language'], None)

    def test_language_passthrough(self):
        fake = {'text': 'hi', 'language': 'en', 'processing_ms': 100, 'model_load_ms': 0}
        with patch('chat.asr.asr_available', return_value=True), \
                patch('chat.asr.transcribe_bytes', return_value=fake) as mock_transcribe:
            self.client.post(self.url, {'audio': SimpleUploadedFile(
                'clip.wav', b'x', content_type='audio/wav'), 'language': 'en'})
        self.assertEqual(mock_transcribe.call_args.kwargs['language'], 'en')


class AsrReadinessTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='ready_user', password='pw')
        self.client.force_login(self.user)

    def test_readiness_shape(self):
        response = self.client.get('/api/chat/asr_readiness/')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        for key in ('available', 'installed', 'loaded', 'provider', 'model', 'device', 'compute_type', 'hint'):
            self.assertIn(key, body)


class TtsReservedEndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tts_user', password='pw')
        self.client.force_login(self.user)

    def _post(self, payload):
        return self.client.post('/api/chat/tts/', payload, content_type='application/json')

    def test_missing_text_returns_400(self):
        response = self._post({})
        self.assertEqual(response.status_code, 400)

    def test_oversized_text_returns_400(self):
        response = self._post({'text': '啊' * 1001})
        self.assertEqual(response.status_code, 400)

    def test_provider_none_returns_501(self):
        with override_settings(TTS_PROVIDER='none'):
            response = self._post({'text': '你好'})
        self.assertEqual(response.status_code, 501)
        body = response.json()
        self.assertTrue(body['error'])
        self.assertIn('available', body['readiness'])

    def test_unreachable_service_returns_503_with_hint(self):
        with override_settings(TTS_GENIE_URL='http://127.0.0.1:1'):
            response = self._post({'text': '你好'})
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertIn('不可达', body['error'])
        self.assertFalse(body['readiness']['reachable'])

    def test_success_returns_wav_and_latency_headers(self):
        fake = {
            'audio': b'RIFF....WAVEfmt ',
            'content_type': 'audio/wav',
            'provider': 'genie',
            'processing_ms': 830,
            'first_byte_ms': 410,
        }
        with patch('chat.tts.synthesize_speech', return_value=fake) as mock_synth:
            response = self._post({'text': '今晚的月色真美。'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'audio/wav')
        self.assertEqual(response['X-TTS-Provider'], 'genie')
        self.assertEqual(response['X-TTS-Processing-Ms'], '830')
        self.assertEqual(mock_synth.call_args.kwargs['provider'], None)

    def test_provider_override_passthrough(self):
        fake = {'audio': b'RIFF', 'content_type': 'audio/wav',
                'provider': 'gptsovits', 'processing_ms': 10, 'first_byte_ms': None}
        with patch('chat.tts.synthesize_speech', return_value=fake) as mock_synth:
            response = self._post({'text': '你好', 'provider': 'gptsovits'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_synth.call_args.kwargs['provider'], 'gptsovits')

    @override_settings(DEV_AUTO_LOGIN_ENABLED=False)
    def test_character_genie_version_mismatch_returns_503(self):
        # 角色界面选了 v4 + genie：明确报版本不兼容，而不是静默用错引擎
        # （关掉 dev 自动登录：否则中间件会把 request.user 覆盖成 demo_user，
        #   角色归属校验失败静默回退全局音色）
        character = Character.objects.create(
            created_by=self.user, name='V4角色',
            tts_config={'provider': 'genie', 'model_version': 'v4', 'voice_name': 'v4voice'},
        )
        mock_instance = MagicMock()
        mock_instance.readiness_probe.return_value = (True, '')
        with patch('chat.tts.get_tts_provider_instance', return_value=mock_instance):
            response = self._post({'text': '你好', 'character_id': character.id})
        self.assertEqual(response.status_code, 503)
        self.assertIn('v4', response.json()['error'])

    @override_settings(DEV_AUTO_LOGIN_ENABLED=False)
    def test_character_voice_config_passed_to_genie(self):
        character = Character.objects.create(
            created_by=self.user, name='圣亚',
            tts_config={
                'voice_name': 'seia',
                'onnx_model_dir': 'D:/models/seia_onnx',
                'model_version': 'v2proplus',
                'language': 'zh',
            },
        )
        mock_instance = MagicMock()
        mock_instance.readiness_probe.return_value = (True, '')
        mock_instance.synthesize.return_value = {
            'audio': b'RIFF....', 'content_type': 'audio/wav',
            'provider': 'genie', 'processing_ms': 100, 'first_byte_ms': 50,
        }
        with patch('chat.tts.get_tts_provider_instance', return_value=mock_instance):
            response = self._post({'text': '你好', 'character_id': character.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['X-TTS-Provider'], 'genie')
        voice = mock_instance.synthesize.call_args.args[1]
        self.assertEqual(voice['name'], 'seia')
        self.assertEqual(voice['onnx_model_dir'], 'D:/models/seia_onnx')

    def test_invalid_character_id_falls_back_to_global(self):
        fake = {'audio': b'RIFF', 'content_type': 'audio/wav',
                'provider': 'genie', 'processing_ms': 10, 'first_byte_ms': None}
        with patch('chat.tts.synthesize_speech', return_value=fake) as mock_synth:
            response = self._post({'text': '你好', 'character_id': '999999'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_synth.call_args.kwargs['character_tts_config'], None)

    def test_readiness_shape(self):
        response = self.client.get('/api/chat/tts_readiness/')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        for key in ('provider', 'configured', 'reachable', 'available', 'label', 'hint', 'providers'):
            self.assertIn(key, body)
