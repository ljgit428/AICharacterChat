"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { apiService } from '@/utils/api';
import { MemoryExplorerEntry, MemoryExplorerFile } from '@/types';
import FileTree, { FileTreeNode } from '@/components/FileTree';
import {
  ChevronRight,
  FileCode2,
  FileImage,
  FolderTree,
  Link2,
  RefreshCw,
  Search,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import { useI18n } from '@/i18n/provider';

interface SoulPanelProps {
  characterId: string;
  characterName?: string;
  refreshKey?: string;
  isOpen: boolean;
  isMobile?: boolean;
  hideToggleButton?: boolean;
  onToggle: () => void;
  className?: string;
}

const UPLOADS_ROOT = 'raw/character_setup/uploads';
// 打开面板时默认展开到上传文件组所在层级，让用户第一眼看到自己的资料。
const DEFAULT_EXPANDED = ['raw', 'raw/character_setup', UPLOADS_ROOT];

function normalizePrefix(prefix: string) {
  return (prefix || '').replace(/^\/+|\/+$/g, '');
}

function parentPath(path: string) {
  const index = path.lastIndexOf('/');
  return index === -1 ? '' : path.slice(0, index);
}

function entryToNode(entry: MemoryExplorerEntry, listings: Record<string, MemoryExplorerEntry[]>): FileTreeNode {
  const children = entry.entryType === 'directory' && entry.path in listings
    ? listings[entry.path].map((child) => entryToNode(child, listings))
    : undefined;
  return {
    path: entry.path,
    title: entry.title || entry.path.split('/').pop() || entry.path,
    isDirectory: entry.entryType === 'directory',
    childCount: entry.childCount,
    sizeHint: entry.sizeHint,
    updatedAt: entry.updatedAt,
    manageable: entry.manageable,
    previewKind: entry.previewKind,
    children,
  };
}

function buildTreeNodes(listings: Record<string, MemoryExplorerEntry[]>): FileTreeNode[] {
  const roots = listings[''] || [];
  // 目录排在文件前面（后端已排序），这里保持顺序。
  return roots.map((entry) => entryToNode(entry, listings));
}

export default function SoulPanel({
  characterId,
  characterName,
  refreshKey,
  isOpen,
  isMobile = false,
  hideToggleButton = false,
  onToggle,
  className = '',
}: SoulPanelProps) {
  const { messages, formatDateTime } = useI18n();
  const copy = messages.soul;
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pendingSelectedAssetIdRef = useRef<string | null>(null);

  const [listings, setListings] = useState<Record<string, MemoryExplorerEntry[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loadingDirs, setLoadingDirs] = useState<Set<string>>(new Set());
  const [focusDir, setFocusDir] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<MemoryExplorerEntry[] | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [searchTruncated, setSearchTruncated] = useState(false);

  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [preview, setPreview] = useState<MemoryExplorerFile | null>(null);
  const [isLoadingFile, setIsLoadingFile] = useState(false);
  const [isReadingMore, setIsReadingMore] = useState(false);

  const [isUploading, setIsUploading] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);

  const ensureListing = useCallback(async (prefix: string) => {
    const normalized = normalizePrefix(prefix);
    setLoadingDirs((prev) => new Set(prev).add(normalized));
    try {
      const response = await apiService.listSoulFiles(characterId, normalized, false);
      if (response.error) {
        throw new Error(response.error);
      }
      const entries = response.data || [];
      setListings((prev) => ({ ...prev, [normalized]: entries }));
      return entries;
    } finally {
      setLoadingDirs((prev) => {
        const next = new Set(prev);
        next.delete(normalized);
        return next;
      });
    }
  }, [characterId]);

  const loadInitialTree = useCallback(async () => {
    setError(null);
    try {
      await ensureListing('');
      setExpanded((prev) => {
        const next = new Set(prev);
        DEFAULT_EXPANDED.forEach((path) => next.add(path));
        return next;
      });
      setFocusDir((prev) => (prev ? prev : UPLOADS_ROOT));
      await Promise.all(DEFAULT_EXPANDED.map((prefix) => ensureListing(prefix)));
      if (pendingSelectedAssetIdRef.current) {
        // 等树就绪后再定位新上传的资产；找不到就放弃。
        pendingSelectedAssetIdRef.current = null;
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : copy.failedToLoadSoulFiles);
    }
  }, [copy.failedToLoadSoulFiles, ensureListing]);

  useEffect(() => {
    let isCancelled = false;
    if (!isOpen && !isMobile) {
      return;
    }
    setListings({});
    setSelectedPath(null);
    setPreview(null);
    setSearchQuery('');
    setSearchResults(null);
    void (async () => {
      await loadInitialTree();
      if (isCancelled) {
        return;
      }
      // 刷新后按需恢复选中：优先定位刚上传的资产，否则选第一个文件。
    })();
    return () => {
      isCancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [characterId, reloadNonce, isOpen]);

  // 搜索：输入变化后延迟触发一次 recursive 全量查询，客户端过滤。
  useEffect(() => {
    const trimmed = searchQuery.trim().toLowerCase();
    if (!trimmed) {
      setSearchResults(null);
      setIsSearching(false);
      setSearchTruncated(false);
      return;
    }

    let isCancelled = false;
    setIsSearching(true);
    const handle = setTimeout(async () => {
      try {
        const response = await apiService.listSoulFiles(characterId, '', true);
        if (isCancelled) {
          return;
        }
        if (response.error) {
          throw new Error(response.error);
        }
        const all = response.data || [];
        setSearchTruncated(Boolean(response.data && (all.length >= 200)));
        setSearchResults(
          all.filter(
            (entry) =>
              entry.entryType === 'file' &&
              (entry.title.toLowerCase().includes(trimmed) || entry.path.toLowerCase().includes(trimmed)),
          ),
        );
      } catch (searchError) {
        if (!isCancelled) {
          setError(searchError instanceof Error ? searchError.message : copy.failedToLoadSoulFiles);
        }
      } finally {
        if (!isCancelled) {
          setIsSearching(false);
        }
      }
    }, 300);
    return () => {
      isCancelled = true;
      clearTimeout(handle);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchQuery, characterId]);

  const loadSelectedFile = useCallback(async (path: string) => {
    setIsLoadingFile(true);
    setError(null);
    try {
      const response = await apiService.readSoulFile(characterId, path);
      if (response.error) {
        throw new Error(response.error);
      }
      setPreview(response.data || null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : copy.failedToLoadSoulFiles);
      setPreview(null);
    } finally {
      setIsLoadingFile(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [characterId]);

  useEffect(() => {
    if (!selectedPath) {
      setPreview(null);
      return;
    }
    void loadSelectedFile(selectedPath);
  }, [selectedPath, loadSelectedFile]);

  // 会话更新（page.tsx 传入的 refreshKey 变化）时整树重载。
  const prevRefreshKeyRef = useRef(refreshKey);
  useEffect(() => {
    if (prevRefreshKeyRef.current !== refreshKey) {
      prevRefreshKeyRef.current = refreshKey;
      setReloadNonce((current) => current + 1);
    }
  }, [refreshKey]);

  const handleToggleDir = (node: FileTreeNode) => {    setFocusDir(node.path);
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(node.path)) {
        next.delete(node.path);
      } else {
        next.add(node.path);
      }
      return next;
    });
    if (!expanded.has(node.path) && !(node.path in listings)) {
      void ensureListing(node.path).catch((loadError) => {
        setError(loadError instanceof Error ? loadError.message : copy.failedToLoadSoulFiles);
      });
    }
  };

  const handleSelectFile = (node: FileTreeNode) => {
    setSelectedPath(node.path);
  };

  const triggerRefresh = () => {
    setReloadNonce((current) => current + 1);
  };

  const handleReadMore = async () => {
    if (!selectedPath || !preview?.hasMore || preview.nextOffset == null) {
      return;
    }
    setIsReadingMore(true);
    setError(null);
    try {
      const response = await apiService.readSoulFile(characterId, selectedPath, preview.nextOffset);
      if (response.error) {
        throw new Error(response.error);
      }
      const chunk = response.data;
      if (chunk) {
        setPreview({
          ...chunk,
          content: preview.content + chunk.content,
          offset: preview.offset ?? 0,
        });
      }
    } catch (readError) {
      setError(readError instanceof Error ? readError.message : copy.failedToLoadSoulFiles);
    } finally {
      setIsReadingMore(false);
    }
  };

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const uploadRelativeDir = (() => {
    if (focusDir === UPLOADS_ROOT) {
      return '';
    }
    if (focusDir.startsWith(`${UPLOADS_ROOT}/`)) {
      return focusDir.slice(UPLOADS_ROOT.length + 1);
    }
    return '';
  })();

  const handleUploadChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    event.target.value = '';
    if (!files.length) {
      return;
    }

    setIsUploading(true);
    setError(null);
    try {
      const relativePaths = files.map(
        (file) => (uploadRelativeDir ? `${uploadRelativeDir}/${file.name}` : file.name),
      );
      const response = await apiService.uploadKnowledgeAssets(characterId, files, relativePaths);
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
    if (!preview?.manageable || !preview.assetId) {
      return;
    }
    const confirmed = window.confirm(copy.confirmDeleteFile(preview.title || selectedPath || ''));
    if (!confirmed) {
      return;
    }
    setIsDeleting(true);
    setError(null);
    try {
      const response = await apiService.deleteKnowledgeAsset(characterId, preview.assetId);
      if (response.error) {
        throw new Error(response.error);
      }
      setSelectedPath(null);
      setPreview(null);
      triggerRefresh();
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : copy.failedToDeleteFile);
    } finally {
      setIsDeleting(false);
    }
  };

  const treeNodes = useMemo(() => buildTreeNodes(listings), [listings]);
  const breadcrumbSegments = useMemo(() => focusDir.split('/').filter(Boolean), [focusDir]);
  const selectedEntryMeta = useMemo(() => {
    if (searchResults) {
      const hit = searchResults.find((entry) => entry.path === selectedPath);
      if (hit) {
        return hit;
      }
    }
    const dirEntries = listings[parentPath(selectedPath || '')] || listings[''] || [];
    return dirEntries.find((entry) => entry.path === selectedPath) || null;
  }, [listings, searchResults, selectedPath]);

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
      </aside>
    );
  }

  const searching = Boolean(searchQuery.trim());

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
              {copy.title(characterName)}
            </h3>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              {copy.sidebarSubtitle}
            </p>
          </div>
          {!hideToggleButton && (
            <button
              type="button"
              onClick={onToggle}
              className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-slate-600 transition-colors hover:bg-slate-200 hover:text-slate-900"
              title={messages.chat.toggleSoulPanel}
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        <div className="relative mt-3">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
          <input
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder={copy.searchPlaceholder}
            className="w-full rounded-full border border-slate-200 bg-white px-9 py-2 text-xs outline-none transition-colors focus:border-sky-400 focus:ring-2 focus:ring-sky-100"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery('')}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-full p-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              title={messages.soul.clearSearch}
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {!searching && (
          <div className="mt-2 flex flex-wrap items-center gap-1 text-[11px] text-slate-500">
            <button
              type="button"
              onClick={() => setFocusDir('')}
              className="rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-700 transition-colors hover:bg-slate-200"
            >
              {copy.breadcrumbRoot}
            </button>
            {breadcrumbSegments.map((segment, index) => {
              const segmentPath = breadcrumbSegments.slice(0, index + 1).join('/');
              return (
                <span key={segmentPath} className="inline-flex items-center gap-1">
                  <ChevronRight className="h-3 w-3 text-slate-300" />
                  <button
                    type="button"
                    onClick={() => setFocusDir(segmentPath)}
                    className={`max-w-[10rem] truncate rounded-full px-2 py-0.5 transition-colors ${
                      index === breadcrumbSegments.length - 1
                        ? 'bg-sky-50 font-medium text-sky-700'
                        : 'hover:bg-slate-100'
                    }`}
                  >
                    {segment}
                  </button>
                </span>
              );
            })}
          </div>
        )}

        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={handleUploadClick}
            disabled={isUploading || isDeleting}
            title={
              uploadRelativeDir
                ? copy.uploadIntoFolder(uploadRelativeDir)
                : copy.uploadToUploads
            }
            className="inline-flex items-center gap-2 rounded-full bg-slate-900 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            <Upload className="h-3.5 w-3.5" />
            <span>{isUploading ? copy.uploading : copy.upload}</span>
          </button>
          <button
            type="button"
            onClick={triggerRefresh}
            disabled={isUploading || isDeleting}
            className="inline-flex items-center gap-2 rounded-full bg-slate-100 px-3 py-2 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            <span>{copy.refresh}</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="border-b border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid min-h-0 flex-1 gap-px bg-slate-200 xl:grid-cols-[0.95fr_1.15fr]">
        <div className="flex min-h-0 flex-col bg-white">
          <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 text-sm font-medium text-slate-800">
            <span className="inline-flex items-center gap-2">
              <FolderTree className="h-4 w-4" />
              <span>{copy.files}</span>
            </span>
            {isSearching && <RefreshCw className="h-3.5 w-3.5 animate-spin text-slate-400" />}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {searching ? (
              searchResults === null ? (
                <div className="px-3 py-6 text-sm text-slate-500">{copy.loadingFiles}</div>
              ) : searchResults.length === 0 ? (
                <div className="px-3 py-6 text-sm text-slate-500">{copy.noSearchResults}</div>
              ) : (
                <>
                  {searchTruncated && (
                    <div className="mb-1 rounded-lg bg-amber-50 px-2 py-1 text-[11px] text-amber-700">
                      {copy.listingTruncated}
                    </div>
                  )}
                  <ul className="space-y-0.5">
                    {searchResults.map((entry) => (
                      <li key={entry.path}>
                        <button
                          type="button"
                          onClick={() => setSelectedPath(entry.path)}
                          className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] transition-colors ${
                            entry.path === selectedPath ? 'bg-sky-50 text-sky-700' : 'text-slate-600 hover:bg-slate-50'
                          }`}
                        >
                          {entry.previewKind === 'image'
                            ? <FileImage className="h-3.5 w-3.5 shrink-0 text-sky-500" />
                            : <FileCode2 className="h-3.5 w-3.5 shrink-0 text-slate-400" />}
                          <span className="truncate">{entry.title}</span>
                          <span className="ml-auto shrink-0 truncate pl-2 text-[10px] text-slate-400">
                            {parentPath(entry.path)}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              )
            ) : loadingDirs.has('') && !treeNodes.length ? (
              <div className="px-3 py-6 text-sm text-slate-500">{copy.loadingFiles}</div>
            ) : !treeNodes.length ? (
              <div className="px-3 py-6 text-sm text-slate-500">{copy.noFilesYet}</div>
            ) : (
              <FileTree
                nodes={treeNodes}
                expandedPaths={expanded}
                loadingPaths={loadingDirs}
                selectedPath={selectedPath}
                onToggleDir={handleToggleDir}
                onSelectFile={handleSelectFile}
                emptyDirLabel={copy.emptyFolder}
              />
            )}
          </div>
        </div>

        <div className="flex min-h-0 flex-col bg-white">
          <div className="border-b border-slate-200 px-4 py-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-slate-900">
                  {preview?.path || copy.selectAFile}
                </div>
                {preview && (
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <span>{preview.kind}</span>
                    <span>{preview.layer}</span>
                    {typeof preview.totalChars === 'number' && (
                      <span>{`${preview.totalChars}c`}</span>
                    )}
                    {preview.manageable ? (
                      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-emerald-700">
                        {copy.userFile}
                      </span>
                    ) : (
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">
                        {copy.readOnly}
                      </span>
                    )}
                  </div>
                )}
              </div>
              {preview?.manageable && preview.assetId && (
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={isDeleting || isUploading}
                  className="inline-flex items-center gap-1.5 rounded-full bg-rose-50 px-3 py-2 text-xs font-medium text-rose-700 transition-colors hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  <span>{isDeleting ? copy.deleting : copy.delete}</span>
                </button>
              )}
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {!selectedPath ? (
              <div className="flex h-full items-center justify-center text-sm text-slate-500">
                {copy.selectFileToInspect}
              </div>
            ) : isLoadingFile ? (
              <div className="flex h-full items-center justify-center text-sm text-slate-500">
                {copy.loadingFile}
              </div>
            ) : preview ? (
              <div className="space-y-3">
                {preview.readHint && (
                  <div className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600">
                    {preview.readHint}
                  </div>
                )}

                {preview.previewKind === 'image' && preview.fileUrl ? (
                  <div className="overflow-hidden rounded-2xl border border-slate-200 bg-slate-50">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={preview.fileUrl}
                      alt={preview.title || selectedPath}
                      className="max-h-[26rem] w-full object-contain bg-slate-100"
                    />
                  </div>
                ) : preview.previewKind === 'text' ? (
                  <textarea
                    value={preview.content}
                    readOnly
                    className="h-[22rem] w-full rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 font-mono text-sm leading-6 text-slate-700 outline-none"
                  />
                ) : (
                  <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                    <div className="flex items-center gap-2 text-sm font-medium text-slate-700">
                      <FileCode2 className="h-4 w-4" />
                      <span>{copy.binaryPreviewUnavailable}</span>
                    </div>
                    <pre className="mt-3 whitespace-pre-wrap text-xs leading-6 text-slate-600">{preview.content}</pre>
                  </div>
                )}

                {(preview.hasMore || typeof preview.totalChars === 'number') && preview.previewKind === 'text' && (
                  <div className="flex items-center justify-between gap-3 text-xs text-slate-500">
                    <span>
                      {copy.charProgress((preview.content || '').length, preview.totalChars ?? 0)}
                    </span>
                    {preview.hasMore && (
                      <button
                        type="button"
                        onClick={handleReadMore}
                        disabled={isReadingMore}
                        className="inline-flex items-center gap-1.5 rounded-full bg-sky-50 px-3 py-1.5 font-medium text-sky-700 transition-colors hover:bg-sky-100 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        <RefreshCw className={`h-3 w-3 ${isReadingMore ? 'animate-spin' : ''}`} />
                        <span>{copy.readMore}</span>
                      </button>
                    )}
                  </div>
                )}

                <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-3 py-3 text-xs text-slate-500">
                  <div className="flex flex-wrap items-center gap-3">
                    {selectedEntryMeta?.updatedAt && (
                      <span>{formatDateTime(selectedEntryMeta.updatedAt)}</span>
                    )}
                    {preview.mimeType && (
                      <span>{preview.mimeType}</span>
                    )}
                  </div>
                  {preview.fileUrl && (
                    <a
                      href={preview.fileUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1.5 font-medium text-slate-700 transition-colors hover:bg-slate-200"
                    >
                      <Link2 className="h-3.5 w-3.5" />
                      <span>{copy.openOriginal}</span>
                    </a>
                  )}
                </div>
              </div>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-slate-500">
                {copy.selectFileToInspect}
              </div>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}
