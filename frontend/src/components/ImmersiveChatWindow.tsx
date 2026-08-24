"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Character, Message, MessageAttachment, ModelConfig, RootState, ToolCallInfo } from '@/types';
import { useSelector } from 'react-redux';
import { BrainCircuit, Check, Cpu, Expand, FileText, ImageIcon, Music, Plus, Sparkles, Square, Video, X } from 'lucide-react';
import { I18nMessages } from '@/i18n/messages';
import { AttachmentKind, AttachmentSupport, MediaHandlingMode, classifyAttachmentFile } from '@/utils/modelCapabilities';
import { useI18n } from '@/i18n/provider';

interface ImmersiveChatWindowProps {
  onSendMessage: (message: string, attachments: PendingAttachment[]) => void;
  isLoading: boolean;
  isFirstMessage: boolean;
  currentUserLabel: string;
  attachmentSupport: AttachmentSupport;
  localizedMediaMode?: (mode: MediaHandlingMode) => string;
  contextWindowTokens?: number | null;
  /** Natural-chat spec §2: aborts the in-flight generation. */
  onStop?: () => void;
  /** Texts queued while a reply was streaming; rendered as pending chips. */
  pendingQueueTexts?: string[];
  /** One-line notice (e.g. "Memory +2") shown above the composer. */
  memoryNotice?: string;
  /** 联网搜索已开启但未配置 key 时的一次性提示（memory/search v2）。 */
  webSearchHint?: string;
  /** 可选的主模型（text 角色）快速切换：配置列表 + 当前生效项 + 切换回调。 */
  modelConfigs?: ModelConfig[];
  activeTextModel?: ModelConfig | null;
  onTextModelChange?: (modelId: string) => void | Promise<void>;
}

export interface PendingAttachment {
  id: string;
  file: File;
  kind: AttachmentKind;
  previewUrl?: string;
}

interface PreviewAttachment {
  fileName: string;
  fileType: AttachmentKind;
  src: string;
  href: string;
}

// Context-window denominator for the composer usage ring. Not stored per model
// yet, so this is a visual estimate anchored at the common 128K floor.
const CONTEXT_WINDOW_ASSUMPTION = 128_000;

function ComposerContextRing({
  progress,
  hoverSections,
}: {
  progress: number;
  hoverSections: Array<{ label: string; detail: string }>;
}) {
  const radius = 15;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.min(Math.max(progress, 0), 1);
  const ariaSummary = hoverSections.map((section) => `${section.label} ${section.detail}`).join('；');

  return (
    <div className="group/ring relative flex h-9 w-9 flex-shrink-0 items-center justify-center" aria-label={ariaSummary}>
      <svg viewBox="0 0 36 36" className="h-7 w-7 -rotate-90">
        <circle cx="18" cy="18" r={radius} fill="none" stroke="#e2e8f0" strokeWidth="2.5" />
        <circle
          cx="18"
          cy="18"
          r={radius}
          fill="none"
          stroke="#0ea5e9"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - clamped)}
        />
      </svg>
      <div className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 hidden w-max max-w-[16rem] -translate-x-1/2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-left shadow-[0_12px_36px_rgba(15,23,42,0.14)] group-hover/ring:block">
        {hoverSections.map((section) => (
          <div key={section.label} className="mb-1.5 last:mb-0">
            <p className="text-xs font-semibold text-slate-800">{section.label}</p>
            <p className="mt-0.5 text-[11px] leading-5 text-slate-500">{section.detail}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function buildPendingAttachmentId(file: File, kind: AttachmentKind) {
  return `${file.name}:${file.size}:${file.lastModified}:${kind}`;
}

function revokeAttachmentPreview(attachment?: { previewUrl?: string }) {
  if (attachment?.previewUrl?.startsWith('blob:')) {
    URL.revokeObjectURL(attachment.previewUrl);
  }
}

function formatFileSize(size: number) {
  if (size < 1024 * 1024) {
    return `${Math.max(1, Math.round(size / 1024))} KB`;
  }
  return `${(size / 1024 / 1024).toFixed(2)} MB`;
}

function buildPreviewAttachment(attachment: PendingAttachment | MessageAttachment): PreviewAttachment | null {
  if ('file' in attachment) {
    if (!attachment.previewUrl || attachment.kind === 'text') {
      return null;
    }
    return {
      fileName: attachment.file.name,
      fileType: attachment.kind,
      src: attachment.previewUrl,
      href: attachment.previewUrl,
    };
  }

  const fileType = (attachment.fileType as AttachmentKind) || 'text';
  const href = attachment.fileUri || attachment.filePreviewUrl;
  const src = attachment.filePreviewUrl || attachment.fileUri;
  if (!src || !href || fileType === 'text') {
    return null;
  }

  return {
    fileName: attachment.fileName || 'attachment',
    fileType,
    src,
    href,
  };
}

export default function ImmersiveChatWindow({
  onSendMessage,
  isLoading,
  isFirstMessage,
  currentUserLabel,
  attachmentSupport,
  localizedMediaMode,
  contextWindowTokens,
  onStop,
  pendingQueueTexts,
  memoryNotice,
  webSearchHint,
  modelConfigs,
  activeTextModel,
  onTextModelChange,
}: ImmersiveChatWindowProps) {
  const { messages: copy } = useI18n();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const attachmentInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const pendingAttachmentsRef = useRef<PendingAttachment[]>([]);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const COMPOSER_MAX_HEIGHT = 192; // ~8 lines of leading-6 + py-2.5
  const [draftMessage, setDraftMessage] = useState('');
  const [pendingAttachments, setPendingAttachments] = useState<PendingAttachment[]>([]);
  const [composerError, setComposerError] = useState<string | null>(null);
  const [previewAttachment, setPreviewAttachment] = useState<PreviewAttachment | null>(null);
  const messages = useSelector((state: RootState) => state.chat.messages);
  const character = useSelector((state: RootState) => state.chat.character);

  const usageStats = useMemo(() => {
    const withUsage = messages.filter(
      (message) => message.role === 'assistant' && message.tokenUsage?.totalTokens
    );
    if (withUsage.length === 0) {
      return null;
    }

    const promptTokens = withUsage.reduce((sum, message) => sum + (message.tokenUsage?.promptTokens || 0), 0);
    const cachedTokens = withUsage.reduce((sum, message) => sum + (message.tokenUsage?.cachedTokens || 0), 0);
    const latest = withUsage[withUsage.length - 1].tokenUsage!;
    const contextTokens = latest.promptTokens + latest.completionTokens;
    const cacheRate = promptTokens > 0 ? cachedTokens / promptTokens : 0;

    return { promptTokens, cachedTokens, contextTokens, cacheRate };
  }, [messages]);

  const contextWindow = contextWindowTokens || CONTEXT_WINDOW_ASSUMPTION;
  const isContextEstimated = !contextWindowTokens;

  useEffect(() => {
    pendingAttachmentsRef.current = pendingAttachments;
  }, [pendingAttachments]);

  // 打开会话/批量加载历史时必须用 useLayoutEffect：在浏览器绘制前同步钉底，
  // 否则会先画出一帧顶部再跳底部（可见闪烁）。逐条新消息仍走平滑滚动。
  // 头像等图片晚于首帧加载会把内容再撑高，下一帧与 250ms 各补钉一次。
  const lastAnchorIdRef = useRef<string | null>(null);
  const lastCountRef = useRef(0);
  useLayoutEffect(() => {
    const firstId = messages[0]?.id ?? null;
    const isBulkChange =
      firstId !== lastAnchorIdRef.current || messages.length - lastCountRef.current > 1;
    lastAnchorIdRef.current = firstId;
    lastCountRef.current = messages.length;
    const container = scrollAreaRef.current;
    if (isBulkChange) {
      if (!container) return;
      container.scrollTop = container.scrollHeight;
      const raf = requestAnimationFrame(() => {
        container.scrollTop = container.scrollHeight;
      });
      const timer = window.setTimeout(() => {
        container.scrollTop = container.scrollHeight;
      }, 250);
      return () => {
        cancelAnimationFrame(raf);
        window.clearTimeout(timer);
      };
    }
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (isFirstMessage) {
      setDraftMessage('');
      setPendingAttachments((currentAttachments) => {
        currentAttachments.forEach(revokeAttachmentPreview);
        return [];
      });
      setComposerError(null);
      setPreviewAttachment(null);
    }
  }, [isFirstMessage]);

  useEffect(() => () => {
    pendingAttachmentsRef.current.forEach(revokeAttachmentPreview);
  }, []);

  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) {
      return;
    }
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, COMPOSER_MAX_HEIGHT)}px`;
  }, [draftMessage]);

  useEffect(() => {
    if (!previewAttachment) {
      return undefined;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setPreviewAttachment(null);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [previewAttachment]);

  const submitMessage = (explicitText?: string) => {
    // explicitText comes straight from the textarea element on Enter so a
    // state flush lag can never drop a submission.
    const message = (explicitText ?? draftMessage).trim();
    if (!message && pendingAttachments.length === 0 && !isFirstMessage) {
      return;
    }

    onSendMessage(message, pendingAttachments);
    setDraftMessage('');
    setComposerError(null);
    setPreviewAttachment(null);
    pendingAttachments.forEach(revokeAttachmentPreview);
    setPendingAttachments([]);
    if (attachmentInputRef.current) {
      attachmentInputRef.current.value = '';
    }
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      if (isFirstMessage) {
        return;
      }
      submitMessage(event.currentTarget.value);
    }
  };

  const removePendingAttachment = (attachmentId: string) => {
    setPendingAttachments((currentAttachments) => {
      const target = currentAttachments.find((attachment) => attachment.id === attachmentId);
      revokeAttachmentPreview(target);
      if (target?.previewUrl && previewAttachment?.src === target.previewUrl) {
        setPreviewAttachment(null);
      }
      return currentAttachments.filter((attachment) => attachment.id !== attachmentId);
    });
    setComposerError(null);
    if (attachmentInputRef.current) {
      attachmentInputRef.current.value = '';
    }
  };

  const handleAttachmentChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = Array.from(event.target.files || []);
    if (selectedFiles.length === 0) {
      return;
    }

    setPendingAttachments((currentAttachments) => {
      const existingIds = new Set(currentAttachments.map((attachment) => attachment.id));
      const nextAttachments = [...currentAttachments];
      let unsupportedCount = 0;

      selectedFiles.forEach((file) => {
        const kind = classifyAttachmentFile(file);
        if (!kind) {
          unsupportedCount += 1;
          return;
        }

        const id = buildPendingAttachmentId(file, kind);
        if (existingIds.has(id)) {
          return;
        }

        existingIds.add(id);
        nextAttachments.push({
          id,
          file,
          kind,
          previewUrl: kind === 'image' || kind === 'video' ? URL.createObjectURL(file) : undefined,
        });
      });

      setComposerError(
        unsupportedCount > 0
          ? copy.immersiveChat.unsupportedAttachmentSome(unsupportedCount)
          : null
      );

      return nextAttachments;
    });

    event.target.value = '';
  };

  const formatTimestamp = (timestamp: string) =>
    new Date(timestamp).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    });

  const getSenderProfile = (message: Message, activeCharacter: Character | null) => {
    if (message.senderType === 'system') {
      return {
        key: message.senderId || 'system',
        name: message.senderName || copy.immersiveChat.system,
        avatarUrl: message.senderAvatarUrl,
        role: 'system' as const,
      };
    }

    if (message.role === 'user') {
      return {
        key: message.senderId || 'user',
        name: message.senderName || currentUserLabel,
        avatarUrl: message.senderAvatarUrl,
        role: 'user' as const,
      };
    }

    return {
      key: message.senderId || activeCharacter?.id || 'assistant',
      name: message.senderName || activeCharacter?.name || copy.immersiveChat.character,
      avatarUrl: message.senderAvatarUrl || activeCharacter?.avatarUrl,
      role: 'assistant' as const,
    };
  };

  const groups = messages.reduce<Array<{
    senderKey: string;
    role: 'user' | 'assistant' | 'system';
    name: string;
    avatarUrl?: string;
    messages: Message[];
  }>>((allGroups, message) => {
    const profile = getSenderProfile(message, character);
    const lastGroup = allGroups[allGroups.length - 1];

    if (lastGroup && lastGroup.senderKey === profile.key && lastGroup.role === profile.role) {
      lastGroup.messages.push(message);
      return allGroups;
    }

    allGroups.push({
      senderKey: profile.key,
      role: profile.role,
      name: profile.name,
      avatarUrl: profile.avatarUrl,
      messages: [message],
    });

    return allGroups;
  }, []);

  // 左侧索引条（minimap）：每个用户发言为一格，预览该轮"用户消息 / 助手回复"。
  const turns = useMemo(() => {
    const result: Array<{
      key: string;
      anchor: string;
      userPreview: string;
      assistantPreview: string;
    }> = [];
    groups.forEach((group, index) => {
      if (group.role !== 'user') return;
      const userPreview = group.messages
        .map((message) => message.content)
        .join(' ')
        .replace(/\s+/g, ' ')
        .trim();
      let assistantPreview = '';
      for (let next = index + 1; next < groups.length; next += 1) {
        if (groups[next].role === 'user') break;
        if (groups[next].role === 'assistant') {
          assistantPreview = groups[next].messages
            .map((message) => message.content)
            .join(' ')
            .replace(/\s+/g, ' ')
            .trim();
          break;
        }
      }
      result.push({
        key: group.messages[0].id,
        anchor: `${group.senderKey}-${group.messages[0].id}`,
        userPreview,
        assistantPreview,
      });
    });
    return result;
  }, [groups]);

  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const jumpToTurn = (anchor: string) => {
    const target = scrollAreaRef.current?.querySelector<HTMLElement>(`[data-chat-anchor="${anchor}"]`);
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-[2rem] border border-white/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.9),rgba(243,247,250,0.95))] shadow-[0_24px_80px_rgba(15,23,42,0.08)]">
      <div className="border-b border-slate-200/70 bg-[radial-gradient(circle_at_top,#ffffff_0%,#f7fafc_100%)] px-5 py-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.2em] text-slate-400">{copy.immersiveChat.conversationSpace}</p>
            <h3 className="mt-1 text-base font-semibold text-slate-900">
              {character ? copy.immersiveChat.talkingWith(character.name) : copy.immersiveChat.preparingConversation}
            </h3>
          </div>
          <div className="inline-flex items-center gap-2 rounded-full bg-white/90 px-3 py-1.5 text-xs text-slate-500 ring-1 ring-slate-200">
            <Sparkles className="h-3.5 w-3.5 text-amber-500" />
            <span>{messages.length > 0 ? copy.immersiveChat.messagesCount(messages.length) : copy.immersiveChat.immersiveMode}</span>
          </div>
        </div>
      </div>

      <div className="relative min-h-0 flex-1">
        {turns.length > 1 && (
          <div className="absolute left-1 top-1/2 z-10 hidden -translate-y-1/2 flex-col items-center gap-1 md:flex">
            {turns.map((turn) => (
              <div key={turn.key} className="group/tick relative flex items-center">
                <button
                  type="button"
                  onClick={() => jumpToTurn(turn.anchor)}
                  className="flex h-3 w-5 items-center justify-center"
                  title={turn.userPreview}
                >
                  <span className="h-0.5 w-2.5 rounded-full bg-slate-400/60 transition-all group-hover/tick:h-1 group-hover/tick:w-4 group-hover/tick:bg-slate-700" />
                </button>
                <div className="pointer-events-none absolute left-6 z-20 hidden w-64 rounded-2xl border border-white/10 bg-slate-950/90 px-4 py-3 shadow-[0_18px_50px_rgba(15,23,42,0.4)] backdrop-blur group-hover/tick:block">
                  <p className="line-clamp-2 text-sm font-medium leading-6 text-white">
                    {turn.userPreview || copy.immersiveChat.minimapNoText}
                  </p>
                  <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-400">
                    {turn.assistantPreview || copy.immersiveChat.minimapNoReply}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
        <div ref={scrollAreaRef} className="h-full overflow-y-auto px-4 py-5 md:px-6">
        {messages.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="max-w-xl rounded-[2rem] border border-white/80 bg-white/80 px-6 py-8 text-center shadow-[0_20px_60px_rgba(15,23,42,0.08)] backdrop-blur">
              <div className="mx-auto flex h-20 w-20 items-center justify-center overflow-hidden rounded-[1.5rem] bg-gradient-to-br from-sky-100 via-cyan-50 to-amber-50 shadow-sm">
                {character?.avatarUrl ? (
                  /* eslint-disable-next-line @next/next/no-img-element */
                  <img src={character.avatarUrl} alt={character.name} className="h-full w-full object-cover" />
                ) : (
                  <span className="text-2xl font-semibold text-sky-700">
                    {character?.name?.charAt(0) || 'C'}
                  </span>
                )}
              </div>
              <p className="mt-5 text-xs font-medium uppercase tracking-[0.24em] text-slate-400">{copy.immersiveChat.sceneSetup}</p>
              <h4 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">
                {character?.name ? copy.immersiveChat.enterSpace(character.name) : copy.immersiveChat.startConversation}
              </h4>
              <p className="mt-3 text-sm leading-7 text-slate-600">
                {character?.scenario || character?.description || copy.immersiveChat.defaultSceneDescription}
              </p>
              <p className="mt-5 text-xs text-slate-500">
                {copy.immersiveChat.pressStart}
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-6">
            {groups.map((group) => {
              // 渲染分层（2026-08-24 交互规范）：
              // 工具调用 = 浅色文字无气泡无头像；思考 = 虚线边框气泡无头像；
              // 只有角色说话的内容才配头像和实线气泡。
              const hasSpeech = (m: Message) =>
                Boolean((m.content ?? '').trim()) || Boolean(m.attachments?.length);
              const contentMessages = group.messages.filter(
                (m) => group.role === 'user' || hasSpeech(m),
              );
              const metaMessages = group.messages.filter(
                (m) => Boolean((m.thinking ?? '').trim()) || (m.toolCalls?.length ?? 0) > 0,
              );

              return (
                <div
                  key={`${group.senderKey}-${group.messages[0].id}`}
                  data-chat-anchor={`${group.senderKey}-${group.messages[0].id}`}
                  className="space-y-3"
                >
                  {metaMessages.length > 0 && (
                    <div className="max-w-[min(48rem,86vw)] space-y-2">
                      {metaMessages.map((message) => (
                        <div key={`meta-${message.id}`} className="flex flex-col gap-1.5 pl-1">
                          <MessageThinking message={message} copy={copy} />
                          <ToolCallLines message={message} copy={copy} />
                        </div>
                      ))}
                    </div>
                  )}

                  {contentMessages.length > 0 && (
                    <div className={`flex gap-3 ${group.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      {group.role !== 'user' && (
                        <div className="mt-1 flex-shrink-0">
                          <AvatarBadge
                            name={group.name}
                            avatarUrl={group.avatarUrl}
                            tone={group.role === 'assistant' ? 'character' : 'system'}
                          />
                        </div>
                      )}

                      <div className={`flex max-w-[min(48rem,86vw)] flex-col ${group.role === 'user' ? 'items-end' : 'items-start'}`}>
                        <div className={`mb-2 flex items-center gap-2 px-1 ${group.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                          <span className="text-sm font-medium text-slate-700">{group.name}</span>
                          <span className="text-xs text-slate-400">
                            {formatTimestamp(contentMessages[contentMessages.length - 1].timestamp)}
                          </span>
                        </div>

                        <div className={`flex w-full flex-col space-y-2 ${group.role === 'user' ? 'items-end' : 'items-start'}`}>
                          {contentMessages.map((message, index) => (
                            <div
                              key={message.id}
                              className={`w-fit max-w-full rounded-[1.6rem] px-4 py-3 text-sm leading-7 shadow-sm ${
                                group.role === 'user'
                                  ? 'bg-slate-900 text-white'
                                  : 'border border-white/80 bg-white/90 text-slate-800'
                              } ${
                                group.role === 'user'
                                  ? index === contentMessages.length - 1
                                    ? 'rounded-br-md'
                                    : ''
                                  : index === contentMessages.length - 1
                                    ? 'rounded-bl-md'
                                    : ''
                              }`}
                            >
                              <MessageAttachments message={message} onPreview={setPreviewAttachment} previewLabel={copy.gallery.viewDetails} />
                              {message.content && <p className="whitespace-pre-wrap">{message.content}</p>}
                            </div>
                          ))}
                        </div>
                      </div>

                      {group.role === 'user' && (
                        <div className="mt-1 flex-shrink-0">
                          <AvatarBadge
                            name={group.name}
                            avatarUrl={group.avatarUrl}
                            tone="user"
                          />
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {isLoading && (!messages.length || messages[messages.length - 1].role === 'user') && (
          <div className="flex gap-3">
            <div className="mt-1 flex-shrink-0">
              <AvatarBadge
                name={character?.name || copy.immersiveChat.character}
                avatarUrl={character?.avatarUrl}
                tone="character"
              />
            </div>
            <div className="rounded-[1.6rem] rounded-bl-md border border-white/80 bg-white/90 px-4 py-3 shadow-sm">
              <div className="flex items-center gap-2">
                <div className="h-2 w-2 animate-pulse rounded-full bg-emerald-500"></div>
                <span className="text-sm text-slate-600">{copy.immersiveChat.characterIsTyping}</span>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
        </div>
      </div>

      <div className="border-t border-slate-200/70 bg-white/80 p-4 backdrop-blur">
        {(isLoading || (pendingQueueTexts?.length ?? 0) > 0 || memoryNotice) && (
          <div className="mx-1 mb-2 flex flex-wrap items-center gap-2">
            {memoryNotice && (
              <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700 ring-1 ring-indigo-200">
                {memoryNotice}
              </span>
            )}
            {webSearchHint && (
              <span className="rounded-full bg-rose-50 px-3 py-1 text-xs font-medium text-rose-700 ring-1 ring-rose-200">
                ⚠︎ {webSearchHint}
              </span>
            )}
            {(pendingQueueTexts?.length ?? 0) > 0 && (
              <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700 ring-1 ring-amber-200">
                {copy.immersiveChat.pendingQueuedCount(pendingQueueTexts!.length)}
              </span>
            )}
            {pendingQueueTexts?.map((text, index) => (
              <span
                key={index}
                className="max-w-[14rem] truncate rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-500 ring-1 ring-slate-200"
              >
                ⏳ {text || copy.immersiveChat.pendingAttachmentOnly}
              </span>
            ))}
          </div>
        )}
        <div className="rounded-[1.75rem] border border-slate-200 bg-white px-3 py-3 shadow-[0_14px_40px_rgba(15,23,42,0.05)]">
          {pendingAttachments.length > 0 && (
            <div className="mb-3 rounded-2xl border border-slate-200 bg-slate-50 p-3">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-slate-800">{copy.immersiveChat.selectedAttachments(pendingAttachments.length)}</p>
                  <p className="mt-1 text-xs text-slate-500">{copy.immersiveChat.addMoreFiles}</p>
                </div>
                <button
                  type="button"
                  onClick={() => attachmentInputRef.current?.click()}
                  className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900"
                  disabled={isFirstMessage}
                >
                  {copy.immersiveChat.addMoreFiles}
                </button>
              </div>

              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {pendingAttachments.map((attachment) => (
                  <PendingAttachmentCard
                    key={attachment.id}
                    attachment={attachment}
                    disabled={isLoading}
                    onPreview={setPreviewAttachment}
                    previewLabel={copy.gallery.viewDetails}
                    onRemove={() => removePendingAttachment(attachment.id)}
                    removeLabel={copy.immersiveChat.removeAttachment}
                  />
                ))}
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                {pendingAttachments.some((attachment) => attachment.kind === 'text') && (
                  <span className="rounded-full bg-white px-3 py-1 text-xs text-slate-600 ring-1 ring-slate-200">
                    {copy.immersiveChat.textFileContext}
                  </span>
                )}
                {pendingAttachments.some((attachment) => attachment.kind === 'image') && (
                  <span className="rounded-full bg-white px-3 py-1 text-xs text-slate-600 ring-1 ring-slate-200">
                    {copy.immersiveChat.imageHandling(localizedMediaMode?.(attachmentSupport.image) || attachmentSupport.image)}
                  </span>
                )}
                {pendingAttachments.some((attachment) => attachment.kind === 'audio') && (
                  <span className="rounded-full bg-white px-3 py-1 text-xs text-slate-600 ring-1 ring-slate-200">
                    {copy.immersiveChat.audioHandling(localizedMediaMode?.(attachmentSupport.audio) || attachmentSupport.audio)}
                  </span>
                )}
                {pendingAttachments.some((attachment) => attachment.kind === 'video') && (
                  <span className="rounded-full bg-white px-3 py-1 text-xs text-slate-600 ring-1 ring-slate-200">
                    {copy.immersiveChat.videoHandling(localizedMediaMode?.(attachmentSupport.video) || attachmentSupport.video)}
                  </span>
                )}
              </div>
            </div>
          )}

          <input
            ref={attachmentInputRef}
            type="file"
            className="hidden"
            accept=".txt,.md,.markdown,.json,.jsonl,.csv,.tsv,.log,.yaml,.yml,.xml,.ini,.cfg,.conf,.py,.js,.ts,.tsx,.jsx,.html,.css,.sql,text/*,image/*,audio/*,.mp3,.wav,.ogg,.m4a,.aac,.flac,video/*"
            multiple
            onChange={handleAttachmentChange}
            disabled={isFirstMessage}
          />
          <textarea
            ref={textareaRef}
            className="max-h-48 w-full resize-none overflow-y-auto border-0 bg-transparent px-2 pb-1 pt-1.5 text-sm leading-6 text-slate-800 outline-none placeholder:text-slate-400 disabled:cursor-not-allowed disabled:text-slate-400"
            placeholder={isFirstMessage ? copy.immersiveChat.clickStart : copy.immersiveChat.writeNextMessage}
            rows={2}
            value={draftMessage}
            onChange={(event) => setDraftMessage(event.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isFirstMessage}
            title={copy.immersiveChat.enterToSend}
          />
          <div className="mt-1 flex items-center justify-between gap-3 px-1">
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => attachmentInputRef.current?.click()}
                className="flex h-9 w-9 items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
                disabled={isFirstMessage}
                title={copy.immersiveChat.attachFile}
              >
                <Plus className="h-5 w-5" />
              </button>
              {usageStats && (
                <ComposerContextRing
                  progress={usageStats.contextTokens / contextWindow}
                  hoverSections={[
                    {
                      label: copy.immersiveChat.usageContextLabel,
                      detail: copy.immersiveChat.usageContextTitle(
                        usageStats.contextTokens.toLocaleString(),
                        contextWindow.toLocaleString()
                      ) + (isContextEstimated ? copy.immersiveChat.usageContextEstimateNote : ''),
                    },
                    {
                      label: copy.immersiveChat.usageCacheLabel,
                      detail: copy.immersiveChat.usageCacheTitle(
                        `${Math.round(usageStats.cacheRate * 100)}%`,
                        usageStats.cachedTokens.toLocaleString(),
                        usageStats.promptTokens.toLocaleString()
                      ),
                    },
                  ]}
                />
              )}
              {modelConfigs && modelConfigs.length > 0 && (
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => setModelMenuOpen((open) => !open)}
                    title={copy.immersiveChat.mainModelTitle}
                    className="flex h-9 max-w-[11rem] items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900"
                  >
                    <Cpu className="h-3.5 w-3.5 flex-shrink-0 text-slate-400" />
                    <span className="truncate">{activeTextModel?.name || copy.immersiveChat.mainModelNone}</span>
                  </button>
                  {modelMenuOpen && (
                    <>
                      <div className="fixed inset-0 z-10" onClick={() => setModelMenuOpen(false)} />
                      <div className="absolute bottom-11 left-0 z-20 w-64 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_18px_50px_rgba(15,23,42,0.18)]">
                        <p className="px-3 pb-1 pt-2.5 text-[11px] font-medium uppercase tracking-[0.14em] text-slate-400">
                          {copy.immersiveChat.mainModel}
                        </p>
                        <div className="max-h-56 overflow-y-auto pb-1">
                          {modelConfigs.map((config) => (
                            <button
                              key={config.id}
                              type="button"
                              onClick={() => {
                                setModelMenuOpen(false);
                                void onTextModelChange?.(config.id);
                              }}
                              className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors ${
                                config.id === activeTextModel?.id
                                  ? 'bg-sky-50 text-sky-700'
                                  : 'text-slate-700 hover:bg-slate-50'
                              }`}
                            >
                              <span className="min-w-0 flex-1 truncate">{config.name}</span>
                              <span className="flex-shrink-0 text-[10px] uppercase tracking-wide text-slate-400">
                                {config.provider}
                              </span>
                              {config.id === activeTextModel?.id && (
                                <Check className="h-3.5 w-3.5 flex-shrink-0" />
                              )}
                            </button>
                          ))}
                        </div>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
            {isLoading ? (
              <button
                type="button"
                onClick={onStop}
                disabled={!onStop}
                title={copy.immersiveChat.stop}
                aria-label={copy.immersiveChat.stop}
                className="flex h-9 items-center gap-2 rounded-full bg-rose-600 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-rose-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Square className="h-3.5 w-3.5" fill="currentColor" />
                {copy.immersiveChat.stop}
              </button>
            ) : (
              <button
                className="rounded-full bg-slate-900 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
                onClick={() => submitMessage()}
                disabled={!isFirstMessage && !draftMessage.trim() && pendingAttachments.length === 0}
              >
                {isFirstMessage ? copy.immersiveChat.start : copy.immersiveChat.send}
              </button>
            )}
          </div>
        </div>
        {composerError && (
          <p className="mt-2 px-2 text-xs text-rose-600">{composerError}</p>
        )}
      </div>

      {previewAttachment && (
        <AttachmentPreviewModal
          attachment={previewAttachment}
          closeLabel={copy.auth.close}
          onClose={() => setPreviewAttachment(null)}
        />
      )}
    </div>
  );
}

function AvatarBadge({
  name,
  avatarUrl,
  tone,
}: {
  name: string;
  avatarUrl?: string;
  tone: 'user' | 'character' | 'system';
}) {
  const palette = {
    user: 'bg-slate-900 text-white',
    character: 'bg-gradient-to-br from-sky-100 via-cyan-50 to-amber-50 text-sky-700',
    system: 'bg-amber-100 text-amber-700',
  };

  return (
    <div className={`flex h-10 w-10 items-center justify-center overflow-hidden rounded-2xl text-sm font-semibold shadow-sm ${palette[tone]}`}>
      {avatarUrl ? (
        /* eslint-disable-next-line @next/next/no-img-element */
        <img src={avatarUrl} alt={name} className="h-full w-full object-cover" />
      ) : (
        <span>{name.charAt(0).toUpperCase()}</span>
      )}
    </div>
  );
}

function MessageAttachments({
  message,
  onPreview,
  previewLabel,
}: {
  message: Message;
  onPreview: (attachment: PreviewAttachment | null) => void;
  previewLabel: string;
}) {
  const attachments = message.attachments?.length
    ? message.attachments
    : (message.fileName || message.fileUri || message.filePreviewUrl || message.fileType || message.fileMimeType)
      ? [{
          fileUri: message.fileUri,
          fileName: message.fileName,
          filePreviewUrl: message.filePreviewUrl,
          fileType: message.fileType,
          fileMimeType: message.fileMimeType,
        }]
      : [];

  if (attachments.length === 0) {
    return null;
  }

  return (
    <div className="mb-3 grid gap-3 sm:grid-cols-2">
      {attachments.map((attachment, index) => (
        <MessageAttachmentCard
          key={`${attachment.fileUri || attachment.filePreviewUrl || attachment.fileName || 'attachment'}-${index}`}
          attachment={attachment}
          onPreview={onPreview}
          previewLabel={previewLabel}
        />
      ))}
    </div>
  );
}

function MessageAttachmentCard({
  attachment,
  onPreview,
  previewLabel,
}: {
  attachment: MessageAttachment;
  onPreview: (attachment: PreviewAttachment | null) => void;
  previewLabel: string;
}) {
  const kind = (attachment.fileType as AttachmentKind) || 'text';
  const href = attachment.fileUri || attachment.filePreviewUrl || '#';
  const previewAttachment = buildPreviewAttachment(attachment);

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200/80 bg-white/85 shadow-sm">
      {kind === 'image' && attachment.filePreviewUrl ? (
        <button
          type="button"
          onClick={() => onPreview(previewAttachment)}
          className="block w-full overflow-hidden bg-slate-100 text-left"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={attachment.filePreviewUrl} alt={attachment.fileName || 'image attachment'} className="max-h-72 w-full object-cover transition-transform duration-200 hover:scale-[1.01]" />
        </button>
      ) : kind === 'video' && attachment.filePreviewUrl ? (
        <video
          className="max-h-72 w-full bg-black"
          src={attachment.filePreviewUrl}
          controls
          preload="metadata"
        />
      ) : kind === 'audio' && attachment.filePreviewUrl ? (
        <div className="flex items-center gap-3 bg-slate-50 px-4 py-3">
          <AttachmentIcon kind="audio" className="h-6 w-6 flex-shrink-0 text-slate-500" />
          <audio className="w-full" src={attachment.filePreviewUrl} controls preload="metadata" />
        </div>
      ) : (
        <div className="flex min-h-28 items-center justify-center bg-slate-50 text-slate-500">
          <AttachmentIcon kind={kind} className="h-8 w-8" />
        </div>
      )}

      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="flex items-center gap-2 px-3 py-2 text-xs text-slate-600 transition-colors hover:bg-slate-50 hover:text-slate-900"
      >
        <AttachmentIcon kind={kind} className="h-4 w-4 flex-shrink-0" />
        <span className="truncate">{attachment.fileName || 'attachment'}</span>
      </a>
      {previewAttachment && (
        <div className="border-t border-slate-100 px-3 py-2">
          <button
            type="button"
            onClick={() => onPreview(previewAttachment)}
            className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-700 transition-colors hover:bg-slate-200"
          >
            <Expand className="h-3.5 w-3.5" />
            <span>{previewLabel}</span>
          </button>
        </div>
      )}
    </div>
  );
}

function PendingAttachmentCard({
  attachment,
  disabled,
  onPreview,
  previewLabel,
  onRemove,
  removeLabel,
}: {
  attachment: PendingAttachment;
  disabled: boolean;
  onPreview: (attachment: PreviewAttachment | null) => void;
  previewLabel: string;
  onRemove: () => void;
  removeLabel: string;
}) {
  const previewAttachment = buildPreviewAttachment(attachment);

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between gap-2 px-3 py-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-slate-800">{attachment.file.name}</p>
          <p className="mt-1 text-xs text-slate-500">{formatFileSize(attachment.file.size)}</p>
        </div>
        <button
          type="button"
          onClick={onRemove}
          className="rounded-full p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
          disabled={disabled}
          aria-label={removeLabel}
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {attachment.kind === 'image' && attachment.previewUrl ? (
        <button
          type="button"
          onClick={() => onPreview(previewAttachment)}
          className="block w-full overflow-hidden border-t border-slate-100 bg-slate-100 text-left"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={attachment.previewUrl} alt={attachment.file.name} className="max-h-56 w-full object-cover" />
        </button>
      ) : attachment.kind === 'video' && attachment.previewUrl ? (
        <video className="max-h-56 w-full border-t border-slate-100 bg-black" src={attachment.previewUrl} controls preload="metadata" />
      ) : (
        <div className="flex min-h-28 items-center justify-center border-t border-slate-100 bg-slate-50 text-slate-500">
          <AttachmentIcon kind={attachment.kind} className="h-8 w-8" />
        </div>
      )}

      {previewAttachment && (
        <div className="border-t border-slate-100 px-3 py-2">
          <button
            type="button"
            onClick={() => onPreview(previewAttachment)}
            className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-700 transition-colors hover:bg-slate-200"
            disabled={disabled}
          >
            <Expand className="h-3.5 w-3.5" />
            <span>{previewLabel}</span>
          </button>
        </div>
      )}
    </div>
  );
}

function AttachmentPreviewModal({
  attachment,
  closeLabel,
  onClose,
}: {
  attachment: PreviewAttachment;
  closeLabel: string;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/75 p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className="relative flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-[2rem] border border-white/10 bg-slate-950 shadow-[0_32px_120px_rgba(15,23,42,0.45)]"
        onClick={(event) => event.stopPropagation()}
      >
        <button
          type="button"
          onClick={onClose}
          className="absolute right-4 top-4 z-10 rounded-full bg-black/50 p-2 text-white transition-colors hover:bg-black/70"
          aria-label={closeLabel}
          title={closeLabel}
        >
          <X className="h-5 w-5" />
        </button>

        <div className="flex-1 overflow-auto bg-black p-4 md:p-6">
          {attachment.fileType === 'image' ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={attachment.src} alt={attachment.fileName} className="mx-auto max-h-[75vh] w-auto max-w-full rounded-2xl object-contain" />
          ) : (
            <video
              className="mx-auto max-h-[75vh] w-auto max-w-full rounded-2xl bg-black"
              src={attachment.src}
              controls
              autoPlay
              preload="metadata"
            />
          )}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-white/10 bg-slate-900/95 px-5 py-4 text-sm text-slate-200">
          <span className="truncate">{attachment.fileName}</span>
          <a
            href={attachment.href}
            target="_blank"
            rel="noreferrer"
            className="rounded-full bg-white/10 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-white/20"
          >
            {attachment.fileName}
          </a>
        </div>
      </div>
    </div>
  );
}

function AttachmentIcon({
  kind,
  className,
}: {
  kind: AttachmentKind;
  className?: string;
}) {
  if (kind === 'image') {
    return <ImageIcon className={className} />;
  }
  if (kind === 'video') {
    return <Video className={className} />;
  }
  if (kind === 'audio') {
    return <Music className={className} />;
  }
  return <FileText className={className} />;
}

function MessageThinking({
  message,
  copy,
}: {
  message: Message;
  copy: I18nMessages;
}) {
  const thinking = message.thinking?.trim();
  if (!thinking) {
    return null;
  }

  return (
    <details className="rounded-xl border border-dashed border-slate-300/80 bg-slate-50/60 px-3 py-2 open:pb-3">
      <summary className="flex cursor-pointer select-none items-center gap-1.5 text-xs font-medium text-slate-500 transition-colors hover:text-slate-700">
        <BrainCircuit className="h-3.5 w-3.5" />
        <span>{copy.immersiveChat.thinking}</span>
      </summary>
      <p className="mt-2 whitespace-pre-wrap text-xs leading-6 text-slate-500">{thinking}</p>
    </details>
  );
}

function ToolCallLines({
  message,
  copy,
}: {
  message: Message;
  copy: I18nMessages;
}) {
  const toolCalls = message.toolCalls || [];
  if (toolCalls.length === 0) {
    return null;
  }

  return (
    <div className="space-y-0.5">
      {toolCalls.map((toolCall, index) => (
        <p key={`${toolCall.tool}-${index}`} className="text-[11px] italic leading-5 text-slate-400">
          {describeToolCall(toolCall, copy)}
        </p>
      ))}
    </div>
  );
}

function describeToolCall(toolCall: ToolCallInfo, copy: I18nMessages): string {
  const args = toolCall.arguments || {};
  if (toolCall.tool === 'web_search') {
    return copy.immersiveChat.toolSearch(String(args.query || ''));
  }
  if (toolCall.tool === 'read_memory_file') {
    return copy.immersiveChat.toolReadMemory(String(args.path || ''));
  }
  if (toolCall.tool === 'list_memory_files') {
    return copy.immersiveChat.toolListMemory;
  }
  return copy.immersiveChat.toolDefault(toolCall.tool);
}
