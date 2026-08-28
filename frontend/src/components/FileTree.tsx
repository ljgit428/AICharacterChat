"use client";

// 展示型文件树：供聊天右侧面板（服务端 VFS）与角色表单（本地待保存文件组）
// 复用。children 为 undefined 表示“还没加载”（由调用方懒加载），[] 表示空目录。
import { ChevronDown, ChevronRight, FileImage, FileText, Folder, FolderOpen, Loader2, X } from 'lucide-react';

export interface FileTreeNode {
  path: string;
  title: string;
  isDirectory: boolean;
  childCount?: number;
  sizeHint?: number;
  updatedAt?: string;
  manageable?: boolean;
  previewKind?: string;
  children?: FileTreeNode[] | null;
}

export function formatFileSize(sizeHint?: number) {
  if (sizeHint == null) {
    return '';
  }
  if (sizeHint >= 10000) {
    return `${Math.round(sizeHint / 1000)}k`;
  }
  if (sizeHint >= 1000) {
    return `${(sizeHint / 1000).toFixed(1)}k`;
  }
  return String(sizeHint);
}

interface FileTreeProps {
  nodes: FileTreeNode[];
  expandedPaths: Set<string>;
  loadingPaths?: Set<string>;
  selectedPath?: string | null;
  removable?: boolean;
  onToggleDir: (node: FileTreeNode) => void;
  onSelectFile: (node: FileTreeNode) => void;
  onRemoveNode?: (node: FileTreeNode) => void;
  removeTitle?: string;
  emptyDirLabel?: string;
}

export default function FileTree({
  nodes,
  expandedPaths,
  loadingPaths,
  selectedPath,
  removable = false,
  onToggleDir,
  onSelectFile,
  onRemoveNode,
  removeTitle,
  emptyDirLabel = '(empty)',
}: FileTreeProps) {
  return (
    <ul className="space-y-0.5">
      {nodes.map((node) => (
        <FileTreeRow
          key={node.path}
          node={node}
          depth={0}
          expandedPaths={expandedPaths}
          loadingPaths={loadingPaths}
          selectedPath={selectedPath}
          removable={removable}
          onToggleDir={onToggleDir}
          onSelectFile={onSelectFile}
          onRemoveNode={onRemoveNode}
          removeTitle={removeTitle}
          emptyDirLabel={emptyDirLabel}
        />
      ))}
    </ul>
  );
}

interface FileTreeRowProps extends Omit<FileTreeProps, 'nodes'> {
  node: FileTreeNode;
  depth: number;
}

function FileTreeRow({
  node,
  depth,
  expandedPaths,
  loadingPaths,
  selectedPath,
  removable,
  onToggleDir,
  onSelectFile,
  onRemoveNode,
  removeTitle,
  emptyDirLabel,
}: FileTreeRowProps) {
  const isExpanded = expandedPaths.has(node.path);
  const isLoading = Boolean(loadingPaths?.has(node.path));
  const indent = 8 + depth * 14;

  const metaBits: string[] = [];
  if (node.isDirectory && typeof node.childCount === 'number') {
    metaBits.push(String(node.childCount));
  }
  if (!node.isDirectory) {
    const sizeLabel = formatFileSize(node.sizeHint);
    if (sizeLabel) {
      metaBits.push(`${sizeLabel}c`);
    }
  }

  const iconClass = 'h-3.5 w-3.5 shrink-0';
  const fileIcon = node.previewKind === 'image'
    ? <FileImage className={`${iconClass} text-sky-500`} />
    : <FileText className={`${iconClass} text-slate-400`} />;

  const rowClass = `group flex w-full items-center gap-1.5 rounded-lg py-1.5 pr-1.5 text-left text-[13px] transition-colors ${
    !node.isDirectory && node.path === selectedPath
      ? 'bg-sky-50 text-sky-700'
      : node.isDirectory
        ? 'text-slate-700 hover:bg-slate-50'
        : 'text-slate-600 hover:bg-slate-50'
  }`;

  const handleRemove = (event: React.MouseEvent) => {
    event.stopPropagation();
    onRemoveNode?.(node);
  };

  return (
    <li>
      <div className={rowClass} style={{ paddingLeft: `${indent}px` }}>
        {node.isDirectory ? (
          <>
            <button
              type="button"
              onClick={() => onToggleDir(node)}
              className="flex min-w-0 flex-1 items-center gap-1.5"
              title={node.path}
            >
              {isLoading ? (
                <Loader2 className={`${iconClass} shrink-0 animate-spin text-slate-400`} />
              ) : isExpanded ? (
                <ChevronDown className={`${iconClass} shrink-0 text-slate-400`} />
              ) : (
                <ChevronRight className={`${iconClass} shrink-0 text-slate-400`} />
              )}
              {isExpanded
                ? <FolderOpen className={`${iconClass} text-amber-500`} />
                : <Folder className={`${iconClass} text-amber-500`} />}
              <span className="truncate font-medium">{node.title}</span>
            </button>
            {metaBits.length > 0 && (
              <span className="shrink-0 rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">
                {metaBits.join(' · ')}
              </span>
            )}
          </>
        ) : (
          <>
            <button
              type="button"
              onClick={() => onSelectFile(node)}
              className="flex min-w-0 flex-1 items-center gap-1.5"
              title={node.path}
            >
              {fileIcon}
              <span className="truncate">{node.title}</span>
              {metaBits.length > 0 && (
                <span className="shrink-0 text-[10px] text-slate-400">{metaBits.join(' · ')}</span>
              )}
            </button>
            {removable && onRemoveNode && (
              <button
                type="button"
                onClick={handleRemove}
                className="hidden h-4 w-4 shrink-0 items-center justify-center rounded-full text-slate-300 transition-colors hover:bg-rose-50 hover:text-rose-600 group-hover:flex"
                aria-label={removeTitle || 'remove'}
                title={removeTitle || 'remove'}
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </>
        )}
      </div>

      {node.isDirectory && isExpanded && (
        <ul className="ml-[13px] border-l border-slate-200/70 pl-0">
          {node.children?.length ? (
            node.children.map((child) => (
              <FileTreeRow
                key={child.path}
                node={child}
                depth={depth + 1}
                expandedPaths={expandedPaths}
                loadingPaths={loadingPaths}
                selectedPath={selectedPath}
                removable={removable}
                onToggleDir={onToggleDir}
                onSelectFile={onSelectFile}
                onRemoveNode={onRemoveNode}
                removeTitle={removeTitle}
                emptyDirLabel={emptyDirLabel}
              />
            ))
          ) : node.children ? (
            <li
              className="py-1 text-xs text-slate-400"
              style={{ paddingLeft: `${14}px` }}
            >
              {emptyDirLabel}
            </li>
          ) : null}
        </ul>
      )}
    </li>
  );
}
