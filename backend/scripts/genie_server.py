"""启动 Genie-TTS 服务器（实时模式"语音回复"的引擎侧）。

服务器本身与具体角色无关：Django 侧每次合成请求都会带上该角色自己的
onnx_model_dir，首次使用时自动加载（见 chat/tts.py 的 GenieTtsProvider）。
因此常规用法只需启动服务：

    python backend/scripts/genie_server.py

如想在启动时预载某个角色（省掉首次合成前的加载等待），显式传参即可；
每个角色传各自的模型目录，想预载多个角色就把脚本跑多份或改用端口区分：

    python backend/scripts/genie_server.py --character seia \
        --model-dir D:/models/seia_onnx --language zh

    python backend/scripts/genie_server.py --character ryuko \
        --model-dir D:/models/ryuko_onnx --language jp \
        --ref-audio F:/voice/ryuko/sample.wav --ref-text "..." --ref-lang jp

可选参数：
    --character / --model-dir / --language
        预载角色的音色键、其 ONNX 模型目录（convert_to_onnx 产物）、模型语言。
        三者需同时给出才触发预载；省略则只起空服务器，等 Django 按需加载。
    --ref-audio / --ref-text / --ref-lang
        预载角色的参考音频与台词（音色克隆），可省略。
    --host / --port
        监听地址（默认 127.0.0.1:8050，对应 TTS_GENIE_URL）。
    --device
        ONNX 推理设备：cpu（默认）或 cuda。默认纯 CPU 已可实时；有 NVIDIA
        GPU 时可加 --device cuda 进一步降低首响延迟：

        python backend/scripts/genie_server.py --device cuda

        cuda 需要 onnxruntime-gpu；检测不到 CUDA 时打印警告并回退 CPU。

模型转换（一次性，需要 torch），每个角色各自转换出自己的目录：
    python -c "import genie_tts as genie; genie.convert_to_onnx(
        torch_pth_path=r'.../<角色>_e8_s240.pth',
        torch_ckpt_path=r'.../<角色>-e15.ckpt',
        output_dir=r'D:/models/<角色>_onnx')"
"""

import argparse
import threading
import time

import requests

import genie_tts as genie


def enable_cuda_if_available() -> bool:
    """把 model_manager 切到 CUDA 优先的 ONNX providers，返回是否启用成功。

    genie_tts 的 ModelManager 默认写死 ["CPUExecutionProvider"]，而各会话在
    load_character 时才创建；workers=1 时 uvicorn 与本脚本同进程，启动期改
    这个单例属性即可让之后所有加载都走 GPU。
    """
    import onnxruntime

    from genie_tts.ModelManager import model_manager

    available = onnxruntime.get_available_providers()
    if 'CUDAExecutionProvider' not in available:
        print(
            '警告：当前 onnxruntime 不支持 CUDA'
            f'（可用 providers：{", ".join(available)}），回退 CPU 推理。'
            '需要 GPU 请先安装 onnxruntime-gpu 并确认驱动可用。'
        )
        return False
    model_manager.providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
    print('ONNX 推理设备：CUDA')
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--character', help='预载角色的音色键')
    parser.add_argument('--model-dir', help='该角色的 ONNX 模型目录')
    parser.add_argument('--language', default='zh', help='模型语言 zh/jp/en/ko（默认 zh）')
    parser.add_argument('--ref-audio', help='参考音频路径（音色克隆，可省略）')
    parser.add_argument('--ref-text', default='', help='参考音频的台词文本')
    parser.add_argument('--ref-lang', default='', help='参考音频语言（默认同 --language）')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8050)
    parser.add_argument(
        '--device',
        choices=('cpu', 'cuda'),
        default='cpu',
        help='ONNX 推理设备（默认 cpu；cuda 需 onnxruntime-gpu 与 NVIDIA GPU）',
    )
    return parser.parse_args()


def wait_until_ready(base_url: str, timeout_seconds: int = 30) -> None:
    for _ in range(timeout_seconds * 2):
        try:
            requests.get(f'{base_url}/docs', timeout=2)
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f'Genie-TTS 服务器 {base_url} 未在 {timeout_seconds}s 内就绪')


def main() -> None:
    args = parse_args()
    if args.device == 'cuda':
        enable_cuda_if_available()
    base_url = f'http://{args.host}:{args.port}'

    server_thread = threading.Thread(
        target=genie.start_server,
        kwargs={'host': args.host, 'port': args.port, 'workers': 1},
        daemon=True,
    )
    server_thread.start()
    wait_until_ready(base_url)

    # 角色必须在 worker 进程内加载（uvicorn worker 独立进程），所以即使
    # 预载也走 HTTP 自调用，而不是进程内直接 genie.load_character。
    if args.character and args.model_dir:
        response = requests.post(f'{base_url}/load_character', json={
            'character_name': args.character,
            'onnx_model_dir': args.model_dir,
            'language': args.language,
        }, timeout=300)
        print(f'加载角色 {args.character} ({args.language})：{response.status_code} {response.text[:120]}')

        if args.ref_audio:
            response = requests.post(f'{base_url}/set_reference_audio', json={
                'character_name': args.character,
                'audio_path': args.ref_audio,
                'audio_text': args.ref_text,
                'language': args.ref_lang or args.language,
            }, timeout=60)
            print(f'参考音频 {args.ref_audio}：{response.status_code}')
    elif args.character or args.model_dir:
        raise SystemExit('--character 与 --model-dir 必须同时提供')

    print(f'Genie-TTS 服务器就绪：{base_url}')
    server_thread.join()


if __name__ == '__main__':
    main()
