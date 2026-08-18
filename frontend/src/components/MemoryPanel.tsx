"use client";

import { useCallback, useEffect, useState } from "react";
import { useI18n } from "@/i18n/provider";
import { apiService } from "@/utils/api";
import { MemorySnapshot } from "@/types";
import { Database, Loader2, RefreshCw, Sparkles, X } from "lucide-react";

interface MemoryPanelProps {
  characterId: string;
  chatSessionId?: string | null;
  refreshKey?: string;
  onPrivateModeChanged?: (isPrivateMode: boolean) => void;
  onClose?: () => void;
}

function safeError(value: unknown, fallback: string): string {
  if (typeof value === "string") return value;
  if (value instanceof Error) return value.message;
  return fallback;
}

export default function MemoryPanel({
  characterId,
  chatSessionId,
  refreshKey,
  onPrivateModeChanged,
  onClose,
}: MemoryPanelProps) {
  const { messages: copy } = useI18n();
  const [snapshot, setSnapshot] = useState<MemorySnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);
  const [privateMode, setPrivateMode] = useState(false);
  const [busyPrivate, setBusyPrivate] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiService.getCharacterMemory(characterId);
      if (response.error || !response.data) {
        setError(response.error || copy.memory.failedToLoadMemory);
        setSnapshot(null);
        return;
      }
      setSnapshot(response.data);
    } catch (loadError) {
      setError(safeError(loadError, copy.memory.failedToLoadMemory));
    } finally {
      setLoading(false);
    }
  }, [characterId, copy.memory.failedToLoadMemory]);

  const loadSession = useCallback(async () => {
    if (!chatSessionId) {
      setPrivateMode(false);
      return;
    }
    try {
      const response = await apiService.getChatSession(String(chatSessionId));
      if (!response.error && response.data) {
        setPrivateMode(Boolean(response.data.isPrivateMode));
      }
    } catch {
      // Non-fatal: the panel will still toggle optimistically on user click.
    }
  }, [chatSessionId]);

  useEffect(() => {
    void load();
  }, [load, refreshKey, reloadNonce]);

  useEffect(() => {
    void loadSession();
  }, [loadSession, refreshKey, reloadNonce]);

  const totalEntries = snapshot?.count || 0;
  const sectionCount = snapshot?.sections.length || 0;

  const handlePrivateToggle = async () => {
    if (!chatSessionId) {
      setError(copy.memory.privateModeNoSessionHint);
      return;
    }
    const nextValue = !privateMode;
    setPrivateMode(nextValue);
    setBusyPrivate(true);
    setError(null);
    try {
      const response = await apiService.setSessionPrivateMode(String(chatSessionId), nextValue);
      if (response.error) {
        setError(safeError(new Error(response.error), copy.memory.failedToLoadMemory));
        setPrivateMode(!nextValue);
        return;
      }
      onPrivateModeChanged?.(nextValue);
    } catch (toggleError) {
      setError(safeError(toggleError, copy.memory.failedToLoadMemory));
      setPrivateMode(!nextValue);
    } finally {
      setBusyPrivate(false);
    }
  };

  const previewLines = (snapshot?.wikiMarkdown || "").split("\n").slice(0, 8);

  return (
    <aside className="flex h-full min-h-0 w-full flex-col overflow-hidden rounded-[1.75rem] border border-white/70 bg-white/85 shadow-[0_20px_60px_rgba(15,23,42,0.06)] backdrop-blur">
      <div className="border-b border-slate-200/70 bg-[linear-gradient(180deg,rgba(248,250,252,0.95),rgba(255,255,255,0.92))] px-4 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Database size={14} className="text-violet-600" />
              <h3 className="text-sm font-semibold text-slate-900">{copy.memory.pageTitle}</h3>
            </div>
            <p className="mt-1 text-xs leading-5 text-slate-500">{copy.memory.pageSubtitle}</p>
          </div>
          <div className="flex flex-shrink-0 gap-1">
            <button
              type="button"
              onClick={() => setReloadNonce((prev) => prev + 1)}
              disabled={loading}
              className="inline-flex h-9 w-9 items-center justify-center rounded-2xl bg-slate-100 text-slate-600 transition-colors hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-60"
              title={copy.memory.refresh}
            >
              {loading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
            </button>
            {onClose && (
              <button
                type="button"
                onClick={onClose}
                className="inline-flex h-9 w-9 items-center justify-center rounded-2xl bg-slate-100 text-slate-600 transition-colors hover:bg-slate-200"
                title={copy.memory.closePanel}
              >
                <X size={16} />
              </button>
            )}
          </div>
        </div>

        <div className="mt-4 flex items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2">
          <div>
            <p className="text-xs font-medium text-slate-700">{copy.memory.privateModeToggle}</p>
            <p className="mt-0.5 text-[11px] text-slate-500">
              {privateMode ? copy.memory.privateModeOn : copy.memory.privateModeOff}
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={privateMode}
            disabled={busyPrivate}
            onClick={handlePrivateToggle}
            className={`relative h-6 w-11 flex-shrink-0 rounded-full transition-colors ${
              privateMode ? "bg-amber-500" : "bg-slate-300"
            }`}
          >
            <span
              className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
                privateMode ? "translate-x-5" : "translate-x-0.5"
              }`}
            />
          </button>
        </div>
      </div>

      {error && (
        <div className="border-b border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-700">{error}</div>
      )}

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-4">
        <div className="mb-3 flex items-center gap-2 text-xs text-slate-500">
          <Sparkles size={12} className="text-violet-500" />
          <span>
            {loading
              ? copy.memory.loadingMemory
              : copy.memory.sectionCount(sectionCount, totalEntries)}
          </span>
        </div>

        {loading ? (
          <div className="flex flex-1 items-center justify-center text-sm text-slate-500">
            <Loader2 size={16} className="mr-2 animate-spin" />
            {copy.memory.loadingMemory}
          </div>
        ) : totalEntries === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">
            <Database size={20} className="text-slate-300" />
            <p>{copy.memory.noEntries}</p>
          </div>
        ) : (
          <div className="space-y-3">
            {snapshot?.sections.slice(0, 4).map((section) => (
              <div key={section.section} className="rounded-2xl border border-slate-200 bg-white px-3 py-2">
                <div className="flex items-center justify-between">
                  <h4 className="text-sm font-semibold text-slate-900">{section.section}</h4>
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600">
                    {section.items.length}
                  </span>
                </div>
                <ul className="mt-2 space-y-1 text-xs text-slate-600">
                  {section.items.slice(0, 3).map((entry) => (
                    <li key={entry.shortId} className="line-clamp-2 leading-5">
                      - {entry.description}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500">
              <p className="font-medium text-slate-600">{copy.memory.wikiMarkdown}</p>
              <pre className="mt-2 whitespace-pre-wrap font-mono text-[10px] leading-4 text-slate-500">
                {previewLines.join("\n")}
              </pre>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
