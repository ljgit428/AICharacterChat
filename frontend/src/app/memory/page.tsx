"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useI18n } from "@/i18n/provider";
import { apiService } from "@/utils/api";
import { Character, MemoryEntry, MemoryNarrative, MemorySectionGroup } from "@/types";
import {
  ArrowLeft,
  Database,
  Eye,
  EyeOff,
  GitMerge,
  Heart,
  Loader2,
  PlusCircle,
  RefreshCw,
  Sparkles,
  Trash2,
  Wand2,
} from "lucide-react";

// Section names the extraction agent is trained to use (memory v2 §4).
const RELATIONSHIP_SECTION = "关系";
const MILESTONE_SECTION = "里程碑";

interface CreatedState {
  section: string;
  description: string;
  reason: string;
}

interface EditingState {
  shortId: string;
  section: string;
  description: string;
  reason: string;
}

interface MergeState {
  id1: string;
  id2: string;
  content: string;
  section: string;
  reason: string;
}

const DESC_LIMIT = 200;

function safeError(value: unknown, fallback: string): string {
  if (typeof value === "string") return value;
  if (value instanceof Error) return value.message;
  return fallback;
}

function MemoryBrowserContent() {
  const { messages: copy } = useI18n();
  const router = useRouter();
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loadingCharacters, setLoadingCharacters] = useState(true);
  const [selectedCharacterId, setSelectedCharacterId] = useState<string | null>(null);
  const [sections, setSections] = useState<MemorySectionGroup[]>([]);
  const [wikiMarkdown, setWikiMarkdown] = useState("");
  const [loadingMemory, setLoadingMemory] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedShortIds, setSelectedShortIds] = useState<string[]>([]);
  const [showWiki, setShowWiki] = useState(true);
  const [creating, setCreating] = useState<CreatedState | null>(null);
  const [editing, setEditing] = useState<EditingState | null>(null);
  const [merging, setMerging] = useState<MergeState | null>(null);
  const [busy, setBusy] = useState<"create" | "edit" | "delete" | "merge" | "wipe" | null>(null);
  const [expansion, setExpansion] = useState<Record<string, boolean>>({});
  // Memory v2 §5.2: growth cards + AI-view preview.
  const [narrative, setNarrative] = useState<MemoryNarrative | null>(null);
  const [showAiView, setShowAiView] = useState(false);

  const loadCharacters = useCallback(async () => {
    setLoadingCharacters(true);
    try {
      const response = await apiService.getCharacters();
      if (response.error) {
        setError(response.error);
        return;
      }
      const data = response.data || [];
      setCharacters(data);
      if (data.length && !selectedCharacterId) {
        setSelectedCharacterId(data[0].id);
      }
    } catch (loadError) {
      setError(safeError(loadError, copy.memory.failedToLoadMemory));
    } finally {
      setLoadingCharacters(false);
    }
  }, [copy.memory.failedToLoadMemory, selectedCharacterId]);

  const loadMemory = useCallback(async (characterId: string) => {
    setLoadingMemory(true);
    setError(null);
    try {
      const response = await apiService.getCharacterMemory(characterId);
      if (response.error || !response.data) {
        setError(response.error || copy.memory.failedToLoadMemory);
        setSections([]);
        setWikiMarkdown("");
        return;
      }
      setSections(response.data.sections || []);
      setWikiMarkdown(response.data.wikiMarkdown || "");
    } catch (loadError) {
      setError(safeError(loadError, copy.memory.failedToLoadMemory));
    } finally {
      setLoadingMemory(false);
    }

    try {
      const narrativeResponse = await apiService.getMemoryNarrative(characterId);
      if (narrativeResponse.data) {
        setNarrative(narrativeResponse.data);
      }
    } catch {
      // Preview is best-effort; the page works without it.
    }
  }, [copy.memory.failedToLoadMemory]);

  useEffect(() => {
    void loadCharacters();
  }, [loadCharacters]);

  useEffect(() => {
    if (selectedCharacterId) {
      void loadMemory(selectedCharacterId);
      setSelectedShortIds([]);
      setCreating(null);
      setEditing(null);
      setMerging(null);
    }
  }, [selectedCharacterId, loadMemory]);

  const selectedCharacter = useMemo(
    () => characters.find((character) => character.id === selectedCharacterId) || null,
    [characters, selectedCharacterId]
  );

  const totalItems = useMemo(
    () => sections.reduce((all, section) => all + section.items.length, 0),
    [sections]
  );

  const selectedSectionName = useMemo(() => {
    if (!selectedShortIds.length) return null;
    const match = sections.flatMap((section) => section.items).find((item) => item.shortId === selectedShortIds[0]);
    return match?.section || null;
  }, [selectedShortIds, sections]);

  const toggleSelect = (item: MemoryEntry) => {
    setSelectedShortIds((current) => {
      if (current.includes(item.shortId)) {
        return current.filter((id) => id !== item.shortId);
      }
      const next = [...current, item.shortId];
      return next.length > 2 ? next.slice(next.length - 2) : next;
    });
  };

  const startCreate = () => {
    if (!selectedCharacter) return;
    setCreating({ section: "", description: "", reason: "" });
    setEditing(null);
    setMerging(null);
  };

  const submitCreate = async () => {
    if (!selectedCharacter || !creating) return;
    const section = creating.section.trim();
    const description = creating.description.trim();
    if (!section || !description || description.length > DESC_LIMIT) return;
    setBusy("create");
    try {
      const response = await apiService.createMemoryEntry(
        selectedCharacter.id,
        section,
        description,
        creating.reason.trim()
      );
      if (response.error) {
        setError(safeError(new Error(response.error), copy.memory.failedToSaveMemory));
        return;
      }
      setCreating(null);
      await loadMemory(selectedCharacter.id);
    } finally {
      setBusy(null);
    }
  };

  const startEdit = (item: MemoryEntry) => {
    setEditing({
      shortId: item.shortId,
      section: item.section,
      description: item.description,
      reason: "",
    });
    setCreating(null);
    setMerging(null);
  };

  const submitEdit = async () => {
    if (!selectedCharacter || !editing) return;
    const description = editing.description.trim();
    if (!description || description.length > DESC_LIMIT) return;
    setBusy("edit");
    try {
      const response = await apiService.updateMemoryEntry(
        selectedCharacter.id,
        editing.shortId,
        description,
        editing.section.trim() || undefined,
        editing.reason.trim()
      );
      if (response.error) {
        setError(safeError(new Error(response.error), copy.memory.failedToSaveMemory));
        return;
      }
      setEditing(null);
      await loadMemory(selectedCharacter.id);
    } finally {
      setBusy(null);
    }
  };

  const deleteEntry = async (entry: MemoryEntry) => {
    if (!selectedCharacter) return;
    if (!window.confirm(copy.memory.confirmDelete(entry.description))) return;
    setBusy("delete");
    try {
      const response = await apiService.deleteMemoryEntry(selectedCharacter.id, entry.shortId);
      if (response.error) {
        setError(safeError(new Error(response.error), copy.memory.failedToDeleteMemory));
        return;
      }
      setSelectedShortIds((current) => current.filter((id) => id !== entry.shortId));
      await loadMemory(selectedCharacter.id);
    } finally {
      setBusy(null);
    }
  };

  const startMerge = () => {
    if (selectedShortIds.length !== 2 || !selectedSectionName) return;
    const [id1, id2] = selectedShortIds;
    const secondEntry = sections
      .flatMap((section) => section.items)
      .find((item) => item.shortId === id2);
    setMerging({
      id1,
      id2,
      content: secondEntry?.description || "",
      section: selectedSectionName,
      reason: "",
    });
    setCreating(null);
    setEditing(null);
  };

  const submitMerge = async () => {
    if (!selectedCharacter || !merging) return;
    setBusy("merge");
    try {
      const response = await apiService.mergeMemoryEntries(
        selectedCharacter.id,
        merging.id1,
        merging.id2,
        merging.content.trim(),
        merging.section.trim(),
        merging.reason.trim()
      );
      if (response.error) {
        setError(safeError(new Error(response.error), copy.memory.failedToMergeMemory));
        return;
      }
      setMerging(null);
      setSelectedShortIds([]);
      await loadMemory(selectedCharacter.id);
    } finally {
      setBusy(null);
    }
  };

  const wipeAll = async () => {
    if (!selectedCharacter || totalItems === 0) return;
    if (!window.confirm(copy.memory.confirmWipeAll(totalItems))) return;
    setBusy("wipe");
    try {
      const response = await apiService.wipeCharacterMemory(selectedCharacter.id);
      if (response.error) {
        setError(safeError(new Error(response.error), copy.memory.failedToWipeMemory));
        return;
      }
      setSelectedShortIds([]);
      await loadMemory(selectedCharacter.id);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="min-h-screen w-full bg-[linear-gradient(180deg,#f5f8fc_0%,#eef3f7_50%,#f6efe8_100%)] text-slate-700">
      <div className="mx-auto flex max-w-7xl flex-col gap-6 px-5 py-8 lg:px-10">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <button
              type="button"
              onClick={() => router.push("/")}
              className="inline-flex items-center gap-2 rounded-full bg-white/80 px-3 py-1.5 text-xs text-slate-600 ring-1 ring-slate-200 transition-colors hover:bg-white hover:text-slate-900"
            >
              <ArrowLeft size={14} />
              <span>{copy.memory.backlinkToWorkspace}</span>
            </button>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">
              {copy.memory.pageTitle}
            </h1>
            <p className="mt-2 max-w-3xl text-sm leading-7 text-slate-600">
              {copy.memory.pageSubtitle}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex items-center gap-2 rounded-full bg-violet-50 px-3 py-1.5 text-xs font-medium text-violet-700">
              <Database size={12} />
              <span>
                {selectedCharacter
                  ? copy.memory.sectionCount(sections.length, totalItems)
                  : `${sections.length}/${totalItems}`}
              </span>
            </div>
            <button
              type="button"
              onClick={() => setShowWiki((prev) => !prev)}
              className="inline-flex items-center gap-2 rounded-full bg-white/80 px-3 py-1.5 text-xs font-medium text-slate-600 ring-1 ring-slate-200 transition-colors hover:bg-white hover:text-slate-900"
            >
              {showWiki ? <EyeOff size={14} /> : <Eye size={14} />}
              <span>{copy.memory.wikiMarkdown}</span>
            </button>
          </div>
        </div>

        {error && (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {error}
          </div>
        )}

        <div className="grid gap-5 xl:grid-cols-[22rem_minmax(0,1fr)]">
          <aside className="rounded-[1.75rem] border border-white/70 bg-white/85 p-4 shadow-[0_20px_60px_rgba(15,23,42,0.06)] backdrop-blur">
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-slate-400">
              {copy.gallery.character}
            </p>
            <div className="mt-3 space-y-2">
              {loadingCharacters ? (
                <div className="flex items-center gap-2 px-3 py-6 text-sm text-slate-500">
                  <Loader2 size={14} className="animate-spin" />
                  <span>{copy.gallery.loadingCharacters}</span>
                </div>
              ) : (
                characters.map((character) => (
                  <button
                    key={character.id}
                    type="button"
                    onClick={() => setSelectedCharacterId(character.id)}
                    className={`flex w-full items-center gap-3 rounded-2xl border px-3 py-2 text-left transition-colors ${
                      selectedCharacterId === character.id
                        ? "border-sky-200 bg-sky-50 text-sky-700"
                        : "border-transparent text-slate-600 hover:bg-slate-50"
                    }`}
                  >
                    <div className="flex h-10 w-10 items-center justify-center overflow-hidden rounded-2xl bg-gradient-to-br from-sky-100 via-cyan-50 to-amber-50 text-sky-700">
                      {character.avatarUrl ? (
                        /* eslint-disable-next-line @next/next/no-img-element */
                        <img src={character.avatarUrl} alt={character.name} className="h-full w-full object-cover" />
                      ) : (
                        <span className="text-sm font-semibold">{character.name.charAt(0).toUpperCase()}</span>
                      )}
                    </div>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{character.name}</p>
                      <p className="truncate text-xs text-slate-500">{character.affiliation || copy.gallery.noCoreBriefYet}</p>
                    </div>
                  </button>
                ))
              )}
            </div>

            <div className="mt-5 border-t border-slate-200 pt-4">
              <p className="text-xs font-medium uppercase tracking-[0.18em] text-slate-400">
                {copy.memory.wikiMarkdown}
              </p>
              <p className="mt-2 text-xs leading-5 text-slate-500">
                {copy.memory.wikiMarkdownHint}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={busy === "wipe" || !selectedCharacter || totalItems === 0}
                  onClick={wipeAll}
                  className="inline-flex items-center gap-2 rounded-full bg-rose-50 px-3 py-2 text-xs font-medium text-rose-700 transition-colors hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {busy === "wipe" ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                  <span>{copy.memory.wipeAll}</span>
                </button>
                <button
                  type="button"
                  disabled={!selectedCharacter}
                  onClick={() => selectedCharacterId && loadMemory(selectedCharacterId)}
                  className="inline-flex items-center gap-2 rounded-full bg-slate-900 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {loadingMemory ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                  <span>{copy.memory.refresh}</span>
                </button>
              </div>
            </div>
          </aside>

          <section className="space-y-5">
            {showWiki && selectedCharacter && (
              <div className="rounded-[1.75rem] border border-white/70 bg-white/85 p-5 shadow-[0_20px_60px_rgba(15,23,42,0.06)] backdrop-blur">
                <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                  <Sparkles size={14} className="text-violet-600" />
                  <span>{copy.memory.wikiMarkdown}</span>
                </div>
                <p className="mt-1 text-xs text-slate-500">{copy.memory.wikiMarkdownHint}</p>
                <textarea
                  readOnly
                  value={wikiMarkdown || "# Long-Term Memory (User Model)\n\nNo durable memories recorded yet.\n"}
                  className="mt-4 h-48 w-full rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 font-mono text-xs leading-6 text-slate-700 outline-none"
                />
                <p className="mt-2 text-xs text-slate-500">
                  {copy.memory.longTermMemoryNarrative}
                </p>
              </div>
            )}

            <div className="rounded-[1.75rem] border border-white/70 bg-white/85 p-5 shadow-[0_20px_60px_rgba(15,23,42,0.06)] backdrop-blur">
              {!selectedCharacter ? (
                <div className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-sm text-slate-500">
                  <Database size={24} className="text-slate-300" />
                  <p>{copy.memory.noEntries}</p>
                </div>
              ) : loadingMemory ? (
                <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500">
                  <Loader2 size={14} className="animate-spin" />
                  <span>{copy.memory.loadingMemory}</span>
                </div>
              ) : totalItems === 0 ? (
                <div className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-sm text-slate-500">
                  <Database size={24} className="text-slate-300" />
                  <p>{copy.memory.noEntries}</p>
                  <button
                    type="button"
                    onClick={startCreate}
                    className="inline-flex items-center gap-2 rounded-full bg-slate-900 px-4 py-2 text-xs font-medium text-white transition-colors hover:bg-slate-800"
                  >
                    <PlusCircle size={14} />
                    <span>{copy.memory.addEntry}</span>
                  </button>
                </div>
              ) : (
                <>
                  <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                    <div className="text-sm text-slate-700">
                      {copy.memory.sectionCount(sections.length, totalItems)}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={startCreate}
                        className="inline-flex items-center gap-2 rounded-full bg-violet-50 px-3 py-2 text-xs font-medium text-violet-700 transition-colors hover:bg-violet-100"
                      >
                        <PlusCircle size={14} />
                        <span>{copy.memory.addEntry}</span>
                      </button>
                      <button
                        type="button"
                        disabled={selectedShortIds.length !== 2 || !selectedSectionName || busy === "merge"}
                        onClick={startMerge}
                        className="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-700 transition-colors hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {busy === "merge" ? <Loader2 size={12} className="animate-spin" /> : <GitMerge size={12} />}
                        <span>{copy.memory.merge}</span>
                      </button>
                      <button
                        type="button"
                        disabled={!narrative}
                        onClick={() => setShowAiView(true)}
                        className="inline-flex items-center gap-2 rounded-full bg-indigo-50 px-3 py-2 text-xs font-medium text-indigo-700 transition-colors hover:bg-indigo-100 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        <Eye size={12} />
                        <span>{copy.memory.aiView}</span>
                      </button>
                    </div>
                  </div>

                  {selectedShortIds.length === 2 && selectedSectionName && (
                    <p className="mb-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
                      {copy.memory.mergeHint}
                    </p>
                  )}

                  <div className="space-y-6">
                    {(() => {
                      const relationshipGroup = sections.find((group) => group.section === RELATIONSHIP_SECTION);
                      const milestoneGroup = sections.find((group) => group.section === MILESTONE_SECTION);
                      if (!relationshipGroup && !milestoneGroup) return null;
                      return (
                        <div className="grid gap-4 lg:grid-cols-2">
                          {relationshipGroup && (
                            <div className="rounded-2xl border border-rose-100 bg-gradient-to-br from-rose-50/80 to-white p-4 shadow-[0_12px_40px_rgba(15,23,42,0.05)]">
                              <div className="flex items-center gap-2 border-b border-rose-100 pb-2">
                                <Heart size={16} className="text-rose-500" />
                                <h3 className="text-sm font-semibold text-slate-900">{copy.memory.relationshipCard}</h3>
                              </div>
                              {relationshipGroup.items.map((entry) => (
                                <div key={entry.shortId} className="pt-3">
                                  <p className="text-sm text-slate-900">{entry.description}</p>
                                  {(entry.descriptionHistory?.length ?? 0) > 0 && (
                                    <ol className="mt-3 space-y-2 border-l-2 border-rose-200 pl-3">
                                      {entry.descriptionHistory!.slice().reverse().map((change, index) => (
                                        <li key={index} className="text-xs text-slate-600">
                                          <span>{change.old_desc}</span>
                                          {" → "}
                                          <span className="font-medium text-rose-600">{change.new_desc}</span>
                                          {change.reason && (
                                            <p className="mt-0.5 text-slate-400">{change.reason}</p>
                                          )}
                                        </li>
                                      ))}
                                    </ol>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                          {milestoneGroup && (
                            <div className="rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50/80 to-white p-4 shadow-[0_12px_40px_rgba(15,23,42,0.05)]">
                              <div className="flex items-center gap-2 border-b border-indigo-100 pb-2">
                                <Sparkles size={16} className="text-indigo-500" />
                                <h3 className="text-sm font-semibold text-slate-900">{copy.memory.milestoneTimeline}</h3>
                              </div>
                              <ol className="mt-3 space-y-2">
                                {milestoneGroup.items.map((entry) => (
                                  <li key={entry.shortId} className="flex gap-2 text-sm text-slate-800">
                                    <span className="mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-indigo-400" />
                                    <span>{entry.description}</span>
                                  </li>
                                ))}
                              </ol>
                            </div>
                          )}
                        </div>
                      );
                    })()}
                    {sections.map((section) => (
                      <div key={section.section} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-[0_12px_40px_rgba(15,23,42,0.05)]">
                        <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                          <h3 className="text-base font-semibold text-slate-900">{section.section}</h3>
                          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
                            {section.items.length}
                          </span>
                        </div>
                        <div className="divide-y divide-slate-100">
                          {section.items.map((entry) => {
                            const isSelected = selectedShortIds.includes(entry.shortId);
                            const isExpanded = expansion[entry.shortId] || false;
                            return (
                              <div
                                key={entry.shortId}
                                className={`flex flex-col gap-3 px-1 py-3 ${
                                  isSelected ? "rounded-2xl bg-violet-50/60" : ""
                                }`}
                              >
                                <div className="flex flex-wrap items-start gap-3">
                                  <input
                                    type="checkbox"
                                    checked={isSelected}
                                    onChange={() => toggleSelect(entry)}
                                    className="mt-1 h-4 w-4 rounded border-slate-300 text-violet-600 focus:ring-violet-300"
                                    aria-label={`select ${entry.shortId}`}
                                  />
                                  <div className="min-w-0 flex-1">
                                    <p className="text-sm font-medium text-slate-900">{entry.description}</p>
                                    <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                                      <span className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[10px] text-slate-600">
                                        {entry.shortId}
                                      </span>
                                      <span>{copy.memory.charCount(entry.description.length)}</span>
                                    </p>
                                  </div>
                                  <div className="flex flex-shrink-0 flex-wrap gap-1.5">
                                    <button
                                      type="button"
                                      onClick={() => startEdit(entry)}
                                      className="inline-flex items-center gap-1 rounded-full bg-slate-900 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-slate-800"
                                    >
                                      <Wand2 size={12} />
                                      <span>{copy.memory.saveEdit}</span>
                                    </button>
                                    <button
                                      type="button"
                                      disabled={busy === "delete"}
                                      onClick={() => deleteEntry(entry)}
                                      className="inline-flex items-center gap-1 rounded-full bg-rose-50 px-3 py-1.5 text-xs font-medium text-rose-700 transition-colors hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60"
                                    >
                                      {busy === "delete" ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                                      <span>{copy.memory.delete}</span>
                                    </button>
                                  </div>
                                </div>

                                {Array.isArray(entry.descriptionHistory) && entry.descriptionHistory.length > 0 && (
                                  <div className="ml-7 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                                    <button
                                      type="button"
                                      onClick={() =>
                                        setExpansion((prev) => ({ ...prev, [entry.shortId]: !isExpanded }))
                                      }
                                      className="font-medium text-slate-700"
                                    >
                                      {isExpanded ? copy.memory.expandedHistory : copy.memory.collapsedHistory} ·{" "}
                                      {copy.memory.historyCount(entry.descriptionHistory.length)}
                                    </button>
                                    {isExpanded && (
                                      <ul className="mt-2 space-y-2">
                                        {entry.descriptionHistory.map((revision, index) => (
                                          <li key={`${entry.shortId}-${index}`} className="rounded-xl bg-white px-3 py-2">
                                            <p className="text-xs text-slate-500">{copy.memory.reasonLabel}: {revision.reason || "—"}</p>
                                            <p className="mt-1 text-sm text-slate-700">{revision.new_desc}</p>
                                            {revision.old_desc && (
                                              <p className="mt-1 text-xs italic text-slate-400">was: {revision.old_desc}</p>
                                            )}
                                          </li>
                                        ))}
                                      </ul>
                                    )}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </section>
        </div>

        {creating && (
          <Modal title={copy.memory.addEntry} onClose={() => !busy && setCreating(null)} busy={busy === "create"}>
            <ModalSection label={copy.memory.save}>
              <input
                type="text"
                value={creating.section}
                onChange={(event) => setCreating({ ...creating, section: event.target.value })}
                placeholder={copy.memory.sectionPlaceholder}
                className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-300 focus:ring-2 focus:ring-violet-100"
              />
            </ModalSection>
            <ModalSection label={copy.memory.descriptionPlaceholder}>
              <textarea
                value={creating.description}
                onChange={(event) => setCreating({ ...creating, description: event.target.value })}
                placeholder={copy.memory.descriptionPlaceholder}
                rows={3}
                className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-300 focus:ring-2 focus:ring-violet-100"
              />
              <p className="mt-1 text-xs text-slate-500">{copy.memory.charCount(creating.description.length)}</p>
            </ModalSection>
            <ModalSection label={copy.memory.reasonLabel}>
              <input
                type="text"
                value={creating.reason}
                onChange={(event) => setCreating({ ...creating, reason: event.target.value })}
                placeholder={copy.memory.reasonPlaceholder}
                className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-300 focus:ring-2 focus:ring-violet-100"
              />
            </ModalSection>
            <ModalFooter
              saveLabel={copy.memory.save}
              cancelLabel={copy.memory.cancelEdit}
              busy={busy === "create"}
              onSave={submitCreate}
              onCancel={() => setCreating(null)}
            />
          </Modal>
        )}

        {editing && (
          <Modal title={copy.memory.editingEntry} onClose={() => !busy && setEditing(null)} busy={busy === "edit"}>
            <ModalSection label="short_id">
              <p className="rounded-2xl bg-slate-100 px-3 py-2 font-mono text-xs text-slate-700">{editing.shortId}</p>
            </ModalSection>
            <ModalSection label={copy.memory.save}>
              <input
                type="text"
                value={editing.section}
                onChange={(event) => setEditing({ ...editing, section: event.target.value })}
                placeholder={copy.memory.sectionPlaceholder}
                className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-300 focus:ring-2 focus:ring-violet-100"
              />
            </ModalSection>
            <ModalSection label={copy.memory.editingDescriptionPlaceholder}>
              <textarea
                value={editing.description}
                onChange={(event) => setEditing({ ...editing, description: event.target.value })}
                rows={3}
                placeholder={copy.memory.editingDescriptionPlaceholder}
                className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-300 focus:ring-2 focus:ring-violet-100"
              />
              <p className="mt-1 text-xs text-slate-500">{copy.memory.charCount(editing.description.length)}</p>
            </ModalSection>
            <ModalSection label={copy.memory.reasonLabel}>
              <input
                type="text"
                value={editing.reason}
                onChange={(event) => setEditing({ ...editing, reason: event.target.value })}
                placeholder={copy.memory.reasonPlaceholder}
                className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-300 focus:ring-2 focus:ring-violet-100"
              />
            </ModalSection>
            <ModalFooter
              saveLabel={copy.memory.saveEdit}
              cancelLabel={copy.memory.cancelEdit}
              busy={busy === "edit"}
              onSave={submitEdit}
              onCancel={() => setEditing(null)}
            />
          </Modal>
        )}

        {merging && (
          <Modal title={copy.memory.merge} onClose={() => !busy && setMerging(null)} busy={busy === "merge"}>
            <ModalSection label="merge_short_ids">
              <p className="rounded-2xl bg-slate-100 px-3 py-2 font-mono text-xs text-slate-700">
                {merging.id1} + {merging.id2}
              </p>
            </ModalSection>
            <ModalSection label={copy.memory.merge}>
              <input
                type="text"
                value={merging.section}
                onChange={(event) => setMerging({ ...merging, section: event.target.value })}
                placeholder={copy.memory.sectionPlaceholder}
                className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-300 focus:ring-2 focus:ring-violet-100"
              />
            </ModalSection>
            <ModalSection label={copy.memory.mergePlaceholder}>
              <textarea
                value={merging.content}
                onChange={(event) => setMerging({ ...merging, content: event.target.value })}
                rows={3}
                placeholder={copy.memory.mergePlaceholder}
                className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-300 focus:ring-2 focus:ring-violet-100"
              />
              <p className="mt-1 text-xs text-slate-500">{copy.memory.charCount(merging.content.length)}</p>
            </ModalSection>
            <ModalSection label={copy.memory.reasonLabel}>
              <input
                type="text"
                value={merging.reason}
                onChange={(event) => setMerging({ ...merging, reason: event.target.value })}
                placeholder={copy.memory.reasonPlaceholder}
                className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-300 focus:ring-2 focus:ring-violet-100"
              />
            </ModalSection>
            <ModalFooter
              saveLabel={copy.memory.merge}
              cancelLabel={copy.memory.cancelEdit}
              busy={busy === "merge"}
              onSave={submitMerge}
              onCancel={() => setMerging(null)}
            />
          </Modal>
        )}

        {showAiView && narrative && (
          <Modal title={copy.memory.aiViewTitle} busy={false} onClose={() => setShowAiView(false)}>
            {narrative.truncated && (
              <p className="mb-3 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
                {copy.memory.truncatedWarning}
              </p>
            )}
            <pre className="max-h-[50vh] overflow-auto whitespace-pre-wrap rounded-2xl bg-slate-900 p-4 text-xs leading-6 text-slate-100">
              {narrative.narrative}
            </pre>
            <p className="mt-2 text-xs text-slate-500">{copy.memory.aiViewCount(narrative.count)}</p>
          </Modal>
        )}
      </div>
    </div>
  );
}

function Modal({
  title,
  busy,
  onClose,
  children,
}: {
  title: string;
  busy: boolean;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/55 p-4 backdrop-blur-sm sm:items-center">
      <div className="w-full max-w-lg overflow-hidden rounded-[1.75rem] border border-white/70 bg-white shadow-[0_32px_120px_rgba(15,23,42,0.35)]">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
          <button
            type="button"
            disabled={busy}
            onClick={onClose}
            className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600 transition-colors hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-60"
          >
            close
          </button>
        </div>
        <div className="space-y-4 px-5 py-5">{children}</div>
      </div>
    </div>
  );
}

function ModalSection({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium uppercase tracking-[0.14em] text-slate-400">{label}</span>
      {children}
    </label>
  );
}

function ModalFooter({
  saveLabel,
  cancelLabel,
  busy,
  onSave,
  onCancel,
}: {
  saveLabel: string;
  cancelLabel: string;
  busy: boolean;
  onSave: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="flex items-center justify-end gap-2 border-t border-slate-200 pt-4">
      <button
        type="button"
        disabled={busy}
        onClick={onCancel}
        className="rounded-full border border-slate-200 bg-white px-4 py-2 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {cancelLabel}
      </button>
      <button
        type="button"
        disabled={busy}
        onClick={onSave}
        className="inline-flex items-center gap-2 rounded-full bg-slate-900 px-4 py-2 text-xs font-medium text-white transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {busy ? <Loader2 size={12} className="animate-spin" /> : null}
        <span>{busy ? "\u2026" : saveLabel}</span>
      </button>
    </div>
  );
}

export default function MemoryPage() {
  return (
    <Suspense fallback={null}>
      <MemoryBrowserContent />
    </Suspense>
  );
}
