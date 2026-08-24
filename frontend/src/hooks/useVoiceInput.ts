"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiService } from "@/utils/api";

/**
 * 实时模式的持续语音输入 hook。
 *
 * 交互模型（用户确认）：进入实时模式后不需要按住任何按钮——麦克风常开，
 * 自适应静音阈值（VAD）检测到说话开始录音，约 1.2s 静音即断句，
 * 自动上传 /chat/asr 转写后回调文本。AI 回复期间通过 `paused` 暂停新断句
 * （v1 不做打断，Phase B 再考虑）。
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
  /** true 时不开新断句（AI 回复进行中）。进行中的录音会自然收尾。 */
  paused: boolean;
}

/** 判定"说完"的静音时长；延迟预算的固定组成部分。 */
const SILENCE_HANGOVER_MS = 1200;
/** 有效语音的最短时长，过滤咳嗽/碰撞等瞬态噪声。 */
const MIN_SPEECH_MS = 400;
const TICK_MS = 50;

function pickRecorderMime(): string {
  if (typeof MediaRecorder === "undefined") return "";
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"];
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

export function useVoiceInput({ onTranscribed, paused }: UseVoiceInputOptions) {
  const [status, setStatus] = useState<VoiceInputStatus>("off");
  const [errorHint, setErrorHint] = useState<string | null>(null);
  const [lastAsrMs, setLastAsrMs] = useState<number | null>(null);

  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const tickRef = useRef<number | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const speechStartedAtRef = useRef<number>(0);
  const lastVoiceAtRef = useRef<number>(0);
  const noiseFloorRef = useRef(0.01);
  // 转写请求在途标记：防止同一片段重复提交。
  const inflightRef = useRef(false);
  const pausedRef = useRef(paused);
  const onTranscribedRef = useRef(onTranscribed);
  const statusRef = useRef<VoiceInputStatus>("off");

  pausedRef.current = paused;
  onTranscribedRef.current = onTranscribed;

  const setStatusSafe = useCallback((next: VoiceInputStatus) => {
    statusRef.current = next;
    setStatus(next);
  }, []);

  const finishSegment = useCallback(() => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") return;
    recorder.stop();
  }, []);

  const submitSegment = useCallback(async (blob: Blob, spokenMs: number) => {
    if (blob.size === 0 || spokenMs < MIN_SPEECH_MS) return;
    inflightRef.current = true;
    setStatusSafe("transcribing");
    try {
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
    }
  }, [setStatusSafe]);

  const tick = useCallback(() => {
    const analyser = audioContextRef.current?.state === "running"
      ? analyserRef.current
      : null;
    if (!analyser) return;

    const buffer = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(buffer);
    let sum = 0;
    for (let i = 0; i < buffer.length; i += 1) {
      const centered = (buffer[i] - 128) / 128;
      sum += centered * centered;
    }
    const rms = Math.sqrt(sum / buffer.length);
    const now = performance.now();

    // 自适应噪声地板：缓慢下探跟随安静环境，快速上浮避免持续噪声误触。
    if (rms < noiseFloorRef.current) {
      noiseFloorRef.current = noiseFloorRef.current * 0.95 + rms * 0.05;
    } else if (rms > noiseFloorRef.current * 4) {
      noiseFloorRef.current = Math.min(noiseFloorRef.current * 1.02 + rms * 0.05, 0.2);
    }
    const threshold = Math.max(0.015, noiseFloorRef.current * 2.8);
    const isVoice = rms > threshold;

    if (!recorderRef.current) {
      if (isVoice && !pausedRef.current && !inflightRef.current) {
        const stream = streamRef.current;
        if (!stream) return;
        const mimeType = pickRecorderMime();
        const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
        chunksRef.current = [];
        recorder.ondataavailable = (event) => {
          if (event.data.size > 0) chunksRef.current.push(event.data);
        };
        recorder.onstop = () => {
          const blob = new Blob(chunksRef.current, { type: mimeType || "audio/webm" });
          chunksRef.current = [];
          recorderRef.current = null;
          const spokenMs = lastVoiceAtRef.current - speechStartedAtRef.current;
          void submitSegment(blob, spokenMs);
        };
        recorder.start(250);
        speechStartedAtRef.current = now;
        lastVoiceAtRef.current = now;
        setStatusSafe("speech");
      }
      return;
    }

    if (isVoice) {
      lastVoiceAtRef.current = now;
    } else if (
      statusRef.current === "speech" &&
      now - lastVoiceAtRef.current > SILENCE_HANGOVER_MS
    ) {
      finishSegment();
    }
  }, [finishSegment, setStatusSafe, submitSegment]);

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
      const context = new AudioContextCtor();
      await context.resume();
      const source = context.createMediaStreamSource(stream);
      const analyser = context.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      analyserRef.current = analyser;
      audioContextRef.current = context;

      noiseFloorRef.current = 0.01;
      tickRef.current = window.setInterval(tick, TICK_MS);
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
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.onstop = null;
      recorder.stop();
    }
    recorderRef.current = null;
    chunksRef.current = [];
    analyserRef.current = null;
    void audioContextRef.current?.close();
    audioContextRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    inflightRef.current = false;
    setStatusSafe("off");
  }, [setStatusSafe]);

  // 卸载兜底清理（切换角色/离开页面）。
  useEffect(() => stop, [stop]);

  return { status, start, stop, lastAsrMs, errorHint };
}
