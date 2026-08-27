"""实时模式语音合成（TTS）provider 层。

架构（2026-08-24 定稿）：
- 全部 provider 都是"HTTP 客户端"——TTS 引擎以独立服务运行，Django 不背
  PyTorch 栈。当前实现：
  * genie     —— Genie-TTS FastAPI 服务器（GPT-SoVITS ONNX 推理，服务端
                 默认 CPU、可 --device cuda 走 GPU，CPU 首响 ~1.1s，
                 支持 v2/v2ProPlus 转换后的角色音色，圣亚即此路线）
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
from pathlib import PurePath

import requests
from django.conf import settings

from .models import TtsServiceSettings, TtsVoiceModel

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


def get_tts_config(overrides: dict | None = None) -> dict:
    """环境变量为底的引擎配置；overrides（来自用户级 TtsServiceSettings）
    里的非空字段覆盖同名项。"""
    config = {
        'provider': _env('TTS_PROVIDER', 'genie').strip().lower(),
        'genie_url': _env('TTS_GENIE_URL', 'http://127.0.0.1:8050').rstrip('/'),
        'gptsovits_url': _env('TTS_GPTSOVITS_URL', 'http://127.0.0.1:9880').rstrip('/'),
        'gptsovits_text_lang': _env('TTS_GPTSOVITS_TEXT_LANG', 'zh'),
        'gptsovits_ref_audio_path': _env('TTS_GPTSOVITS_REF_AUDIO_PATH'),
        'gptsovits_prompt_text': _env('TTS_GPTSOVITS_PROMPT_TEXT'),
        'gptsovits_prompt_lang': _env('TTS_GPTSOVITS_PROMPT_LANG', 'zh'),
        'indextts_url': _env('TTS_INDEXTTS_URL').rstrip('/'),
        'indextts_text_field': _env('TTS_INDEXTTS_TEXT_FIELD', 'text'),
    }
    for key, value in (overrides or {}).items():
        if key in config and str(value or '').strip():
            config[key] = str(value).strip().rstrip('/') if key.endswith('_url') else str(value).strip().lower()
    return config


PROVIDER_LABELS = {
    'genie': 'Genie-TTS（GPT-SoVITS ONNX 实时，CPU/GPU 取决于服务端启动参数）',
    'gptsovits': 'GPT-SoVITS api_v2（支持 v2/v2pro/v2proplus/v4，建议 GPU 部署）',
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

    角色音色按需自动加载；情感组参考音频在每次合成时按需切换。
    """

    name = 'genie'

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self._loaded_voices: set[str] = set()
        # 跟踪每个音色当前在 genie 服务端设置的参考音频，避免重复请求。
        self._ref_audios: dict[str, tuple[str, str, str]] = {}

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
        self._loaded_voices.add(name)

    def _ensure_ref_audio(self, voice: dict, emotion: str | None) -> None:
        """确保 genie 服务的参考音频为本请求所需（情感或默认）。
        仅在内容变化时发请求。
        """
        name = voice['name']
        ref = pick_emotion_ref(voice, emotion)
        if ref is None and voice.get('ref_audio_path'):
            ref = {
                'ref_audio_path': voice['ref_audio_path'],
                'ref_audio_text': voice.get('ref_audio_text', ''),
                'ref_audio_language': (voice.get('ref_audio_language')
                                       or voice['language']),
            }
        if ref is None:
            # 既无情感参考又无默认参考音频——genie 服务端仍有上次的值，
            # 但 /tts 会报 404。让上游返回错误，调用方可见。
            return
        key = (ref['ref_audio_path'], ref['ref_audio_text'], ref['ref_audio_language'])
        if self._ref_audios.get(name) == key:
            return
        response = requests.post(
            f'{self.base_url}/set_reference_audio',
            json={
                'character_name': name,
                'audio_path': ref['ref_audio_path'],
                'audio_text': ref['ref_audio_text'],
                'language': ref['ref_audio_language'],
            },
            timeout=60,
        )
        if response.status_code != 200:
            raise TtsUnavailableError(
                f'Genie-TTS 设置参考音频（情感：{emotion or "默认"}）失败：'
                f'{response.text[:200]}'
            )
        self._ref_audios[name] = key

    def synthesize(self, text: str, voice: dict, timeout: float = 60.0,
                   emotion: str | None = None):
        self.ensure_voice_loaded(voice)
        self._ensure_ref_audio(voice, emotion)
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

    def synthesize(self, text: str, voice: dict | None = None, timeout: float = 120.0,
                   emotion: str | None = None):
        ref = pick_emotion_ref(voice, emotion) if voice else None
        ref_audio_path = (ref or {}).get('ref_audio_path') or (voice or {}).get('ref_audio_path') or self.ref_audio_path
        prompt_text = (ref or {}).get('ref_audio_text') or (voice or {}).get('ref_audio_text') or self.prompt_text
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


def build_provider(provider: str, config: dict | None = None):
    config = config or get_tts_config()
    if provider == 'genie':
        return GenieTtsProvider(config['genie_url'])
    if provider == 'gptsovits':
        return GptSoVitsProvider(config)
    if provider == 'indextts':
        return IndexTtsProvider(config)
    raise TtsUnavailableError(f'未知 TTS provider：{provider}')

# 角色音色的版本→引擎兼容性：genie 只能加载 v2 / v2ProPlus 转换的模型，
# v2pro 与 v4 必须走官方 api_v2 通道。genie-tts 升级支持更多版本时只需改这里。
GENIE_SUPPORTED_MODEL_VERSIONS = {'', 'v2', 'v2proplus'}

# 存量数据里 model_version 曾写作 v2pr，读取时归一化为 v2pro。
TTS_MODEL_VERSION_ALIASES = {'v2pr': 'v2pro'}

# 角色未在语音设置里选择语言时的兜底（中文底模最常见）。
# 仅此一项保留默认值；模型目录、参考音频一律只认音色库/角色自己的配置。
DEFAULT_GENIE_LANGUAGE = 'zh'


def _normalize_model_version(version: str) -> str:
    version = (version or '').strip().lower()
    return TTS_MODEL_VERSION_ALIASES.get(version, version)


def _resolve_server_path(path: str) -> str:
    """把 MEDIA_ROOT 相对路径解析为服务器绝对路径；绝对路径原样返回。"""
    path = (path or '').strip()
    if not path or os.path.isabs(path):
        return path
    return os.path.join(str(settings.MEDIA_ROOT), path)


def _voice_model_record(character_tts_config: dict | None, user=None):
    """角色 tts_config.voice_model_id → 音色库记录（限定属于该用户）。"""
    raw_id = str((character_tts_config or {}).get('voice_model_id') or '').strip()
    if not raw_id:
        return None
    try:
        pk = int(raw_id)
    except (TypeError, ValueError):
        return None
    queryset = TtsVoiceModel.objects.all()
    if user is not None:
        queryset = queryset.filter(user=user)
    return queryset.filter(pk=pk).first()


def merged_voice_fields(character_tts_config: dict | None, user=None) -> dict:
    """合成所需的音色字段。优先级：角色显式字段 > 音色库记录 > 空。

    旧角色的 tts_config 直接存 onnx_model_dir/ref_audio_path（无
    voice_model_id）也走同一条路，行为与迁移前一致。
    """
    cfg = character_tts_config or {}
    record = _voice_model_record(cfg, user)

    def pick(key: str) -> str:
        value = (cfg.get(key) or '').strip() if isinstance(cfg.get(key), str) else ''
        if value:
            return value
        return (getattr(record, key, '') or '').strip() if record else ''

    # 情感组：角色显式配置优先（旧角色数据兼容）；未配置时用音色库记录的情感组。
    raw_emotions = cfg.get('emotions') or []
    emotions = raw_emotions if isinstance(raw_emotions, list) else []
    if not emotions and record is not None:
        record_emotions = record.emotions or []
        emotions = record_emotions if isinstance(record_emotions, list) else []

    ref_audio_language = pick('ref_audio_language')
    language = pick('language')
    result = {
        'provider': pick('provider'),
        'model_version': _normalize_model_version(pick('model_version')),
        'onnx_model_dir': pick('onnx_model_dir'),
        'voice_name': pick('voice_name'),
        'language': language,
        'ref_audio_path': _resolve_server_path(pick('ref_audio_path')),
        'ref_audio_text': pick('ref_audio_text'),
        'ref_audio_language': ref_audio_language or language,
        'emotions': emotions,
    }
    if not result['voice_name'] and record is not None:
        # 音色库条目的名字即 genie 侧音色键（目录名只兜底旧数据直填场景）。
        result['voice_name'] = (record.name or '').strip()
    return result


def pick_emotion_ref(voice: dict, emotion: str | None) -> dict | None:
    """按情感名从 voice['emotions'] 挑参考音频；未命中返回 None（走默认参考音频）。

    情感组按语言分组：只挑 ref_audio_language 与合成语言一致的条目（语言为空
    时视为任意语言，兼容旧数据）。返回 {ref_audio_path, ref_audio_text,
    ref_audio_language}，路径已解析为服务端绝对路径。
    """
    if not emotion or not isinstance(voice, dict):
        return None
    target = emotion.strip()
    voice_lang = str(voice.get('language') or '').strip().lower()
    for entry in voice.get('emotions') or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get('name') or '').strip() != target:
            continue
        entry_lang = str(entry.get('ref_audio_language') or '').strip().lower()
        if voice_lang and entry_lang and entry_lang != voice_lang:
            continue
        path = _resolve_server_path(str(entry.get('ref_audio_path') or '').strip())
        if not path:
            continue
        return {
            'ref_audio_path': path,
            'ref_audio_text': str(entry.get('ref_audio_text') or '').strip(),
            'ref_audio_language': entry_lang or voice_lang
                                or voice.get('ref_audio_language') or voice.get('language')
                                or DEFAULT_GENIE_LANGUAGE,
        }
    return None


def build_genie_voice(character_tts_config: dict | None, user=None) -> dict:
    """构造一次 genie 合成所需的音色描述。

    每个音色对应自己的 ONNX 模型：模型目录/参考音频来自设置页登记的音色
    库（或旧数据的角色级直填），不设全局环境变量兜底——缺关键配置时抛
    可操作的错误，而不是静默加载到错误的模型上。
    """
    fields = merged_voice_fields(character_tts_config, user)
    onnx_model_dir = fields['onnx_model_dir']
    if not onnx_model_dir:
        raise TtsUnavailableError(
            '该角色尚未配置语音模型：请在 设置→语音设置 登记音色后，'
            '在角色编辑页「语音模型」中选择。'
        )
    # 音色键默认取模型目录名：同一模型的多个角色共享 genie 侧的一次加载。
    voice_name = fields['voice_name'] or PurePath(onnx_model_dir.replace('\\', '/')).name
    return {
        'name': voice_name,
        'onnx_model_dir': onnx_model_dir,
        'language': fields['language'] or DEFAULT_GENIE_LANGUAGE,
        'ref_audio_path': fields['ref_audio_path'],
        'ref_audio_text': fields['ref_audio_text'],
        'ref_audio_language': fields['ref_audio_language'],
        'emotions': fields.get('emotions', []),
    }


def resolve_provider_and_voice(
    provider: str | None = None,
    character_tts_config: dict | None = None,
    user=None,
) -> tuple[str, dict | None]:
    """确定本次合成使用的 provider 与音色覆盖（含版本兼容校验）。"""
    config = get_tts_config()
    fields = merged_voice_fields(character_tts_config, user)
    selected = (fields['provider'] or provider or config['provider']).strip().lower()
    model_version = fields['model_version']

    voice = None
    if selected == 'genie':
        if model_version and model_version not in GENIE_SUPPORTED_MODEL_VERSIONS:
            raise TtsUnavailableError(
                f'Genie-TTS 不支持 {model_version} 模型版本（仅 v2/v2proplus）；'
                f'该音色请改用 gptsovits 通道。'
            )
        voice = build_genie_voice(character_tts_config, user)
    elif fields['ref_audio_path'] or fields['ref_audio_text'] or fields.get('emotions'):
        # 非 genie 引擎：透传音色级参考音频覆盖（情感组一并带上，合成时按需挑）
        voice = {key: fields[key] for key in ('ref_audio_path', 'ref_audio_text') if fields[key]}
        if fields.get('emotions'):
            voice['emotions'] = fields['emotions']
    return selected, voice


_provider_instances: dict = {}


def get_tts_provider_instance(provider: str, config: dict | None = None):
    """按 (provider, base_url) 缓存 provider 实例——不同用户的引擎地址可能不同。"""
    config = config or get_tts_config()
    base_url = _provider_config(config, provider).get('url', '')
    cache_key = (provider, base_url)
    if cache_key not in _provider_instances:
        _provider_instances[cache_key] = build_provider(provider, config)
    return _provider_instances[cache_key]


def get_tts_provider(provider: str | None = None, config: dict | None = None):
    """按配置（或请求覆盖）构建 provider；未就绪时抛 TtsUnavailableError。"""
    config = config or get_tts_config()
    selected = (provider or config['provider']).strip().lower()
    ok, hint = provider_ready(config, selected)
    if not ok:
        raise TtsUnavailableError(hint)
    instance = get_tts_provider_instance(selected, config)
    reachable, reach_hint = instance.readiness_probe()
    if not reachable:
        raise TtsUnavailableError(reach_hint)
    return instance


def service_overrides_for_user(user) -> dict | None:
    """用户级 TtsServiceSettings → get_tts_config 的 overrides 字典。

    空字段不进字典，保持环境变量默认生效。未登录/未配置返回 None。
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return None
    row = TtsServiceSettings.get_for_user(user)
    if not row:
        return None
    return {
        'provider': (row.default_provider or '').strip(),
        'genie_url': (row.genie_url or '').strip(),
        'gptsovits_url': (row.gptsovits_url or '').strip(),
        'indextts_url': (row.indextts_url or '').strip(),
    }


def readiness(service_overrides: dict | None = None) -> dict:
    """前端"语音回复"开关的提示数据源。"""
    config = get_tts_config(service_overrides)
    provider = config['provider']
    configured_ok, hint = provider_ready(config, provider)
    reachable = False
    if configured_ok:
        try:
            instance = build_provider(provider, config)
            reachable, reach_hint = instance.readiness_probe()
            hint = hint or reach_hint
        except TtsUnavailableError as exc:
            hint = str(exc)
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
    user=None,
    service_overrides: dict | None = None,
    emotion: str | None = None,
) -> dict:
    """合成一段文本。

    引擎地址/默认 provider：用户级设置（service_overrides）> 环境变量。
    音色：角色 tts_config 里的显式字段 > 其所选音色库记录。
    emotion：角色情感组里的情感名，命中时用该情感的参考音频（否则默认）。
    """
    config = get_tts_config(service_overrides)
    selected, voice = resolve_provider_and_voice(provider, character_tts_config, user)
    instance = get_tts_provider_instance(selected, config)
    ok, hint = instance.readiness_probe()
    if not ok:
        raise TtsUnavailableError(hint)
    if voice is not None:
        result = instance.synthesize(text, voice, emotion=emotion)
    else:
        result = instance.synthesize(text)
    result['provider'] = selected
    logger.info(
        "TTS done via %s in %dms (first_byte=%s, chars=%d, emotion=%s)",
        selected, result['processing_ms'], result.get('first_byte_ms'), len(text),
        emotion or '-',
    )
    return result
