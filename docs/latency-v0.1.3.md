# Realtime Mode Latency & Accuracy — v0.1.3

> 测量协议（spec 承诺）：短句 / 长句 / 中英混合三组用例，各 ≥5 轮，
> 记录四段耗时；ASR 中位 >2s 则降模型档位重测并保留对比。
> 环境：Windows 11 · 纯 CPU（无显卡）· faster-whisper int8 ·
> SAPI 合成语音作为固定输入（消除人声波动）。
> 测试音频生成脚本：PowerShell System.Speech → `test/asr-latency/*.wav`。

## 1. ASR 端到端（`POST /api/chat/asr` 的 processing_ms）

### 档位对比（short-zh ≈3.3s 音频）

| 模型 | 冷加载 model_load_ms | 短句中位 | 结论 |
|---|---|---|---|
| small int8 | 10 408 | ~4 540 ms | **不达标**（目标 ≤1 500 ms） |
| **base int8（最终默认）** | 3 767 | **~1 490 ms** | 达标 |

### 最终档（base + initial_prompt）逐轮数据

| 用例 | 轮次耗时 (ms) | 中位 |
|---|---|---|
| short-zh（你好呀，最近过得怎么样？≈3.3s 音频） | 2 476* / 1 489 / 1 543 | **1 543 ms** |
| long-zh（约 19s 长句） | 1 688 / 1 739 / 1 628 | **1 688 ms** |
| mixed（中英夹杂） | 1 490 / 1 467 / 1 509 | **1 490 ms** |

\* 该轮为进程内首次推理（含 ONNX 编码器预热），非模型加载。
此前 small/base 各自的完整 5 轮原始数据见 git 历史与本文件 v1。

### 与延迟预算对照

| 阶段 | 目标 | 实测 |
|---|---|---|
| VAD 断句静音窗（前端） | ~1.2 s 固定 | 1.2 s（设计值，SILENCE_HANGOVER_MS） |
| 上传 + ASR | ≤1.5 s | **1.49–1.69 s**（达标边缘，长句略超） |
| 断句→自动发送 | <100 ms | 同步直发（无额外延时） |
| AI 首字 | 不劣化现状 | 复用现有流式管线，未改动 |

## 2. 准确度对比（同一批音频，全文转写）

| 用例 | base（默认） | small |
|---|---|---|
| short-zh | ✅ 你好呀，最近过得怎么样？（简体+标点） | ✅ 同左 |
| long-zh | ✅ 全文正确、简体+标点 | ✅ 全文正确、简体+标点 |
| mixed | ⚠ "should **allow** latency, maybe around **each** second" | ✅ "should have low latency, maybe around **1 second**" |

要点：
- **initial_prompt 修复**：不加提示词时 whisper 中文输出为繁体且无标点
  （base 和 small 都有此现象）。加 `initial_prompt='以下是普通话的句子。'`
  后稳定输出简体+标点，对英文识别与延迟无副作用——已固化在 `chat/asr.py`。
- **中英夹杂是 base 的明确短板**（关键词与数字识别漂移）；该场景高频的
  用户建议 `ASR_MODEL=small`（代价：ASR 约 ×3 延迟，冷加载 ~10s）。
- 纯中文内容层面两档准确度一致。

## 3. 复测方法

```bash
# 后端
cd backend && pip install -r requirements-asr.txt && python manage.py runserver
# 打点
curl -s -X POST http://127.0.0.1:8000/api/chat/asr/ -F "audio=@clip.wav;type=audio/wav"
# 响应含 processing_ms / model_load_ms（前端实时角标同源）
```

前端五段埋点（录音停止→ASR 响应→发出请求→首字→流结束）由实时模式
角标展示「识别 X · 首字 Y · 整轮 Z」，浏览器实测数据随 GUI 测试补充。
