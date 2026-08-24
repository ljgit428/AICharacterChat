"""启动 Genie-TTS 服务器并加载角色音色（实时模式"语音回复"的引擎侧）。

用法：
    python backend/scripts/genie_server.py

环境变量（均有默认值，可在 backend/.env 里覆盖）：
    GENIE_ONNX_MODEL_DIR  已转换的 ONNX 模型目录（genie.convert_to_onnx 产物）
    GENIE_CHARACTER       角色名（默认 seia，与 TTS_GENIE_CHARACTER 一致）
    GENIE_LANGUAGE        模型语言（zh / jp / en / ko）
    GENIE_REF_AUDIO_PATH  参考音频（服务器本地路径，用于音色克隆）
    GENIE_REF_AUDIO_TEXT  参考音频的台词文本
    GENIE_REF_AUDIO_LANGUAGE 参考音频语言（默认与 GENIE_LANGUAGE 相同）
    GENIE_HOST / GENIE_PORT  监听地址（默认 127.0.0.1:8050，与 TTS_GENIE_URL 对应）

注意：角色必须在服务器启动后通过 HTTP /load_character 加载
（uvicorn worker 是独立进程，脚本内直接调用 genie.load_character 不会
作用于服务进程）。本脚本起线程跑服务器，再对自身发加载请求。

模型转换（一次性，需要 torch）：
    python -c "import genie_tts as genie; genie.convert_to_onnx(
        torch_pth_path=r'.../Seia_e8_s240.pth',
        torch_ckpt_path=r'.../Seia-e15.ckpt',
        output_dir=r'backend/models/seia_onnx')"
"""

import os
import sys
import threading
import time

import requests

import genie_tts as genie


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def main() -> None:
    character = _env('GENIE_CHARACTER', 'seia')
    onnx_model_dir = _env('GENIE_ONNX_MODEL_DIR')
    language = _env('GENIE_LANGUAGE', 'zh')
    host = _env('GENIE_HOST', '127.0.0.1')
    port = int(_env('GENIE_PORT', '8050'))
    ref_audio_path = _env('GENIE_REF_AUDIO_PATH')
    ref_audio_text = _env('GENIE_REF_AUDIO_TEXT')
    ref_audio_language = _env('GENIE_REF_AUDIO_LANGUAGE', language)
    base_url = f'http://{host}:{port}'

    if not onnx_model_dir:
        print('环境变量 GENIE_ONNX_MODEL_DIR 未设置：指向 convert_to_onnx 的输出目录。')
        sys.exit(1)

    server_thread = threading.Thread(
        target=genie.start_server,
        kwargs={'host': host, 'port': port, 'workers': 1},
        daemon=True,
    )
    server_thread.start()

    # 等服务端口就绪后，通过 HTTP 加载角色（worker 进程内生效）。
    for _ in range(60):
        try:
            requests.get(f'{base_url}/docs', timeout=2)
            break
        except Exception:
            time.sleep(0.5)

    response = requests.post(f'{base_url}/load_character', json={
        'character_name': character,
        'onnx_model_dir': onnx_model_dir,
        'language': language,
    }, timeout=300)
    print(f'加载角色 {character} ({language})：{response.status_code} {response.text[:120]}')

    if ref_audio_path:
        response = requests.post(f'{base_url}/set_reference_audio', json={
            'character_name': character,
            'audio_path': ref_audio_path,
            'audio_text': ref_audio_text,
            'language': ref_audio_language,
        }, timeout=60)
        print(f'参考音频 {ref_audio_path} ({ref_audio_language})：{response.status_code}')

    print(f'Genie-TTS 服务器就绪：{base_url}')
    server_thread.join()


if __name__ == '__main__':
    main()
