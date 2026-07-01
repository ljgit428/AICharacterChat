"use client";

import { useEffect, useRef, useState } from 'react';
import { Character, Message, MessageAttachment, RootState } from '@/types';
import { useSelector } from 'react-redux';
import { Expand, FileText, ImageIcon, Paperclip, Sparkles, Video, X } from 'lucide-react';
import { AttachmentKind, AttachmentSupport, classifyAttachmentFile } from '@/utils/modelCapabilities';
import { useI18n } from '@/i18n/provider';

interface ImmersiveChatWindowProps {
  onSendMessage: (message: string, attachments: PendingAttachment[]) => void;
  isLoading: boolean;
  isFirstMessage: boolean;
  currentUserLabel: string;
  attachmentSupport: AttachmentSupport;
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
}: ImmersiveChatWindowProps) {
  const { messages: copy } = useI18n();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const attachmentInputRef = useRef<HTMLInputElement>(null);
  const pendingAttachmentsRef = useRef<PendingAttachment[]>([]);
  const [draftMessage, setDraftMessage] = useState('');
  const [pendingAttachments, setPendingAttachments] = useState<PendingAttachment[]>([]);
  const [composerError, setComposerError] = useState<string | null>(null);
  const [previewAttachment, setPreviewAttachment] = useState<PreviewAttachment | null>(null);
  const messages = useSelector((state: RootState) => state.chat.messages);
  const character = useSelector((state: RootState) => state.chat.character);

  useEffect(() => {
    pendingAttachmentsRef.current = pendingAttachments;
  }, [pendingAttachments]);

  useEffect(() => {
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

  const submitMessage = () => {
    const message = draftMessage.trim();
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
      submitMessage();
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

      <div className="flex-1 overflow-y-auto px-4 py-5 md:px-6">
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
            {groups.map((group) => (
              <div
                key={`${group.senderKey}-${group.messages[0].id}`}
                className={`flex gap-3 ${group.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
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
                      {formatTimestamp(group.messages[group.messages.length - 1].timestamp)}
                    </span>
                  </div>

                  <div className={`flex w-full flex-col space-y-2 ${group.role === 'user' ? 'items-end' : 'items-start'}`}>
                    {group.messages.map((message, index) => (
                      <div
                        key={message.id}
                        className={`w-fit max-w-full rounded-[1.6rem] px-4 py-3 text-sm leading-7 shadow-sm ${
                          group.role === 'user'
                            ? 'bg-slate-900 text-white'
                            : group.role === 'assistant'
                              ? 'border border-white/80 bg-white/90 text-slate-800'
                              : 'border border-amber-200/70 bg-amber-50 text-amber-900'
                        } ${
                          group.role === 'user'
                            ? index === group.messages.length - 1
                              ? 'rounded-br-md'
                              : ''
                            : index === group.messages.length - 1
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
            ))}
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

      <div className="border-t border-slate-200/70 bg-white/80 p-4 backdrop-blur">
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
                  disabled={isLoading || isFirstMessage}
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
                    {copy.immersiveChat.imageHandling(attachmentSupport.image)}
                  </span>
                )}
                {pendingAttachments.some((attachment) => attachment.kind === 'video') && (
                  <span className="rounded-full bg-white px-3 py-1 text-xs text-slate-600 ring-1 ring-slate-200">
                    {copy.immersiveChat.videoHandling(attachmentSupport.video)}
                  </span>
                )}
              </div>
            </div>
          )}

          <div className="flex items-end gap-3">
            <input
              ref={attachmentInputRef}
              type="file"
              className="hidden"
              accept=".txt,.md,.markdown,.json,.jsonl,.csv,.tsv,.log,.yaml,.yml,.xml,.ini,.cfg,.conf,.py,.js,.ts,.tsx,.jsx,.html,.css,.sql,text/*,image/*,video/*"
              multiple
              onChange={handleAttachmentChange}
              disabled={isLoading || isFirstMessage}
            />
            <button
              type="button"
              onClick={() => attachmentInputRef.current?.click()}
              className="rounded-2xl border border-slate-200 bg-slate-50 p-3 text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={isLoading || isFirstMessage}
              title={copy.immersiveChat.attachFile}
            >
              <Paperclip className="h-5 w-5" />
            </button>
            <textarea
              className="min-h-[72px] flex-1 resize-none border-0 bg-transparent px-3 py-2 text-sm leading-6 text-slate-800 outline-none placeholder:text-slate-400 disabled:cursor-not-allowed disabled:text-slate-400"
              placeholder={isFirstMessage ? copy.immersiveChat.clickStart : copy.immersiveChat.writeNextMessage}
              rows={3}
              value={draftMessage}
              onChange={(event) => setDraftMessage(event.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isLoading || isFirstMessage}
            />
            <button
              className="rounded-2xl bg-slate-900 px-5 py-3 text-sm font-medium text-white transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
              onClick={submitMessage}
              disabled={isLoading || (!isFirstMessage && !draftMessage.trim() && pendingAttachments.length === 0)}
            >
              {isFirstMessage ? copy.immersiveChat.start : copy.immersiveChat.send}
            </button>
          </div>
        </div>
        <p className="mt-2 px-2 text-xs text-slate-500">
          {copy.immersiveChat.enterToSend}
        </p>
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
  return <FileText className={className} />;
}
