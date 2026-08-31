"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useI18n } from "@/i18n/provider";
import { apiService } from "@/utils/api";
import { Character, TtsAudioOutput } from "@/types";
import {
  ArrowLeft,
  AudioLines,
  Download,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  Search,
  Trash2,
} from "lucide-react";

function safeError(value: unknown, fallback: string): string {
  if (typeof value === "string") return value;
  if (value instanceof Error) return value.message;
  return fallback;
}

const PROVIDER_LABELS: Record<string, string> = {
  genie: "Genie-TTS",
  gptsovits: "GPT-SoVITS",
  indextts: "IndexTTS",
};

function AudioOutputsContent() {
  const { messages: copy, formatDate, formatTime } = useI18n();
  const t = copy.audioOutputs;
  const router = useRouter();

  const [characters, setCharacters] = useState<Character[]>([]);
  const [outputs, setOutputs] = useState<TtsAudioOutput[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterCharacterId, setFilterCharacterId] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState("");
  const [playingId, setPlayingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const audioRef = useRef<HTMLAudioElement | null>(null);

  const loadCharacters = useCallback(async () => {
    try {
      const response = await apiService.getCharacters();
      if (!response.error && response.data) {
        setCharacters(response.data);
      }
    } catch {
      // 角色列表用于过滤，加载失败不影响主列表。
    }
  }, []);

  const loadOutputs = useCallback(async (characterId?: string) => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiService.listTtsAudioOutputs(characterId || undefined);
      if (response.error) {
        setError(response.error);
        return;
      }
      setOutputs(response.data || []);
    } catch (loadError) {
      setError(safeError(loadError, t.loadFailed));
    } finally {
      setLoading(false);
    }
  }, [t.loadFailed]);

  useEffect(() => {
    void loadCharacters();
    void loadOutputs();
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void loadOutputs(filterCharacterId || undefined);
  }, [filterCharacterId, loadOutputs]);

  const stopPlayback = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    setPlayingId(null);
  }, []);

  const togglePlay = (output: TtsAudioOutput) => {
    if (playingId === output.id) {
      stopPlayback();
      return;
    }
    stopPlayback();
    const audio = new Audio(output.audioUrl);
    audioRef.current = audio;
    setPlayingId(output.id);
    const finish = () => {
      audioRef.current = null;
      setPlayingId(null);
    };
    audio.onended = finish;
    audio.onerror = finish;
    void audio.play().catch(finish);
  };

  const downloadOutput = (output: TtsAudioOutput) => {
    const link = document.createElement("a");
    link.href = output.audioUrl;
    link.download = `tts-${output.id}-${(output.characterName || "voice").replace(/\s+/g, "-")}.wav`;
    document.body.appendChild(link);
    link.click();
    link.remove();
  };

  const deleteOutput = async (output: TtsAudioOutput) => {
    if (!window.confirm(t.deleteConfirm)) return;
    setDeletingId(output.id);
    try {
      const response = await apiService.deleteTtsAudioOutput(output.id);
      if (response.error) {
        setError(response.error);
        return;
      }
      if (playingId === output.id) {
        stopPlayback();
      }
      setOutputs((current) => current.filter((item) => item.id !== output.id));
    } catch (deleteError) {
      setError(safeError(deleteError, t.deleteFailed));
    } finally {
      setDeletingId(null);
    }
  };

  const normalizedQuery = searchQuery.trim().toLowerCase();
  const filteredOutputs = useMemo(() => {
    if (!normalizedQuery) {
      return outputs;
    }
    return outputs.filter((item) => (item.text || "").toLowerCase().includes(normalizedQuery));
  }, [outputs, normalizedQuery]);

  const providerLabel = (provider: string) => PROVIDER_LABELS[provider] || provider || "—";
  const emotionLabel = (emotion: string) => emotion || t.defaultEmotion;
  const formatTimestamp = (value: string) =>
    value && !Number.isNaN(new Date(value).getTime())
      ? `${formatDate(value)} ${formatTime(value)}`
      : t.unknownDate;

  return (
    <div className="min-h-screen w-full bg-[linear-gradient(180deg,#f5f8fc_0%,#eef3f7_50%,#f6efe8_100%)] text-slate-700">
      <div className="mx-auto flex max-w-5xl flex-col gap-6 px-5 py-8 lg:px-10">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <button
              type="button"
              onClick={() => router.push("/")}
              className="inline-flex items-center gap-2 rounded-full bg-white/80 px-3 py-1.5 text-xs text-slate-600 ring-1 ring-slate-200 transition-colors hover:bg-white hover:text-slate-900"
            >
              <ArrowLeft size={14} />
              <span>{t.backlinkToWorkspace}</span>
            </button>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">
              {t.pageTitle}
            </h1>
            <p className="mt-2 max-w-3xl text-sm leading-7 text-slate-600">
              {t.pageSubtitle}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-2 rounded-full bg-violet-50 px-3 py-1.5 text-xs font-medium text-violet-700">
              <AudioLines size={12} />
              <span>{t.count(filteredOutputs.length)}</span>
            </span>
            <button
              type="button"
              onClick={() => void loadOutputs(filterCharacterId || undefined)}
              className="inline-flex items-center gap-2 rounded-full bg-slate-900 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-slate-800"
            >
              {loading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
              <span>{t.refresh}</span>
            </button>
          </div>
        </div>

        {error && (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {error}
          </div>
        )}

        <div className="flex flex-col gap-3 rounded-[1.5rem] border border-white/70 bg-white/85 p-4 shadow-[0_16px_50px_rgba(15,23,42,0.06)] backdrop-blur sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search size={16} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="search"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder={t.searchPlaceholder}
              className="w-full rounded-2xl border border-slate-200 bg-white py-2.5 pl-10 pr-4 text-sm text-slate-700 outline-none transition focus:border-sky-300 focus:ring-4 focus:ring-sky-100"
            />
          </div>
          <select
            value={filterCharacterId}
            onChange={(event) => setFilterCharacterId(event.target.value)}
            className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-700 outline-none transition focus:border-sky-300 focus:ring-4 focus:ring-sky-100 sm:w-52"
          >
            <option value="">{t.allCharacters}</option>
            {characters.map((character) => (
              <option key={character.id} value={character.id}>
                {character.name}
              </option>
            ))}
          </select>
        </div>

        {loading ? (
          <div className="flex items-center justify-center gap-2 rounded-[1.75rem] border border-white/70 bg-white/85 py-16 text-sm text-slate-500 shadow-[0_20px_60px_rgba(15,23,42,0.06)]">
            <Loader2 size={14} className="animate-spin" />
            <span>{t.loading}</span>
          </div>
        ) : filteredOutputs.length === 0 ? (
          <div className="rounded-[1.75rem] border border-dashed border-slate-200 bg-white/70 py-20 text-center text-slate-500 shadow-[0_18px_60px_rgba(15,23,42,0.05)]">
            <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-slate-50">
              <AudioLines size={32} className="text-slate-400" />
            </div>
            <p className="text-lg font-medium text-slate-900">{t.emptyTitle}</p>
            <p className="mx-auto mt-1 max-w-sm text-sm">{t.emptyDescription}</p>
          </div>
        ) : (
          <div className="space-y-3">
            {filteredOutputs.map((output) => (
              <div
                key={output.id}
                className="flex flex-col gap-3 rounded-[1.5rem] border border-white/70 bg-white/85 p-4 shadow-[0_16px_50px_rgba(15,23,42,0.06)] backdrop-blur sm:flex-row sm:items-center"
              >
                <button
                  type="button"
                  onClick={() => togglePlay(output)}
                  title={playingId === output.id ? t.pause : t.play}
                  className={`flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-2xl transition-colors ${
                    playingId === output.id
                      ? "bg-slate-900 text-white hover:bg-slate-800"
                      : "bg-gradient-to-br from-sky-100 via-cyan-50 to-amber-50 text-sky-700 hover:from-sky-100 hover:via-sky-50 hover:to-amber-50"
                  }`}
                >
                  {playingId === output.id ? <Pause size={18} /> : <Play size={18} />}
                </button>

                <div className="min-w-0 flex-1">
                  <p className="line-clamp-2 text-sm leading-6 text-slate-800">
                    {output.text || "—"}
                  </p>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-600">
                      {output.characterName || t.unknownCharacter}
                    </span>
                    <span className="rounded-full bg-violet-50 px-2 py-0.5 font-medium text-violet-700">
                      {t.emotionLabel} · {emotionLabel(output.emotion)}
                    </span>
                    <span className="rounded-full bg-sky-50 px-2 py-0.5 font-medium text-sky-700">
                      {t.providerLabel} · {providerLabel(output.provider)}
                    </span>
                    {output.processingMs != null && (
                      <span className="rounded-full bg-emerald-50 px-2 py-0.5 font-medium text-emerald-700">
                        {t.processingLabel(output.processingMs)}
                      </span>
                    )}
                    <span className="text-slate-400">{formatTimestamp(output.createdAt)}</span>
                  </div>
                </div>

                <div className="flex flex-shrink-0 items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => downloadOutput(output)}
                    title={t.download}
                    className="inline-flex items-center gap-1.5 rounded-xl bg-slate-100 px-3 py-2 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-200"
                  >
                    <Download size={14} />
                    <span className="hidden sm:inline">{t.download}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => deleteOutput(output)}
                    disabled={deletingId === output.id}
                    title={t.delete}
                    className="inline-flex items-center gap-1.5 rounded-xl bg-rose-50 px-3 py-2 text-xs font-medium text-rose-700 transition-colors hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {deletingId === output.id ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <Trash2 size={14} />
                    )}
                    <span className="hidden sm:inline">{t.delete}</span>
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function AudioOutputsPage() {
  return <AudioOutputsContent />;
}
