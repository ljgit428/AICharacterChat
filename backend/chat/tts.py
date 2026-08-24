"""TTS 预留层（实时模式 Phase C）。

v0.1.3 只定义接口形状与能力协商，不做任何实现：
- 端点返回 501 + capabilities，前端据此渲染"即将支持"的禁用态；
- 与 ASR 对称：同样走 CPU 本地 provider（候选 piper / kokoro-onnx），
  届时在此文件落实现，端点只换掉 501 分支。
"""

CAPABILITIES = {
    'available': False,
    'phase': 'realtime Phase C',
    'providers': [],
    'planned_note': 'CPU 本地语音合成预留接口；实现落地前所有请求返回 501。',
}


def tts_available():
    return False
