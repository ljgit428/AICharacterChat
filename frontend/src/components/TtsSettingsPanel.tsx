"use client";

// 设置页「语音设置」面板：引擎服务地址/默认引擎 + 音色库管理（手动登记、
// 上传 GPT-SoVITS torch 权重交给 Genie 转 ONNX）。角色表单只从这里选音色。
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  Loader2,
  Mic,
  PlusCircle,
  RefreshCw,
  Save,
  Upload,
} from 'lucide-react';
import { apiService } from '@/utils/api';
import { TtsEngine, TtsServiceSettings, TtsVoiceEmotionConfig, TtsVoiceModel } from '@/types';
import { useI18n } from '@/i18n/provider';

const ENGINES: TtsEngine[] = ['genie', 'gptsovits', 'indextts'];

const EMPTY_SETTINGS: TtsServiceSettings = {
  defaultProvider: '',
  genieUrl: '',
  gptsovitsUrl: '',
  indexttsUrl: '',
};

interface VoiceFormState {
  name: string;
  engine: TtsEngine;
  modelVersion: string;
  language: string;
  onnxModelDir: string;
  refAudioPath: string;
  refAudioText: string;
  emotions: TtsVoiceEmotionConfig[];
}

const EMPTY_VOICE_FORM: VoiceFormState = {
  name: '',
  engine: 'genie',
  modelVersion: 'v2proplus',
  language: 'zh',
  onnxModelDir: '',
  refAudioPath: '',
  refAudioText: '',
  emotions: [],
};

const LANGUAGES = ['zh', 'jp', 'en', 'ko'];

const CONVERSION_POLL_MS = 3000;

export default function TtsSettingsPanel() {
  const { messages } = useI18n();
  const copy = messages.voiceSettings;

  const [settings, setSettings] = useState<TtsServiceSettings>(EMPTY_SETTINGS);
  const [loadingSettings, setLoadingSettings] = useState(true);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [settingsNotice, setSettingsNotice] = useState<string | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);

  const [voices, setVoices] = useState<TtsVoiceModel[]>([]);
  const [loadingVoices, setLoadingVoices] = useState(true);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<VoiceFormState>(EMPTY_VOICE_FORM);
  const [isSavingVoice, setIsSavingVoice] = useState(false);

  // 上传并转换（genie 通道）：ckpt/pth 必填，参考音频可选。
  const [convertName, setConvertName] = useState('');
  const [convertLanguage, setConvertLanguage] = useState('zh');
  const [convertVersion, setConvertVersion] = useState('v2proplus');
  const [convertRefText, setConvertRefText] = useState('');
  const [ckptFile, setCkptFile] = useState<File | null>(null);
  const [pthFile, setPthFile] = useState<File | null>(null);
  const [refAudioFile, setRefAudioFile] = useState<File | null>(null);
  const [isConverting, setIsConverting] = useState(false);
  const [convertError, setConvertError] = useState<string | null>(null);

  const [testingEngine, setTestingEngine] = useState<TtsEngine | null>(null);
  const [testResults, setTestResults] = useState<Partial<Record<TtsEngine, { ok: boolean; hint: string }>>>({});
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 路径选择：参考音频（音色级 / 情感组级）与 ONNX 模型文件夹
  const refAudioInputRef = useRef<HTMLInputElement>(null);
  const emotionAudioInputRef = useRef<HTMLInputElement>(null);
  const onnxDirInputRef = useRef<HTMLInputElement>(null);
  const [uploadingRefAudio, setUploadingRefAudio] = useState(false);
  const [uploadingEmotionAudio, setUploadingEmotionAudio] = useState<number | null>(null);
  const [uploadingOnnxDir, setUploadingOnnxDir] = useState(false);
  const [emotionAudioTarget, setEmotionAudioTarget] = useState<number | null>(null);

  const handlePickRefAudio = async (file: File | undefined) => {
    if (!file) {
      return;
    }
    setUploadingRefAudio(true);
    const response = await apiService.uploadTtsRefAudio(file);
    setUploadingRefAudio(false);
    if (response.error || !response.data) {
      setVoiceError(response.error || copy.refAudioUploadFailed);
      return;
    }
    setForm((prev) => ({ ...prev, refAudioPath: response.data!.path }));
  };

  const handlePickEmotionAudio = async (index: number, file: File | undefined) => {
    if (!file) {
      return;
    }
    setEmotionAudioTarget(index);
    setUploadingEmotionAudio(index);
    const response = await apiService.uploadTtsRefAudio(file);
    setUploadingEmotionAudio(null);
    setEmotionAudioTarget(null);
    if (response.error || !response.data) {
      setVoiceError(response.error || copy.refAudioUploadFailed);
      return;
    }
    updateEmotion(index, { refAudioPath: response.data!.path });
  };

  const handlePickOnnxDir = async (files: FileList | null) => {
    if (!files || files.length === 0) {
      return;
    }
    setUploadingOnnxDir(true);
    const fileList = Array.from(files);
    const relativePaths = fileList.map((file) => {
      const webkitPath = (file as File & { webkitRelativePath?: string }).webkitRelativePath;
      return webkitPath || file.name;
    });
    const response = await apiService.uploadTtsOnnxDir(fileList, relativePaths, form.name.trim());
    setUploadingOnnxDir(false);
    if (response.error || !response.data) {
      setVoiceError(response.error || copy.onnxDirUploadFailed);
      return;
    }
    setForm((prev) => ({ ...prev, onnxModelDir: response.data!.path }));
  };

  const fetchVoices = useCallback(async () => {
    try {
      setLoadingVoices(true);
      const response = await apiService.listTtsVoiceModels();
      if (response.error) {
        setVoiceError(response.error);
        return;
      }
      setVoiceError(null);
      setVoices(response.data || []);
    } catch (err) {
      console.error('Failed to fetch voice models:', err);
      setVoiceError(copy.loadFailed);
    } finally {
      setLoadingVoices(false);
    }
  }, [copy.loadFailed]);

  const fetchSettings = useCallback(async () => {
    try {
      setLoadingSettings(true);
      const response = await apiService.getTtsSettings();
      if (response.error) {
        setSettingsError(response.error);
        return;
      }
      setSettingsError(null);
      if (response.data) {
        setSettings(response.data);
      }
    } catch (err) {
      console.error('Failed to fetch TTS settings:', err);
      setSettingsError(copy.loadFailed);
    } finally {
      setLoadingSettings(false);
    }
  }, [copy.loadFailed]);

  useEffect(() => {
    void fetchSettings();
    void fetchVoices();
    return () => {
      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 有转换中的条目就轮询刷新；全部到终态即停。
  useEffect(() => {
    const pending = voices.some((voice) => voice.conversionStatus === 'converting' || voice.conversionStatus === 'pending');
    if (!pending) {
      return;
    }
    pollTimerRef.current = setTimeout(async () => {
      const pendingIds = voices
        .filter((voice) => voice.conversionStatus === 'converting' || voice.conversionStatus === 'pending')
        .map((voice) => voice.id);
      await Promise.all(pendingIds.map((id) => apiService.pollTtsConversionStatus(id)));
      await fetchVoices();
    }, CONVERSION_POLL_MS);
    return () => {
      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
      }
    };
  }, [voices, fetchVoices]);

  const handleSaveSettings = async () => {
    setIsSavingSettings(true);
    setSettingsNotice(null);
    setSettingsError(null);
    const response = await apiService.updateTtsSettings(settings);
    setIsSavingSettings(false);
    if (response.error) {
      setSettingsError(response.error);
      return;
    }
    setSettingsNotice(copy.settingsSaved);
  };

  const handleTestEngine = async (engine: TtsEngine) => {
    setTestingEngine(engine);
    const response = await apiService.testTtsEngine(engine);
    setTestingEngine(null);
    if (response.error || !response.data) {
      setTestResults((prev) => ({ ...prev, [engine]: { ok: false, hint: response.error || copy.testFailed } }));
      return;
    }
    setTestResults((prev) => ({ ...prev, [engine]: response.data! }));
  };

  const startEdit = (voice: TtsVoiceModel) => {
    setEditingId(voice.id);
    setForm({
      name: voice.name,
      engine: voice.engine,
      modelVersion: voice.modelVersion,
      language: voice.language,
      onnxModelDir: voice.onnxModelDir,
      refAudioPath: voice.refAudioPath,
      refAudioText: voice.refAudioText,
      emotions: (voice.emotions || []).map((emotion) => ({ ...emotion })),
    });
  };

  const resetForm = () => {
    setEditingId(null);
    setForm({ ...EMPTY_VOICE_FORM });
  };

  const updateEmotion = (index: number, patch: Partial<TtsVoiceEmotionConfig>) => {
    setForm((prev) => ({
      ...prev,
      emotions: prev.emotions.map((emotion, i) => (i === index ? { ...emotion, ...patch } : emotion)),
    }));
  };

  const addEmotion = () => {
    setForm((prev) => ({
      ...prev,
      emotions: [
        ...prev.emotions,
        { name: '', refAudioPath: '', refAudioText: '', refAudioLanguage: prev.language },
      ],
    }));
  };

  const removeEmotion = (index: number) => {
    setForm((prev) => ({
      ...prev,
      emotions: prev.emotions.filter((_, i) => i !== index),
    }));
  };

  const handleSaveVoice = async () => {
    if (!form.name.trim()) {
      setVoiceError(copy.nameRequired);
      return;
    }
    setIsSavingVoice(true);
    setVoiceError(null);
    const payload = {
      ...form,
      voiceName: '',
      refAudioLanguage: '',
    };
    const response = editingId
      ? await apiService.updateTtsVoiceModel(editingId, payload)
      : await apiService.createTtsVoiceModel(payload);
    setIsSavingVoice(false);
    if (response.error) {
      setVoiceError(response.error);
      return;
    }
    resetForm();
    await fetchVoices();
  };

  const handleDeleteVoice = async (voice: TtsVoiceModel) => {
    if (!window.confirm(copy.confirmDelete(voice.name))) {
      return;
    }
    const response = await apiService.deleteTtsVoiceModel(voice.id);
    if (response.error) {
      setVoiceError(response.error);
      return;
    }
    if (editingId === voice.id) {
      resetForm();
    }
    await fetchVoices();
  };

  const handleUploadConvert = async () => {
    if (!ckptFile || !pthFile) {
      setConvertError(copy.weightsRequired);
      return;
    }
    setIsConverting(true);
    setConvertError(null);
    const response = await apiService.uploadConvertVoiceModel({
      ckpt: ckptFile,
      pth: pthFile,
      refAudio: refAudioFile || undefined,
      name: convertName.trim() || undefined,
      language: convertLanguage,
      modelVersion: convertVersion,
      refAudioText: convertRefText.trim() || undefined,
    });
    setIsConverting(false);
    if (response.error || !response.data) {
      setConvertError(response.error || copy.convertSubmitFailed);
      return;
    }
    setCkptFile(null);
    setPthFile(null);
    setRefAudioFile(null);
    setConvertName('');
    setConvertRefText('');
    await fetchVoices();
  };

  const conversionStatusLabel = (status: TtsVoiceModel['conversionStatus']) => {
    switch (status) {
      case 'ready':
        return copy.statusReady;
      case 'pending':
        return copy.statusPending;
      case 'converting':
        return copy.statusConverting;
      case 'failed':
        return copy.statusFailed;
      default:
        return '';
    }
  };

  const inputClassName =
    'w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition-all focus:border-sky-500 focus:ring-2 focus:ring-sky-500/20';

  return (
    <div className="h-full overflow-y-auto bg-[linear-gradient(180deg,#f5f8fc_0%,#eef3f7_50%,#f6efe8_100%)]">
      <div className="mx-auto max-w-4xl space-y-6 px-4 py-6 sm:px-8">
        <header>
          <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight text-slate-900">
            <Mic size={20} />
            {copy.title}
          </h1>
          <p className="mt-1 text-sm text-slate-500">{copy.subtitle}</p>
        </header>

        {/* 引擎服务 */}
        <section className="rounded-2xl border border-white/70 bg-white/80 p-5 shadow-sm">
          <h2 className="text-base font-semibold text-slate-900">{copy.engineSectionTitle}</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">{copy.engineSectionHint}</p>

          {loadingSettings ? (
            <div className="flex items-center gap-2 py-6 text-sm text-slate-400">
              <Loader2 className="h-4 w-4 animate-spin" /> {copy.loading}
            </div>
          ) : (
            <div className="mt-4 space-y-4">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-slate-500">{copy.defaultProviderLabel}</label>
                <select
                  value={settings.defaultProvider}
                  onChange={(e) =>
                    setSettings((prev) => ({ ...prev, defaultProvider: e.target.value as TtsServiceSettings['defaultProvider'] }))
                  }
                  className={inputClassName}
                >
                  <option value="">{copy.defaultProviderEmpty}</option>
                  {ENGINES.map((engine) => (
                    <option key={engine} value={engine}>
                      {copy[`engine_${engine}` as keyof typeof copy] as string}
                    </option>
                  ))}
                </select>
              </div>

              {(
                [
                  ['genieUrl', 'genie'],
                  ['gptsovitsUrl', 'gptsovits'],
                  ['indexttsUrl', 'indextts'],
                ] as Array<[keyof TtsServiceSettings, TtsEngine]>
              ).map(([field, engine]) => (
                <div key={field} className="space-y-1.5">
                  <label className="text-xs font-medium text-slate-500">
                    {copy[`engine_${engine}` as keyof typeof copy] as string} URL
                  </label>
                  <div className="flex gap-2">
                    <input
                      value={settings[field] as string}
                      onChange={(e) => setSettings((prev) => ({ ...prev, [field]: e.target.value }))}
                      placeholder={`http://127.0.0.1:${engine === 'genie' ? 8050 : engine === 'gptsovits' ? 9880 : 8000}`}
                      className={`${inputClassName} font-mono`}
                    />
                    <button
                      type="button"
                      onClick={() => handleTestEngine(engine)}
                      disabled={testingEngine !== null}
                      className="inline-flex shrink-0 items-center gap-1.5 rounded-xl bg-slate-100 px-3 py-2 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {testingEngine === engine && <Loader2 className="h-3 w-3 animate-spin" />}
                      {copy.testButton}
                    </button>
                  </div>
                  {testResults[engine] && (
                    <p
                      className={`flex items-start gap-1.5 text-xs ${testResults[engine]!.ok ? 'text-emerald-600' : 'text-amber-600'}`}
                    >
                      {testResults[engine]!.ok
                        ? <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0" />
                        : <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />}
                      {testResults[engine]!.ok ? copy.testOk : testResults[engine]!.hint}
                    </p>
                  )}
                </div>
              ))}

              <div className="flex items-center justify-between gap-3 pt-1">
                <p className="text-[11px] leading-4 text-slate-400">{copy.emptyFollowsEnv}</p>
                <button
                  type="button"
                  onClick={handleSaveSettings}
                  disabled={isSavingSettings}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-slate-900 px-4 py-2 text-xs font-medium text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isSavingSettings ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                  {copy.saveSettings}
                </button>
              </div>
              {settingsNotice && <p className="text-xs text-emerald-600">{settingsNotice}</p>}
              {settingsError && <p className="text-xs text-rose-600">{settingsError}</p>}
            </div>
          )}
        </section>

        {/* 上传并转换 */}
        <section className="rounded-2xl border border-white/70 bg-white/80 p-5 shadow-sm">
          <h2 className="text-base font-semibold text-slate-900">{copy.convertSectionTitle}</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">{copy.convertSectionHint}</p>

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-slate-500">T2S (.ckpt)</label>
              <input
                type="file"
                accept=".ckpt"
                onChange={(e) => setCkptFile(e.target.files?.[0] || null)}
                className="w-full text-xs text-slate-600"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-slate-500">VITS (.pth)</label>
              <input
                type="file"
                accept=".pth"
                onChange={(e) => setPthFile(e.target.files?.[0] || null)}
                className="w-full text-xs text-slate-600"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-slate-500">{copy.voiceNameLabel}</label>
              <input value={convertName} onChange={(e) => setConvertName(e.target.value)} placeholder={copy.voiceNamePlaceholder} className={inputClassName} />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-slate-500">{copy.modelVersionLabel}</label>
              <select value={convertVersion} onChange={(e) => setConvertVersion(e.target.value)} className={inputClassName}>
                <option value="">—</option>
                <option value="v2">v2</option>
                <option value="v2pro">v2pro</option>
                <option value="v2proplus">v2proplus</option>
                <option value="v4">v4</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-slate-500">{copy.languageLabel}</label>
              <select value={convertLanguage} onChange={(e) => setConvertLanguage(e.target.value)} className={inputClassName}>
                <option value="zh">zh</option>
                <option value="jp">jp</option>
                <option value="en">en</option>
                <option value="ko">ko</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-slate-500">{copy.refAudioLabel}</label>
              <input type="file" accept="audio/*,.wav,.flac,.ogg,.aif,.aiff" onChange={(e) => setRefAudioFile(e.target.files?.[0] || null)} className="w-full text-xs text-slate-600" />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <label className="text-xs font-medium text-slate-500">{copy.refTextLabel}</label>
              <textarea value={convertRefText} onChange={(e) => setConvertRefText(e.target.value)} rows={2} className={inputClassName} />
            </div>
          </div>

          <div className="mt-4 flex items-center justify-between gap-3">
            <p className="text-[11px] leading-4 text-slate-400">{copy.convertUnsupportedHint}</p>
            <button
              type="button"
              onClick={handleUploadConvert}
              disabled={isConverting}
              className="inline-flex items-center gap-1.5 rounded-xl bg-sky-600 px-4 py-2 text-xs font-medium text-white transition-colors hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isConverting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Upload className="h-3 w-3" />}
              {copy.convertSubmit}
            </button>
          </div>
          {convertError && <p className="mt-2 text-xs text-rose-600">{convertError}</p>}
        </section>

        {/* 音色库 */}
        <section className="rounded-2xl border border-white/70 bg-white/80 p-5 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-base font-semibold text-slate-900">{copy.librarySectionTitle}</h2>
            <button
              type="button"
              onClick={fetchVoices}
              className="inline-flex items-center gap-1.5 rounded-xl bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-200"
            >
              <RefreshCw className="h-3 w-3" /> {copy.refresh}
            </button>
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-500">{copy.librarySectionHint}</p>

          {loadingVoices ? (
            <div className="flex items-center gap-2 py-6 text-sm text-slate-400">
              <Loader2 className="h-4 w-4 animate-spin" /> {copy.loading}
            </div>
          ) : voices.length === 0 ? (
            <p className="py-6 text-sm text-slate-400">{copy.noVoices}</p>
          ) : (
            <ul className="mt-4 space-y-2">
              {voices.map((voice) => (
                <li key={voice.id} className="rounded-xl border border-slate-200 bg-white px-4 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-slate-900">{voice.name}</span>
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] uppercase tracking-wider text-slate-600">
                      {voice.engine}
                    </span>
                    {voice.modelVersion && (
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] uppercase tracking-wider text-slate-600">
                        {voice.modelVersion}
                      </span>
                    )}
                    {voice.language && (
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] uppercase tracking-wider text-slate-600">
                        {voice.language}
                      </span>
                    )}
                    {(voice.conversionStatus === 'converting' || voice.conversionStatus === 'pending') && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700">
                        <Loader2 className="h-2.5 w-2.5 animate-spin" />
                        {conversionStatusLabel(voice.conversionStatus)}
                      </span>
                    )}
                    {voice.conversionStatus === 'ready' && (
                      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
                        {conversionStatusLabel('ready')}
                      </span>
                    )}
                    {voice.conversionStatus === 'failed' && (
                      <span className="rounded-full bg-rose-50 px-2 py-0.5 text-[10px] font-medium text-rose-700">
                        {conversionStatusLabel('failed')}
                      </span>
                    )}
                    <span className="ml-auto flex items-center gap-2">
                      <button type="button" onClick={() => startEdit(voice)} className="text-xs font-medium text-sky-600 hover:text-sky-700">
                        {copy.edit}
                      </button>
                      <button type="button" onClick={() => handleDeleteVoice(voice)} className="text-xs font-medium text-rose-600 hover:text-rose-700">
                        {copy.delete}
                      </button>
                    </span>
                  </div>
                  {voice.emotions && voice.emotions.length > 0 && (
                    <p className="mt-1.5 text-xs text-slate-500">
                      {copy.emotionSectionTitle}：{voice.emotions.map((e) => e.name).filter(Boolean).join(' · ')}
                    </p>
                  )}
                  {voice.conversionError && (
                    <p className="mt-1.5 flex items-start gap-1.5 text-xs text-amber-600">
                      <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" /> {voice.conversionError}
                    </p>
                  )}
                  {!voice.conversionError && voice.onnxModelDir && (
                    <p className="mt-1 truncate font-mono text-[11px] text-slate-400">{voice.onnxModelDir}</p>
                  )}
                  {!voice.onnxModelDir && voice.refAudioPath && (
                    <p className="mt-1 truncate font-mono text-[11px] text-slate-400">{voice.refAudioPath}</p>
                  )}
                </li>
              ))}
            </ul>
          )}

          {/* 手动登记 / 编辑 */}
          <div className="mt-5 rounded-xl border border-dashed border-slate-300 bg-slate-50/60 p-4">
            <div className="mb-3 flex items-center justify-between gap-2">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                {editingId ? copy.editVoiceTitle : copy.addVoiceTitle}
              </p>
              {editingId !== null && (
                <button type="button" onClick={resetForm} className="text-xs text-slate-500 hover:text-slate-700">
                  {copy.cancelEdit}
                </button>
              )}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-slate-500">{copy.voiceNameLabel}</label>
                <input value={form.name} onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))} className={inputClassName} />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-slate-500">{copy.engineLabel}</label>
                <select value={form.engine} onChange={(e) => setForm((prev) => ({ ...prev, engine: e.target.value as TtsEngine }))} className={inputClassName}>
                  {ENGINES.map((engine) => (
                    <option key={engine} value={engine}>
                      {copy[`engine_${engine}` as keyof typeof copy] as string}
                    </option>
                  ))}
                </select>
              </div>
              {form.engine !== 'indextts' && (
                <>
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-slate-500">{copy.modelVersionLabel}</label>
                    <input value={form.modelVersion} onChange={(e) => setForm((prev) => ({ ...prev, modelVersion: e.target.value }))} placeholder="v2 / v2pro / v2proplus / v4" className={inputClassName} />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-slate-500">{copy.languageLabel}</label>
                    <input value={form.language} onChange={(e) => setForm((prev) => ({ ...prev, language: e.target.value }))} placeholder="zh / jp / en / ko" className={inputClassName} />
                  </div>
                </>
              )}
              {form.engine === 'genie' && (
                <div className="space-y-1.5 sm:col-span-2">
                  <label className="text-xs font-medium text-slate-500">{copy.onnxDirLabel}</label>
                  <div className="flex gap-2">
                    <input value={form.onnxModelDir} onChange={(e) => setForm((prev) => ({ ...prev, onnxModelDir: e.target.value }))} placeholder="D:/models/<name>_onnx" className={`${inputClassName} font-mono`} />
                    <input
                      ref={onnxDirInputRef}
                      type="file"
                      multiple
                      className="hidden"
                      {...({ webkitdirectory: '', directory: '' } as Record<string, string>)}
                      onChange={(e) => { void handlePickOnnxDir(e.target.files); e.target.value = ''; }}
                    />
                    <button
                      type="button"
                      onClick={() => onnxDirInputRef.current?.click()}
                      disabled={uploadingOnnxDir}
                      className="inline-flex shrink-0 items-center gap-1.5 rounded-xl bg-slate-100 px-3 py-2 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {uploadingOnnxDir ? <Loader2 className="h-3 w-3 animate-spin" /> : <Upload className="h-3 w-3" />}
                      {uploadingOnnxDir ? copy.uploading : copy.pickOnnxDir}
                    </button>
                  </div>
                </div>
              )}
              {form.engine !== 'indextts' && (
                <>
                  <div className="space-y-1.5 sm:col-span-2">
                    <label className="text-xs font-medium text-slate-500">{copy.refAudioPathLabel}</label>
                    <div className="flex gap-2">
                      <input value={form.refAudioPath} onChange={(e) => setForm((prev) => ({ ...prev, refAudioPath: e.target.value }))} placeholder="F:/voice/sample.wav" className={`${inputClassName} font-mono`} />
                      <input
                        ref={refAudioInputRef}
                        type="file"
                        accept="audio/*,.wav,.flac,.ogg,.aif,.aiff"
                        className="hidden"
                        onChange={(e) => { void handlePickRefAudio(e.target.files?.[0]); e.target.value = ''; }}
                      />
                      <button
                        type="button"
                        onClick={() => refAudioInputRef.current?.click()}
                        disabled={uploadingRefAudio}
                        className="inline-flex shrink-0 items-center gap-1.5 rounded-xl bg-slate-100 px-3 py-2 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {uploadingRefAudio ? <Loader2 className="h-3 w-3 animate-spin" /> : <Upload className="h-3 w-3" />}
                        {uploadingRefAudio ? copy.uploading : copy.pickRefAudio}
                      </button>
                    </div>
                  </div>
                  <div className="space-y-1.5 sm:col-span-2">
                    <label className="text-xs font-medium text-slate-500">{copy.refTextLabel}</label>
                    <textarea value={form.refAudioText} onChange={(e) => setForm((prev) => ({ ...prev, refAudioText: e.target.value }))} rows={2} className={inputClassName} />
                  </div>
                </>
              )}
            </div>

            {/* 情感组：每种情感一份参考音频，合成时按情感名切换；随音色保存。 */}
            {form.engine !== 'indextts' && (
              <div className="mt-4 space-y-2 border-t border-dashed border-slate-300 pt-4">
                <div>
                  <p className="text-xs font-bold text-slate-700">{copy.emotionSectionTitle}</p>
                  <p className="mt-0.5 text-[11px] leading-4 text-slate-400">{copy.emotionSectionHint}</p>
                </div>
                {form.emotions.map((emotion, index) => (
                  <div key={index} className="space-y-2 rounded-xl border border-slate-200 bg-white p-3">
                    <div className="flex items-end gap-2">
                      <div className="flex-1 space-y-1">
                        <label className="text-[11px] font-medium text-slate-500">{copy.emotionNameLabel}</label>
                        <input
                          value={emotion.name}
                          onChange={(e) => updateEmotion(index, { name: e.target.value })}
                          placeholder={copy.emotionNamePlaceholder}
                          className={inputClassName}
                        />
                      </div>
                      <button
                        type="button"
                        onClick={() => removeEmotion(index)}
                        title={copy.emotionRemove}
                        className="mb-0.5 rounded-lg bg-rose-50 px-2.5 py-1.5 text-xs font-medium text-rose-500 transition-colors hover:bg-rose-100"
                      >
                        ✕
                      </button>
                    </div>
                    <div className="space-y-1">
                      <label className="text-[11px] font-medium text-slate-500">{copy.emotionRefAudioLabel}</label>
                      <div className="flex gap-2">
                        <input
                          value={emotion.refAudioPath}
                          onChange={(e) => updateEmotion(index, { refAudioPath: e.target.value })}
                          placeholder={copy.emotionRefAudioPlaceholder}
                          className={`${inputClassName} font-mono`}
                        />
                        <input
                          ref={emotionAudioInputRef}
                          type="file"
                          accept="audio/*,.wav,.flac,.ogg,.aif,.aiff"
                          className="hidden"
                          onChange={(e) => { void handlePickEmotionAudio(index, e.target.files?.[0]); e.target.value = ''; }}
                        />
                        <button
                          type="button"
                          onClick={() => { setEmotionAudioTarget(index); emotionAudioInputRef.current?.click(); }}
                          disabled={uploadingEmotionAudio !== null}
                          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-slate-100 px-2.5 py-1.5 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {uploadingEmotionAudio === index ? <Loader2 className="h-3 w-3 animate-spin" /> : <Upload className="h-3 w-3" />}
                          {uploadingEmotionAudio === index ? copy.uploading : copy.pickRefAudio}
                        </button>
                      </div>
                    </div>
                    <div className="space-y-1">
                      <label className="text-[11px] font-medium text-slate-500">{copy.emotionRefTextLabel}</label>
                      <textarea
                        value={emotion.refAudioText}
                        onChange={(e) => updateEmotion(index, { refAudioText: e.target.value })}
                        placeholder={copy.emotionRefTextPlaceholder}
                        rows={2}
                        className={inputClassName}
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-[11px] font-medium text-slate-500">{copy.emotionRefLanguageLabel}</label>
                      <select
                        value={emotion.refAudioLanguage}
                        onChange={(e) => updateEmotion(index, { refAudioLanguage: e.target.value })}
                        className={inputClassName}
                      >
                        <option value="">—</option>
                        {LANGUAGES.map((lang) => (
                          <option key={lang} value={lang}>{lang}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                ))}
                <button
                  type="button"
                  onClick={addEmotion}
                  className="w-full rounded-lg border border-dashed border-slate-300 bg-white/60 px-3 py-2 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50"
                >
                  ＋ {copy.emotionAdd}
                </button>
              </div>
            )}
            <div className="mt-3 flex items-center justify-between gap-3">
              <p className="text-[11px] leading-4 text-slate-400">{copy.manualEntryHint}</p>
              <button
                type="button"
                onClick={handleSaveVoice}
                disabled={isSavingVoice}
                className="inline-flex items-center gap-1.5 rounded-xl bg-slate-900 px-4 py-2 text-xs font-medium text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isSavingVoice ? <Loader2 className="h-3 w-3 animate-spin" /> : <PlusCircle className="h-3 w-3" />}
                {editingId ? copy.saveVoice : copy.addVoice}
              </button>
            </div>
            {voiceError && <p className="mt-2 text-xs text-rose-600">{voiceError}</p>}
          </div>
        </section>
      </div>
    </div>
  );
}
