"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, AudioLines, Home, KeyRound, Settings, UserCircle2 } from "lucide-react";
import ModelApiSettingsPanel from "@/components/ModelApiSettingsPanel";
import TtsSettingsPanel from "@/components/TtsSettingsPanel";
import UserSettingsPanel from "@/components/UserSettingsPanel";
import { useI18n } from "@/i18n/provider";
import { apiService } from "@/utils/api";
import {
  ModelConfig,
  ModelRoleAssignments,
  UserProfile,
  WebSearchConfig,
} from "@/types";
import { APP_NAME, APP_VERSION } from "@/constants";

type SettingsSection = "user" | "api" | "voice";

const SECTIONS: Array<{ key: SettingsSection; label: string; icon: React.ReactNode }> = [
  { key: "user", label: "用户设置", icon: <UserCircle2 size={18} /> },
  { key: "api", label: "API 设置", icon: <KeyRound size={18} /> },
  { key: "voice", label: "语音设置", icon: <AudioLines size={18} /> },
];

function SettingsPageContent() {
  const { messages } = useI18n();
  const router = useRouter();

  const [activeSection, setActiveSection] = useState<SettingsSection>("user");
  const [userProfile, setUserProfile] = useState<UserProfile | null>(null);
  const [loadingUserProfile, setLoadingUserProfile] = useState(true);
  const [userProfileError, setUserProfileError] = useState<string | null>(null);
  const [modelConfigs, setModelConfigs] = useState<ModelConfig[]>([]);
  const [modelRoles, setModelRoles] = useState<ModelRoleAssignments | null>(null);
  const [webSearchConfig, setWebSearchConfig] = useState<WebSearchConfig | null>(null);
  const [loadingModelConfigs, setLoadingModelConfigs] = useState(true);
  const [loadingModelRoles, setLoadingModelRoles] = useState(true);
  const [loadingWebSearchConfig, setLoadingWebSearchConfig] = useState(true);
  const [modelConfigError, setModelConfigError] = useState<string | null>(null);
  const [webSearchConfigError, setWebSearchConfigError] = useState<string | null>(null);

  const fetchUserProfile = useCallback(async () => {
    try {
      setLoadingUserProfile(true);
      const response = await apiService.getUserProfile();

      if (response.error) {
        setUserProfileError(response.error);
        return;
      }

      setUserProfileError(null);
      setUserProfile(response.data || null);
    } catch (err) {
      console.error("Failed to fetch user profile:", err);
      setUserProfileError(messages.user.failedToLoad);
    } finally {
      setLoadingUserProfile(false);
    }
  }, [messages.user.failedToLoad]);

  const fetchModelConfigs = useCallback(async () => {
    try {
      setLoadingModelConfigs(true);
      const response = await apiService.getModelConfigs();

      if (response.error) {
        setModelConfigError(response.error);
        return;
      }

      setModelConfigError(null);
      setModelConfigs(response.data || []);
    } catch (err) {
      console.error("Failed to fetch model configurations:", err);
      setModelConfigError(messages.modelApi.failedToLoadModelConfigurations);
    } finally {
      setLoadingModelConfigs(false);
    }
  }, [messages.modelApi.failedToLoadModelConfigurations]);

  const fetchModelRoles = useCallback(async () => {
    try {
      setLoadingModelRoles(true);
      const response = await apiService.getModelRoles();

      if (response.error) {
        setModelConfigError(response.error);
        return;
      }

      setModelRoles(response.data || null);
    } catch (err) {
      console.error("Failed to fetch model role assignments:", err);
      setModelConfigError(messages.modelApi.failedToLoadRoles);
    } finally {
      setLoadingModelRoles(false);
    }
  }, [messages.modelApi.failedToLoadRoles]);

  const fetchWebSearchConfig = useCallback(async () => {
    try {
      setLoadingWebSearchConfig(true);
      const response = await apiService.getWebSearchConfig();

      if (response.error) {
        setWebSearchConfigError(response.error);
        return;
      }

      setWebSearchConfigError(null);
      setWebSearchConfig(response.data || null);
    } catch (err) {
      console.error("Failed to fetch web search configuration:", err);
      setWebSearchConfigError(messages.modelApi.failedToLoadWebSearchConfiguration);
    } finally {
      setLoadingWebSearchConfig(false);
    }
  }, [messages.modelApi.failedToLoadWebSearchConfiguration]);

  useEffect(() => {
    void fetchUserProfile();
    void fetchModelConfigs();
    void fetchModelRoles();
    void fetchWebSearchConfig();
  }, [fetchUserProfile, fetchModelConfigs, fetchModelRoles, fetchWebSearchConfig]);

  const hasModelConfigs = modelConfigs.length > 0;

  const sectionNavItem = (section: SettingsSection) => {
    const item = SECTIONS.find((s) => s.key === section)!;
    const active = activeSection === section;
    const badge =
      section === "api"
        ? hasModelConfigs
          ? messages.shell.modelApiReady
          : messages.shell.modelApiRequired
        : undefined;
    const badgeTone = section === "api" ? (hasModelConfigs ? "ready" : "warning") : "neutral";
    const badgeClassName =
      badgeTone === "warning"
        ? "bg-amber-100 text-amber-800"
        : badgeTone === "ready"
          ? "bg-emerald-100 text-emerald-700"
          : "bg-slate-100 text-slate-600";

    return (
      <button
        key={section}
        type="button"
        onClick={() => setActiveSection(section)}
        aria-current={active ? "page" : undefined}
        className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-200 ${
          active
            ? "bg-sky-50 text-sky-700 ring-1 ring-sky-100"
            : "text-slate-600 hover:bg-white/80 hover:text-slate-900"
        }`}
      >
        <span className={active ? "text-sky-600" : "text-slate-400"}>{item.icon}</span>
        <span className="min-w-0 flex-1 truncate text-left">{item.label}</span>
        {badge && (
          <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] ${badgeClassName}`}>
            {badge}
          </span>
        )}
      </button>
    );
  };

  return (
    <div className="flex h-screen w-full bg-[linear-gradient(180deg,#f5f8fc_0%,#eef3f7_50%,#f6efe8_100%)] text-slate-700">
      <aside className="hidden w-[280px] flex-shrink-0 flex-col border-r border-white/60 bg-[linear-gradient(180deg,rgba(255,255,255,0.88),rgba(244,247,250,0.92))] backdrop-blur-xl md:flex">
        <div className="flex h-[60px] flex-shrink-0 items-center justify-between gap-2 border-b border-slate-200/70 px-4">
          <button
            type="button"
            onClick={() => router.push("/")}
            className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl bg-white/90 text-slate-500 ring-1 ring-slate-200 transition-colors hover:bg-white hover:text-slate-900"
            title={messages.memory.backlinkToWorkspace}
          >
            <span className="sr-only">{messages.memory.backlinkToWorkspace}</span>
            <ArrowLeft size={17} />
          </button>
          <div className="min-w-0 text-right">
            <div className="flex items-center justify-end gap-2">
              <span className="rounded-full bg-slate-900 px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.16em] text-white">
                {messages.shell.settings}
              </span>
              <span className="text-[11px] font-medium uppercase tracking-[0.16em] text-slate-400">
                {APP_VERSION}
              </span>
            </div>
            <div className="font-semibold text-lg tracking-tight text-slate-900">
              <span className="text-sky-700">{APP_NAME}</span>
            </div>
          </div>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
          <button
            type="button"
            onClick={() => router.push("/")}
            className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-slate-600 transition-all duration-200 hover:bg-white/80 hover:text-slate-900"
          >
            <span className="text-slate-400"><Home size={18} /></span>
            <span className="min-w-0 flex-1 truncate text-left">{messages.shell.home}</span>
          </button>

          <div className="rounded-[1.5rem] border border-white/70 bg-white/60 p-3 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
            <p className="mb-2 px-1 text-[11px] font-medium uppercase tracking-[0.18em] text-slate-400">
              {messages.shell.settings}
            </p>
            <div className="space-y-1">{SECTIONS.map((s) => sectionNavItem(s.key))}</div>
          </div>
        </div>

        <div className="flex flex-shrink-0 items-center justify-between border-t border-slate-200/70 px-4 py-3">
          <span className="text-[11px] font-medium uppercase tracking-[0.16em] text-slate-400">
            {APP_VERSION}
          </span>
          <span className="inline-flex items-center gap-1.5 text-[11px] text-slate-400">
            <Settings size={12} />
            {messages.shell.settings}
          </span>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-shrink-0 flex-col gap-3 border-b border-white/70 bg-white/65 px-4 py-3 backdrop-blur-xl md:hidden">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => router.push("/")}
              className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl bg-white/90 text-slate-500 ring-1 ring-slate-200 transition-colors hover:bg-white hover:text-slate-900"
              title={messages.memory.backlinkToWorkspace}
            >
              <span className="sr-only">{messages.memory.backlinkToWorkspace}</span>
              <ArrowLeft size={17} />
            </button>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h1 className="truncate text-base font-semibold tracking-tight text-slate-900">
                  {messages.shell.settings}
                </h1>
                <span className="rounded-full bg-slate-900 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.14em] text-white">
                  {APP_VERSION}
                </span>
              </div>
              <p className="truncate text-xs text-slate-400">{messages.shell.settingsPageSubtitle}</p>
            </div>
          </div>

          <nav
            className="inline-flex items-center gap-1 rounded-2xl bg-white/80 p-1 ring-1 ring-slate-200"
            aria-label={messages.shell.settings}
          >
            {SECTIONS.map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => setActiveSection(tab.key)}
                aria-current={activeSection === tab.key ? "page" : undefined}
                className={`inline-flex flex-1 items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-all ${
                  activeSection === tab.key
                    ? "bg-slate-900 text-white shadow-sm"
                    : "text-slate-600 hover:bg-white hover:text-slate-900"
                }`}
              >
                <span className={activeSection === tab.key ? "text-white" : "text-slate-400"}>
                  {tab.icon}
                </span>
                <span>{tab.label}</span>
              </button>
            ))}
          </nav>
        </header>

        <main className="min-h-0 flex-1 overflow-hidden">
          {activeSection === "user" ? (
            <UserSettingsPanel
              profile={userProfile}
              loading={loadingUserProfile}
              error={userProfileError}
              onRefresh={fetchUserProfile}
              onOpenModelSettings={() => setActiveSection("api")}
            />
          ) : activeSection === "voice" ? (
            <TtsSettingsPanel />
          ) : (
            <ModelApiSettingsPanel
              modelConfigs={modelConfigs}
              modelRoles={modelRoles}
              webSearchConfig={webSearchConfig}
              loading={loadingModelConfigs}
              loadingRoles={loadingModelRoles}
              loadingWebSearchConfig={loadingWebSearchConfig}
              error={modelConfigError}
              webSearchError={webSearchConfigError}
              onRefresh={fetchModelConfigs}
              onRefreshModelRoles={fetchModelRoles}
              onRefreshWebSearchConfig={fetchWebSearchConfig}
            />
          )}
        </main>
      </div>
    </div>
  );
}

export default function SettingsPage() {
  return <SettingsPageContent />;
}
