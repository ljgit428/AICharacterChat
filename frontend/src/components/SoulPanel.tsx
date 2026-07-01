"use client";

import { useEffect, useMemo, useRef, useState } from 'react';
import { apiService } from '@/utils/api';
import { MemoryExplorerEntry, MemoryExplorerFile } from '@/types';
import { ChevronLeft, FileCode2, FileImage, Folder, FolderTree, Link2, RefreshCw, Trash2, Upload } from 'lucide-react';
import { useI18n } from '@/i18n/provider';

interface SoulPanelProps {
  characterId: string;
  characterName?: string;
  refreshKey?: string;
  isOpen: boolean;
  isMobile?: boolean;
  onToggle: () => void;
  className?: string;
}

function getPreviewLabel(entry: MemoryExplorerEntry | MemoryExplorerFile | null, fallback: string) {
  if (!entry) {
    return fallback;
  }
  return entry.title || entry.path || fallback;
}

export default function SoulPanel({
  characterId,
  characterName,
  refreshKey,
  isOpen,
  isMobile = false,
  onToggle,
  className = '',
}: SoulPanelProps) {
  const { messages, formatDateTime, locale } = useI18n();
  const pendingSelectedAssetIdRef = useRef<string | null>(null);
  const localCopy = locale === 'zh-CN'
    ? {
        sidebarSubtitle: '在这里浏览完整的记忆文件树。只有已上传的参考文件可以新增或删除。',
        noFilesYet: '暂无可用的记忆文件。',
        upload: '上传',
        uploading: '正在上传...',
        refresh: '刷新',
        delete: '删除',
        deleting: '正在删除...',
        openOriginal: '打开原文件',
        userFile: '用户文件',
        readOnlyExplorer: '只读记忆树',
        binaryPreviewUnavailable: '这种文件类型暂不支持内联预览。',
        failedToDeleteFile: '删除文件失败',
        confirmDeleteFile: (name: string) => `确定删除“${name}”这个参考文件吗？`,
      }
    : {
        sidebarSubtitle: 'Browse the full memory tree. Only uploaded reference files can be added or removed here.',
        noFilesYet: 'No files are available in memory yet.',
        upload: 'Upload',
        uploading: 'Uploading...',
        refresh: 'Refresh',
        delete: 'Delete',
        deleting: 'Deleting...',
        openOriginal: 'Open original',
        userFile: 'User file',
        readOnlyExplorer: 'Read-only memory tree',
        binaryPreviewUnavailable: 'Inline preview is not available for this file type.',
        failedToDeleteFile: 'Failed to delete file',
        confirmDeleteFile: (name: string) => `Delete "${name}" from character reference files?`,
      };
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [entries, setEntries] = useState<MemoryExplorerEntry[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<MemoryExplorerFile | null>(null);
  const [isLoadingTree, setIsLoadingTree] = useState(true);
  const [isLoadingFile, setIsLoadingFile] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [reloadNonce, setReloadNonce] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isCancelled = false;

    const loadTree = async () => {
      setIsLoadingTree(true);
      setError(null);

      try {
        const response = await apiService.listSoulFiles(characterId, '', true);
        if (response.error) {
          throw new Error(response.error);
        }

        if (isCancelled) {
          return;
        }

        const nextEntries = response.data || [];
        const nextFiles = nextEntries.filter((entry) => entry.entryType === 'file');
        setEntries(nextEntries);
        setSelectedPath((prev) => {
          if (pendingSelectedAssetIdRef.current) {
            const nextSelected = nextFiles.find((entry) => entry.assetId === pendingSelectedAssetIdRef.current)?.path;
            if (nextSelected) {
              return nextSelected;
            }
          }
          if (prev && nextFiles.some((entry) => entry.path === prev)) {
            return prev;
          }
          return nextFiles[0]?.path || null;
        });
        pendingSelectedAssetIdRef.current = null;
      } catch (loadError) {
        if (!isCancelled) {
          setError(loadError instanceof Error ? loadError.message : messages.soul.failedToLoadSoulFiles);
        }
      } finally {
        if (!isCancelled) {
          setIsLoadingTree(false);
        }
      }
    };

    void loadTree();

    return () => {
      isCancelled = true;
    };
  }, [characterId, refreshKey, reloadNonce, messages.soul.failedToLoadSoulFiles]);

  useEffect(() => {
    let isCancelled = false;

    const loadFile = async () => {
      if (!selectedPath) {
        setSelectedFile(null);
        return;
      }

      setIsLoadingFile(true);
      setError(null);
      try {
        const response = await apiService.readSoulFile(characterId, selectedPath);
        if (response.error) {
          throw new Error(response.error);
        }
        if (!isCancelled) {
          setSelectedFile(response.data || null);
        }
      } catch (loadError) {
        if (!isCancelled) {
          setError(loadError instanceof Error ? loadError.message : messages.soul.failedToLoadSoulFiles);
          setSelectedFile(null);
        }
      } finally {
        if (!isCancelled) {
          setIsLoadingFile(false);
        }
      }
    };

    void loadFile();

    return () => {
      isCancelled = true;
    };
  }, [characterId, selectedPath, messages.soul.failedToLoadSoulFiles]);

  const visibleEntries = useMemo(
    () => entries.filter((entry) => entry.path !== '/'),
    [entries]
  );
  const selectedEntry = useMemo(
    () => visibleEntries.find((entry) => entry.path === selectedPath) || null,
    [selectedPath, visibleEntries]
  );

  const triggerRefresh = () => {
    setReloadNonce((current) => current + 1);
  };

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleUploadChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    event.target.value = '';
    if (!files.length) {
      return;
    }

    setIsUploading(true);
    setError(null);
    try {
      const response = await apiService.uploadKnowledgeAssets(characterId, files);
      if (response.error) {
        throw new Error(response.error);
      }

      const uploadedAssets = response.data || [];
      pendingSelectedAssetIdRef.current = uploadedAssets[uploadedAssets.length - 1]?.id || null;
      triggerRefresh();
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : messages.characterForm.uploadFailed);
    } finally {
      setIsUploading(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedFile?.manageable || !selectedFile.assetId) {
      return;
    }

    const confirmed = window.confirm(localCopy.confirmDeleteFile(getPreviewLabel(selectedFile, selectedPath || '')));
    if (!confirmed) {
      return;
    }

    setIsDeleting(true);
    setError(null);
    try {
      const response = await apiService.deleteKnowledgeAsset(characterId, selectedFile.assetId);
      if (response.error) {
        throw new Error(response.error);
      }
      setSelectedFile(null);
      triggerRefresh();
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : localCopy.failedToDeleteFile);
    } finally {
      setIsDeleting(false);
    }
  };

  if (!isOpen && !isMobile) {
    return (
      <aside className={`flex h-full w-full flex-shrink-0 flex-col items-center gap-3 rounded-[1.75rem] border border-slate-200/80 bg-white/75 px-2 py-3 shadow-[0_20px_60px_rgba(15,23,42,0.08)] backdrop-blur ${className}`}>
        <button
          type="button"
          onClick={onToggle}
          className="flex h-10 w-10 items-center justify-center rounded-2xl bg-slate-900 text-white transition-colors hover:bg-slate-800"
          title={messages.chat.toggleSoulPanel}
        >
          <FolderTree className="h-5 w-5" />
        </button>
        <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-slate-100 text-slate-500">
          <Upload className="h-4 w-4" />
        </div>
        <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-slate-100 text-slate-500">
          <FileCode2 className="h-4 w-4" />
        </div>
      </aside>
    );
  }

  return (
    <aside className={`flex h-full min-h-0 w-full flex-col overflow-hidden rounded-[1.75rem] border border-slate-200/80 bg-white/90 shadow-[0_24px_80px_rgba(15,23,42,0.08)] backdrop-blur ${className}`}>
      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        multiple
        accept=".txt,.md,.markdown,.json,.jsonl,.csv,.tsv,.log,.yaml,.yml,.xml,.ini,.cfg,.conf,.py,.js,.ts,.tsx,.jsx,.html,.css,.sql,text/*,image/*"
        onChange={handleUploadChange}
      />

      <div className="border-b border-slate-200/80 bg-[linear-gradient(180deg,rgba(248,250,252,0.95),rgba(255,255,255,0.92))] px-4 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-slate-900">
              {messages.soul.title(characterName)}
            </h3>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              {localCopy.sidebarSubtitle}
            </p>
          </div>
          <button
            type="button"
            onClick={onToggle}
            className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-slate-600 transition-colors hover:bg-slate-200 hover:text-slate-900"
            title={messages.chat.toggleSoulPanel}
          >
            <ChevronLeft className={`h-4 w-4 transition-transform ${isMobile ? 'rotate-180' : ''}`} />
          </button>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={handleUploadClick}
            disabled={isUploading || isDeleting}
            className="inline-flex items-center gap-2 rounded-full bg-slate-900 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            <Upload className="h-3.5 w-3.5" />
            <span>{isUploading ? localCopy.uploading : localCopy.upload}</span>
          </button>
          <button
            type="button"
            onClick={triggerRefresh}
            disabled={isLoadingTree || isUploading || isDeleting}
            className="inline-flex items-center gap-2 rounded-full bg-slate-100 px-3 py-2 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isLoadingTree ? 'animate-spin' : ''}`} />
            <span>{localCopy.refresh}</span>
          </button>
          <div className="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
            <FolderTree className="h-3.5 w-3.5" />
            <span>{localCopy.readOnlyExplorer}</span>
          </div>
        </div>
      </div>

      {error && (
        <div className="border-b border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid min-h-0 flex-1 gap-px bg-slate-200 xl:grid-cols-[0.95fr_1.15fr]">
        <div className="flex min-h-0 flex-col bg-white">
          <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-3 text-sm font-medium text-slate-800">
            <FolderTree className="h-4 w-4" />
            <span>{messages.soul.files}</span>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {isLoadingTree ? (
              <div className="px-3 py-6 text-sm text-slate-500">{messages.soul.loadingFiles}</div>
            ) : visibleEntries.length === 0 ? (
              <div className="px-3 py-6 text-sm text-slate-500">{localCopy.noFilesYet}</div>
            ) : visibleEntries.map((entry) => {
              const depth = entry.path.split('/').length - 1;
              const isDirectory = entry.entryType === 'directory';
              const isSelected = entry.entryType === 'file' && entry.path === selectedPath;
              const Icon = isDirectory
                ? Folder
                : entry.previewKind === 'image'
                  ? FileImage
                  : FileCode2;

              return isDirectory ? (
                <div
                  key={entry.path}
                  className="mb-1 flex items-center gap-2 rounded-xl px-3 py-2 text-left text-sm text-slate-500"
                  style={{ paddingLeft: `${12 + depth * 14}px` }}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  <span className="truncate">{entry.path}</span>
                </div>
              ) : (
                <button
                  key={entry.path}
                  type="button"
                  onClick={() => setSelectedPath(entry.path)}
                  className={`mb-1 flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm transition-colors ${
                    isSelected ? 'bg-sky-50 text-sky-700' : 'text-slate-600 hover:bg-slate-50'
                  }`}
                  style={{ paddingLeft: `${12 + depth * 14}px` }}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  <span className="min-w-0 flex-1 truncate">{entry.path}</span>
                  {entry.manageable && (
                    <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.14em] text-emerald-700">
                      {localCopy.userFile}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex min-h-0 flex-col bg-white">
          <div className="border-b border-slate-200 px-4 py-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-slate-900">
                  {selectedFile?.path || messages.soul.selectAFile}
                </div>
                {selectedFile && (
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <span>{selectedFile.kind}</span>
                    <span>{selectedFile.layer}</span>
                    {selectedFile.manageable ? (
                      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-emerald-700">
                        {localCopy.userFile}
                      </span>
                    ) : (
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">
                        {messages.soul.readOnly}
                      </span>
                    )}
                  </div>
                )}
              </div>
              {selectedFile?.manageable && selectedFile.assetId && (
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={isDeleting || isUploading}
                  className="inline-flex items-center gap-1.5 rounded-full bg-rose-50 px-3 py-2 text-xs font-medium text-rose-700 transition-colors hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  <span>{isDeleting ? localCopy.deleting : localCopy.delete}</span>
                </button>
              )}
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {!selectedPath ? (
              <div className="flex h-full items-center justify-center text-sm text-slate-500">
                {messages.soul.selectFileToInspect}
              </div>
            ) : isLoadingFile ? (
              <div className="flex h-full items-center justify-center text-sm text-slate-500">
                {messages.soul.loadingFile}
              </div>
            ) : selectedFile ? (
              <div className="space-y-3">
                {selectedFile.readHint && (
                  <div className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600">
                    {selectedFile.readHint}
                  </div>
                )}

                {selectedFile.previewKind === 'image' && selectedFile.fileUrl ? (
                  <div className="overflow-hidden rounded-2xl border border-slate-200 bg-slate-50">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={selectedFile.fileUrl}
                      alt={getPreviewLabel(selectedFile, selectedPath)}
                      className="max-h-[26rem] w-full object-contain bg-slate-100"
                    />
                  </div>
                ) : selectedFile.previewKind === 'text' ? (
                  <textarea
                    value={selectedFile.content}
                    readOnly
                    className="h-[22rem] w-full rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 font-mono text-sm leading-6 text-slate-700 outline-none"
                  />
                ) : (
                  <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                    <div className="flex items-center gap-2 text-sm font-medium text-slate-700">
                      <FileCode2 className="h-4 w-4" />
                      <span>{localCopy.binaryPreviewUnavailable}</span>
                    </div>
                    <pre className="mt-3 whitespace-pre-wrap text-xs leading-6 text-slate-600">{selectedFile.content}</pre>
                  </div>
                )}

                <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-3 py-3 text-xs text-slate-500">
                  <div className="flex flex-wrap items-center gap-3">
                    {selectedEntry?.updatedAt && (
                      <span>{formatDateTime(selectedEntry.updatedAt)}</span>
                    )}
                    {selectedFile.mimeType && (
                      <span>{selectedFile.mimeType}</span>
                    )}
                    {selectedFile.truncated && (
                      <span>{messages.soul.truncated}</span>
                    )}
                  </div>
                  {selectedFile.fileUrl && (
                    <a
                      href={selectedFile.fileUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1.5 font-medium text-slate-700 transition-colors hover:bg-slate-200"
                    >
                      <Link2 className="h-3.5 w-3.5" />
                      <span>{localCopy.openOriginal}</span>
                    </a>
                  )}
                </div>
              </div>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-slate-500">
                {messages.soul.selectFileToInspect}
              </div>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}
