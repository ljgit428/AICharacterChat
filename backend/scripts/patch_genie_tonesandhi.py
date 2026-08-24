"""修补 genie-tts 中文声调连读的 IndexError。

Genie-TTS 的 ToneSandhi 对「嗯」等没有韵母的字（lazy_pinyin FINALS_TONE3
产出空韵母串）执行 `[-1][-1]` 时越界崩溃，服务端返回空音频。上游修复前，
用本脚本给安装目录打上空串守卫（幂等，可重复执行）：

    python backend/scripts/patch_genie_tonesandhi.py
"""

import os

import genie_tts  # noqa: F401  触发资源检查（已装好时无副作用）

TARGET = os.path.join(
    os.path.dirname(genie_tts.__file__), 'G2P', 'Chinese', 'ToneSandhi.py'
)

PATCHES = [
    (
        'and finals_list[0][-1][-1] == "3"',
        'and finals_list[0][-1] and finals_list[0][-1][-1] == "3"',
    ),
    (
        'and sub_finals_list[i - 1][-1][-1] == "3"',
        'and sub_finals_list[i - 1][-1] and sub_finals_list[i - 1][-1][-1] == "3"',
    ),
]


def main() -> None:
    with open(TARGET, encoding='utf-8') as handle:
        source = handle.read()

    applied = 0
    for old, new in PATCHES:
        if new in source:
            applied += 1
            continue
        if old not in source:
            print(f'⚠ 未找到目标片段（可能上游已修复）：{old}')
            continue
        source = source.replace(old, new)
        applied += 1

    with open(TARGET, 'w', encoding='utf-8') as handle:
        handle.write(source)
    print(f'补丁完成：{applied}/{len(PATCHES)} 处 → {TARGET}')
    print('需要重启 Genie-TTS 服务器生效。')


if __name__ == '__main__':
    main()
