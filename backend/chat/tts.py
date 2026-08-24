"""实时模式语音合成（TTS）provider 层。

架构（2026-08-24 定稿）：
- 全部 provider 都是"HTTP 客户端"——TTS 引擎以独立服务运行，Django 不背
  PyTorch 栈。当前实现：
  * genie     —— Genie-TTS FastAPI 服务器（GPT-SoVITS ONNX CPU 推理，
                 首响 ~1.1s，支持 v2/v2ProPlus 转换后的角色音色，圣亚即此路线）
  * gptsovits —— 官方 GPT-SoVITS api_v2 服务器（支持 v2/v2pro/v2proplus/v4
                 全部四种模型版本；CPU 推理慢，留给有 GPU 的场景）
  * indextts  —— IndexTTS HTTP 服务（预留，POST JSON 返回音频）
- provider 由 TTS_PROVIDER 选择；请求体里也可临时覆盖（provider 字段）。
- 延迟是一等指标：/tts 端点把上游音频流透传给前端（首字节即首音频），
  processing_ms 记录在日志；readiness 提供可读 hint。
"""

import io
import logging
import os
import time
import wave

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _wrap_pcm_as_wav(pcm: bytes, sample_rate: int = 32000, channels: int = 1, sampwidth: int = 2) -> bytes:
    """Genie /tts 返回裸 PCM（32kHz/16bit/mono），包上 WAV 头供浏览器播放。"""
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(sampwidth)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)
    return buffer.getvalue()


class TtsUnavailableError(Exception):
    """TTS provider 未配置、依赖缺失或上游服务不可达。"""


def _env(key: str, default: str = "") -> str:
    return str(getattr(settings, key, None) or os.getenv(key) or default)


def get_tts_config() -> dict:
    return {
        'provider': _env('TTS_PROVIDER', 'genie').strip().lower(),
        'genie_url': _env('TTS_GENIE_URL', 'http://127.0.0.1:8050').rstrip('/'),
        'genie_character': _env('TTS_GENIE_CHARACTER', 'seia'),
        'genie_language': _env('TTS_GENIE_LANGUAGE', 'zh'),
        'gptsovits_url': _env('TTS_GPTSOVITS_URL', 'http://127.0.0.1:9880').rstrip('/'),
        'gptsovits_text_lang': _env('TTS_GPTSOVITS_TEXT_LANG', 'zh'),
        'gptsovits_ref_audio_path': _env('TTS_GPTSOVITS_REF_AUDIO_PATH'),
        'gptsovits_prompt_text': _env('TTS_GPTSOVITS_PROMPT_TEXT'),
        'gptsovits_prompt_lang': _env('TTS_GPTSOVITS_PROMPT_LANG', 'zh'),
        'indextts_url': _env('TTS_INDEXTTS_URL').rstrip('/'),
        'indextts_text_field': _env('TTS_INDEXTTS_TEXT_FIELD', 'text'),
    }


PROVIDER_LABELS = {
    'genie': 'Genie-TTS（GPT-SoVITS ONNX，CPU 实时）',
    'gptsovits': 'GPT-SoVITS api_v2（支持 v2/v2pro/v2proplus/v4）',
    'indextts': 'IndexTTS HTTP 服务',
}


def _provider_config(config: dict, provider: str) -> dict:
    return {key[len(provider) + 1:]: value for key, value in config.items() if key.startswith(f'{provider}_')}


def provider_ready(config: dict, provider: str) -> tuple[bool, str]:
    """配置层面是否就绪（不发网络请求）。返回 (ok, hint)。"""
    if provider == 'none':
        return False, '语音回复未启用（TTS_PROVIDER=none）。'
    if provider not in PROVIDER_LABELS:
        return False, f'未知 TTS provider：{provider}'
    provider_cfg = _provider_config(config, provider)
    url = provider_cfg.get('url', '')
    if not url:
        return False, (
            f'{PROVIDER_LABELS[provider]}未配置服务地址：'
            f'请设置 TTS_{provider.upper()}_URL 并启动对应服务。'
        )
    return True, ''


class GenieTtsProvider:
    """Genie-TTS 服务器客户端。/tts 返回裸 PCM（32kHz/16bit/mono）→ 包 WAV 头。

    角色音色按需自动加载：voice 字典带 onnx_model_dir / 参考音频时，
    首次合成前自动 POST /load_character + /set_reference_audio。
    """

    name = 'genie'

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self._loaded_voices: set[str] = set()

    def ensure_voice_loaded(self, voice: dict) -> None:
        name = voice['name']
        if name in self._loaded_voices:
            return
        response = requests.post(
            f'{self.base_url}/load_character',
            json={
                'character_name': name,
                'onnx_model_dir': voice['onnx_model_dir'],
                'language': voice['language'],
            },
            timeout=300,
        )
        if response.status_code != 200:
            raise TtsUnavailableError(
                f'Genie-TTS 加载角色 {name} 失败：{response.text[:200]}'
            )
        if voice.get('ref_audio_path'):
            requests.post(
                f'{self.base_url}/set_reference_audio',
                json={
                    'character_name': name,
                    'audio_path': voice['ref_audio_path'],
                    'audio_text': voice.get('ref_audio_text', ''),
                    'language': voice.get('ref_audio_language') or voice['language'],
                },
                timeout=60,
            )
        self._loaded_voices.add(name)

    def synthesize(self, text: str, voice: dict, timeout: float = 60.0):
        self.ensure_voice_loaded(voice)
        payload = {
            'character_name': voice['name'],
            'text': text,
            'split_sentence': True,
        }
        started = time.perf_counter()
        with requests.post(
            f'{self.base_url}/tts',
            json=payload,
            stream=True,
            timeout=(5, timeout),
        ) as response:
            if response.status_code != 200:
                detail = response.text[:200]
                raise TtsUnavailableError(
                    f'Genie-TTS 返回 {response.status_code}：{detail}'
                )
            chunks = []
            first_byte_ms = None
            for chunk in response.iter_content(chunk_size=8192):
                if chunk and first_byte_ms is None:
                    first_byte_ms = int((time.perf_counter() - started) * 1000)
                chunks.append(chunk)
        audio = b''.join(chunks)
        # Genie /tts 返回裸 PCM（32kHz/16bit/mono，见官方教程播放参数），
        # 包上 WAV 头浏览器才能直接 <audio> 播放。
        if not audio.startswith(b'RIFF'):
            audio = _wrap_pcm_as_wav(audio)
        return {
            'audio': audio,
            'content_type': 'audio/wav',
            'first_byte_ms': first_byte_ms,
            'processing_ms': int((time.perf_counter() - started) * 1000),
        }

    def readiness_probe(self) -> tuple[bool, str]:
        try:
            requests.get(f'{self.base_url}/docs', timeout=3)
            return True, ''
        except Exception as exc:
            return False, f'Genie-TTS 服务不可达（{self.base_url}）：{exc.__class__.__name__}'


class GptSoVitsProvider:
    """官方 GPT-SoVITS api_v2 客户端（支持全部四种模型版本）。"""

    name = 'gptsovits'

    def __init__(self, config: dict):
        self.base_url = config['gptsovits_url']
        self.text_lang = config['gptsovits_text_lang']
        self.ref_audio_path = config['gptsovits_ref_audio_path']
        self.prompt_text = config['gptsovits_prompt_text']
        self.prompt_lang = config['gptsovits_prompt_lang']

    def synthesize(self, text: str, voice: dict | None = None, timeout: float = 120.0):
        ref_audio_path = (voice or {}).get('ref_audio_path') or self.ref_audio_path
        prompt_text = (voice or {}).get('ref_audio_text') or self.prompt_text
        if not ref_audio_path:
            raise TtsUnavailableError(
                'GPT-SoVITS 缺少参考音频配置：请设置 TTS_GPTSOVITS_REF_AUDIO_PATH '
                '与 TTS_GPTSOVITS_PROMPT_TEXT（或在该角色的语音模型配置里填写）。'
            )
        params = {
            'text': text,
            'text_lang': self.text_lang,
            'ref_audio_path': ref_audio_path,
            'prompt_text': prompt_text,
            'prompt_lang': self.prompt_lang,
            'streaming_mode': 'false',
            'text_split_method': 'cut5',
        }
        started = time.perf_counter()
        response = requests.get(f'{self.base_url}/tts', params=params, timeout=timeout)
        if response.status_code != 200 or not response.content[:4].startswith(b'RIFF'):
            detail = response.text[:200] if response.status_code != 200 else '响应不是 WAV'
            raise TtsUnavailableError(f'GPT-SoVITS 返回异常：{detail}')
        return {
            'audio': response.content,
            'content_type': 'audio/wav',
            'first_byte_ms': None,
            'processing_ms': int((time.perf_counter() - started) * 1000),
        }

    def readiness_probe(self) -> tuple[bool, str]:
        try:
            requests.get(self.base_url, timeout=3)
            return True, ''
        except Exception as exc:
            return False, f'GPT-SoVITS 服务不可达（{self.base_url}）：{exc.__class__.__name__}'


class IndexTtsProvider:
    """IndexTTS HTTP 服务客户端：POST JSON {text字段: 文本} → 音频字节。"""

    name = 'indextts'

    def __init__(self, config: dict):
        self.base_url = config['indextts_url']
        self.text_field = config['indextts_text_field']

    def synthesize(self, text: str, timeout: float = 120.0):
        started = time.perf_counter()
        response = requests.post(
            f'{self.base_url}',
            json={self.text_field: text},
            timeout=timeout,
        )
        if response.status_code != 200:
            raise TtsUnavailableError(
                f'IndexTTS 返回 {response.status_code}：{response.text[:200]}'
            )
        content_type = response.headers.get('Content-Type', 'audio/wav')
        return {
            'audio': response.content,
            'content_type': content_type if content_type.startswith('audio') else 'audio/wav',
            'first_byte_ms': None,
            'processing_ms': int((time.perf_counter() - started) * 1000),
        }

    def readiness_probe(self) -> tuple[bool, str]:
        try:
            requests.get(self.base_url, timeout=3)
            return True, ''
        except Exception as exc:
            return False, f'IndexTTS 服务不可达（{self.base_url}）：{exc.__class__.__name__}'


PROVIDER_CLASSES = {
    'genie': GenieTtsProvider,
    'gptsovits': GptSoVitsProvider,
    'indextts': IndexTtsProvider,
}

_provider_instances: dict = {}


def build_provider(provider: str):
    config = get_tts_config()
    if provider == 'genie':
        return GenieTtsProvider(config['genie_url'])
    if provider == 'gptsovits':
        return GptSoVitsProvider(config)
    if provider == 'indextts':
        return IndexTtsProvider(config)
    raise TtsUnavailableError(f'未知 TTS provider：{provider}')


# 角色音色的版本→引擎兼容性：genie 只能加载 v2 / v2ProPlus 转换的模型，
# v2pro（v2pr）与 v4 必须走官方 api_v2 通道。
GENIE_SUPPORTED_MODEL_VERSIONS = {'', 'v2', 'v2proplus'}


def build_genie_voice(config: dict, character_tts_config: dict | None) -> dict:
    """合并全局默认与角色级 tts_config，得到一次合成所需的音色描述。"""
    cfg = character_tts_config or {}
    language = cfg.get('language') or config['genie_language']
    return {
        'name': cfg.get('voice_name') or config['genie_character'],
        'onnx_model_dir': cfg.get('onnx_model_dir') or _env('TTS_GENIE_ONNX_MODEL_DIR'),
        'language': language,
        'ref_audio_path': cfg.get('ref_audio_path') or _env('TTS_GENIE_REF_AUDIO_PATH'),
        'ref_audio_text': cfg.get('ref_audio_text') or _env('TTS_GENIE_REF_AUDIO_TEXT'),
        'ref_audio_language': cfg.get('ref_audio_language') or _env('TTS_GENIE_REF_AUDIO_LANGUAGE') or language,
    }


def resolve_provider_and_voice(
    provider: str | None = None,
    character_tts_config: dict | None = None,
) -> tuple[str, dict | None]:
    """确定本次合成使用的 provider 与音色覆盖（含版本兼容校验）。"""
    config = get_tts_config()
    cfg = character_tts_config or {}
    selected = (cfg.get('provider') or provider or config['provider']).strip().lower()
    model_version = (cfg.get('model_version') or '').strip().lower()

    voice = None
    if selected == 'genie':
        if model_version and model_version not in GENIE_SUPPORTED_MODEL_VERSIONS:
            raise TtsUnavailableError(
                f'Genie-TTS 不支持 {model_version} 模型版本（仅 v2/v2proplus）；'
                f'该角色的音色请改用 gptsovits 通道。'
            )
        voice = build_genie_voice(config, cfg)
    elif cfg.get('ref_audio_path') or cfg.get('ref_audio_text'):
        # 非 genie 引擎：仅透传角色级参考音频覆盖
        voice = {key: cfg[key] for key in ('ref_audio_path', 'ref_audio_text') if cfg.get(key)}
    return selected, voice


_provider_instances: dict = {}


def get_tts_provider_instance(provider: str):
    if provider not in _provider_instances:
        _provider_instances[provider] = build_provider(provider)
    return _provider_instances[provider]


def get_tts_provider(provider: str | None = None):
    """按配置（或请求覆盖）构建 provider；未就绪时抛 TtsUnavailableError。"""
    config = get_tts_config()
    selected = (provider or config['provider']).strip().lower()
    ok, hint = provider_ready(config, selected)
    if not ok:
        raise TtsUnavailableError(hint)
    instance = get_tts_provider_instance(selected)
    reachable, reach_hint = instance.readiness_probe()
    if not reachable:
        raise TtsUnavailableError(reach_hint)
    return instance


def readiness() -> dict:
    """前端"语音回复"开关的提示数据源。"""
    config = get_tts_config()
    provider = config['provider']
    configured_ok, hint = provider_ready(config, provider)
    reachable = False
    if configured_ok:
        instance = build_provider(provider)
        reachable, reach_hint = instance.readiness_probe()
        hint = hint or reach_hint
    if configured_ok and reachable:
        hint = ''
    return {
        'provider': provider,
        'configured': configured_ok,
        'reachable': reachable,
        'available': configured_ok and reachable,
        'label': PROVIDER_LABELS.get(provider, provider),
        'hint': hint,
        'providers': [
            {'key': key, 'label': label} for key, label in PROVIDER_LABELS.items()
        ],
    }


def synthesize_speech(
    text: str,
    provider: str | None = None,
    character_tts_config: dict | None = None,
) -> dict:
    """合成一段文本。角色级 tts_config 优先于全局配置（语音模型的唯一配置入口在角色界面）。"""
    selected, voice = resolve_provider_and_voice(provider, character_tts_config)
    instance = get_tts_provider_instance(selected)
    ok, hint = instance.readiness_probe()
    if not ok:
        raise TtsUnavailableError(hint)
    result = instance.synthesize(text, voice) if voice is not None else instance.synthesize(text)
    result['provider'] = selected
    logger.info(
        "TTS done via %s in %dms (first_byte=%s, chars=%d)",
        selected, result['processing_ms'], result.get('first_byte_ms'), len(text),
    )
    return result
