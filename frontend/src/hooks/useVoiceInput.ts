"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiService } from "@/utils/api";

/**
 * 实时模式的持续语音输入 hook（v0.1.6 重写采集路径）。
 *
 * 交互模型（不变）：麦克风常开，自适应静音阈值（VAD）检测到说话开始录音，
 * 约 1.2s 静音即断句，自动上传 /chat/asr 转写后回调文本。AI 回复期间通过
 * `paused` 暂停新断句。
 *
 * v0.1.6 变化：
 * - 采集从 MediaRecorder(webm) 换成 AudioWorklet PCM：16kHz mono 16-bit WAV
 *   直出，配合后端 SenseVoice 引擎（服务端不再需要 ffmpeg/webm 解码）。
 * - 灰色预测字（Owl Meeting 低延迟模式机制）：说话期间按 REFRESH_INTERVAL_MS
 *   周期把「最近 PREVIEW_CONTEXT_MS 音频」发去识别，onInterim 回调灰色展示；
 *   断句后取消在途预览、发整段（上限 MAX_UTTERANCE_MS），onTranscribed 给出
 *   最终文本。preview=false 时退回纯断句模式（省 CPU）。
 *
 * 延迟：ASR 返回的 processing_ms 通过 lastAsrMs 暴露给实时角标。
 */

export type VoiceInputStatus =
  | "off"
  | "starting"
  | "listening"
  | "speech"
  | "transcribing"
  | "error";

interface UseVoiceInputOptions {
  /** 断句转写完成（文本可能为空串——无效段会被丢弃，不会回调空文本）。 */
  onTranscribed: (text: string, meta: { asrMs: number | null }) => void;
  /** 灰色预测字回调（仅 preview=true 的说话期间触发；空串=清空）。 */
  onInterim?: (text: string) => void;
  /** true 时不开新断句（AI 回复进行中）。进行中的录音会自然收尾。 */
  paused: boolean;
  /** 灰色预测字开关（localStorage 持久化由调用方负责）。 */
  preview?: boolean;
}

/** 判定"说完"的静音时长；延迟预算的固定组成部分。 */
const SILENCE_HANGOVER_MS = 1200;
/** 有效语音的最短时长，过滤咳嗽/碰撞等瞬态噪声。 */
const MIN_SPEECH_MS = 400;
const TICK_MS = 50;
/** 预测字刷新间隔（Owl Meeting「刷新间隔」机制，文档建议 CPU 紧张时调大）。 */
const REFRESH_INTERVAL_MS = 1000;
/** 预测字每次推理携带的上下文音频长度（Owl「上下文窗口」）。 */
const PREVIEW_CONTEXT_MS = 20_000;
/** 单句上限：防无限长语音拖垮识别与内存（Owl「最大语音时长」等价物）。 */
const MAX_UTTERANCE_MS = 60_000;
const TARGET_SAMPLE_RATE = 16000;

/** 音量条订阅：避免 20fps 的 level 更新重渲染整个 ChatInterface。 */
export type LevelListener = (level: number) => void;

// AudioWorklet 处理器源码：Float32 → Int16 下采样传输。Blob URL 内联，
// 不依赖 public/ 静态资源（保持 hook 自包含，Next 构建无需额外配置）。
const RECORDER_WORKLET = `
class PcmRecorderProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._targetRate = 16000;
    this._lastIndex = 0;
    this._resampleBuffer = null;
  }
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    let samples = channel;
    const ratio = sampleRate / this._targetRate;
    if (Math.abs(ratio - 1) > 0.001) {
      const inputLength = samples.length;
      const outputLength = Math.max(1, Math.floor(inputLength / ratio));
      const out = new Float32Array(outputLength);
      let pos = this._lastIndex;
      for (let i = 0; i < outputLength; i += 1) {
        // 线性插值下采样（128 帧很小，逐点足够）。
        const idx = Math.floor(pos);
        const frac = pos - idx;
        const a = samples[Math.min(idx, inputLength - 1)];
        const b = samples[Math.min(idx + 1, inputLength - 1)];
        out[i] = a + (b - a) * frac;
        pos += ratio;
      }
      this._lastIndex = pos - inputLength;
      samples = out;
    }
    const pcm = new Int16Array(samples.length);
    for (let i = 0; i < samples.length; i += 1) {
      const clamped = Math.max(-1, Math.min(1, samples[i]));
      pcm[i] = Math.round(clamped * 32767);
    }
    if (pcm.length > 0) {
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }
    return true;
  }
}
registerProcessor('pcm-recorder', PcmRecorderProcessor);
`;

/** Int16 PCM 帧序列 → 16k mono WAV Blob（后端 sense_voice 的输入格式）。 */
function encodeWav(frames: Int16Array[], sampleRate = TARGET_SAMPLE_RATE): Blob {
  let total = 0;
  for (const frame of frames) total += frame.length;
  const payload = new Uint8Array(44 + total * 2);
  const view = new DataView(payload.buffer);
  const writeAscii = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i));
  };
  writeAscii(0, "RIFF");
  view.setUint32(4, 36 + total * 2, true);
  writeAscii(8, "WAVE");
  writeAscii(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeAscii(36, "data");
  view.setUint32(40, total * 2, true);
  let offset = 44;
  for (const frame of frames) {
    for (let i = 0; i < frame.length; i += 1) {
      view.setInt16(offset, frame[i], true);
      offset += 2;
    }
  }
  return new Blob([payload], { type: "audio/wav" });
}

export function useVoiceInput({
  onTranscribed,
  onInterim,
  paused,
  preview = true,
}: UseVoiceInputOptions) {
  const [status, setStatus] = useState<VoiceInputStatus>("off");
  const [errorHint, setErrorHint] = useState<string | null>(null);
  const [lastAsrMs, setLastAsrMs] = useState<number | null>(null);
  const [interimText, setInterimText] = useState("");

  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<AudioWorkletNode | null>(null);
  const workletUrlRef = useRef<string | null>(null);
  const tickRef = useRef<number | null>(null);
  // 连续的当前句 PCM 帧（含语音起点前的少量 padding，改善句首吞字）。
  const utteranceFramesRef = useRef<Int16Array[]>([]);
  const speechStartedAtRef = useRef<number>(0);
  const lastVoiceAtRef = useRef<number>(0);
  const noiseFloorRef = useRef(0.01);
  const lastRmsRef = useRef(0);
  // VAD 用滚动窗口缓存最近 ~1s 的帧（语音起点前 padding 也从这里来）。
  const preRollFramesRef = useRef<Int16Array[]>([]);
  const preRollBytesRef = useRef(0);
  // 转写请求在途标记：防止同一片段重复提交。
  const inflightRef = useRef(false);
  // 预览在途请求的 AbortController（断句/停止时取消）。
  const previewAbortRef = useRef<AbortController | null>(null);
  const lastPreviewAtRef = useRef(0);
  // utterance 序号：防止取消慢的预览请求把上一句的文本串到当前句。
  const utteranceSeqRef = useRef(0);
  const pausedRef = useRef(paused);
  const previewRef = useRef(preview);
  const onTranscribedRef = useRef(onTranscribed);
  const onInterimRef = useRef(onInterim);
  const statusRef = useRef<VoiceInputStatus>("off");
  const levelListenersRef = useRef(new Set<LevelListener>());

  pausedRef.current = paused;
  previewRef.current = preview;
  onTranscribedRef.current = onTranscribed;
  onInterimRef.current = onInterim;

  const setStatusSafe = useCallback((next: VoiceInputStatus) => {
    statusRef.current = next;
    setStatus(next);
  }, []);

  const emitInterim = useCallback((text: string) => {
    setInterimText(text);
    onInterimRef.current?.(text);
  }, []);

  const clearPreview = useCallback(() => {
    previewAbortRef.current?.abort();
    previewAbortRef.current = null;
    emitInterim("");
  }, [emitInterim]);

  const submitSegment = useCallback(async (frames: Int16Array[], spokenMs: number, seq: number) => {
    if (frames.length === 0 || spokenMs < MIN_SPEECH_MS) {
      // 无效段（咳嗽/碰撞等瞬态）：回聆听态，不进入 transcribing。
      setStatusSafe("listening");
      return;
    }
    inflightRef.current = true;
    setStatusSafe("transcribing");
    try {
      const blob = encodeWav(frames);
      const response = await apiService.transcribeAudio(blob);
      const text = (response.data?.text || "").trim();
      const asrMs = response.data?.processing_ms ?? null;
      setLastAsrMs(asrMs);
      if (text) {
        onTranscribedRef.current(text, { asrMs });
      }
    } catch {
      // 转写失败不终止实时模式：回到聆听状态即可，错误已在控制台可见。
      console.error("ASR request failed");
    } finally {
      inflightRef.current = false;
      if (statusRef.current === "transcribing") {
        setStatusSafe("listening");
      }
      // 最终文本落地后才清灰色字（被更快的新预览覆盖的情形除外）。
      if (utteranceSeqRef.current === seq) {
        emitInterim("");
      }
    }
  }, [emitInterim, setStatusSafe]);

  /** 灰色预测字：拿最近 PREVIEW_CONTEXT_MS 音频发一次识别。 */
  const maybePreview = useCallback(async (seq: number) => {
    if (!previewRef.current) return;
    // 上一次预览还在途：跳过本次刷新（推理慢时自然降频，省 CPU）。
    if (previewAbortRef.current) return;
    const now = performance.now();
    if (now - lastPreviewAtRef.current < REFRESH_INTERVAL_MS) return;
    lastPreviewAtRef.current = now;
    const frames = utteranceFramesRef.current;
    if (frames.length === 0) return;
    const previewFrames: Int16Array[] = [];
    let bytes = 0;
    // 上下文窗口：从最近往前收，直到 PREVIEW_CONTEXT_MS。
    const maxBytes = (PREVIEW_CONTEXT_MS / 1000) * TARGET_SAMPLE_RATE * 2;
    for (let i = frames.length - 1; i >= 0; i -= 1) {
      bytes += frames[i].length * 2;
      previewFrames.unshift(frames[i]);
      if (bytes >= maxBytes) break;
    }
    const controller = new AbortController();
    previewAbortRef.current = controller;
    try {
      const response = await apiService.transcribeAudio(encodeWav(previewFrames), { signal: controller.signal });
      if (utteranceSeqRef.current !== seq) return;
      const text = (response.data?.text || "").trim();
      if (text) emitInterim(text);
    } catch {
      // 预览失败静默：下一次刷新会重试，最终转写兜底。
    } finally {
      if (previewAbortRef.current === controller) {
        previewAbortRef.current = null;
      }
    }
  }, [emitInterim]);

  const startUtterance = useCallback((now: number) => {
    utteranceSeqRef.current += 1;
    const preRoll = preRollFramesRef.current;
    utteranceFramesRef.current = preRoll.map((frame) => frame.slice());
    speechStartedAtRef.current = now;
    lastVoiceAtRef.current = now;
    lastPreviewAtRef.current = 0;
    setStatusSafe("speech");
  }, [setStatusSafe]);

  const finishSegment = useCallback(() => {
    const frames = utteranceFramesRef.current;
    const spokenMs = lastVoiceAtRef.current - speechStartedAtRef.current;
    const seq = utteranceSeqRef.current;
    clearPreview();
    utteranceFramesRef.current = [];
    void submitSegment(frames, spokenMs, seq);
  }, [clearPreview, submitSegment]);

  const tick = useCallback((rms: number) => {
    const now = performance.now();
    lastRmsRef.current = rms;

    // 自适应噪声地板：缓慢下探跟随安静环境，快速上浮避免持续噪声误触。
    if (rms < noiseFloorRef.current) {
      noiseFloorRef.current = noiseFloorRef.current * 0.95 + rms * 0.05;
    } else if (rms > noiseFloorRef.current * 4) {
      noiseFloorRef.current = Math.min(noiseFloorRef.current * 1.02 + rms * 0.05, 0.2);
    }
    const threshold = Math.max(0.015, noiseFloorRef.current * 2.8);
    const isVoice = rms > threshold;

    const recording = statusRef.current === "speech";
    if (!recording && isVoice && !pausedRef.current && !inflightRef.current) {
      startUtterance(now);
      return;
    }
    if (recording) {
      if (isVoice) {
        lastVoiceAtRef.current = now;
      } else if (now - lastVoiceAtRef.current > SILENCE_HANGOVER_MS) {
        finishSegment();
        return;
      }
      if (now - speechStartedAtRef.current > MAX_UTTERANCE_MS) {
        finishSegment();
        return;
      }
      void maybePreview(utteranceSeqRef.current);
    }
  }, [finishSegment, maybePreview, startUtterance]);

  /** 音量订阅：音量条组件专挂，避免 level 高频更新打进主 state。 */
  const subscribeLevel = useCallback((listener: LevelListener) => {
    levelListenersRef.current.add(listener);
    listener(lastRmsRef.current);
    return () => levelListenersRef.current.delete(listener);
  }, []);

  const start = useCallback(async () => {
    if (statusRef.current !== "off") return;
    setStatusSafe("starting");
    setErrorHint(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      streamRef.current = stream;

      const AudioContextCtor = window.AudioContext
        || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AudioContextCtor) throw new Error("AudioContext unavailable");
      // 指定 16k 让浏览器做硬件级重采样；不支持时 worklet 里还有软件下采样。
      const context = new AudioContextCtor(
        { sampleRate: TARGET_SAMPLE_RATE } as ConstructorParameters<typeof AudioContext>[0],
      );
      await context.resume();
      audioContextRef.current = context;

      const workletUrl = URL.createObjectURL(
        new Blob([RECORDER_WORKLET], { type: "application/javascript" }),
      );
      workletUrlRef.current = workletUrl;
      await context.audioWorklet.addModule(workletUrl);

      const source = context.createMediaStreamSource(stream);
      const recorder = new AudioWorkletNode(context, "pcm-recorder");
      // PCM 帧三路分流：VAD 预滚窗口 / 当前句缓冲 / RMS 滑动窗口。
      // 预滚窗口保留最近 ~1.2s：语音起点检测天然滞后几十毫秒，用它补上
      // 句首几个字，改善吞字（对齐 Owl Meeting 降噪增益的同一目标）。
      const windowFrames: Int16Array[] = [];
      let windowBytes = 0;
      const windowMaxBytes = TARGET_SAMPLE_RATE * 2 * 1.2;
      recorder.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
        const frame = new Int16Array(event.data);
        preRollFramesRef.current.push(frame);
        preRollBytesRef.current += frame.length * 2;
        while (preRollBytesRef.current > windowMaxBytes && preRollFramesRef.current.length > 1) {
          const dropped = preRollFramesRef.current.shift();
          preRollBytesRef.current -= (dropped?.length || 0) * 2;
        }
        if (statusRef.current === "speech") {
          utteranceFramesRef.current.push(frame);
        }
        windowFrames.push(frame);
        windowBytes += frame.length * 2;
        while (windowBytes > windowMaxBytes && windowFrames.length > 1) {
          const dropped = windowFrames.shift();
          windowBytes -= (dropped?.length || 0) * 2;
        }
      };
      source.connect(recorder);
      // 不连 destination：纯数据通路，无监听回声。
      sourceRef.current = recorder;

      // RMS 从最近 ~1.2s 窗口重算（VAD 阈值按该窗口的自适应地板比较）。
      const tickRms = () => {
        let sum = 0;
        let count = 0;
        for (const frame of windowFrames) {
          for (let i = 0; i < frame.length; i += 1) {
            const normalized = frame[i] / 32768;
            sum += normalized * normalized;
          }
          count += frame.length;
        }
        const rms = count > 0 ? Math.sqrt(sum / count) : 0;
        for (const listener of levelListenersRef.current) listener(rms);
        tick(rms);
      };
      noiseFloorRef.current = 0.01;
      tickRef.current = window.setInterval(tickRms, TICK_MS);
      setStatusSafe("listening");
    } catch (error) {
      console.error("Failed to start voice input:", error);
      setErrorHint(
        error instanceof DOMException && error.name === "NotAllowedError"
          ? "permission"
          : "unavailable",
      );
      setStatusSafe("error");
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
  }, [setStatusSafe, tick]);

  const stop = useCallback(() => {
    if (tickRef.current !== null) {
      window.clearInterval(tickRef.current);
      tickRef.current = null;
    }
    clearPreview();
    utteranceFramesRef.current = [];
    preRollFramesRef.current = [];
    preRollBytesRef.current = 0;
    inflightRef.current = false;
    sourceRef.current?.disconnect();
    sourceRef.current = null;
    if (workletUrlRef.current) {
      URL.revokeObjectURL(workletUrlRef.current);
      workletUrlRef.current = null;
    }
    void audioContextRef.current?.close();
    audioContextRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setStatusSafe("off");
    emitInterim("");
  }, [clearPreview, emitInterim, setStatusSafe]);

  // 卸载兜底清理（切换角色/离开页面）。
  useEffect(() => stop, [stop]);

  return { status, start, stop, lastAsrMs, interimText, errorHint, subscribeLevel };
}
