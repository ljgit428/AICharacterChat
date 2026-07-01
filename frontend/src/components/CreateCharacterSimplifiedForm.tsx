"use client";

import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { useMutation, useQuery, gql } from '@apollo/client';
import { UPLOAD_API_URL } from '@/constants';
import { useI18n } from '@/i18n/provider';
import AvatarCropper from '@/components/AvatarCropper';
import {
  Upload,
  Sparkles,
  Save,
  Image as ImageIcon,
  Loader2,
  FileText,
  ArrowLeft,
  X,
  Undo2,
} from 'lucide-react';

type ReferenceFile = {
  name: string;
  url: string;
  type: string;
};

type PromptPreviewLocale = 'zh-CN' | 'en-US';

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
  mutation GenerateDraft($fileUrls: [String!], $textContext: String, $locale: String) {
    generateCharacterDraft(fileUrls: $fileUrls, textContext: $textContext, locale: $locale) {
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
  onFilesAdded: (files: File[]) => void;
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
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isBackgroundDragging, setIsBackgroundDragging] = useState(false);

  const hasTextSource = textReferenceCount > 0 || autoInputText.trim().length > 0;
  const canGenerate = hasTextSource && !isUploading && !isGenerating;

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleUploadChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const fileList = Array.from(event.target.files || []);
    event.target.value = '';
    if (fileList.length) {
      onFilesAdded(fileList);
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

      const fileList = Array.from(event.dataTransfer.files || []);
      if (fileList.length) {
        onFilesAdded(fileList);
      }
    },
    [onFilesAdded],
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

      {files.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {files.map((file) => (
            <div
              key={file.url}
              className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-white px-2.5 py-1 text-[11px] text-gray-700"
            >
              <span className="font-medium text-gray-500">
                {file.type === 'image' ? copy.imageReferenceLabel : copy.textReferenceLabel}
              </span>
              <span className="max-w-[160px] truncate">{file.name}</span>
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  onRemoveFile(file.url);
                }}
                className="rounded-full p-0.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700"
                aria-label={copy.removeBackgroundFile}
                title={copy.removeBackgroundFile}
              >
                <X size={10} />
              </button>
            </div>
          ))}
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
    avatarUrl: ''
  });
  const [autoInputText, setAutoInputText] = useState('');
  const [backgroundFiles, setBackgroundFiles] = useState<ReferenceFile[]>([]);
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

  const uploadSingleFile = useCallback(async (file: File) => {
    const formData = new FormData();
    formData.append('file', file);

    const res = await fetch(UPLOAD_API_URL, { method: 'POST', body: formData });
    if (!res.ok) {
      throw new Error(copy.characterForm.uploadFailed);
    }

    const uploadData = await res.json();
    return {
      uploadedUrl: uploadData.url || uploadData.uri,
      uploadedName: uploadData.display_name || uploadData.name || file.name,
      uploadedType: file.type.startsWith('image/') ? 'image' : 'text',
      file,
    };
  }, [copy.characterForm.uploadFailed]);

  const processFileUpload = useCallback(async (file: File, target: 'avatar' | 'background') => {
    setUploadingTarget(target);
    try {
      const uploaded = await uploadSingleFile(file);

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

  const processBackgroundFilesUpload = useCallback(async (files: File[]) => {
    if (!files.length) {
      return;
    }

    setUploadingTarget('background');
    try {
      const uploadedFiles = await Promise.all(files.map((file) => uploadSingleFile(file)));
      setBackgroundFiles((prev) => [
        ...prev,
        ...uploadedFiles.map((uploaded) => ({
          name: uploaded.uploadedName,
          url: uploaded.uploadedUrl,
          type: uploaded.uploadedType,
        })),
      ]);
    } catch (error) {
      console.error(error);
      alert(copy.characterForm.uploadFailedAlert);
    } finally {
      setUploadingTarget(null);
    }
  }, [copy.characterForm.uploadFailedAlert, uploadSingleFile]);

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
            disabled={saveLoading}
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

