"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { RootState, Message, ChatSession, ModelConfig, ModelRoleAssignments, MessageAttachment, UserProfile, AgentStep } from '@/types';
import { useDispatch, useSelector } from 'react-redux';
import { setCharacter, addMessage, setMessages, setLoading, setError, clearChat, setChatSession, upsertMessage, appendToMessage, appendToMessageThinking, appendToMessageToolCall, updateMessageSteps, removeMessage, replaceMessage, updateChatSession, cacheMessages } from '@/store/chatSlice';
import ImmersiveChatWindow from '@/components/ImmersiveChatWindow';
import CameraPanel from '@/components/CameraPanel';
import SubtitleBar, { SubtitleContent } from '@/components/SubtitleOverlay';
import MicLevelMeter from '@/components/MicLevelMeter';
import { useVoiceInput } from '@/hooks/useVoiceInput';
import ResearchPanel from '@/components/ResearchPanel';
import SoulPanel from '@/components/SoulPanel';
import MemoryPanel from '@/components/MemoryPanel';
import { apiService, normalizeTokenUsage, SendMessageRequest, StreamMessageEvent } from '@/utils/api';
import { buildSpeechSegments, SpeechSegment } from '@/utils/replySegments';
import { AttachmentKind, getAttachmentAvailability } from '@/utils/modelCapabilities';
import { FolderTree, Brain, Globe, Menu, Mic, Monitor, Pencil, Video, Volume2 } from 'lucide-react';
import { createRoot } from 'react-dom/client';
import { useI18n } from '@/i18n/provider';

interface ChatInterfaceProps {
  characterId?: string;
  initialSessionId?: string | null;
  modelConfigs: ModelConfig[];
  modelRoles?: ModelRoleAssignments | null;
  defaultModelConfigId?: string | null;
  userProfile?: UserProfile | null;
  sessionOrigin?: 'topic' | 'chat';
  onBack?: () => void;
  onSessionUpdate?: () => void;
  onSoulRefreshKeyChange?: (value: string) => void;
  /** 话题模式：聚焦活动会话时 shell 顶栏隐藏，侧边栏开关并入本 header。 */
  onToggleSidebar?: () => void;
}

interface PendingAttachment {
  file: File;
  kind: AttachmentKind;
  previewUrl?: string;
}

function normalizeStreamMessage(apiMessage: {
  id: string | number;
  content: string;
  role: 'user' | 'assistant';
  timestamp: string;
  thinking?: string | null;
  raw_reasoning?: string | null;
  steps?: Array<{ kind: 'thinking' | 'tool'; text?: string; raw_text?: string; tool?: string; arguments?: Record<string, unknown> }>;
  tool_calls?: Array<{
    tool: string;
    arguments?: Record<string, unknown>;
  }>;
  file_uri?: string | null;
  file_name?: string | null;
  file_preview_url?: string | null;
  file_type?: string | null;
  file_mime_type?: string | null;
  attachments?: Array<{
    file_uri?: string | null;
    file_name?: string | null;
    file_preview_url?: string | null;
    file_type?: string | null;
    file_mime_type?: string | null;
  }>;
}): Message {
  const attachments: MessageAttachment[] = apiMessage.attachments?.length
    ? apiMessage.attachments.map((attachment) => ({
        fileUri: attachment.file_uri || undefined,
        fileName: attachment.file_name || undefined,
        filePreviewUrl: attachment.file_preview_url || undefined,
        fileType: attachment.file_type || undefined,
        fileMimeType: attachment.file_mime_type || undefined,
      }))
    : (apiMessage.file_name || apiMessage.file_uri || apiMessage.file_preview_url || apiMessage.file_type || apiMessage.file_mime_type)
      ? [{
          fileUri: apiMessage.file_uri || undefined,
          fileName: apiMessage.file_name || undefined,
          filePreviewUrl: apiMessage.file_preview_url || undefined,
          fileType: apiMessage.file_type || undefined,
          fileMimeType: apiMessage.file_mime_type || undefined,
        }]
      : [];
  const primaryAttachment = attachments[0];

  return {
    id: String(apiMessage.id),
    content: apiMessage.content || '',
    role: apiMessage.role,
    timestamp: apiMessage.timestamp,
    thinking: apiMessage.thinking || '',
    rawReasoning: apiMessage.raw_reasoning || '',
    steps: apiMessage.steps || undefined,
    toolCalls: (apiMessage.tool_calls || [])
      .filter((call) => call?.tool)
      .map((call) => ({
        tool: call.tool,
        arguments: call.arguments || {},
      })),
    attachments,
    fileUri: primaryAttachment?.fileUri || apiMessage.file_uri || undefined,
    fileName: primaryAttachment?.fileName || apiMessage.file_name || undefined,
    filePreviewUrl: primaryAttachment?.filePreviewUrl || apiMessage.file_preview_url || undefined,
    fileType: primaryAttachment?.fileType || apiMessage.file_type || undefined,
    fileMimeType: primaryAttachment?.fileMimeType || apiMessage.file_mime_type || undefined,
  };
}

function formatLatencyMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export default function ChatInterface({
  characterId,
  initialSessionId,
  modelConfigs,
  modelRoles,
  defaultModelConfigId,
  sessionOrigin,
  onSessionUpdate,
  onSoulRefreshKeyChange,
  onToggleSidebar,
}: ChatInterfaceProps) {
  const { messages: copy } = useI18n();
  const failedToLoadCharacterMessage = copy.chat.failedToLoadCharacter;
  const failedToLoadHistoryMessage = copy.chat.failedToLoadHistory;

  const [showResearchPanel, setShowResearchPanel] = useState(false);
  const [showSoulPanel, setShowSoulPanel] = useState(false);
  const [showMemoryPanel, setShowMemoryPanel] = useState(false);
  const [hasStartedConversation, setHasStartedConversation] = useState(false);
  const [chatSessionId, setChatSessionId] = useState<string | null>(initialSessionId || null);
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState('');

  const dispatch = useDispatch();
  const character = useSelector((state: RootState) => state.chat.character);
  const chatSession = useSelector((state: RootState) => state.chat.chatSession);
  const isLoading = useSelector((state: RootState) => state.chat.isLoading);
  const messages = useSelector((state: RootState) => state.chat.messages);
  const messagesBySession = useSelector((state: RootState) => state.chat.messagesBySession);

  // Natural-chat spec §2/§3.3: abortable streaming + queued sends.
  const abortRef = useRef<AbortController | null>(null);
  const pendingQueueRef = useRef<Array<{ text: string; attachments: PendingAttachment[] }>>([]);
  const [pendingQueueTexts, setPendingQueueTexts] = useState<string[]>([]);
  const handleSendMessageRef = useRef<(message: string, attachments: PendingAttachment[]) => void>(() => {});
  // Memory-growth chip (memory v2 §5.1): poll count after each turn.
  const lastMemoryCountRef = useRef<number | null>(null);
  const [memoryNotice, setMemoryNotice] = useState<string | null>(null);
  // 联网搜索配置缺失提示（2026-08-24：开启但未配 key 时提醒用户）
  const [webSearchMissingKey, setWebSearchMissingKey] = useState(false);
  // 实时模式（语音 ASR + 可选摄像头/屏幕帧）：转写文本自动发送，回复完成后继续聆听。
  const [realtimeOn, setRealtimeOn] = useState(false);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [screenOpen, setScreenOpen] = useState(false);
  const [subtitlesVisible, setSubtitlesVisible] = useState(true);
  const [subtitlePipActive, setSubtitlePipActive] = useState(false);
  const [realtimeNotice, setRealtimeNotice] = useState<string | null>(null);
  const [asrReady, setAsrReady] = useState<{ available: boolean; hint: string } | null>(null);
  const [lastTurnLatency, setLastTurnLatency] = useState<{ firstMs: number | null; totalMs: number } | null>(null);
  // 灰色预测字开关（Owl 低延迟模式机制）：localStorage 持久化，默认开。
  const [sttPreviewOn, setSttPreviewOn] = useState(
    () => typeof window !== 'undefined' && window.localStorage.getItem('prismate.sttPreview') !== '0',
  );
  // 主模型快速切换：记录本会话内最近一次切换（PUT /model-roles 已同步服务端），
  // 未切换时回退到角色分配 / 默认配置。
  const [textModelOverrideId, setTextModelOverrideId] = useState<string | null>(null);
  // 语音回复（TTS）：开启后角色回复按句合成并自动朗读。
  const [voiceReplyOn, setVoiceReplyOn] = useState(
    () => typeof window !== 'undefined' && window.localStorage.getItem('prismate.voiceReply') === '1',
  );
  const [ttsReady, setTtsReady] = useState<{ available: boolean; hint: string } | null>(null);
  // 卡拉OK高亮状态：正在朗读/合成的句属于哪条消息、第几句（传给 ImmersiveChatWindow）。
  const [speechPlayback, setSpeechPlayback] = useState<{
    messageId: string;
    activeIndex: number | null;
    synthesizingIndex: number | null;
  } | null>(null);
  const voiceReplyRef = useRef(voiceReplyOn);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const speakCancelRef = useRef(false);
  voiceReplyRef.current = voiceReplyOn;
  // frameGrabberRef 挂摄像头抓帧、screenGrabberRef 挂屏幕抓帧；同轮附帧时屏幕优先。
  const frameGrabberRef = useRef<(() => File | null) | null>(null);
  const screenGrabberRef = useRef<(() => File | null) | null>(null);
  const lastFrameAtRef = useRef(0);
  const subtitlePipRef = useRef<{
    window: Window;
    root: { render: (node: React.ReactNode) => void; unmount: () => void };
  } | null>(null);
  const characterIdForMemory = character?.id;

  // 实时模式：转写文本直接走发送 ref（loading 中会自动排队，见 handleSendMessage），
  // 屏幕共享或摄像头开着且距上帧 ≥5s 时随本轮附带一帧（屏幕优先），让角色"看到"用户。
  // 灰色预测字经 voiceInput.interimText 提升到本组件 state（字幕条 + PiP 窗消费）。
  const [interimText, setInterimText] = useState('');
  const voiceInput = useVoiceInput({
    paused: isLoading,
    preview: sttPreviewOn,
    onInterim: setInterimText,
    onTranscribed: (text) => {
      if (!text.trim()) return;
      const attachments: PendingAttachment[] = [];
      const now = performance.now();
      if (now - lastFrameAtRef.current > 5000) {
        const grab = screenGrabberRef.current || frameGrabberRef.current;
        const file = grab ? grab() : null;
        if (file) {
          attachments.push({ file, kind: 'image', previewUrl: URL.createObjectURL(file) });
          lastFrameAtRef.current = now;
        }
      }
      handleSendMessageRef.current(text, attachments);
    },
  });

  const registerCameraGrabber = useCallback((grab: (() => File | null) | null) => {
    frameGrabberRef.current = grab;
  }, []);

  const registerScreenGrabber = useCallback((grab: (() => File | null) | null) => {
    screenGrabberRef.current = grab;
  }, []);

  // 语音回复（TTS）：逐句合成、顺序朗读；随时可取消（取消同时清掉高亮）。
  const cancelSpeech = useCallback(() => {
    speakCancelRef.current = true;
    currentAudioRef.current?.pause();
    currentAudioRef.current = null;
    setSpeechPlayback(null);
  }, []);

  const playBlob = (blob: Blob) => new Promise<void>((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    currentAudioRef.current = audio;
    audio.onended = () => {
      URL.revokeObjectURL(url);
      resolve();
    };
    audio.onpause = () => {
      URL.revokeObjectURL(url);
      reject(new Error('speech cancelled'));
    };
    audio.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('speech playback failed'));
    };
    void audio.play().catch(() => reject(new Error('speech autoplay blocked')));
  });

  // 语音分段：后端对带【情感】标记的回复做解析后的产物；emotion 空 = 默认情感。
  // 情感分段只服务于朗读（见 done 事件处理），前端展示分句见 utils/replySegments。

  // 单段朗读（消息气泡旁的喇叭按钮）：不依赖全局"自动朗读"开关，独立发声。
  // 点击时合成并缓存，后续点击直接播放缓存。不预合成（预合成曾导致缓存与渲染
  // 段落不一致，产生"播放内容混入别的文本"的 bug）。
  const ttsQueueRef = useRef<Promise<unknown>>(Promise.resolve());
  const runTtsSerialized = useCallback(<T,>(task: () => Promise<T>): Promise<T> => {
    const run = ttsQueueRef.current.then(task, task);
    ttsQueueRef.current = run.then(
      () => undefined,
      () => undefined,
    );
    return run;
  }, []);

  const segmentAudioCacheRef = useRef<Map<string, Blob>>(new Map());

  const synthesizeSegmentCached = useCallback(async (text: string, emotion?: string): Promise<Blob> => {
    const cacheKey = `${character?.id ?? 'global'}:${emotion ?? ''}:${text}`;
    const cached = segmentAudioCacheRef.current.get(cacheKey);
    if (cached) {
      return cached;
    }
    const blob = await runTtsSerialized(() =>
      apiService.synthesizeSpeech(text.trim(), {
        characterId: character?.id,
        emotion,
      }),
    );
    segmentAudioCacheRef.current.set(cacheKey, blob);
    return blob;
  }, [character?.id, runTtsSerialized]);

  /** 语音队列：按句段顺序合成并朗读，每句同步卡拉OK高亮状态；随时可取消。 */
  const runSpeechQueue = async (messageId: string, segments: SpeechSegment[]) => {
    if (!segments.length) return;
    speakCancelRef.current = false;
    for (let index = 0; index < segments.length; index += 1) {
      if (speakCancelRef.current) return;
      setSpeechPlayback({ messageId, activeIndex: null, synthesizingIndex: index });
      try {
        const blob = await synthesizeSegmentCached(segments[index].text, segments[index].emotion);
        if (speakCancelRef.current) return;
        setSpeechPlayback({ messageId, activeIndex: index, synthesizingIndex: null });
        await playBlob(blob);
      } catch {
        break; // 合成或播放失败（含被取消）即停止本轮朗读
      }
    }
    setSpeechPlayback(null);
  };
  const speakQueueRef = useRef<(messageId: string, segments: SpeechSegment[]) => Promise<void>>(async () => {});
  speakQueueRef.current = runSpeechQueue;

  /** 单句试听：点击气泡中的句子，独立合成并播放该句。 */
  const speakSentence = async (messageId: string, index: number, segment: SpeechSegment) => {
    if (!segment.text.trim()) return;
    cancelSpeech();
    speakCancelRef.current = false;
    setSpeechPlayback({ messageId, activeIndex: index, synthesizingIndex: index });
    try {
      const blob = await synthesizeSegmentCached(segment.text, segment.emotion);
      if (speakCancelRef.current) return;
      setSpeechPlayback({ messageId, activeIndex: index, synthesizingIndex: null });
      await playBlob(blob);
    } catch {
      // 合成或播放失败即静默停止
    }
    setSpeechPlayback((current) => (current && current.messageId === messageId ? null : current));
  };

  /** 整条回复连播：先停掉当前朗读，再从第一句开始按句播放。 */
  const handlePlayAll = (messageId: string, segments: SpeechSegment[]) => {
    cancelSpeech();
    void speakQueueRef.current(messageId, segments);
  };

  // 单段音频下载：优先用缓存，否则现场合成后以 .wav 保存到本地。
  const downloadSegment = async (text: string) => {
    if (!text.trim()) return;
    try {
      const blob = await synthesizeSegmentCached(text);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${character?.name || 'voice'}-segment-${Date.now()}.wav`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch {
      // 合成失败即静默停止
    }
  };

  useEffect(() => cancelSpeech, [cancelSpeech]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await apiService.getTtsReadiness();
        if (!cancelled && response.data) {
          setTtsReady({ available: response.data.available, hint: response.data.hint });
        }
      } catch {
        // readiness is best-effort
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const toggleVoiceReply = async () => {
    if (voiceReplyOn) {
      cancelSpeech();
      setVoiceReplyOn(false);
      window.localStorage.removeItem('prismate.voiceReply');
      return;
    }

    let readiness = ttsReady;
    if (!readiness) {
      try {
        const response = await apiService.getTtsReadiness();
        if (response.data) {
          readiness = { available: response.data.available, hint: response.data.hint };
          setTtsReady(readiness);
        }
      } catch {
        // readiness is best-effort; fall through and try enabling anyway.
      }
    }
    if (readiness && !readiness.available) {
      setRealtimeNotice(readiness.hint || copy.realtime.voiceReplyUnavailable);
      window.setTimeout(() => setRealtimeNotice(null), 6000);
      return;
    }

    setVoiceReplyOn(true);
    window.localStorage.setItem('prismate.voiceReply', '1');
  };

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await apiService.getAsrReadiness();
        if (!cancelled && response.data) {
          setAsrReady({ available: response.data.available, hint: response.data.hint });
        }
      } catch {
        // readiness is best-effort
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const toggleRealtime = async () => {
    if (realtimeOn || voiceInput.status !== 'off') {
      voiceInput.stop();
      setRealtimeOn(false);
      if (subtitlePipActive) {
        closeSubtitlePip();
      }
      return;
    }

    let readiness = asrReady;
    if (!readiness) {
      try {
        const response = await apiService.getAsrReadiness();
        if (response.data) {
          readiness = { available: response.data.available, hint: response.data.hint };
          setAsrReady(readiness);
        }
      } catch {
        // readiness is best-effort; fall through and try starting anyway.
      }
    }
    if (readiness && !readiness.available) {
      setRealtimeNotice(copy.realtime.asrNotReady(readiness.hint));
      window.setTimeout(() => setRealtimeNotice(null), 6000);
      return;
    }

    setRealtimeOn(true);
    setSubtitlesVisible(true);
    await voiceInput.start();
  };

  useEffect(() => {
    if (voiceInput.status !== 'error') return;
    setRealtimeNotice(
      voiceInput.errorHint === 'permission'
        ? copy.realtime.statusErrorPermission
        : copy.realtime.statusErrorUnavailable,
    );
    const timer = window.setTimeout(() => setRealtimeNotice(null), 6000);
    return () => window.clearTimeout(timer);
  }, [copy, voiceInput.errorHint, voiceInput.status]);

  // 切换角色时结束实时会话，避免把下一句话转写发给新角色。
  const activeCharacterIdRef = useRef<string | undefined>(characterId);
  useEffect(() => {
    if (activeCharacterIdRef.current === characterId) return;
    activeCharacterIdRef.current = characterId;
    if (statusRefSafe()) {
      voiceInput.stop();
      setRealtimeOn(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [characterId]);

  const closeSubtitlePip = useCallback(() => {
    const entry = subtitlePipRef.current;
    if (!entry) return;
    subtitlePipRef.current = null;
    setSubtitlePipActive(false);
    try {
      entry.root.unmount();
    } catch {
      // window 已关闭时忽略
    }
    entry.window.close();
  }, []);

  const openSubtitlePip = useCallback(async () => {
    const dpip = (
      window as unknown as {
        documentPictureInPicture?: {
          requestWindow: (options: { width: number; height: number }) => Promise<Window>;
        };
      }
    ).documentPictureInPicture;
    if (!dpip) {
      setRealtimeNotice(copy.realtime.subtitlePopUnavailable);
      window.setTimeout(() => setRealtimeNotice(null), 6000);
      return;
    }
    try {
      const win = await dpip.requestWindow({ width: 520, height: 170 });
      const host = win.document.createElement('div');
      win.document.body.style.margin = '0';
      win.document.body.style.background = '#0f172a';
      win.document.body.style.padding = '14px 18px';
      win.document.title = 'Subtitles';
      win.document.body.appendChild(host);
      const root = createRoot(host);
      root.render(<SubtitleContent pip userText="" assistantText="" />);
      win.addEventListener('pagehide', () => {
        subtitlePipRef.current = null;
        setSubtitlePipActive(false);
        try {
          root.unmount();
        } catch {
          // already gone
        }
      });
      subtitlePipRef.current = { window: win, root };
      setSubtitlePipActive(true);
    } catch (error) {
      console.error('Failed to open subtitle PiP window:', error);
      setRealtimeNotice(copy.realtime.subtitlePopUnavailable);
      window.setTimeout(() => setRealtimeNotice(null), 6000);
    }
  }, [copy]);

  function statusRefSafe() {
    return voiceInput.status !== 'off';
  }
  useEffect(() => {
    if (!characterIdForMemory) return;
    let cancelled = false;
    void (async () => {
      try {
        const response = await apiService.getWebSearchReadiness(characterIdForMemory);
        if (!cancelled && response.data) {
          setWebSearchMissingKey(Boolean(response.data.enabled && !response.data.configured));
        }
      } catch {
        // readiness is best-effort
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [characterIdForMemory]);

  useEffect(() => {
    if (!characterIdForMemory) return;
    let cancelled = false;
    void (async () => {
      try {
        const response = await apiService.getCharacterMemory(characterIdForMemory);
        if (!cancelled && response.data && response.data.count != null) {
          lastMemoryCountRef.current = response.data.count;
        }
      } catch {
        // Baseline is best-effort; the chip simply stays quiet on failure.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [characterIdForMemory]);

  useEffect(() => {

    const loadCharacter = async () => {
      if (character && (!characterId || character.id === characterId)) {
        return;
      }

      dispatch(setLoading(true));
      try {
        let serverCharacter;

        if (characterId) {
          const response = await apiService.getCharacter(characterId);
          if (response.data) {
            serverCharacter = response.data;
          } else {
            throw new Error(failedToLoadCharacterMessage);
          }
        } else {
          const response = await apiService.getCharacters();
          if (response.data && response.data.length > 0) {
            serverCharacter = response.data[0];
          }
        }

        if (serverCharacter) {
          dispatch(setCharacter(serverCharacter));
        } else {
          console.error("Fatal Error: Character not found in database.");
        }
      } catch (error) {
        console.error("Failed to load character:", error);
        dispatch(setError(error instanceof Error ? error.message : failedToLoadCharacterMessage));
      } finally {
        dispatch(setLoading(false));
      }
    };

    loadCharacter();
  }, [dispatch, character, characterId, failedToLoadCharacterMessage]);

  // 缓存命中：绘制前同步渲染上次的历史（配合子组件 useLayoutEffect 钉底），
  // 切换会话的第一帧就是最底部，全程无加载占位；随后后台静默刷新。
  const seededSessionRef = useRef<string | null | undefined>(undefined);
  useLayoutEffect(() => {
    if (seededSessionRef.current === initialSessionId) return;
    seededSessionRef.current = initialSessionId;
    if (!initialSessionId) return;
    const cached = messagesBySession[initialSessionId];
    if (cached && cached.length > 0 && messages.length === 0) {
      dispatch(setMessages(cached));
      setHasStartedConversation(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSessionId]);

  useEffect(() => {
    const loadChatHistory = async () => {
      if (!initialSessionId) {
        dispatch(clearChat());
        dispatch(setChatSession(null));
        setChatSessionId(null);
        setHasStartedConversation(false);
        return;
      }

      // 缓存命中时不清屏、不转圈：上面已同步渲染缓存历史，这里只做
      // 后台静默刷新；无缓存的冷打开才显示加载占位。
      const cached = messagesBySession[initialSessionId];
      const hasCache = Boolean(cached && cached.length > 0);
      if (!hasCache) {
        dispatch(clearChat());
        dispatch(setLoading(true));
      }
      setChatSessionId(initialSessionId);

      try {
        const [messagesRes, sessionRes] = await Promise.all([
          apiService.getMessages(initialSessionId),
          apiService.getChatSession(initialSessionId),
        ]);

        if (messagesRes.data && messagesRes.data.length > 0) {
          dispatch(setMessages(messagesRes.data));
          dispatch(cacheMessages({ sessionId: initialSessionId, messages: messagesRes.data }));
          setHasStartedConversation(true);
        } else if (!hasCache) {
          setHasStartedConversation(false);
        }

        if (sessionRes.data) {
          dispatch(setChatSession(sessionRes.data));
        }
      } catch (err) {
        console.error("Failed to load chat history:", err);
        if (!hasCache) {
          dispatch(setError(failedToLoadHistoryMessage));
        }
      } finally {
        if (!hasCache) {
          dispatch(setLoading(false));
        }
      }
    };

    loadChatHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSessionId, dispatch, failedToLoadHistoryMessage]);

  const syncSessionState = async (sessionId: string, options?: { pollUntilTitled?: boolean }) => {
    const pollUntilTitled = options?.pollUntilTitled ?? false;
    let originalTitle: string | null = null;
    const deadline = Date.now() + 20000;

    // v0.1.6: 标题由后端在 done 事件之后异步生成（收尾派发）。若这里轮询，
    // 则等自动标题落地后再刷新，避免界面一直停留在 "Chat with …" 旧值。
    for (;;) {
      const response = await apiService.getChatSession(sessionId);
      if (!response.data) {
        return;
      }
      const title = response.data.title || '';
      if (originalTitle === null) {
        originalTitle = title;
      }
      dispatch(setChatSession(response.data as ChatSession));
      // 标题已从默认值变为自动生成的标题（或本就不需要生成：greeting 轮/
      // 手动标题下第一次循环即退出，零额外等待）。
      if (!pollUntilTitled || title !== originalTitle || Date.now() > deadline) {
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
  };

  const startEditTitle = () => {
    setTitleDraft(chatSession?.title || '');
    setIsEditingTitle(true);
  };

  const handleSaveTitle = async () => {
    const trimmed = titleDraft.trim();
    setIsEditingTitle(false);

    if (!chatSessionId || !trimmed || trimmed === (chatSession?.title || '')) {
      return;
    }

    try {
      const response = await apiService.updateChatSession(chatSessionId, { title: trimmed });
      if (response.data) {
        dispatch(updateChatSession({ title: response.data.title }));
        onSessionUpdate?.();
      }
    } catch (error) {
      console.error('Failed to update session title:', error);
    }
  };

  const handleSendMessage = async (userInput: string, attachments: PendingAttachment[] = []) => {
    if (!character) return;

    // 新一轮开始时停止上一轮的朗读，避免声音交叠。
    cancelSpeech();

    // While a reply is streaming, submissions are queued and auto-sent when
    // the current turn finishes (natural-chat spec §2) instead of being blocked.
    if (isLoading) {
      const queuedText = userInput.trim();
      if (!queuedText && attachments.length === 0) return;
      pendingQueueRef.current = [...pendingQueueRef.current, { text: queuedText, attachments }];
      setPendingQueueTexts(pendingQueueRef.current.map((item) => item.text));
      return;
    }

    const isFirstMessage = !hasStartedConversation;
    const trimmedInput = userInput.trim();
    const streamingAssistantId = `stream-${Date.now()}`;
    const optimisticUserMessageId = `local-user-${Date.now()}`;
    const previousStartedState = hasStartedConversation;
    const currentUserLabel = copy.chat.you;
    const optimisticAttachments: MessageAttachment[] = attachments.map((attachment) => ({
      fileName: attachment.file.name,
      fileType: attachment.kind,
      fileMimeType: attachment.file.type || undefined,
      filePreviewUrl:
        attachment.kind === 'image' || attachment.kind === 'video'
          ? URL.createObjectURL(attachment.file)
          : undefined,
    }));
    const primaryOptimisticAttachment = optimisticAttachments[0];

    if (!isFirstMessage && !trimmedInput && attachments.length === 0) {
      return;
    }

    // 问候轮（首条且无文字无附件，角色先开口）没有用户消息可显示；带文字或
    // 附件的首条是真实对话轮，和后续消息一样先乐观上屏，不等服务端 session 事件。
    const isGreetingTurn = isFirstMessage && !trimmedInput && attachments.length === 0;

    if (isFirstMessage) {
      setHasStartedConversation(true);
    }

    if (!isGreetingTurn) {
      dispatch(addMessage({
        id: optimisticUserMessageId,
        content: trimmedInput,
        role: 'user',
        timestamp: new Date().toISOString(),
        senderId: 'user',
        senderName: currentUserLabel,
        senderType: 'user',
        attachments: optimisticAttachments,
        fileName: primaryOptimisticAttachment?.fileName,
        fileType: primaryOptimisticAttachment?.fileType,
        fileMimeType: primaryOptimisticAttachment?.fileMimeType,
        filePreviewUrl: primaryOptimisticAttachment?.filePreviewUrl,
        fileUri: primaryOptimisticAttachment?.filePreviewUrl,
      }));
    }

    dispatch(upsertMessage({
      id: streamingAssistantId,
      content: '',
      role: 'assistant',
      timestamp: new Date().toISOString(),
      senderId: character.id,
      senderName: character.name,
      senderAvatarUrl: character.avatarUrl,
      senderType: 'character',
    }));

    dispatch(setLoading(true));
    dispatch(setError(null));

    // 流式时间线（v0.1.5）：按轮构建"思考 · 第 N 轮 / 工具"步骤——生成过程中
    // 按序逐步出现在占位消息上，不再只有 done 之后才看到完整列表。
    const streamSteps: AgentStep[] = [];
    let streamThinkingRound: number | null = null;
    let streamThinkingParts: string[] = [];
    const buildLiveSteps = (): AgentStep[] => {
      const result = [...streamSteps];
      const pending = streamThinkingParts.join('');
      if (pending.trim()) {
        result.push({ kind: 'thinking', text: pending });
      }
      return result;
    };
    const flushLiveThinking = () => {
      const text = streamThinkingParts.join('').trim();
      if (text) {
        streamSteps.push({ kind: 'thinking', text });
      }
      streamThinkingParts = [];
    };

    const controller = new AbortController();
    abortRef.current = controller;
    let streamedContent = '';
    // 延迟埋点：首字与整轮耗时，供实时模式角标展示（docs/latency 记录协议）。
    const turnStartedAt = performance.now();
    let firstTokenAt: number | null = null;

    try {
      const requestData: SendMessageRequest = {
        message: trimmedInput,
        character_id: character.id,
        chat_session_id: chatSessionId || undefined,
        // Greeting only fires for an explicit empty-composer start on a fresh
        // session; a typed first message is a real turn and must be saved and
        // answered (memory v2 spec §3.3).
        start_conversation: isFirstMessage && !trimmedInput && attachments.length === 0,
        origin: sessionOrigin,
        attachments: attachments.map((attachment) => attachment.file),
      };

      const response = await apiService.streamMessage(requestData, {
        onEvent: (event: StreamMessageEvent) => {          if (event.type === 'session') {
            setChatSessionId(String(event.chat_session_id));
            if (event.user_message) {
              optimisticAttachments.forEach((attachment) => {
                if (attachment.filePreviewUrl?.startsWith('blob:')) {
                  URL.revokeObjectURL(attachment.filePreviewUrl);
                }
              });
              // 原位换成服务端消息：保持"用户消息在流式回复占位符之上"的顺序。
              dispatch(replaceMessage({
                id: optimisticUserMessageId,
                message: {
                  ...normalizeStreamMessage(event.user_message),
                  senderId: 'user',
                  senderName: currentUserLabel,
                  senderType: 'user',
                },
              }));
            }
            return;
          }

          if (event.type === 'delta') {
            if (firstTokenAt === null) {
              firstTokenAt = performance.now();
            }
            streamedContent += event.content;
            dispatch(appendToMessage({
              id: streamingAssistantId,
              content: event.content,
            }));
            return;
          }

          if (event.type === 'thinking') {
            // 轮次切换时把上一轮思考结算成一条"思考 · 第 N 轮"步骤；
            // 同轮增量追加到当前步骤文本（随时间增长）。
            const roundKey = (event as StreamMessageEvent & { round?: number }).round ?? null;
            if (roundKey !== streamThinkingRound) {
              flushLiveThinking();
              streamThinkingRound = roundKey;
            }
            streamThinkingParts.push(event.content);
            dispatch(updateMessageSteps({ id: streamingAssistantId, steps: buildLiveSteps() }));
            dispatch(appendToMessageThinking({
              id: streamingAssistantId,
              content: event.content,
            }));
            return;
          }

          if (event.type === 'tool') {
            // 工具步骤紧随本轮思考之后，保证"思考→工具→思考→工具…"的顺序。
            flushLiveThinking();
            streamSteps.push({ kind: 'tool', tool: event.tool, arguments: event.arguments || {} });
            dispatch(updateMessageSteps({ id: streamingAssistantId, steps: buildLiveSteps() }));
            dispatch(appendToMessageToolCall({
              id: streamingAssistantId,
              toolCall: {
                tool: event.tool,
                arguments: event.arguments || {},
              },
            }));
            return;
          }

          if (event.type === 'done') {
            // 情感分段（后端解析【情感】标记的产物）随消息保存，供逐句朗读继承语气。
            const ttsSegments = Array.isArray(event.tts_segments)
              ? event.tts_segments.filter((seg) => seg?.text)
              : [];
            dispatch(removeMessage(streamingAssistantId));
            dispatch(addMessage({
              id: String(event.message_id),
              content: event.content,
              role: 'assistant',
              timestamp: event.timestamp,
              senderId: character.id,
              senderName: character.name,
              senderAvatarUrl: character.avatarUrl,
              senderType: 'character',
              thinking: event.thinking || '',
              rawReasoning: event.raw_reasoning || '',
              steps: Array.isArray(event.steps) ? event.steps : undefined,
              toolCalls: (event.tool_calls || [])
                .filter((call) => call?.tool)
                .map((call) => ({
                  tool: call.tool,
                  arguments: call.arguments || {},
                })),
              ttsSegments,
              tokenUsage: normalizeTokenUsage(event.token_usage),
              researchPayload: event.research_payload ? {
                query: event.research_payload.query || '',
                provider: event.research_payload.provider || '',
                items: (event.research_payload.items || []).filter((item) => item?.url).map((item) => ({
                  title: item?.title || item?.url || copy.chat.untitled,
                  url: item?.url || '',
                  snippet: item?.snippet || '',
                  domain: item?.domain || '',
                  source: item?.source || '',
                })),
                error: event.research_payload.error || '',
              } : null,
            }));
            // 语音回复开启时，回复完成后按句合成朗读；情感以后端分段为准，
            // 角色未配情感组时（无分段）全部走默认语气。
            if (voiceReplyRef.current) {
              void speakQueueRef.current(
                String(event.message_id),
                buildSpeechSegments(event.content || '', ttsSegments),
              );
            }
            return;
          }

          if (event.type === 'error') {
            throw new Error(event.error);
          }
        },
      }, { signal: controller.signal });

      if (controller.signal.aborted || (response as { aborted?: boolean }).aborted) {
        // Stopped by the user: keep whatever partial content streamed in as a
        // regular bubble. The backend does not persist interrupted replies.
        dispatch(removeMessage(streamingAssistantId));
        const partial = streamedContent.trim();
        if (partial) {
          dispatch(addMessage({
            id: `${streamingAssistantId}-stopped`,
            content: partial,
            role: 'assistant',
            timestamp: new Date().toISOString(),
            senderId: character.id,
            senderName: character.name,
            senderAvatarUrl: character.avatarUrl,
            senderType: 'character',
          }));
        }
        return;
      }

      if (response.error) {
        throw new Error(response.error);
      }

      setLastTurnLatency({
        firstMs: firstTokenAt !== null ? Math.round(firstTokenAt - turnStartedAt) : null,
        totalMs: Math.round(performance.now() - turnStartedAt),
      });

      if (response.data?.chat_session_id) {
        setChatSessionId(response.data.chat_session_id);
        await syncSessionState(response.data.chat_session_id, { pollUntilTitled: true });

        if (onSessionUpdate) {
          onSessionUpdate();
          setTimeout(() => {
            onSessionUpdate();
          }, 1500);
        }
      }
    } catch (error) {
      console.error('Error sending message:', error);
      optimisticAttachments.forEach((attachment) => {
        if (attachment.filePreviewUrl?.startsWith('blob:')) {
          URL.revokeObjectURL(attachment.filePreviewUrl);
        }
      });
      dispatch(removeMessage(optimisticUserMessageId));
      dispatch(removeMessage(streamingAssistantId));
      if (!previousStartedState) {
        setHasStartedConversation(false);
      }

      const errorMessageContent = error instanceof Error ? error.message : copy.chat.failedToGetResponse;
      dispatch(setError(errorMessageContent));

      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        content: copy.chat.sorryEncounteredError(errorMessageContent),
        role: 'assistant',
        timestamp: new Date().toISOString(),
        senderId: character.id,
        senderName: character.name,
        senderAvatarUrl: character.avatarUrl,
        senderType: 'character',
      };
      dispatch(addMessage(errorMessage));
    } finally {
      dispatch(setLoading(false));
      abortRef.current = null;

      // Auto-send queued submissions (natural-chat spec §2). The short delay
      // absorbs stragglers so a burst of messages becomes one merged turn.
      const queued = pendingQueueRef.current;
      if (queued.length > 0) {
        pendingQueueRef.current = [];
        setPendingQueueTexts([]);
        const mergedText = queued.map((item) => item.text).filter(Boolean).join('\n\n');
        const mergedAttachments = queued.flatMap((item) => item.attachments);
        window.setTimeout(() => {
          handleSendMessageRef.current(mergedText, mergedAttachments);
        }, 800);
      }

      // Memory-growth chip (memory v2 §5.1): compare entry count after the turn.
      if (character) {
        void (async () => {
          try {
            const memoryResponse = await apiService.getCharacterMemory(character.id);
            const count = memoryResponse.data?.count ?? null;
            if (count != null && lastMemoryCountRef.current != null && count > lastMemoryCountRef.current) {
              setMemoryNotice(copy.immersiveChat.memoryGrew(count - lastMemoryCountRef.current));
              window.setTimeout(() => setMemoryNotice(null), 6000);
            }
            if (count != null) {
              lastMemoryCountRef.current = count;
            }
          } catch {
            // Chip is best-effort; ignore polling failures.
          }
        })();
      }
    }
  };

  const handleStopStreaming = () => {
    abortRef.current?.abort();
  };

  handleSendMessageRef.current = handleSendMessage;

  const realtimeStatusLabel = () => {
    if (voiceInput.status === 'starting') return copy.realtime.statusStarting;
    if (voiceInput.status === 'speech') return copy.realtime.statusSpeech;
    if (voiceInput.status === 'transcribing') return copy.realtime.statusTranscribing;
    if (voiceInput.status === 'listening') return copy.realtime.statusListening;
    // off / error 状态显示开关本身的文案，避免误导"已在聆听"。
    return copy.realtime.toggle;
  };

  let subtitleUserText = '';
  let subtitleAssistantText = '';
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (!subtitleAssistantText && message.role === 'assistant' && message.content) {
      subtitleAssistantText = message.content;
    }
    if (!subtitleUserText && message.role === 'user' && message.content) {
      subtitleUserText = message.content;
    }
    if (subtitleUserText && subtitleAssistantText) break;
  }

  useEffect(() => {
    const entry = subtitlePipRef.current;
    if (!entry) return;
    entry.root.render(
      <SubtitleContent pip interimText={interimText} userText={subtitleUserText} assistantText={subtitleAssistantText} />,
    );
  }, [interimText, subtitleAssistantText, subtitleUserText]);

  const handleTextModelChange = async (modelId: string) => {
    const response = await apiService.updateModelRoles({ text: modelId });
    if (response.error) {
      dispatch(setError(response.error));
      return;
    }
    setTextModelOverrideId(modelId);
  };

  const activeModelConfig =
    (textModelOverrideId
      ? modelConfigs.find((config) => config.id === textModelOverrideId)
      : null) ||
    modelRoles?.text ||
    modelConfigs.find((config) => config.id === defaultModelConfigId) ||
    null;
  const attachmentSupport = getAttachmentAvailability(modelRoles, activeModelConfig);
  const localizedMediaMode = (mode: 'analyzed' | 'native' | 'unavailable') =>
    ({
      analyzed: copy.modelApi.attachmentModes.analyzed,
      native: copy.modelApi.attachmentModes.native,
      unavailable: copy.modelApi.attachmentModes.unavailable,
    }[mode]);
  const latestResearchMessage = [...messages].reverse().find(
    (message) => message.role === 'assistant' && message.researchPayload
  ) || null;
  const soulRefreshKey = `${chatSession?.updatedAt || 'no-session'}:${latestResearchMessage?.id || 'no-research'}`;

  useEffect(() => {
    onSoulRefreshKeyChange?.(soulRefreshKey);
  }, [onSoulRefreshKeyChange, soulRefreshKey]);

  return (
    <div className="flex h-full flex-col bg-[linear-gradient(180deg,#f8fbff_0%,#eef4f8_52%,#f4efe8_100%)]">
      <header className="flex flex-shrink-0 items-center justify-between gap-3 border-b border-slate-200/70 bg-white/75 px-4 py-3 backdrop-blur-xl md:px-6">
        <div className="flex min-w-0 items-center gap-3">
          {onToggleSidebar && (
            <button
              type="button"
              onClick={onToggleSidebar}
              className="rounded-xl p-2 text-slate-500 transition-colors hover:bg-white/80 hover:text-slate-900"
              aria-label="Toggle sidebar"
            >
              <Menu size={20} />
            </button>
          )}
          <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center overflow-hidden rounded-[1rem] bg-gradient-to-br from-sky-100 via-cyan-50 to-amber-50 shadow-sm ring-1 ring-white/70">
            {character?.avatarUrl ? (
              /* eslint-disable-next-line @next/next/no-img-element */
              <img src={character.avatarUrl} alt={character.name} className="h-full w-full object-cover" />
            ) : (
              <span className="text-base font-semibold text-sky-700">
                {character?.name?.charAt(0) || 'C'}
              </span>
            )}
          </div>
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold tracking-tight text-slate-900">
              {character?.name || copy.chat.loadingCharacter}
            </h2>
            {sessionOrigin !== 'chat' && chatSessionId && isEditingTitle && (
              <input
                type="text"
                value={titleDraft}
                onChange={(event) => setTitleDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    void handleSaveTitle();
                  } else if (event.key === 'Escape') {
                    setIsEditingTitle(false);
                  }
                }}
                onBlur={() => void handleSaveTitle()}
                autoFocus
                placeholder={copy.chat.titlePlaceholder}
                className="mt-0.5 w-56 max-w-full rounded-lg border border-sky-200 bg-white px-2 py-0.5 text-xs text-slate-700 outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-100"
              />
            )}
            {sessionOrigin !== 'chat' && chatSessionId && !isEditingTitle && (
              <button
                type="button"
                onClick={startEditTitle}
                className="group mt-0.5 flex max-w-full items-center gap-1 text-left"
                title={copy.chat.editTitle}
              >
                <span className="truncate text-xs text-slate-400 transition-colors group-hover:text-slate-600">
                  {chatSession?.title || copy.chat.untitled}
                </span>
                <Pencil size={11} className="flex-shrink-0 text-slate-400 opacity-60 transition-opacity group-hover:opacity-100" />
              </button>
            )}
          </div>
        </div>
        <div className="flex flex-shrink-0 items-center gap-2">
          {realtimeOn && lastTurnLatency && (
            <span className="hidden items-center rounded-full bg-white/80 px-2.5 py-1 text-[11px] font-medium tabular-nums text-slate-500 ring-1 ring-slate-200 md:inline-flex">
              {copy.realtime.latencyBadge(
                voiceInput.lastAsrMs != null ? formatLatencyMs(voiceInput.lastAsrMs) : '—',
                lastTurnLatency.firstMs != null ? formatLatencyMs(lastTurnLatency.firstMs) : '—',
              )}
              <span className="ml-1.5 text-slate-400">·</span>
              <span>{formatLatencyMs(lastTurnLatency.totalMs)}</span>
            </span>
          )}
          <button
            type="button"
            onClick={() => setScreenOpen((prev) => !prev)}
            className={`flex h-10 w-10 items-center justify-center rounded-2xl transition-colors ${
              screenOpen
                ? 'bg-sky-50 text-sky-700 hover:bg-sky-100'
                : 'bg-white/80 text-slate-500 ring-1 ring-slate-200 hover:bg-white hover:text-slate-900'
            }`}
            title={copy.realtime.screenToggle}
          >
            <Monitor size={17} />
          </button>
          <button
            type="button"
            onClick={() => setCameraOpen((prev) => !prev)}
            className={`flex h-10 w-10 items-center justify-center rounded-2xl transition-colors ${
              cameraOpen
                ? 'bg-sky-50 text-sky-700 hover:bg-sky-100'
                : 'bg-white/80 text-slate-500 ring-1 ring-slate-200 hover:bg-white hover:text-slate-900'
            }`}
            title={copy.realtime.cameraToggle}
          >
            <Video size={17} />
          </button>
          <button
            type="button"
            onClick={() => void toggleVoiceReply()}
            title={copy.realtime.voiceReplyTitle}
            className={`flex h-10 w-10 items-center justify-center rounded-2xl transition-colors ${
              voiceReplyOn
                ? 'bg-amber-50 text-amber-700 ring-1 ring-amber-200 hover:bg-amber-100'
                : 'bg-white/80 text-slate-500 ring-1 ring-slate-200 hover:bg-white hover:text-slate-900'
            }`}
          >
            <Volume2 size={17} />
          </button>
          <button
            type="button"
            onClick={() => void toggleRealtime()}
            title={copy.realtime.toggleTitle}
            className={`flex h-10 items-center gap-2 rounded-2xl px-3.5 text-sm font-medium transition-colors ${
              realtimeOn
                ? 'bg-rose-50 text-rose-700 ring-1 ring-rose-200 hover:bg-rose-100'
                : 'bg-white/80 text-slate-500 ring-1 ring-slate-200 hover:bg-white hover:text-slate-900'
            }`}
          >
            {(voiceInput.status === 'listening' || voiceInput.status === 'speech' || voiceInput.status === 'transcribing') && (
              <>
                <span className="h-2 w-2 rounded-full bg-rose-500 motion-safe:animate-pulse" />
                <MicLevelMeter
                  subscribe={voiceInput.subscribeLevel}
                  barClassName="bg-rose-200"
                  activeBarClassName="bg-rose-500"
                />
              </>
            )}
            <Mic size={16} />
            <span className="hidden sm:inline">{realtimeStatusLabel()}</span>
          </button>
        </div>
        <div className="flex items-center gap-2 lg:hidden">
          <button
            onClick={() => setShowSoulPanel((prev) => !prev)}
            className={`flex h-10 w-10 items-center justify-center rounded-2xl transition-colors ${
              showSoulPanel
                ? 'bg-sky-50 text-sky-700 hover:bg-sky-100'
                : 'bg-white/80 text-slate-500 ring-1 ring-slate-200 hover:bg-white hover:text-slate-900'
            }`}
            title={copy.chat.toggleSoulPanel}
          >
            <FolderTree className="h-5 w-5" />
          </button>
          <button
            onClick={() => setShowMemoryPanel((prev) => !prev)}
            className={`flex h-10 w-10 items-center justify-center rounded-2xl transition-colors ${
              showMemoryPanel
                ? 'bg-sky-50 text-sky-700 hover:bg-sky-100'
                : 'bg-white/80 text-slate-500 ring-1 ring-slate-200 hover:bg-white hover:text-slate-900'
            }`}
            title={copy.chat.toggleMemoryPanel}
          >
            <Brain className="h-5 w-5" />
          </button>
          <button
            onClick={() => setShowResearchPanel((prev) => !prev)}
            className={`flex h-10 w-10 items-center justify-center rounded-2xl transition-colors ${
              showResearchPanel
                ? 'bg-sky-50 text-sky-700 hover:bg-sky-100'
                : 'bg-white/80 text-slate-500 ring-1 ring-slate-200 hover:bg-white hover:text-slate-900'
            }`}
            title={copy.chat.toggleResearchPanel}
          >
            <Globe className="h-5 w-5" />
          </button>
        </div>
      </header>

      {realtimeNotice && (
        <div className="mx-4 mt-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 md:mx-6">
          {realtimeNotice}
        </div>
      )}

      <div className="relative flex-1 overflow-hidden px-4 pb-4 pt-4 md:px-6 md:pb-6">
        <ImmersiveChatWindow
          onSendMessage={handleSendMessage}
          isLoading={isLoading}
          isFirstMessage={!hasStartedConversation}
          currentUserLabel={copy.chat.you}
          attachmentSupport={attachmentSupport}
          localizedMediaMode={localizedMediaMode}
          contextWindowTokens={activeModelConfig?.contextWindow || null}
          onStop={handleStopStreaming}
          pendingQueueTexts={pendingQueueTexts}
          memoryNotice={memoryNotice ?? undefined}
          webSearchHint={
            webSearchMissingKey ? copy.immersiveChat.webSearchMissingKey : undefined
          }
          modelConfigs={modelConfigs}
          activeTextModel={activeModelConfig}
          onTextModelChange={handleTextModelChange}
          speechPlayback={speechPlayback}
          onSpeakSentence={(messageId, index, segment) => void speakSentence(messageId, index, segment)}
          onPlayAll={handlePlayAll}
          onStopSpeech={cancelSpeech}
          onDownloadSentence={(text) => void downloadSegment(text)}
        />

        {realtimeOn && subtitlesVisible && !subtitlePipActive && (
          <SubtitleBar
            interimText={interimText}
            userText={subtitleUserText}
            assistantText={subtitleAssistantText}
            popLabel={copy.realtime.subtitlePopOut}
            closeLabel={copy.realtime.subtitleClose}
            previewEnabled={sttPreviewOn}
            previewToggleOnLabel={copy.realtime.previewToggleOn}
            previewToggleOffLabel={copy.realtime.previewToggleOff}
            previewTitleOn={copy.realtime.previewTitleOn}
            previewTitleOff={copy.realtime.previewTitleOff}
            onTogglePreview={() => {
              setSttPreviewOn((prev) => {
                const next = !prev;
                if (typeof window !== 'undefined') {
                  window.localStorage.setItem('prismate.sttPreview', next ? '1' : '0');
                }
                return next;
              });
            }}
            onPopOut={() => void openSubtitlePip()}
            onClose={() => setSubtitlesVisible(false)}
          />
        )}
      </div>

      {showSoulPanel && character && (
        <div
          className="fixed inset-0 z-40 bg-slate-950/35 p-3 backdrop-blur-sm lg:hidden"
          onClick={() => setShowSoulPanel(false)}
        >
          <div className="ml-auto h-full w-full max-w-md" onClick={(event) => event.stopPropagation()}>
            <SoulPanel
              characterId={character.id}
              characterName={character.name}
              refreshKey={soulRefreshKey}
              isOpen
              isMobile
              onToggle={() => setShowSoulPanel(false)}
            />
          </div>
        </div>
      )}

      {showMemoryPanel && character && (
        <div
          className="fixed inset-0 z-40 bg-slate-950/35 p-3 backdrop-blur-sm lg:hidden"
          onClick={() => setShowMemoryPanel(false)}
        >
          <div className="ml-auto h-full w-full max-w-md" onClick={(event) => event.stopPropagation()}>
            <MemoryPanel
              characterId={character.id}
              chatSessionId={chatSessionId}
              refreshKey={soulRefreshKey}
              onPrivateModeChanged={(isPrivateMode) => {
                if (chatSession && isPrivateMode !== chatSession.isPrivateMode) {
                  dispatch(updateChatSession({ isPrivateMode }));
                }
              }}
            />
          </div>
        </div>
      )}

      {showResearchPanel && character && (
        <div
          className="fixed inset-0 z-40 bg-slate-950/35 p-3 backdrop-blur-sm lg:hidden"
          onClick={() => setShowResearchPanel(false)}
        >
          <div className="ml-auto h-full w-full max-w-md" onClick={(event) => event.stopPropagation()}>
            <ResearchPanel />
          </div>
        </div>
      )}

      {cameraOpen && (
        <CameraPanel
          mode="camera"
          onClose={() => setCameraOpen(false)}
          onSnapshot={(file) => {
            handleSendMessage('', [{ file, kind: 'image', previewUrl: URL.createObjectURL(file) }]);
          }}
          registerFrameGrabber={registerCameraGrabber}
          snapshotLabel={copy.realtime.cameraSnapshot}
          closeLabel={copy.realtime.cameraClose}
          deniedLabel={copy.realtime.cameraDenied}
        />
      )}

      {screenOpen && (
        <CameraPanel
          mode="screen"
          onClose={() => setScreenOpen(false)}
          registerFrameGrabber={registerScreenGrabber}
          snapshotLabel={copy.realtime.cameraSnapshot}
          closeLabel={copy.realtime.screenClose}
          deniedLabel={copy.realtime.screenDenied}
        />
      )}
    </div>
  );
}
