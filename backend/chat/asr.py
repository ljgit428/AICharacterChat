"""实时模式的 CPU 语音识别（ASR）provider 层。

设计约束（v0.1.6）：
- 纯 CPU 本地推理。默认 provider 是 sherpa-onnx + SenseVoiceSmall int8
  （Owl Meeting 模型 1 同款：非自回归、原生简体+标点、无 initial_prompt hack）；
  依赖是可选的（backend/requirements-asr.txt），模型文件由
  backend/scripts/download_asr_models.py 下载到 backend/ml_models/asr/。
  未安装/未下载时端点优雅降级为就绪提示。
- faster_whisper 作为回滚档保留（ASR_PROVIDER=faster_whisper），沿用 webm/ogg。
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

# sense_voice 走前端 AudioWorklet 采集的 16kHz mono PCM WAV；wav 一并放行
# 便于工具与测试灌入。faster_whisper 回滚档沿用 MediaRecorder 容器。
WAV_MIME_TYPES = {'audio/wav', 'audio/x-wav'}
CONTAINER_MIME_TYPES = {'audio/webm', 'audio/ogg'} | WAV_MIME_TYPES
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
        'provider': getattr(settings, 'ASR_PROVIDER', 'sense_voice'),
        'model': getattr(settings, 'ASR_MODEL', 'base'),
        'device': getattr(settings, 'ASR_DEVICE', 'cpu'),
        'compute_type': getattr(settings, 'ASR_COMPUTE_TYPE', 'int8'),
        'num_threads': getattr(settings, 'ASR_NUM_THREADS', 2),
        'sense_voice_dir': str(getattr(settings, 'SENSE_VOICE_DIR', '')),
    }


def supported_mime_types():
    """当前 provider 接受的上传 MIME（见 views.asr 的 400 校验）。"""
    provider = getattr(settings, 'ASR_PROVIDER', 'sense_voice')
    if provider == 'faster_whisper':
        return CONTAINER_MIME_TYPES
    return WAV_MIME_TYPES


def _is_package_installed():
    provider = getattr(settings, 'ASR_PROVIDER', 'sense_voice')
    try:
        if provider == 'faster_whisper':
            import faster_whisper  # noqa: F401
        else:
            import sherpa_onnx  # noqa: F401
        return True
    except Exception:
        return False


def _sense_voice_files_present(config):
    from pathlib import Path

    model_dir = Path(config['sense_voice_dir'])
    model = model_dir / 'model.int8.onnx'
    tokens = model_dir / 'tokens.txt'
    return model.is_file() and tokens.is_file()


def _sense_voice_download_hint():
    return '语音模型未下载：运行 python backend/scripts/download_asr_models.py 后重启生效。'


def asr_available():
    config = get_provider_config()
    if not config['provider'] or config['provider'] in ('none', 'off'):
        return False
    if not _is_package_installed():
        return False
    if config['provider'] == 'sense_voice' and not _sense_voice_files_present(config):
        return False
    return True


def readiness():
    """给前端的就绪信息；hint 面向最终用户，直接可展示。"""
    config = get_provider_config()
    installed = _is_package_installed()
    provider_disabled = not config['provider'] or config['provider'] in ('none', 'off')
    files_present = config['provider'] != 'sense_voice' or _sense_voice_files_present(config)
    available = not provider_disabled and installed and files_present
    loaded = _provider is not None and _provider.loaded
    if available:
        hint = '' if loaded else '语音模型将在首次使用或预热时加载（首次约需数秒）。'
    elif provider_disabled:
        hint = '语音输入未启用（ASR_PROVIDER=none）。'
    elif config['provider'] == 'sense_voice' and not files_present:
        hint = _sense_voice_download_hint()
    elif not installed:
        hint = (
            '服务端尚未安装语音识别组件：pip install -r backend/requirements-asr.txt 后重启生效。'
            if config['provider'] == 'sense_voice'
            else '服务端尚未安装语音识别组件：pip install faster-whisper 后重启生效。'
        )
    else:
        hint = ''
    return {
        'available': available,
        'installed': installed,
        'loaded': loaded,
        **config,
        'hint': hint,
    }


def _load_wav_pcm16k_mono(audio_path):
    """stdlib wave 读 16-bit PCM，重采样/降混到 16kHz mono。

    非 PCM 编码或解析失败抛 ValueError；返回值直接喂 sherpa-onnx
    （其内部同样要求 16k mono float32）。
    """
    import wave

    with wave.open(str(audio_path), 'rb') as reader:
        if reader.getcomptype() != 'NONE':
            raise ValueError('仅支持 16-bit PCM WAV（非压缩编码）。')
        channels = reader.getnchannels()
        width = reader.getsampwidth()
        rate = reader.getframerate()
        if width != 2:
            raise ValueError(f'仅支持 16-bit PCM WAV（收到 {width * 8}-bit）。')
        frames = reader.readframes(reader.getnframes())

    import numpy as np

    samples = np.frombuffer(frames, dtype=np.int16)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1).astype(np.int16)
    if rate != 16000:
        # 线性插值重采样：长度以 16k 目标按比例映射。
        target_len = int(len(samples) * 16000 / rate)
        if target_len == 0:
            return np.zeros(0, dtype=np.float32)
        xp = np.linspace(0.0, len(samples) - 1, num=target_len)
        source = samples.astype(np.float64)
        samples = np.interp(xp, np.arange(len(samples)), source).astype(np.int16)
    return (samples.astype(np.float32) / 32768.0).copy()


class SenseVoiceProvider:
    """sherpa-onnx SenseVoiceSmall 懒加载单例。原生简体+标点，无 prompt hack。"""

    name = 'sense_voice'
    _LANGUAGE_ALIASES = {'zh': 'zh', 'en': 'en', 'ja': 'ja', 'ko': 'ko', 'yue': 'yue'}
    _SUPPORTED = {'zh', 'en', 'ja', 'ko', 'yue', 'auto'}
    def __init__(self, model_dir, num_threads):
        self._model_dir = model_dir
        self._num_threads = num_threads
        self._recognizer = None
        self._warmed = False
        self._load_lock = threading.Lock()

    @property
    def loaded(self):
        return self._recognizer is not None

    def _ensure_model(self):
        if self._recognizer is not None:
            return 0.0
        with self._load_lock:
            if self._recognizer is not None:
                return 0.0
            started = time.perf_counter()
            import sherpa_onnx

            self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=f'{self._model_dir}/model.int8.onnx',
                tokens=f'{self._model_dir}/tokens.txt',
                num_threads=self._num_threads,
                use_itn=True,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "ASR model SenseVoice int8 (threads=%d) loaded in %dms",
                self._num_threads, elapsed_ms,
            )
            return elapsed_ms

    def warm_up(self):
        load_ms = self._ensure_model()
        if self._warmed:
            return load_ms
        self._warmed = True
        # 空 stream 跑一次完整前向，摊掉首句的 ONNX 内存池分配。
        import numpy as np

        import sherpa_onnx

        stream = self._recognizer.create_stream()
        stream.accept_waveform(16000, np.zeros(1600, dtype=np.float32))
        self._recognizer.decode_stream(stream)
        return load_ms

    def transcribe(self, audio_path, language=None):
        samples = _load_wav_pcm16k_mono(audio_path)
        if samples.size == 0:
            return {'text': '', 'language': language or 'auto'}
        normalized = (language or 'auto').lower()
        if normalized not in self._SUPPORTED:
            normalized = 'auto'
        stream = self._recognizer.create_stream()
        stream.accept_waveform(16000, samples)
        self._recognizer.decode_stream(stream)
        return {'text': stream.result.text.strip(), 'language': normalized}


class FasterWhisperProvider:
    """faster_whisper 懒加载单例（回滚档）。transcribe 参数按低延迟调优。"""

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
        # initial_prompt 实测（docs/benchmarks/latency-v0.1.3.md）：中文输出
        # 从繁体/无标点修正为简体+标点，对英文识别与延迟无副作用。
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
                if config['provider'] == 'faster_whisper':
                    _provider = FasterWhisperProvider(
                        config['model'],
                        config['device'],
                        config['compute_type'],
                    )
                else:
                    _provider = SenseVoiceProvider(
                        config['sense_voice_dir'],
                        config['num_threads'],
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
    suffix = _MIME_SUFFIXES.get(mime_type, '.wav')
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
