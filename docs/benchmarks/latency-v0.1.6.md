# Realtime Mode Latency & Accuracy — v0.1.6

> 测量协议（沿用 v0.1.3）：短句 / 长句 / 中英混合三组用例，各 3 轮，
> 记录 `POST /api/chat/asr` 的 processing_ms / model_load_ms。
> 环境：Windows 11 · 纯 CPU（无显卡）· sherpa-onnx 1.13.7 +
> SenseVoiceSmall int8（2 线程）· 同一批 SAPI 测试音频
> （`tmp/test-assets/asr-latency/*.wav`，22050Hz，服务端重采样到 16k）。

## 引擎切换

faster-whisper base int8 → **sherpa-onnx SenseVoiceSmall int8**（Owl Meeting
模型 1 同款引擎：非自回归、原生简体+标点、无 initial_prompt hack）。
回滚：`ASR_PROVIDER=faster_whisper`（旧引擎代码保留，webm/ogg 仍支持）。

## 1. ASR 端到端（`POST /api/chat/asr` 的 processing_ms）

### 逐轮数据

| 用例 | 轮次耗时 (ms) | 中位 |
|---|---|---|
| short-zh（你好呀，最近过得怎么样？3.2s 音频） | 1 954* / 205 / 239 | **222 ms** |
| long-zh（约 13.7s 长句） | 802 / 840 / 836 | **836 ms** |
| mixed（中英夹杂 5.7s） | 388 / 332 / 379 | **379 ms** |

\* 首轮含模型冷加载 model_load_ms=1592；引擎独立冒烟（正弦波 1s 音频）
解码 68ms。冷加载单测：1 443ms（比 whisper base 的 3 767ms 快 2.6 倍）。

### 与 v0.1.3（faster-whisper base int8）对照

| 指标 | v0.1.3 whisper base | v0.1.6 SenseVoice | 变化 |
|---|---|---|---|
| 冷加载 | 3 767 ms | 1 592 ms | ×0.42 |
| 短句中位 | ~1 490 ms | **222 ms** | **×0.15** |
| 长句中位 | ~1 688 ms | 836 ms | ×0.50 |
| 中英混合中位 | ~1 490 ms | 379 ms | ×0.25 |
| 延迟预算（≤1.5s） | 边缘 | 大幅达标 | — |

### 与延迟预算对照

| 阶段 | 目标 | 实测 |
|---|---|---|
| VAD 断句静音窗（前端） | ~1.2 s 固定 | 1.2 s（SILENCE_HANGOVER_MS，未改） |
| 上传 + ASR | ≤1.5 s | **0.22–0.84 s**（全部用例达标） |
| 断句→自动发送 | <100 ms | 同步直发（未改） |

## 2. 准确度（同一批音频）

| 用例 | v0.1.6 SenseVoice 输出 |
|---|---|
| short-zh | ✅ 你好呀最近过得怎么样 |
| long-zh | ✅ 全文正确（咖啡店长句，62 字无错字） |
| mixed | ✅/⚠ "I THINK 这个 FEATURE 需要 LOW LATENCY MAYBE AROUND E SECOND"（语义全对；英文全大写为 use_itn 的 ITN 行为，数字 "1"→"E" 一处漂移） |

要点：
- **纯中文两档一致满分**；SenseVoice 输出不带标点（sherpa-onnx 该模型
  的已知行为，后续可评估加标点模型）。
- 中英混合从 base 的「关键词漂移」（allow/each）改善为仅大小写风格与
  单个数字漂移，语义层面与 small 档相当但延迟只有其 1/4。
- v0.1.3 的 initial_prompt hack 不再需要。

## 3. 新增链路说明（v0.1.6）

- 前端采集改为 AudioWorklet PCM（16kHz mono WAV 直出，MediaRecorder/webm
  路径移除）；服务端 stdlib wave 解析 + numpy 重采样。
- 灰色预测字（Owl 低延迟模式）：说话期间每 1s 刷新间隔、携带最近 20s
  上下文窗口发一次识别，字幕条灰色斜体展示中间结果；断句后取消在途
  预览并发送整段（上限 60s）。
- 模型文件下载：`python backend/scripts/download_asr_models.py`
  （~237MB → `backend/ml_models/asr/sense-voice/`，git 忽略）。

## 4. 复测方法

```bash
# 后端（先装依赖+下模型）
cd backend && pip install -r requirements-asr.txt
python scripts/download_asr_models.py
python manage.py runserver
# 打点
curl -s -X POST http://127.0.0.1:8000/api/chat/asr/ -F "audio=@clip.wav;type=audio/wav"
# 响应含 processing_ms / model_load_ms（前端实时角标同源）
```

注：GUI 浏览器实测因会话内点击事件注入失效未完成（页面渲染与 API 通路
已验证），用户首次开启实时模式时可对照本文数据核对角标。
