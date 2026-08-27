"use client";

import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { useMutation, useQuery, gql } from '@apollo/client';
import { FILES_UPLOAD_API_URL } from '@/constants';
import { apiService } from '@/utils/api';
import { TtsVoiceModel } from '@/types';
import { useI18n } from '@/i18n/provider';
import AvatarCropper from '@/components/AvatarCropper';
import FileTree, { FileTreeNode } from '@/components/FileTree';
import {
  Upload,
  Sparkles,
  Save,
  Image as ImageIcon,
  Loader2,
  FileText,
  ArrowLeft,
  Undo2,
} from 'lucide-react';

type ReferenceFile = {
  name: string;
  url: string;
  type: string;
};

type PendingReferenceFile = {
  file: File;
  displayName: string;
  relativePath: string;
};

type ReferenceFileSkipSummary = {
  unsupported: number;
  oversized: number;
  overCap: number;
};

// Mirrors the backend limits in chat/attachments.py (MAX_TEXT_ATTACHMENT_BYTES /
// MAX_IMAGE_ATTACHMENT_BYTES) so oversized files are skipped before upload instead
// of failing the whole character save later.
const MAX_TEXT_UPLOAD_BYTES = 2 * 1024 * 1024;
const MAX_IMAGE_UPLOAD_BYTES = 20 * 1024 * 1024;
const MAX_BATCH_REFERENCE_FILES = 250;
const SUPPORTED_REFERENCE_TEXT_EXTENSIONS = ['.txt', '.md', '.markdown', '.json', '.jsonl'];
const SKIPPED_REFERENCE_FILE_NAMES = new Set(['desktop.ini', 'thumbs.db', '.ds_store']);

function formatReferencePath(value: string) {
  return value.replace(/\\/g, '/').replace(/^\/+/, '');
}

function isHiddenReferenceFileName(name: string) {
  const lower = name.toLowerCase();
  return lower.startsWith('.') || SKIPPED_REFERENCE_FILE_NAMES.has(lower);
}

function isSupportedReferenceFile(file: File) {
  if (isHiddenReferenceFileName(file.name)) {
    return false;
  }
  if (file.type.startsWith('image/')) {
    return true;
  }
  const lower = file.name.toLowerCase();
  return SUPPORTED_REFERENCE_TEXT_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

function isOversizedReferenceFile(file: File) {
  return file.size > (file.type.startsWith('image/') ? MAX_IMAGE_UPLOAD_BYTES : MAX_TEXT_UPLOAD_BYTES);
}

function comparePendingReferenceFiles(a: PendingReferenceFile, b: PendingReferenceFile) {
  // Natural numeric collation keeps script IDs in story order (31010 < 32010 < 84300100300)
  // and makes drop/pick order deterministic across browsers regardless of FS listing order.
  return a.displayName.localeCompare(b.displayName, undefined, { numeric: true });
}

function collectPendingReferenceFiles(candidates: PendingReferenceFile[]) {
  const accepted: PendingReferenceFile[] = [];
  const summary: ReferenceFileSkipSummary = { unsupported: 0, oversized: 0, overCap: 0 };

  for (const candidate of [...candidates].sort(comparePendingReferenceFiles)) {
    if (!isSupportedReferenceFile(candidate.file)) {
      summary.unsupported += 1;
      continue;
    }
    if (isOversizedReferenceFile(candidate.file)) {
      summary.oversized += 1;
      continue;
    }
    if (accepted.length >= MAX_BATCH_REFERENCE_FILES) {
      summary.overCap += 1;
      continue;
    }
    accepted.push(candidate);
  }

  return { accepted, summary };
}

async function collectReferenceFilesFromEntry(
  entry: FileSystemEntry,
  parentPath: string,
  collected: PendingReferenceFile[],
) {
  const entryPath = parentPath ? `${parentPath}/${entry.name}` : entry.name;

  if (entry.isFile) {
    const fileEntry = entry as FileSystemFileEntry;
    const file = await new Promise<File | null>((resolve) => {
      fileEntry.file((value: File) => resolve(value), () => resolve(null));
    });
    if (file) {
      collected.push({ file, displayName: entryPath, relativePath: entryPath });
    }
    return;
  }

  if (!entry.isDirectory) {
    return;
  }

  const reader = (entry as FileSystemDirectoryEntry).createReader();
  const children: FileSystemEntry[] = [];
  // readEntries returns at most 100 entries per call; keep reading until it is empty.
  for (;;) {
    const batch = await new Promise<FileSystemEntry[]>((resolve) => {
      reader.readEntries((values: FileSystemEntry[]) => resolve(values), () => resolve([]));
    });
    if (!batch.length) {
      break;
    }
    children.push(...batch);
  }

  await Promise.all(children.map((child) => collectReferenceFilesFromEntry(child, entryPath, collected)));
}

async function collectFilesFromDataTransfer(dataTransfer: DataTransfer): Promise<PendingReferenceFile[]> {
  // DataTransfer items are only valid synchronously inside the event handler, so
  // snapshot the directory entries before any await, then traverse them async.
  const entries = Array.from(dataTransfer.items || [])
    .map((item) => (typeof item.webkitGetAsEntry === 'function' ? item.webkitGetAsEntry() : null))
    .filter((entry): entry is FileSystemEntry => entry !== null);

  if (!entries.length) {
    return Array.from(dataTransfer.files || []).map((file) => ({ file, displayName: file.name, relativePath: file.name }));
  }

  const collected: PendingReferenceFile[] = [];
  await Promise.all(entries.map((entry) => collectReferenceFilesFromEntry(entry, '', collected)));
  return collected;
}

type PromptPreviewLocale = 'zh-CN' | 'en-US';

type WebSearchMode = 'default' | 'on' | 'off';

// 角色只引用设置页登记的音色（voice_model_id）；引擎地址、模型目录、
// 参考音频等细节全部收敛在 设置→语音设置。
// 情感组是角色级配置：每种情感一份参考音频，合成时按情感切换。
export type EmotionConfigForm = {
  name: string;
  refAudioPath: string;
  refAudioText: string;
  refAudioLanguage: string;
};

type TtsConfigForm = {
  voiceModelId: string;
  language: string;
  emotions: EmotionConfigForm[];
};

const EMPTY_TTS_CONFIG: TtsConfigForm = {
  voiceModelId: '',
  language: '',
  emotions: [],
};

// 从后端 tts_config 反序列化情感组；容错跳过缺名字/非对象的脏条目。
function parseEmotions(raw: unknown): EmotionConfigForm[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((entry): entry is Record<string, unknown> => !!entry && typeof entry === 'object')
    .map((entry) => ({
      name: typeof entry.name === 'string' ? entry.name : '',
      refAudioPath: typeof entry.ref_audio_path === 'string' ? entry.ref_audio_path : '',
      refAudioText: typeof entry.ref_audio_text === 'string' ? entry.ref_audio_text : '',
      refAudioLanguage:
        typeof entry.ref_audio_language === 'string' ? entry.ref_audio_language : '',
    }));
}

function toTtsConfigInput(tts: TtsConfigForm): Record<string, unknown> {
  const config: Record<string, unknown> = {};
  if (tts.voiceModelId) config.voice_model_id = tts.voiceModelId;
  if (tts.language) config.language = tts.language;
  const emotions = tts.emotions
    .map((emotion) => ({
      name: emotion.name.trim(),
      ref_audio_path: emotion.refAudioPath.trim(),
      ref_audio_text: emotion.refAudioText.trim(),
      ref_audio_language: emotion.refAudioLanguage.trim(),
    }))
    .filter((emotion) => emotion.name);
  if (emotions.length) config.emotions = emotions;
  return config;
}

// 音色库下拉的展示标签：名字之外带上引擎/版本，方便区分同名条目。
function ttsOptionLabel(voice: TtsVoiceModel): string {
  const parts = [voice.name];
  if (voice.engine) parts.push(voice.engine);
  if (voice.modelVersion) parts.push(voice.modelVersion);
  return parts.join(' · ');
}

type FormState = {
  name: string;
  description: string;
  userAddress: string;
  personality: string;
  appearance: string;
  affiliation: string;
  responseGuidelines: string;
  scenario: string;
  exampleDialogue: string;
  tags: string;
  avatarUrl: string;
  webSearchMode: WebSearchMode;
  ttsConfig: TtsConfigForm;
};

type AiDraftKey = Extract<keyof FormState, 'name' | 'description' | 'affiliation' | 'tags' | 'exampleDialogue'>;

const AI_HIGHLIGHT_MS = 1200;
const AI_UNDO_WINDOW_MS = 30000;

function normalizePromptPreviewLocale(value: string): PromptPreviewLocale {
  return value === 'en-US' ? 'en-US' : 'zh-CN';
}

function getPromptPreviewCopy(locale: PromptPreviewLocale) {
  if (locale === 'en-US') {
    return {
      identity: 'Identity',
      name: 'Name',
      untitledCharacter: 'Untitled character',
      affiliation: 'Affiliation',
      referenceFiles: 'Reference Files',
      noReferenceFiles: 'No uploaded reference files yet.',
      coreBrief: 'Core Brief',
      noCoreBrief: 'No core brief yet.',
      userAddress: 'User Address',
      userAddressLine: (value: string) => `Calls the user "${value}".`,
      personality: 'Personality',
      appearance: 'Appearance',
      scenario: 'Scenario',
      responseGuidelines: 'Response Guidelines',
      exampleDialogue: 'Example Dialogue',
      targetCharacterName: 'TARGET CHARACTER NAME',
      characterBrief: 'CHARACTER BRIEF',
    };
  }

  return {
    identity: '身份',
    name: '名字',
    untitledCharacter: '未命名角色',
    affiliation: '所属',
    referenceFiles: '参考文件',
    noReferenceFiles: '暂未上传参考文件。',
    coreBrief: '核心简介',
    noCoreBrief: '暂未填写核心简介。',
    userAddress: '对用户的称呼',
    userAddressLine: (value: string) => `称呼用户为“${value}”。`,
    personality: '性格',
    appearance: '外观',
    scenario: '场景',
    responseGuidelines: '回复准则',
    exampleDialogue: '示例对话',
    targetCharacterName: '目标角色名',
    characterBrief: '角色简介',
  };
}

function joinPreviewSections(sections: string[]): string {
  return sections.filter((section) => section.trim()).join('\n\n').trim();
}

function buildCharacterSystemPromptPreview(
  form: {
    name: string;
    description: string;
    userAddress: string;
    personality: string;
    appearance: string;
    affiliation: string;
    responseGuidelines: string;
    scenario: string;
    exampleDialogue: string;
  },
  backgroundFiles: ReferenceFile[],
  locale: PromptPreviewLocale,
): string {
  const copy = getPromptPreviewCopy(locale);
  const identityLines = [
    `## ${copy.identity}`,
    `${copy.name}: ${form.name.trim() || copy.untitledCharacter}`,
  ];

  if (form.affiliation.trim()) {
    identityLines.push(`${copy.affiliation}: ${form.affiliation.trim()}`);
  }

  const referenceFileLines = backgroundFiles.length
    ? [`## ${copy.referenceFiles}`, ...backgroundFiles.map((file) => `- ${file.name} [${file.type || 'file'}]`)]
    : [`## ${copy.referenceFiles}`, `- ${copy.noReferenceFiles}`];

  return joinPreviewSections([
    identityLines.join('\n'),
    `## ${copy.coreBrief}\n${form.description.trim() || copy.noCoreBrief}`,
    form.userAddress.trim() ? `## ${copy.userAddress}\n${copy.userAddressLine(form.userAddress.trim())}` : '',
    form.personality.trim() ? `## ${copy.personality}\n${form.personality.trim()}` : '',
    form.appearance.trim() ? `## ${copy.appearance}\n${form.appearance.trim()}` : '',
    form.scenario.trim() ? `## ${copy.scenario}\n${form.scenario.trim()}` : '',
    form.responseGuidelines.trim() ? `## ${copy.responseGuidelines}\n${form.responseGuidelines.trim()}` : '',
    form.exampleDialogue.trim() ? `## ${copy.exampleDialogue}\n${form.exampleDialogue.trim()}` : '',
    referenceFileLines.join('\n'),
  ]);
}

const GENERATE_DRAFT = gql`
  mutation GenerateDraft($fileUrls: [String!], $fileNames: [String!], $textContext: String, $locale: String) {
    generateCharacterDraft(fileUrls: $fileUrls, fileNames: $fileNames, textContext: $textContext, locale: $locale) {
      name
      description
      affiliation
      tags
      exampleDialogue
    }
  }
`;

const CREATE_CHARACTER = gql`
  mutation CreateCharacter($input: CharacterInput!) {
    createCharacter(input: $input) {
      id
      name
    }
  }
`;

const GET_CHARACTER = gql`
  query GetCharacter($id: ID!) {
    character(id: $id) {
      id
      name
      description
      systemPromptPreview
      userAddress
      personality
      appearance
      responseGuidelines
      scenario
      exampleDialogue
      affiliation
      tags
      avatarUrl
      enableWebSearch
      ttsConfig
      knowledgeAssets {
        fileUrl
        fileName
        fileType
        fileMimeType
      }
    }
  }
`;

const UPDATE_CHARACTER = gql`
  mutation UpdateCharacter($id: ID!, $input: CharacterInput!) {
    updateCharacter(id: $id, input: $input) {
      id
      name
    }
  }
`;

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function pickFormState(form: FormState, keys: readonly AiDraftKey[]): Partial<FormState> {
  const snapshot: Partial<FormState> = {};
  for (const key of keys) {
    snapshot[key] = form[key];
  }
  return snapshot;
}

interface ReferenceAndAiPanelProps {
  files: ReferenceFile[];
  isUploading: boolean;
  isGenerating: boolean;
  canUndo: boolean;
  textReferenceCount: number;
  autoTargetName: string;
  autoInputText: string;
  onAutoTargetNameChange: (value: string) => void;
  onAutoInputTextChange: (value: string) => void;
  onFilesAdded: (files: PendingReferenceFile[]) => void;
  onRemoveFile: (url: string) => void;
  onGenerate: () => void;
  onUndo: () => void;
  copy: ReturnType<typeof useI18n>['messages']['characterForm'];
  locale: PromptPreviewLocale;
}

function ReferenceAndAiPanel({
  files,
  isUploading,
  isGenerating,
  canUndo,
  textReferenceCount,
  autoTargetName,
  autoInputText,
  onAutoTargetNameChange,
  onAutoInputTextChange,
  onFilesAdded,
  onRemoveFile,
  onGenerate,
  onUndo,
  copy,
}: ReferenceAndAiPanelProps) {
  const { locale } = useI18n();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const [isBackgroundDragging, setIsBackgroundDragging] = useState(false);
  const [skipNotice, setSkipNotice] = useState<string | null>(null);
  const [expandedGroupDirs, setExpandedGroupDirs] = useState<Set<string>>(new Set());

  // 把扁平的文件列表按 relative_path 组装成分层树（本地待保存状态，与后端 VFS 无关）。
  const groupedFileNodes = useMemo<FileTreeNode[]>(() => {
    const roots: FileTreeNode[] = [];
    const dirNodes = new Map<string, FileTreeNode>();
    const ensureDir = (dirPath: string): FileTreeNode => {
      const existing = dirNodes.get(dirPath);
      if (existing) {
        return existing;
      }
      const node: FileTreeNode = {
        path: `folder:${dirPath}`,
        title: dirPath.split('/').pop() || dirPath,
        isDirectory: true,
        children: [],
      };
      dirNodes.set(dirPath, node);
      const slashIndex = dirPath.lastIndexOf('/');
      if (slashIndex > -1) {
        ensureDir(dirPath.slice(0, slashIndex)).children!.push(node);
      } else {
        roots.push(node);
      }
      return node;
    };

    const sorted = [...files].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
    for (const file of sorted) {
      const segments = file.name.split('/');
      const title = segments.pop() || file.name;
      const leaf: FileTreeNode = {
        path: file.url,
        title,
        isDirectory: false,
        previewKind: file.type === 'image' ? 'image' : 'text',
      };
      if (segments.length) {
        ensureDir(segments.join('/')).children!.push(leaf);
      } else {
        roots.push(leaf);
      }
    }
    return roots;
  }, [files]);

  // 新出现的顶层文件夹默认展开，用户手动收起的保持收起。
  useEffect(() => {
    setExpandedGroupDirs((prev) => {
      const next = new Set(prev);
      let changed = false;
      for (const node of groupedFileNodes) {
        if (node.isDirectory && !next.has(node.path)) {
          next.add(node.path);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [groupedFileNodes]);

  const toggleGroupDir = (node: FileTreeNode) => {
    setExpandedGroupDirs((prev) => {
      const next = new Set(prev);
      if (next.has(node.path)) {
        next.delete(node.path);
      } else {
        next.add(node.path);
      }
      return next;
    });
  };

  const handleRemoveNode = (node: FileTreeNode) => {
    if (node.isDirectory) {
      const prefix = `${node.path.slice('folder:'.length)}/`;
      files
        .filter((file) => file.name.startsWith(prefix))
        .forEach((file) => onRemoveFile(file.url));
      return;
    }
    onRemoveFile(node.path);
  };


  const attachFolderInputRef = (element: HTMLInputElement | null) => {
    folderInputRef.current = element;
    if (element) {
      element.setAttribute('webkitdirectory', '');
      element.setAttribute('directory', '');
    }
  };

  const hasTextSource = textReferenceCount > 0 || autoInputText.trim().length > 0;
  const canGenerate = hasTextSource && !isUploading && !isGenerating;

  const submitPendingFiles = useCallback(
    (candidates: PendingReferenceFile[]) => {
      const { accepted, summary } = collectPendingReferenceFiles(candidates);
      const noticeParts: string[] = [];
      if (summary.unsupported) {
        noticeParts.push(copy.skippedUnsupportedFiles(summary.unsupported));
      }
      if (summary.oversized) {
        noticeParts.push(copy.skippedOversizedFiles(summary.oversized));
      }
      if (summary.overCap) {
        noticeParts.push(copy.skippedOverCapFiles(summary.overCap, MAX_BATCH_REFERENCE_FILES));
      }
      setSkipNotice(noticeParts.length ? noticeParts.join(' ') : null);
      if (accepted.length) {
        onFilesAdded(accepted);
      }
    },
    [copy, onFilesAdded],
  );

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleFolderClick = () => {
    folderInputRef.current?.click();
  };

  const handleUploadChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const fileList = Array.from(event.target.files || []);
    event.target.value = '';
    if (fileList.length) {
      submitPendingFiles(fileList.map((file) => ({ file, displayName: file.name, relativePath: file.name })));
    }
  };

  const handleFolderChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const fileList = Array.from(event.target.files || []);
    event.target.value = '';
    if (fileList.length) {
      submitPendingFiles(
        fileList.map((file) => ({
          file,
          displayName: formatReferencePath(file.webkitRelativePath || file.name),
          relativePath: formatReferencePath(file.webkitRelativePath || file.name),
        })),
      );
    }
  };

  const onBackgroundDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.stopPropagation();
    setIsBackgroundDragging(true);
  }, []);

  const onBackgroundDragLeave = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.stopPropagation();
    setIsBackgroundDragging(false);
  }, []);

  const onBackgroundDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      event.stopPropagation();
      setIsBackgroundDragging(false);

      void collectFilesFromDataTransfer(event.dataTransfer).then(submitPendingFiles);
    },
    [submitPendingFiles],
  );

  const dropzoneCopy = useMemo(() => {
    if (isUploading) {
      return copy.uploadingBackgroundFile;
    }
    if (files.length > 0) {
      return copy.referenceDropzoneReady(files.length);
    }
    return copy.referenceDropzoneEmpty;
  }, [copy, files.length, isUploading]);

  const buttonLabel = isGenerating
    ? copy.aiPrimaryActionLoading
    : copy.aiPrimaryAction;
  const buttonDisabledReason = !hasTextSource
    ? copy.aiPrimaryActionDisabledHint
    : textReferenceCount === 0
      ? copy.referenceNeedsText
      : undefined;

  return (
    <div className="rounded-2xl border border-amber-100 bg-gradient-to-br from-amber-50 to-white p-5 shadow-sm">
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-gray-900">{copy.referenceAndAi}</h2>
          <p className="mt-0.5 text-xs text-gray-500">{copy.referenceAndAiHelp}</p>
        </div>
        {canUndo && (
          <button
            type="button"
            onClick={onUndo}
            title={copy.undoAiFillTitle}
            className="inline-flex shrink-0 items-center gap-1 rounded-full border border-violet-200 bg-white px-2.5 py-1 text-[11px] font-medium text-violet-700 transition-colors hover:bg-violet-50"
          >
            <Undo2 className="h-3 w-3" />
            <span>{copy.undoAiFill}</span>
          </button>
        )}
      </div>

      <div
        onDragOver={onBackgroundDragOver}
        onDragLeave={onBackgroundDragLeave}
        onDrop={onBackgroundDrop}
        onClick={handleUploadClick}
        className={`flex min-h-[96px] cursor-pointer flex-col items-center justify-center gap-1.5 rounded-xl border-2 border-dashed p-4 text-center transition-all ${
          isBackgroundDragging
            ? 'border-amber-500 bg-amber-100'
            : files.length
              ? 'border-amber-300 bg-amber-50'
              : 'border-amber-200 bg-white hover:border-amber-300 hover:bg-amber-50/70'
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          accept=".txt,.md,.markdown,.json,.jsonl,image/*"
          multiple
          onChange={handleUploadChange}
        />
        <input
          ref={attachFolderInputRef}
          type="file"
          className="hidden"
          multiple
          onChange={handleFolderChange}
        />
        {isUploading ? (
          <div className="flex flex-col items-center text-amber-700">
            <Loader2 className="mb-1 animate-spin" size={24} />
            <span className="text-xs font-medium">{copy.uploadingBackgroundFile}</span>
          </div>
        ) : (
          <>
            <FileText size={24} className={files.length ? 'text-amber-600' : 'text-amber-500'} />
            <span className="text-xs font-medium text-gray-700">{dropzoneCopy}</span>
            <span className="text-[11px] text-gray-400">{copy.referenceDropzoneSupport}</span>
          </>
        )}
      </div>

      <div className="mt-2 flex justify-center">
        <button
          type="button"
          onClick={handleFolderClick}
          className="text-[11px] font-medium text-amber-700 underline-offset-2 transition-colors hover:text-amber-800 hover:underline"
        >
          {copy.selectFolder}
        </button>
      </div>

      {skipNotice && (
        <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-[11px] leading-4 text-amber-800">
          {skipNotice}
        </p>
      )}

      {files.length > 0 && (
        <div className="mt-3 max-h-60 overflow-y-auto rounded-xl border border-amber-100 bg-white/80 p-1.5">
          <FileTree
            nodes={groupedFileNodes}
            expandedPaths={expandedGroupDirs}
            onToggleDir={toggleGroupDir}
            onSelectFile={() => {}}
            removable
            onRemoveNode={handleRemoveNode}
            removeTitle={copy.removeBackgroundFile}
            emptyDirLabel={locale === 'zh-CN' ? '（空文件夹）' : '(empty folder)'}
          />
          <p className="px-2 pb-1 pt-1.5 text-[11px] leading-4 text-gray-400">
            {copy.groupedFilesHint(files.length)}
          </p>
        </div>
      )}

      <p className="mt-2 text-[11px] leading-4 text-gray-500">{copy.imageNote}</p>

      <div className="mt-3 space-y-3">
        <div className="space-y-1">
          <label className="text-xs font-medium text-gray-700">{copy.targetNameLabel}</label>
          <input
            value={autoTargetName}
            onChange={(event) => onAutoTargetNameChange(event.target.value)}
            placeholder={copy.targetNamePlaceholder}
            className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm outline-none transition-all focus:border-amber-500 focus:ring-2 focus:ring-amber-500/20"
          />
          <p className="text-[11px] text-gray-500">{copy.targetNameHelper}</p>
        </div>

        <div className="space-y-1">
          <label className="text-xs font-medium text-gray-700">{copy.additionalDraftContextLabel}</label>
          <textarea
            value={autoInputText}
            onChange={(event) => onAutoInputTextChange(event.target.value)}
            placeholder={copy.aiSourcePlaceholder}
            rows={3}
            className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm outline-none transition-all focus:border-amber-500 focus:ring-2 focus:ring-amber-500/20"
          />
          <p className="text-[11px] text-gray-500">{copy.additionalContextHelper}</p>
        </div>
      </div>

      <button
        type="button"
        onClick={onGenerate}
        disabled={!canGenerate}
        title={buttonDisabledReason ?? copy.regenerateTooltip}
        className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gray-900 px-4 py-3.5 text-sm font-semibold text-white transition-colors hover:bg-black disabled:cursor-not-allowed disabled:bg-gray-400"
      >
        {isGenerating ? <Loader2 className="animate-spin" size={16} /> : <Sparkles size={16} />}
        <span>{buttonLabel}</span>
      </button>

      <p className="mt-2 text-[11px] leading-4 text-gray-500">{copy.aiScopeHintShort}</p>
    </div>
  );
}

export default function CreateCharacterSimplifiedForm({
  characterId,
  onCancel
}: { characterId?: string, onCancel?: () => void }) {
  const { messages: copy, locale } = useI18n();
  const router = useRouter();
  const isEditMode = !!characterId;
  const promptPreviewLocale = normalizePromptPreviewLocale(locale);

  const [form, setForm] = useState<FormState>({
    name: '',
    description: '',
    userAddress: '',
    personality: '',
    appearance: '',
    affiliation: '',
    responseGuidelines: '',
    scenario: '',
    exampleDialogue: '',
    tags: '',
    avatarUrl: '',
    webSearchMode: 'default',
    ttsConfig: { ...EMPTY_TTS_CONFIG },
  });
  const [voiceModels, setVoiceModels] = useState<TtsVoiceModel[]>([]);
  // 音色库来自 设置→语音设置；这里只做引用，不维护模型细节。
  useEffect(() => {
    let cancelled = false;
    void apiService.listTtsVoiceModels().then((response) => {
      if (!cancelled && response.data) {
        setVoiceModels(response.data);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);
  const [autoInputText, setAutoInputText] = useState('');
  const [backgroundFiles, setBackgroundFiles] = useState<ReferenceFile[]>([]);
  // 情感组的增删改：只动 ttsConfig.emotions，不影响音色/语言字段。
  const updateEmotion = (index: number, patch: Partial<EmotionConfigForm>) => {
    setForm((prev) => ({
      ...prev,
      ttsConfig: {
        ...prev.ttsConfig,
        emotions: prev.ttsConfig.emotions.map((emotion, i) =>
          i === index ? { ...emotion, ...patch } : emotion,
        ),
      },
    }));
  };
  const addEmotion = () => {
    setForm((prev) => ({
      ...prev,
      ttsConfig: {
        ...prev.ttsConfig,
        emotions: [
          ...prev.ttsConfig.emotions,
          { name: '', refAudioPath: '', refAudioText: '', refAudioLanguage: prev.ttsConfig.language },
        ],
      },
    }));
  };
  const removeEmotion = (index: number) => {
    setForm((prev) => ({
      ...prev,
      ttsConfig: {
        ...prev.ttsConfig,
        emotions: prev.ttsConfig.emotions.filter((_, i) => i !== index),
      },
    }));
  };
  // 参考文件上传失败的数量：保存前据此提醒用户，避免角色悄悄丢文件。
  const [failedUploadCount, setFailedUploadCount] = useState(0);
  const [autoTargetName, setAutoTargetName] = useState('');
  const [systemPromptPreview, setSystemPromptPreview] = useState('');
  const [uploadingTarget, setUploadingTarget] = useState<'avatar' | 'background' | null>(null);
  const [avatarCropSrc, setAvatarCropSrc] = useState<string | null>(null);
  const [aiFilledFields, setAiFilledFields] = useState<Set<AiDraftKey>>(new Set());
  const [aiEditedFields, setAiEditedFields] = useState<Set<AiDraftKey>>(new Set());
  const [preAiSnapshot, setPreAiSnapshot] = useState<Partial<FormState> | null>(null);
  const [aiUndoDeadline, setAiUndoDeadline] = useState<number>(0);
  const [highlightDeadline, setHighlightDeadline] = useState<number>(0);
  const [now, setNow] = useState<number>(() => Date.now());

  const avatarInputRef = useRef<HTMLInputElement>(null);
  const skipNextPromptPreviewSyncRef = useRef(false);
  const loadedCharacterIdRef = useRef<string | null>(null);

  const [generateDraft, { loading: aiLoading }] = useMutation(GENERATE_DRAFT);
  const [createCharacter, { loading: saveLoading }] = useMutation(CREATE_CHARACTER);
  const [updateCharacter] = useMutation(UPDATE_CHARACTER);

  const { data } = useQuery(GET_CHARACTER, {
    variables: { id: characterId },
    skip: !isEditMode,
  });

  useEffect(() => {
    if (!data?.character) {
      return;
    }

    const char = data.character;
    // 同一角色只在首次加载时预填：Apollo 窗口聚焦会自动 refetch，
    // 不设防的话每次 refetch 都会用服务端旧值覆盖用户正在编辑的表单。
    if (loadedCharacterIdRef.current === String(char.id)) {
      return;
    }
    loadedCharacterIdRef.current = String(char.id);
    const charTts = (char.ttsConfig || {}) as Record<string, unknown>;
    const nextForm: FormState = {
      name: char.name || '',
      description: char.description || '',
      userAddress: char.userAddress || '',
      personality: char.personality || '',
      appearance: char.appearance || '',
      affiliation: char.affiliation || '',
      responseGuidelines: char.responseGuidelines || '',
      scenario: char.scenario || '',
      exampleDialogue: char.exampleDialogue || '',
      tags: Array.isArray(char.tags) ? char.tags.join(', ') : '',
      avatarUrl: char.avatarUrl || '',
      webSearchMode:
        char.enableWebSearch === true ? 'on' : char.enableWebSearch === false ? 'off' : 'default',
      ttsConfig: {
        voiceModelId:
          charTts.voice_model_id != null && String(charTts.voice_model_id) !== ''
            ? String(charTts.voice_model_id)
            : '',
        language: typeof charTts.language === 'string' ? charTts.language : '',
        emotions: parseEmotions(charTts.emotions),
      },
    };
    const nextBackgroundFiles = Array.isArray(char.knowledgeAssets)
      ? char.knowledgeAssets.map((asset: { fileName: string; fileUrl: string; fileType: string }) => ({
          name: asset.fileName,
          url: asset.fileUrl,
          type: asset.fileType,
        }))
      : [];

    setForm(nextForm);
    setBackgroundFiles(nextBackgroundFiles);
    setAiFilledFields(new Set());
    setAiEditedFields(new Set());
    setPreAiSnapshot(null);
    setAiUndoDeadline(0);
    skipNextPromptPreviewSyncRef.current = true;
    setSystemPromptPreview(
      char.systemPromptPreview || buildCharacterSystemPromptPreview(nextForm, nextBackgroundFiles, promptPreviewLocale)
    );
  }, [data, promptPreviewLocale]);

  useEffect(() => {
    if (skipNextPromptPreviewSyncRef.current) {
      skipNextPromptPreviewSyncRef.current = false;
      return;
    }

    setSystemPromptPreview(buildCharacterSystemPromptPreview({
      name: form.name,
      description: form.description,
      userAddress: form.userAddress,
      personality: form.personality,
      appearance: form.appearance,
      affiliation: form.affiliation,
      responseGuidelines: form.responseGuidelines,
      scenario: form.scenario,
      exampleDialogue: form.exampleDialogue,
    }, backgroundFiles, promptPreviewLocale));
  }, [
    backgroundFiles,
    form.affiliation,
    form.appearance,
    form.description,
    form.exampleDialogue,
    form.name,
    form.personality,
    form.responseGuidelines,
    form.scenario,
    form.userAddress,
    promptPreviewLocale,
  ]);

  useEffect(() => {
    if (highlightDeadline === 0 && aiUndoDeadline === 0) {
      return;
    }
    if (now >= highlightDeadline && now >= aiUndoDeadline) {
      return;
    }
    const handle = setTimeout(() => setNow(Date.now()), 120);
    return () => clearTimeout(handle);
  }, [now, highlightDeadline, aiUndoDeadline]);

  const updateForm = (field: keyof FormState, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }));
    if (aiFilledFields.has(field as AiDraftKey)) {
      setAiEditedFields((prevEdited) => {
        if (prevEdited.has(field as AiDraftKey)) {
          return prevEdited;
        }
        const next = new Set(prevEdited);
        next.add(field as AiDraftKey);
        return next;
      });
    }
  };

  const uploadSingleFile = useCallback(async (item: PendingReferenceFile) => {
    const formData = new FormData();
    formData.append('file', item.file);
    // Keep the folder-group hierarchy so the memory filesystem can expose the
    // uploaded tree (Momotalk/xxx/scene.txt) instead of a flat name list.
    formData.append('relative_path', item.relativePath || item.file.name);

    const res = await fetch(FILES_UPLOAD_API_URL, { method: 'POST', body: formData });
    if (!res.ok) {
      throw new Error(copy.characterForm.uploadFailed);
    }

    const uploadData = await res.json();
    return {
      uploadedUrl: uploadData.url || uploadData.uri,
      uploadedName: item.displayName || uploadData.display_name || uploadData.relative_path || uploadData.name || item.file.name,
      uploadedType: item.file.type.startsWith('image/') ? 'image' : 'text',
      file: item.file,
    };
  }, [copy.characterForm.uploadFailed]);

  const processFileUpload = useCallback(async (file: File, target: 'avatar' | 'background') => {
    setUploadingTarget(target);
    try {
      const uploaded = await uploadSingleFile({ file, displayName: file.name, relativePath: file.name });

      if (target === 'background') {
        setBackgroundFiles((prev) => [
          ...prev,
          { name: uploaded.uploadedName, url: uploaded.uploadedUrl, type: uploaded.uploadedType },
        ]);
      } else {
        setForm((prev) => ({ ...prev, avatarUrl: uploaded.uploadedUrl }));
      }
    } catch (error) {
      console.error(error);
      alert(copy.characterForm.uploadFailedAlert);
    } finally {
      setUploadingTarget(null);
    }
  }, [copy.characterForm.uploadFailedAlert, uploadSingleFile]);

  const processBackgroundFilesUpload = useCallback(async (items: PendingReferenceFile[]) => {
    if (!items.length) {
      return;
    }

    setUploadingTarget('background');
    try {
      const results = await Promise.allSettled(items.map((item) => uploadSingleFile(item)));
      const uploadedFiles = results
        .filter((result): result is PromiseFulfilledResult<Awaited<ReturnType<typeof uploadSingleFile>>> => result.status === 'fulfilled')
        .map((result) => result.value);

      if (uploadedFiles.length) {
        setBackgroundFiles((prev) => [
          ...prev,
          ...uploadedFiles.map((uploaded) => ({
            name: uploaded.uploadedName,
            url: uploaded.uploadedUrl,
            type: uploaded.uploadedType,
          })),
        ]);
      }

      const failedCount = items.length - uploadedFiles.length;
      setFailedUploadCount((prev) => prev + failedCount);
      if (failedCount) {
        alert(copy.characterForm.uploadSomeFailed(failedCount));
      }
    } finally {
      setUploadingTarget(null);
    }
  }, [copy.characterForm, uploadSingleFile]);

  const handleAvatarFileSelected = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) {
      return;
    }
    if (!file.type.startsWith('image/')) {
      alert(copy.avatarCropper.mustBeImage);
      return;
    }
    // Revoke any previously held object URL to avoid leaking blobs if the
    // user picks a new file while the cropper is already open.
    setAvatarCropSrc((previous) => {
      if (previous) {
        URL.revokeObjectURL(previous);
      }
      return URL.createObjectURL(file);
    });
  };

  const handleAvatarCropApply = async (blob: Blob) => {
    const croppedFile = new File([blob], 'avatar.jpg', { type: 'image/jpeg' });
    if (avatarCropSrc) {
      URL.revokeObjectURL(avatarCropSrc);
      setAvatarCropSrc(null);
    }
    await processFileUpload(croppedFile, 'avatar');
  };

  const handleAvatarCropCancel = () => {
    if (avatarCropSrc) {
      URL.revokeObjectURL(avatarCropSrc);
      setAvatarCropSrc(null);
    }
  };

  const removeBackgroundFile = (targetUrl: string) => {
    setBackgroundFiles((prev) => prev.filter((file) => file.url !== targetUrl));
  };

  const applyDraftToForm = useCallback((draft: {
    name?: string;
    description?: string;
    affiliation?: string;
    tags?: string[];
    exampleDialogue?: string;
  }) => {
    setForm((prev) => {
      const next: FormState = { ...prev };
      const filled: AiDraftKey[] = [];
      const normalizedExampleDialogue = (draft.exampleDialogue || '').trim();

      if (draft.name && draft.name !== 'Unknown') {
        const targetName = autoTargetName.trim();
        if (draft.name !== prev.name) {
          next.name = targetName || draft.name;
          filled.push('name');
        }
      }
      if (draft.description && draft.description !== prev.description) {
        next.description = draft.description;
        filled.push('description');
      }
      if (draft.affiliation && draft.affiliation !== prev.affiliation) {
        next.affiliation = draft.affiliation;
        filled.push('affiliation');
      }
      if (Array.isArray(draft.tags) && draft.tags.length) {
        const nextTags = draft.tags.join(', ');
        if (nextTags !== prev.tags) {
          next.tags = nextTags;
          filled.push('tags');
        }
      }
      if (normalizedExampleDialogue && normalizedExampleDialogue !== prev.exampleDialogue) {
        next.exampleDialogue = normalizedExampleDialogue;
        filled.push('exampleDialogue');
      }

      if (filled.length) {
        setAiFilledFields(new Set(filled));
        setAiEditedFields(new Set());
        setPreAiSnapshot(pickFormState(prev, filled));
        setAiUndoDeadline(Date.now() + AI_UNDO_WINDOW_MS);
        setHighlightDeadline(Date.now() + AI_HIGHLIGHT_MS);
        setNow(Date.now());
      }
      return next;
    });
  }, [autoTargetName]);

  const handleAiGenerate = async () => {
    const draftSourceFiles = backgroundFiles.filter((file) => file.type === 'text');
    if (!draftSourceFiles.length && !autoInputText.trim()) {
      alert(copy.characterForm.needSourceBeforeGenerate);
      return;
    }

    let combinedContext = '';
    const promptCopy = getPromptPreviewCopy(promptPreviewLocale);
    if (autoTargetName.trim()) {
      combinedContext += `${promptCopy.targetCharacterName}: ${autoTargetName.trim()}\n`;
    }
    combinedContext += `${promptCopy.characterBrief}:\n${autoInputText}`;

    try {
      const response = await generateDraft({
        variables: {
          fileUrls: draftSourceFiles.map((file) => file.url),
          fileNames: draftSourceFiles.map((file) => file.name),
          textContext: combinedContext,
          locale: promptPreviewLocale,
        }
      });

      const draft = response.data.generateCharacterDraft;
      if (draft.name === 'Generation Failed' || draft.name === copy.characterForm.generateFailedName) {
        alert(copy.characterForm.generateFailedAlert(draft.description));
        return;
      }

      applyDraftToForm(draft);
    } catch (error: unknown) {
      console.error('AI Generation Error', error);
      alert(copy.characterForm.generationRequestError(getErrorMessage(error, copy.characterForm.unknownError)));
    }
  };

  const handleUndoAiFill = () => {
    if (!preAiSnapshot) {
      return;
    }
    setForm((prev) => ({ ...prev, ...preAiSnapshot }));
    setAiFilledFields(new Set());
    setAiEditedFields(new Set());
    setPreAiSnapshot(null);
    setAiUndoDeadline(0);
    setHighlightDeadline(0);
  };

  const handleSave = async () => {
    if (!form.name.trim() || !form.description.trim()) {
      alert(copy.characterForm.nameAndBriefRequired);
      return;
    }

    if (form.name === 'Generation Failed' || form.name === copy.characterForm.generateFailedName) {
      alert(copy.characterForm.cannotSaveGenerationError);
      return;
    }

    // 参考文件组还没传完就保存，是“角色存了但文件丢了”的直接原因：
    // 这里必须等上传结束，失败的部分要用户确认后才能继续。
    if (uploadingTarget) {
      alert(copy.characterForm.saveBlockedWhileUploading);
      return;
    }
    if (failedUploadCount > 0) {
      const proceed = window.confirm(copy.characterForm.saveWithFailedUploads(failedUploadCount));
      if (!proceed) {
        return;
      }
    }

    try {
      const input = {
        name: form.name.trim(),
        description: form.description.trim(),
        userAddress: form.userAddress.trim(),
        personality: form.personality.trim(),
        appearance: form.appearance.trim(),
        affiliation: form.affiliation.trim(),
        systemPromptPreview,
        responseGuidelines: form.responseGuidelines.trim(),
        avatarUrl: form.avatarUrl || '',
        scenario: form.scenario.trim(),
        exampleDialogue: form.exampleDialogue.trim(),
        tags: form.tags.split(/[,，]/).map((tag) => tag.trim()).filter(Boolean),
      enableWebSearch:
        form.webSearchMode === 'on' ? true : form.webSearchMode === 'off' ? false : null,
      ttsConfig: toTtsConfigInput(form.ttsConfig),
        backgroundFiles: backgroundFiles.map((file) => ({
          uploadedUrl: file.url,
          fileName: file.name,
        })),
      };

      if (isEditMode) {
        await updateCharacter({ variables: { id: characterId, input } });
      } else {
        await createCharacter({ variables: { input } });
      }

      window.location.href = '/';
    } catch (error: unknown) {
      console.error(error);
      alert(copy.characterForm.saveFailed(getErrorMessage(error, copy.characterForm.unknownError)));
    }
  };

  const isUploadingAvatar = uploadingTarget === 'avatar';
  const isUploadingBackground = uploadingTarget === 'background';
  const textReferenceCount = backgroundFiles.filter((file) => file.type === 'text').length;
  // 仅在「跟随全局（全局可能是 genie）/ 明确 genie」且版本不被 genie 支持时提示；
  // gptsovits 引擎下 v2pr/v4 是合法组合，不应打扰。
  const canUndoAiFill = preAiSnapshot !== null && now < aiUndoDeadline;
  const isHighlighted = (key: AiDraftKey) =>
    aiFilledFields.has(key) && !aiEditedFields.has(key) && now < highlightDeadline;

  const renderFieldBadge = (key: AiDraftKey) => {
    if (!aiFilledFields.has(key)) {
      return null;
    }
    if (aiEditedFields.has(key)) {
      return (
        <span
          title={copy.characterForm.fieldBadgeModifiedTitle}
          className="ml-2 inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-500"
        >
          {copy.characterForm.fieldBadgeModified}
        </span>
      );
    }
    return (
      <span
        title={copy.characterForm.fieldBadgeAiTitle}
        className={`ml-2 inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-violet-700 transition-shadow ${
          isHighlighted(key) ? 'bg-violet-100 ring-2 ring-violet-300' : 'bg-violet-50'
        }`}
      >
        {copy.characterForm.fieldBadgeAi}
      </span>
    );
  };

  const fieldHighlightClass = (key: AiDraftKey) =>
    isHighlighted(key) ? 'ring-2 ring-violet-300 transition-shadow' : '';

  return (      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        {avatarCropSrc && (
          <AvatarCropper
            imageSrc={avatarCropSrc}
            copy={copy.avatarCropper}
            shape="round"
            onCancel={handleAvatarCropCancel}
            onApply={handleAvatarCropApply}
          />
        )}
        <div className="mb-8 flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="flex items-center">
          {isEditMode && (
            <button
              onClick={() => router.back()}
              className="group mr-1 -ml-2 flex h-10 w-10 items-center justify-center rounded-full transition-colors hover:bg-gray-100"
              title={copy.characterForm.back}
            >
              <ArrowLeft className="h-5 w-5 text-gray-400 transition-colors group-hover:text-gray-800" strokeWidth={2.5} />
            </button>
          )}
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-gray-800">
              {isEditMode ? copy.characterForm.editTitle : copy.characterForm.createTitle}
            </h1>
            <p className="mt-1 text-sm text-gray-500">
              {copy.characterForm.heroSubtitle}
            </p>
          </div>
        </div>

        <div className="rounded-2xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-800">
          {copy.characterForm.defaultRequired}
        </div>
      </div>

      <div className="space-y-6">
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
          <div className="space-y-6">
            <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
              <div className="relative mx-auto mb-4 h-40 w-40 overflow-hidden rounded-full border-4 border-white bg-gray-100 shadow-md">
                {form.avatarUrl ? (
                  /* eslint-disable-next-line @next/next/no-img-element */
                  <img
                    src={form.avatarUrl}
                    alt={copy.characterForm.characterAvatarAlt(form.name || copy.gallery.character)}
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-gray-300">
                    <ImageIcon size={40} />
                  </div>
                )}
                <button
                  onClick={() => avatarInputRef.current?.click()}
                  className="absolute inset-0 flex items-center justify-center bg-black/0 text-transparent transition-all hover:bg-black/45 hover:text-white"
                  type="button"
                >
                  {isUploadingAvatar ? <Loader2 className="animate-spin" /> : <Upload />}
                </button>
                <input
                  ref={avatarInputRef}
                  type="file"
                  className="hidden"
                  accept="image/*"
                  onChange={handleAvatarFileSelected}
                />
              </div>

              <div className="space-y-2 text-center">
                <p className="text-sm font-medium text-gray-700">{copy.characterForm.avatar}</p>
                <p className="text-xs leading-6 text-gray-500">{copy.characterForm.avatarHelp}</p>
              </div>
            </div>

            <ReferenceAndAiPanel
              files={backgroundFiles}
              isUploading={isUploadingBackground}
              isGenerating={aiLoading}
              canUndo={canUndoAiFill}
              textReferenceCount={textReferenceCount}
              autoTargetName={autoTargetName}
              autoInputText={autoInputText}
              onAutoTargetNameChange={setAutoTargetName}
              onAutoInputTextChange={setAutoInputText}
              onFilesAdded={(files) => void processBackgroundFilesUpload(files)}
              onRemoveFile={removeBackgroundFile}
              onGenerate={handleAiGenerate}
              onUndo={handleUndoAiFill}
              copy={copy.characterForm}
              locale={promptPreviewLocale}
            />
          </div>

          <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm sm:p-8">
            <div className="mb-6">
              <h2 className="text-xl font-bold text-gray-800">{copy.characterForm.coreCharacter}</h2>
              <p className="mt-1 text-sm text-gray-500">
                {copy.characterForm.coreCharacterHelp}
              </p>
              <p className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                {copy.characterForm.autoGeneratedNeedsReviewHelp}
              </p>
            </div>

            <div className="space-y-6">
              <div className="space-y-2">
                <label className="text-sm font-bold text-gray-700">
                  {copy.characterForm.name}
                  {renderFieldBadge('name')}
                  <span className="text-red-500"> *</span>
                </label>
                <input
                  value={form.name}
                  onChange={(e) => updateForm('name', e.target.value)}
                  placeholder={copy.characterForm.namePlaceholder}
                  className={`w-full rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 ${fieldHighlightClass('name')}`}
                />
              </div>

              <div className="space-y-2">
                <label className="text-sm font-bold text-gray-700">
                  {copy.characterForm.coreCharacterBrief}
                  {renderFieldBadge('description')}
                  <span className="text-red-500"> *</span>
                </label>
                <textarea
                  value={form.description}
                  onChange={(e) => updateForm('description', e.target.value)}
                  rows={8}
                  placeholder={copy.characterForm.coreBriefPlaceholder}
                  className={`w-full rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 ${fieldHighlightClass('description')}`}
                />
                <p className="text-xs text-gray-500">
                  {copy.characterForm.coreBriefHelp}
                </p>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-bold text-gray-700">{copy.characterForm.userAddress}</label>
                <input
                  value={form.userAddress}
                  onChange={(e) => updateForm('userAddress', e.target.value)}
                  placeholder={copy.characterForm.userAddressPlaceholder}
                  className="w-full rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                />
                <p className="text-xs text-gray-500">
                  {copy.characterForm.userAddressHelp}
                </p>
              </div>

              <div className="grid gap-6 xl:grid-cols-2">
                <div className="space-y-2">
                  <label className="text-sm font-bold text-gray-700">{copy.characterForm.personalityNotes}</label>
                  <textarea
                    value={form.personality}
                    onChange={(e) => updateForm('personality', e.target.value)}
                    rows={5}
                    className="w-full rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                  />
                </div>

                <div className="space-y-2">
                  <label className="text-sm font-bold text-gray-700">{copy.characterForm.speakingRules}</label>
                  <textarea
                    value={form.responseGuidelines}
                    onChange={(e) => updateForm('responseGuidelines', e.target.value)}
                    rows={5}
                    placeholder={copy.characterForm.speakingRulesPlaceholder}
                    className="w-full rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                  />
                </div>
              </div>

              <div className="grid gap-6 md:grid-cols-2">
                <div className="space-y-2">
                  <label className="text-sm font-bold text-gray-700">
                    {copy.characterForm.affiliation}
                    {renderFieldBadge('affiliation')}
                  </label>
                  <input
                    value={form.affiliation}
                    onChange={(e) => updateForm('affiliation', e.target.value)}
                    placeholder={copy.characterForm.affiliationPlaceholder}
                    className={`w-full rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 ${fieldHighlightClass('affiliation')}`}
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-bold text-gray-700">
                    {copy.characterForm.tags}
                    {renderFieldBadge('tags')}
                  </label>
                  <input
                    value={form.tags}
                    onChange={(e) => updateForm('tags', e.target.value)}
                    placeholder={copy.characterForm.tagsPlaceholder}
                    className={`w-full rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 ${fieldHighlightClass('tags')}`}
                  />
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-bold text-gray-700">
                  {copy.characterForm.exampleDialogue}
                  {renderFieldBadge('exampleDialogue')}
                </label>
                <textarea
                  value={form.exampleDialogue}
                  onChange={(e) => updateForm('exampleDialogue', e.target.value)}
                  rows={5}
                  placeholder={copy.characterForm.exampleDialoguePlaceholder}
                  className={`w-full rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 ${fieldHighlightClass('exampleDialogue')}`}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-bold text-gray-700">
                  {copy.characterForm.webSearchLabel}
                </label>
                <select
                  value={form.webSearchMode}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, webSearchMode: e.target.value as WebSearchMode }))
                  }
                  className="w-full rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                >
                  <option value="default">{copy.characterForm.webSearchDefault}</option>
                  <option value="on">{copy.characterForm.webSearchOn}</option>
                  <option value="off">{copy.characterForm.webSearchOff}</option>
                </select>
                <p className="text-xs text-gray-400">{copy.characterForm.webSearchHint}</p>
              </div>

              <div className="space-y-3 rounded-2xl border border-amber-100 bg-amber-50/50 p-4">
                <div>
                  <label className="text-sm font-bold text-gray-700">
                    {copy.characterForm.ttsSectionTitle}
                  </label>
                  <p className="mt-1 text-xs text-gray-400">{copy.characterForm.ttsSectionHint}</p>
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-gray-500">
                    {copy.characterForm.ttsVoiceModelLabel}
                  </label>
                  <select
                    value={form.ttsConfig.voiceModelId}
                    onChange={(e) =>
                      setForm((prev) => ({
                        ...prev,
                        ttsConfig: { ...prev.ttsConfig, voiceModelId: e.target.value },
                      }))
                    }
                    className="w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-sm outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                  >
                    <option value="">{copy.characterForm.ttsVoiceModelEmpty}</option>
                    {voiceModels.map((voice) => (
                      <option key={voice.id} value={String(voice.id)}>
                        {ttsOptionLabel(voice)}
                      </option>
                    ))}
                  </select>
                  <p className="text-[11px] leading-4 text-gray-400">
                    {copy.characterForm.ttsVoiceModelHint}
                  </p>
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-gray-500">
                    {copy.characterForm.ttsLanguageLabel}
                  </label>
                  <select
                    value={form.ttsConfig.language}
                    onChange={(e) =>
                      setForm((prev) => ({
                        ...prev,
                        ttsConfig: { ...prev.ttsConfig, language: e.target.value },
                      }))
                    }
                    className="w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-sm outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                  >
                    <option value="">{copy.characterForm.ttsLanguageEmpty}</option>
                    <option value="zh">中文</option>
                    <option value="jp">日本語</option>
                    <option value="en">English</option>
                    <option value="ko">한국어</option>
                  </select>
                  <p className="text-[11px] leading-4 text-gray-400">
                    {copy.characterForm.ttsLanguageHint}
                  </p>
                </div>

                <div className="space-y-2 border-t border-amber-200/70 pt-3">
                  <div>
                    <label className="text-xs font-bold text-gray-700">
                      {copy.characterForm.emotionSectionTitle}
                    </label>
                    <p className="mt-0.5 text-[11px] leading-4 text-gray-400">
                      {copy.characterForm.emotionSectionHint}
                    </p>
                  </div>
                  {form.ttsConfig.emotions.map((emotion, index) => (
                    <div
                      key={index}
                      className="space-y-2 rounded-xl border border-amber-200 bg-white/70 p-3"
                    >
                      <div className="flex items-end gap-2">
                        <div className="flex-1 space-y-1">
                          <label className="text-[11px] font-medium text-gray-500">
                            {copy.characterForm.emotionNameLabel}
                          </label>
                          <input
                            value={emotion.name}
                            onChange={(e) => updateEmotion(index, { name: e.target.value })}
                            placeholder={copy.characterForm.emotionNamePlaceholder}
                            className="w-full rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-sm outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                          />
                        </div>
                        <button
                          type="button"
                          onClick={() => removeEmotion(index)}
                          title={copy.characterForm.emotionRemove}
                          className="mb-0.5 rounded-lg bg-red-50 px-2.5 py-1.5 text-xs font-medium text-red-500 transition-colors hover:bg-red-100"
                        >
                          ✕
                        </button>
                      </div>
                      <div className="space-y-1">
                        <label className="text-[11px] font-medium text-gray-500">
                          {copy.characterForm.emotionRefAudioLabel}
                        </label>
                        <input
                          value={emotion.refAudioPath}
                          onChange={(e) => updateEmotion(index, { refAudioPath: e.target.value })}
                          placeholder={copy.characterForm.emotionRefAudioPlaceholder}
                          className="w-full rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 font-mono text-xs outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                        />
                      </div>
                      <div className="space-y-1">
                        <label className="text-[11px] font-medium text-gray-500">
                          {copy.characterForm.emotionRefTextLabel}
                        </label>
                        <textarea
                          value={emotion.refAudioText}
                          onChange={(e) => updateEmotion(index, { refAudioText: e.target.value })}
                          placeholder={copy.characterForm.emotionRefTextPlaceholder}
                          rows={2}
                          className="w-full rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                        />
                      </div>
                      <div className="space-y-1">
                        <label className="text-[11px] font-medium text-gray-500">
                          {copy.characterForm.emotionRefLanguageLabel}
                        </label>
                        <select
                          value={emotion.refAudioLanguage}
                          onChange={(e) => updateEmotion(index, { refAudioLanguage: e.target.value })}
                          className="w-full rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-sm outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                        >
                          <option value="">{copy.characterForm.ttsLanguageEmpty}</option>
                          <option value="zh">中文</option>
                          <option value="jp">日本語</option>
                          <option value="en">English</option>
                          <option value="ko">한국어</option>
                        </select>
                      </div>
                    </div>
                  ))}
                  <button
                    type="button"
                    onClick={addEmotion}
                    className="w-full rounded-lg border border-dashed border-amber-300 bg-white/60 px-3 py-2 text-xs font-medium text-amber-600 transition-colors hover:bg-amber-50"
                  >
                    ＋ {copy.characterForm.emotionAdd}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="rounded-2xl border border-sky-100 bg-gradient-to-br from-sky-50 to-white p-6 shadow-sm sm:p-8">
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-gray-900">{copy.characterForm.systemPromptPreviewTitle}</h2>
            <p className="mt-1 text-sm text-gray-500">{copy.characterForm.systemPromptPreviewHelp}</p>
            <p className="mt-2 rounded-xl border border-sky-200 bg-white/80 px-3 py-2 text-xs text-sky-900">
              {copy.characterForm.systemPromptPreviewRefreshHint}
            </p>
          </div>

          <textarea
            value={systemPromptPreview}
            onChange={(e) => setSystemPromptPreview(e.target.value)}
            rows={16}
            placeholder={copy.characterForm.systemPromptPreviewPlaceholder}
            className="w-full rounded-2xl border border-sky-200 bg-white px-4 py-3 font-mono text-sm leading-6 text-gray-800 outline-none transition-all focus:border-sky-500 focus:ring-2 focus:ring-sky-500/20"
          />
        </div>

        <div className="flex justify-end gap-4">
          <button
            onClick={() => {
              if (onCancel) {
                onCancel();
              } else {
                router.push('/');
              }
            }}
            className="rounded-xl bg-gray-100 px-6 py-3 font-medium text-gray-700 transition-colors hover:bg-gray-200"
            type="button"
          >
            {copy.characterForm.cancel}
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saveLoading || uploadingTarget !== null}
            className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-6 py-3 font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-70"
          >
            {saveLoading ? <Loader2 className="animate-spin" size={18} /> : <Save size={18} />}
            <span>{isEditMode ? copy.characterForm.updateCharacter : copy.characterForm.saveCharacter}</span>
          </button>
        </div>
      </div>
    </div>
  );
}

