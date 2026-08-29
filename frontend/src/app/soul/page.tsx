"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useI18n } from "@/i18n/provider";
import { apiService } from "@/utils/api";
import { Character } from "@/types";
import { ArrowLeft, FolderTree, Loader2 } from "lucide-react";
import SoulPanel from "@/components/SoulPanel";

function safeError(value: unknown, fallback: string): string {
  if (typeof value === "string") return value;
  if (value instanceof Error) return value.message;
  return fallback;
}

function SoulBrowserContent() {
  const { messages: copy } = useI18n();
  const router = useRouter();
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loadingCharacters, setLoadingCharacters] = useState(true);
  const [selectedCharacterId, setSelectedCharacterId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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
      setError(safeError(loadError, copy.soul.failedToLoadSoulFiles));
    } finally {
      setLoadingCharacters(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [copy.soul.failedToLoadSoulFiles]);

  useEffect(() => {
    void loadCharacters();
  }, [loadCharacters]);

  return (
    <div className="min-h-screen w-full bg-[linear-gradient(180deg,#f5f8fc_0%,#eef3f7_50%,#f6efe8_100%)] text-slate-700">
      <div className="mx-auto flex max-w-7xl flex-col gap-6 px-5 py-8 lg:px-10">
        <div>
          <button
            type="button"
            onClick={() => router.push("/")}
            className="inline-flex items-center gap-2 rounded-full bg-white/80 px-3 py-1.5 text-xs text-slate-600 ring-1 ring-slate-200 transition-colors hover:bg-white hover:text-slate-900"
          >
            <ArrowLeft size={14} />
            <span>{copy.soul.backlinkToWorkspace}</span>
          </button>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">
            {copy.soul.pageTitle}
          </h1>
          <p className="mt-2 max-w-3xl text-sm leading-7 text-slate-600">
            {copy.soul.pageSubtitle}
          </p>
        </div>

        {error && (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {error}
          </div>
        )}

        <div className="grid gap-5 xl:grid-cols-[20rem_minmax(0,1fr)]">
          <aside className="max-h-[24rem] overflow-y-auto rounded-[1.75rem] border border-white/70 bg-white/85 p-4 shadow-[0_20px_60px_rgba(15,23,42,0.06)] backdrop-blur xl:h-full xl:max-h-none">
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
              {!loadingCharacters && characters.length === 0 && (
                <p className="px-3 py-6 text-sm text-slate-500">{copy.soul.selectCharacterToBrowse}</p>
              )}
            </div>
          </aside>

          <div className="h-[calc(100dvh-13rem)] min-h-[32rem]">
            {selectedCharacterId ? (
              <SoulPanel
                characterId={selectedCharacterId}
                characterName={characters.find((character) => character.id === selectedCharacterId)?.name}
                isOpen
                hideToggleButton
                onToggle={() => router.push("/")}
                className="h-full"
              />
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-3 rounded-[1.75rem] border border-white/70 bg-white/85 px-6 py-10 text-sm text-slate-500 shadow-[0_20px_60px_rgba(15,23,42,0.06)] backdrop-blur">
                <FolderTree size={24} className="text-slate-300" />
                <p className="text-center">{copy.soul.selectCharacterToBrowse}</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function SoulPage() {
  return (
    <Suspense fallback={null}>
      <SoulBrowserContent />
    </Suspense>
  );
}
