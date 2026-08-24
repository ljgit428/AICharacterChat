"""实时模式的 CPU 语音识别（ASR）provider 层。

设计约束（v0.1.3）：
- 纯 CPU 本地推理，默认 faster-whisper int8；依赖是可选的
  （backend/requirements-asr.txt），未安装时端点优雅降级为就绪提示。
- 延迟是一等指标：模型懒加载单例 + 可预热，转写参数按低延迟调优，
  每次调用返回 processing_ms / model_load_ms 并写日志，供前端延迟角标
  与 docs/latency 记录使用。
"""

import logging
import tempfile
import threading
import time

from django.conf import settings

logger = logging.getLogger(__name__)

# 与前端 MediaRecorder 的输出对齐；wav 一并放行便于工具与测试灌入。
SUPPORTED_AUDIO_MIME_TYPES = {
    'audio/webm',
    'audio/ogg',
    'audio/wav',
    'audio/x-wav',
}
MAX_ASR_AUDIO_BYTES = 15 * 1024 * 1024

_MIME_SUFFIXES = {
    'audio/webm': '.webm',
    'audio/ogg': '.ogg',
    'audio/wav': '.wav',
    'audio/x-wav': '.wav',
}


class AsrUnavailableError(Exception):
    """ASR 未启用或可选依赖未安装。"""


def get_provider_config():
    return {
        'provider': getattr(settings, 'ASR_PROVIDER', 'faster_whisper'),
        'model': getattr(settings, 'ASR_MODEL', 'small'),
        'device': getattr(settings, 'ASR_DEVICE', 'cpu'),
        'compute_type': getattr(settings, 'ASR_COMPUTE_TYPE', 'int8'),
    }


def is_package_installed():
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def asr_available():
    config = get_provider_config()
    if not config['provider'] or config['provider'] in ('none', 'off'):
        return False
    return is_package_installed()


def readiness():
    """给前端的就绪信息；hint 面向最终用户，直接可展示。"""
    config = get_provider_config()
    installed = is_package_installed()
    available = bool(config['provider']) and config['provider'] not in ('none', 'off') and installed
    loaded = _provider is not None and _provider.loaded
    if available:
        hint = '' if loaded else '语音模型将在首次使用或预热时加载（首次约需数秒）。'
    elif config['provider'] in ('none', 'off'):
        hint = '语音输入未启用（ASR_PROVIDER=none）。'
    elif not installed:
        hint = '服务端尚未安装语音识别组件：pip install -r backend/requirements-asr.txt 后重启生效。'
    else:
        hint = ''
    return {
        'available': available,
        'installed': installed,
        'loaded': loaded,
        **config,
        'hint': hint,
    }


class FasterWhisperProvider:
    """faster-whisper 懒加载单例。transcribe 参数按低延迟调优。"""

    name = 'faster_whisper'

    def __init__(self, model_size, device, compute_type):
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._model = None
        self._load_lock = threading.Lock()

    @property
    def loaded(self):
        return self._model is not None

    def _ensure_model(self):
        if self._model is not None:
            return 0.0
        with self._load_lock:
            if self._model is not None:
                return 0.0
            started = time.perf_counter()
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "ASR model %s (%s/%s) loaded in %dms",
                self._model_size, self._device, self._compute_type, elapsed_ms,
            )
            return elapsed_ms

    def warm_up(self):
        return self._ensure_model()

    def transcribe(self, audio_path, language=None):
        # beam_size=1 + without_timestamps 是低延迟档位；vad_filter 在
        # 服务端再裁一次静音，缩短有效音频长度。
        # initial_prompt 实测（docs/latency-v0.1.3.md）：中文输出从繁体/
        # 无标点修正为简体+标点，对英文识别与延迟无副作用。
        segments, info = self._model.transcribe(
            audio_path,
            language=language or None,
            beam_size=1,
            vad_filter=True,
            without_timestamps=True,
            initial_prompt='以下是普通话的句子。',
        )
        text = ''.join(segment.text for segment in segments).strip()
        return {'text': text, 'language': info.language}


_provider = None
_provider_lock = threading.Lock()


def get_asr_provider():
    global _provider
    if not asr_available():
        raise AsrUnavailableError(readiness()['hint'])
    if _provider is None:
        with _provider_lock:
            if _provider is None:
                config = get_provider_config()
                _provider = FasterWhisperProvider(
                    config['model'],
                    config['device'],
                    config['compute_type'],
                )
    return _provider


def warm_up_asr():
    """供管理命令 / readiness 调用；返回 (provider, model_load_ms)。"""
    provider = get_asr_provider()
    return provider, provider.warm_up()


def transcribe_bytes(audio_bytes, mime_type, language=None):
    """转写一段音频。返回 {text, language, processing_ms, model_load_ms}。

    processing_ms 含临时文件写入与推理；model_load_ms 仅在本次调用
    触发冷加载时非零。
    """
    suffix = _MIME_SUFFIXES.get(mime_type, '.webm')
    provider = get_asr_provider()
    started = time.perf_counter()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(audio_bytes)
        temp_path = handle.name
    try:
        model_load_ms = provider.warm_up()
        result = provider.transcribe(temp_path, language=language)
    finally:
        try:
            import os

            os.unlink(temp_path)
        except OSError:
            pass
    processing_ms = int((time.perf_counter() - started) * 1000)
    payload = {
        **result,
        'processing_ms': processing_ms,
        'model_load_ms': model_load_ms,
    }
    logger.info(
        "ASR turn done in %dms (model_load=%dms, bytes=%d, lang=%s)",
        processing_ms, model_load_ms, len(audio_bytes), result.get('language'),
    )
    return payload
