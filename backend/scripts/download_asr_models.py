"""Download the SenseVoice ONNX model for the realtime chat mode's ASR.

Usage:
    python backend/scripts/download_asr_models.py

Downloads sherpa-onnx-sense-voice-zh-en-ja-ko-yue (int8, ~230MB) from the
sherpa-onnx GitHub release and extracts model.int8.onnx + tokens.txt into
backend/ml_models/asr/sense-voice/. Re-running is a no-op once both files
exist with a sane size.
"""

import argparse
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGET = REPO_ROOT / 'backend' / 'ml_models' / 'asr' / 'sense-voice'

# Pinned so downloads stay reproducible; bump deliberately. Release tag
# `asr-models` hosts rolling model archives; the int8 variant is the
# CPU-lightweight one Owl Meeting also ships (~230MB).
ARCHIVE = 'sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09.tar.bz2'
URL = f'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{ARCHIVE}'
MODEL_FILE = 'model.int8.onnx'
TOKENS_FILE = 'tokens.txt'
MIN_MODEL_BYTES = 100 * 1024 * 1024  # int8 量化版约 230MB；再小必有损坏。


def already_downloaded(target_dir: Path) -> bool:
    model = target_dir / MODEL_FILE
    tokens = target_dir / TOKENS_FILE
    return model.exists() and model.stat().st_size >= MIN_MODEL_BYTES and tokens.exists()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()

    if already_downloaded(args.target):
        print(f'[asr-models] {args.target} 已存在完整模型，跳过下载。')
        return 0

    args.target.mkdir(parents=True, exist_ok=True)
    print(f'[asr-models] 下载 {ARCHIVE}（约 230MB，视网络可能需要数分钟）…')
    with tempfile.TemporaryDirectory() as tmp:
        archive_path = Path(tmp) / ARCHIVE
        urllib.request.urlretrieve(URL, archive_path)

        print('[asr-models] 解压模型…')
        extract_dir = Path(tmp) / 'extract'
        with tarfile.open(archive_path, 'r:bz2') as archive:
            archive.extractall(extract_dir)

        # 压缩包内形如 sherpa-onnx-sense-voice-*/model.int8.onnx
        candidates = list(extract_dir.rglob(MODEL_FILE))
        if not candidates:
            print('[asr-models] ERROR: 压缩包内未找到 model.int8.onnx', file=sys.stderr)
            return 1
        source_dir = candidates[0].parent
        shutil.copy2(source_dir / MODEL_FILE, args.target / MODEL_FILE)
        shutil.copy2(source_dir / TOKENS_FILE, args.target / TOKENS_FILE)

    if not already_downloaded(args.target):
        print('[asr-models] ERROR: 下载结果校验失败（模型文件过小）', file=sys.stderr)
        return 1
    print(f'[asr-models] 完成：{args.target / MODEL_FILE}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
