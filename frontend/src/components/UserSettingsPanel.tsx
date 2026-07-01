"use client";

import Image from 'next/image';
import { useEffect, useRef, useState } from 'react';
import { UserProfile } from '@/types';
import { apiService } from '@/utils/api';
import { MEDIA_BASE_URL } from '@/constants';
import { SUPPORTED_UI_LOCALES, type SupportedLocale } from '@/i18n/messages';
import { useI18n } from '@/i18n/provider';
import AvatarCropper from '@/components/AvatarCropper';
import {
  AlertCircle,
  Clock3,
  Globe,
  MapPinned,
  Save,
  Shield,
  Sparkles,
  Upload,
  UserRound,
} from 'lucide-react';

interface UserSettingsPanelProps {
  profile: UserProfile | null;
  loading: boolean;
  error?: string | null;
  onRefresh: () => Promise<void>;
  onOpenModelSettings: () => void;
}

type UserProfileFormState = {
  avatarUrl: string;
  preferredName: string;
  pronouns: string;
  bio: string;
  defaultEnableWebSearch: boolean;
  timezone: string;
  interfaceLanguage: SupportedLocale;
  shareLocalTime: boolean;
  shareLocation: boolean;
  locationPrecision: 'region' | 'city' | 'exact';
  locationLabel: string;
  shareWeather: boolean;
  allowLongTermMemory: boolean;
  allowPreferenceInference: boolean;
  allowResearchProfileUpdates: boolean;
  blockedTopics: string;
};

const DEFAULT_FORM_STATE: UserProfileFormState = {
  avatarUrl: '',
  preferredName: '',
  pronouns: '',
  bio: '',
  defaultEnableWebSearch: false,
  timezone: 'UTC',
  interfaceLanguage: SUPPORTED_UI_LOCALES[0].value,
  shareLocalTime: true,
  shareLocation: false,
  locationPrecision: 'city',
  locationLabel: '',
  shareWeather: false,
  allowLongTermMemory: true,
  allowPreferenceInference: true,
  allowResearchProfileUpdates: false,
  blockedTopics: '',
};

function getPreferredLanguageCopy(locale: SupportedLocale) {
  if (locale === 'en-US') {
    return {
      label: 'Preferred Language',
      help: 'Used for the interface and as the default language for auto-generated prompts.',
    };
  }

  return {
    label: '偏好语言',
    help: '用于界面语言，也会作为自动生成提示词时的默认语言。',
  };
}

function getBrowserTimezone() {
  if (typeof window === 'undefined') {
    return '';
  }

  return Intl.DateTimeFormat().resolvedOptions().timeZone || '';
}

function formatTimezonePreview(timezone: string, locale: string) {
  const normalizedTimezone = timezone.trim();
  if (!normalizedTimezone) {
    return '';
  }

  try {
    return new Intl.DateTimeFormat(locale, {
      dateStyle: 'full',
      timeStyle: 'short',
      timeZone: normalizedTimezone,
    }).format(new Date());
  } catch {
    return '';
  }
}

function toFormState(profile: UserProfile | null): UserProfileFormState {
  if (!profile) {
    return DEFAULT_FORM_STATE;
  }

  return {
    avatarUrl: profile.avatarUrl || '',
    preferredName: profile.preferredName || '',
    pronouns: profile.pronouns || '',
    bio: profile.bio || '',
    defaultEnableWebSearch: profile.defaultEnableWebSearch,
    timezone: profile.timezone || 'UTC',
    interfaceLanguage: (profile.interfaceLanguage as SupportedLocale) || SUPPORTED_UI_LOCALES[0].value,
    shareLocalTime: profile.shareLocalTime,
    shareLocation: profile.shareLocation,
    locationPrecision: profile.locationPrecision || 'city',
    locationLabel: profile.locationLabel || '',
    shareWeather: profile.shareWeather,
    allowLongTermMemory: profile.allowLongTermMemory,
    allowPreferenceInference: profile.allowPreferenceInference,
    allowResearchProfileUpdates: profile.allowResearchProfileUpdates,
    blockedTopics: profile.blockedTopics || '',
  };
}

export default function UserSettingsPanel({
  profile,
  loading,
  error: externalError,
  onRefresh,
  onOpenModelSettings,
}: UserSettingsPanelProps) {
  const { messages, setLocale, locale } = useI18n();
  const [formState, setFormState] = useState<UserProfileFormState>(DEFAULT_FORM_STATE);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [browserTimezone, setBrowserTimezone] = useState('');
  const [avatarCropSrc, setAvatarCropSrc] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setFormState(toFormState(profile));
  }, [profile]);

  useEffect(() => {
    setBrowserTimezone(getBrowserTimezone());
  }, []);

  useEffect(() => {
    if ((!formState.shareLocation || !formState.locationLabel.trim()) && formState.shareWeather) {
      setFormState((prev) => ({ ...prev, shareWeather: false }));
    }
  }, [formState.locationLabel, formState.shareLocation, formState.shareWeather]);

  const setField = <K extends keyof UserProfileFormState>(field: K, value: UserProfileFormState[K]) => {
    setFormState((prev) => ({ ...prev, [field]: value }));
  };

  const timezonePreview = formatTimezonePreview(formState.timezone, formState.interfaceLanguage);
  const hasLocationHint = formState.shareLocation && Boolean(formState.locationLabel.trim());
  const preferredLanguageCopy = getPreferredLanguageCopy(locale);

  const handleAvatarUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) {
      return;
    }

    if (!file.type.startsWith('image/')) {
      setError(messages.avatarCropper.mustBeImage);
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

    setIsSaving(true);
    setError(null);

    try {
      const response = await apiService.uploadImage(croppedFile);
      if (response.error || !response.data?.uri) {
        throw new Error(response.error || messages.user.saveUserSettingsFailed);
      }

      setField(
        'avatarUrl',
        response.data.uri.startsWith('http') ? response.data.uri : `${MEDIA_BASE_URL}${response.data.uri}`
      );
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : messages.user.saveUserSettingsFailed);
    } finally {
      setIsSaving(false);
    }
  };

  const handleAvatarCropCancel = () => {
    if (avatarCropSrc) {
      URL.revokeObjectURL(avatarCropSrc);
      setAvatarCropSrc(null);
    }
  };

  const handleSave = async () => {
    setIsSaving(true);
    setError(null);

    try {
      const response = await apiService.updateUserProfile({
        avatar_url: formState.avatarUrl.trim(),
        preferred_name: formState.preferredName.trim(),
        pronouns: formState.pronouns.trim(),
        bio: formState.bio.trim(),
        default_enable_web_search: formState.defaultEnableWebSearch,
        timezone: formState.timezone.trim(),
        interface_language: formState.interfaceLanguage,
        share_local_time: formState.shareLocalTime,
        share_location: formState.shareLocation,
        location_precision: formState.locationPrecision,
        location_label: formState.locationLabel.trim(),
        share_weather: formState.shareWeather,
        allow_long_term_memory: formState.allowLongTermMemory,
        allow_preference_inference: formState.allowPreferenceInference,
        allow_research_profile_updates: formState.allowResearchProfileUpdates,
        blocked_topics: formState.blockedTopics.trim(),
      });

      if (response.error) {
        throw new Error(response.error);
      }

      setLocale(formState.interfaceLanguage);
      await onRefresh();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : messages.user.saveUserSettingsFailed);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto bg-slate-50">
      {avatarCropSrc && (
        <AvatarCropper
          imageSrc={avatarCropSrc}
          copy={messages.avatarCropper}
          shape="round"
          onCancel={handleAvatarCropCancel}
          onApply={handleAvatarCropApply}
        />
      )}
      <div className="mx-auto max-w-6xl px-6 py-8 md:px-10">
        <div className="mb-8">
          <h2 className="text-2xl font-bold text-slate-900">{messages.user.title}</h2>
          <p className="mt-1 text-sm text-slate-500">
            {messages.user.subtitle}
          </p>
        </div>

        {(error || externalError) && (
          <div className="mb-6 flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            <AlertCircle size={16} />
            <span>{error || externalError}</span>
          </div>
        )}

        {loading ? (
          <div className="rounded-2xl border border-slate-200 bg-white px-5 py-10 text-sm text-slate-500 shadow-sm">
            {messages.user.loading}
          </div>
        ) : (
          <div className="grid gap-6 lg:grid-cols-[0.8fr_1.2fr]">
            <div className="space-y-6">
              <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                <div className="mb-5 flex items-center gap-3">
                  <div className="rounded-full bg-blue-50 p-2 text-blue-700">
                    <UserRound size={18} />
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold text-slate-900">{messages.user.identity}</h3>
                    <p className="text-sm text-slate-500">{messages.user.identityDescription}</p>
                  </div>
                </div>

                <div className="mb-5 flex items-center gap-4">
                  <div className="relative h-20 w-20 overflow-hidden rounded-2xl border border-slate-200 bg-slate-100">
                    {formState.avatarUrl ? (
                      <Image
                        src={formState.avatarUrl}
                        alt={formState.preferredName || messages.user.avatarAlt}
                        fill
                        unoptimized
                        sizes="80px"
                        className="object-cover"
                      />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center bg-blue-50 text-2xl font-semibold text-blue-700">
                        {(formState.preferredName || 'U').slice(0, 1).toUpperCase()}
                      </div>
                    )}
                  </div>
                  <div className="space-y-2">
                    <button
                      onClick={() => fileInputRef.current?.click()}
                      className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50"
                      type="button"
                    >
                      <Upload size={16} />
                      <span>{messages.user.uploadAvatar}</span>
                    </button>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={handleAvatarUpload}
                    />
                    <p className="text-xs text-slate-500">{messages.user.avatarHelp}</p>
                  </div>
                </div>

                <div className="space-y-4">
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-slate-700">{messages.user.preferredName}</label>
                    <input
                      type="text"
                      value={formState.preferredName}
                      onChange={(event) => setField('preferredName', event.target.value)}
                      placeholder={messages.user.preferredNamePlaceholder}
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                    />
                  </div>

                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-slate-700">{messages.user.pronouns}</label>
                    <input
                      type="text"
                      value={formState.pronouns}
                      onChange={(event) => setField('pronouns', event.target.value)}
                      placeholder={messages.user.optional}
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                    />
                  </div>

                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-slate-700">{messages.user.shortBio}</label>
                    <textarea
                      value={formState.bio}
                      onChange={(event) => setField('bio', event.target.value)}
                      rows={4}
                      placeholder={messages.user.shortBioPlaceholder}
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                    />
                  </div>
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                <div className="mb-5 flex items-center gap-3">
                  <div className="rounded-full bg-emerald-50 p-2 text-emerald-700">
                    <Clock3 size={18} />
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold text-slate-900">{messages.user.realWorldContext}</h3>
                    <p className="text-sm text-slate-500">{messages.user.realWorldContextDescription}</p>
                  </div>
                </div>

                <div className="space-y-4">
                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <div className="mb-1.5 flex items-center justify-between gap-3">
                        <label className="block text-sm font-medium text-slate-700">{messages.user.timezone}</label>
                        <button
                          type="button"
                          onClick={() => browserTimezone && setField('timezone', browserTimezone)}
                          disabled={!browserTimezone}
                          className="text-xs font-medium text-blue-700 transition-colors hover:text-blue-800 disabled:cursor-not-allowed disabled:text-slate-400"
                        >
                          {messages.user.useBrowserTimezone}
                        </button>
                      </div>
                      <input
                        type="text"
                        value={formState.timezone}
                        onChange={(event) => setField('timezone', event.target.value)}
                        placeholder={messages.user.timezonePlaceholder}
                        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                      />
                      <div className="mt-2 space-y-1 text-xs text-slate-500">
                        <p>{messages.user.timezoneHelp}</p>
                        {browserTimezone ? (
                          <p>{messages.user.timezoneDetected.replace('{timezone}', browserTimezone)}</p>
                        ) : null}
                        {timezonePreview ? (
                          <p>{messages.user.timezonePreview.replace('{value}', timezonePreview)}</p>
                        ) : (
                          <p className="text-amber-700">{messages.user.timezoneInvalid}</p>
                        )}
                      </div>
                    </div>
                    <div>
                      <label className="mb-1.5 block text-sm font-medium text-slate-700">{preferredLanguageCopy.label}</label>
                      <select
                        value={formState.interfaceLanguage}
                        onChange={(event) => setField('interfaceLanguage', event.target.value as SupportedLocale)}
                        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                      >
                        {SUPPORTED_UI_LOCALES.map((language) => (
                          <option key={language.value} value={language.value}>{language.nativeLabel} / {language.englishLabel}</option>
                        ))}
                      </select>
                      <p className="mt-2 text-xs text-slate-500">{preferredLanguageCopy.help}</p>
                    </div>
                  </div>

                  <label className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={formState.shareLocalTime}
                      onChange={(event) => setField('shareLocalTime', event.target.checked)}
                      className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span>{messages.user.shareLocalTime}</span>
                  </label>

                  <label className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={formState.shareLocation}
                      onChange={(event) => setField('shareLocation', event.target.checked)}
                      className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span>{messages.user.shareLocation}</span>
                  </label>

                  {formState.shareLocation && (
                    <div className="grid gap-4 md:grid-cols-[0.6fr_1.4fr]">
                      <div>
                        <label className="mb-1.5 block text-sm font-medium text-slate-700">{messages.user.locationPrecision}</label>
                        <select
                          value={formState.locationPrecision}
                          onChange={(event) => setField('locationPrecision', event.target.value as UserProfileFormState['locationPrecision'])}
                          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                        >
                          <option value="region">{messages.user.region}</option>
                          <option value="city">{messages.user.city}</option>
                          <option value="exact">{messages.user.exact}</option>
                        </select>
                      </div>
                      <div>
                        <label className="mb-1.5 block text-sm font-medium text-slate-700">{messages.user.locationHint}</label>
                        <input
                          type="text"
                          value={formState.locationLabel}
                          onChange={(event) => setField('locationLabel', event.target.value)}
                          placeholder={messages.user.locationHintPlaceholder}
                          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                        />
                        <p className="mt-2 text-xs text-slate-500">{messages.user.locationHintHelp}</p>
                      </div>
                    </div>
                  )}

                  <label className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={formState.shareWeather}
                      onChange={(event) => setField('shareWeather', event.target.checked)}
                      disabled={!hasLocationHint}
                      className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span>{messages.user.shareWeather}</span>
                  </label>
                  <p className={`text-xs ${hasLocationHint ? 'text-slate-500' : 'text-amber-700'}`}>
                    {hasLocationHint
                      ? messages.user.shareWeatherHelpEnabled.replace('{location}', formState.locationLabel.trim())
                      : messages.user.shareWeatherHelpDisabled}
                  </p>
                </div>
              </div>
            </div>

            <div className="space-y-6">
              <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                <div className="mb-5 flex items-center gap-3">
                  <div className="rounded-full bg-amber-50 p-2 text-amber-700">
                    <Shield size={18} />
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold text-slate-900">{messages.user.memoryPrivacy}</h3>
                    <p className="text-sm text-slate-500">{messages.user.memoryPrivacyDescription}</p>
                  </div>
                </div>

                <div className="space-y-4">
                  <label className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={formState.allowLongTermMemory}
                      onChange={(event) => setField('allowLongTermMemory', event.target.checked)}
                      className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span>{messages.user.allowLongTermMemory}</span>
                  </label>

                  <label className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={formState.allowPreferenceInference}
                      onChange={(event) => setField('allowPreferenceInference', event.target.checked)}
                      className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span>{messages.user.allowPreferenceInference}</span>
                  </label>

                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-slate-700">{messages.user.blockedTopics}</label>
                    <textarea
                      value={formState.blockedTopics}
                      onChange={(event) => setField('blockedTopics', event.target.value)}
                      rows={4}
                      placeholder={messages.user.blockedTopicsPlaceholder}
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                    />
                  </div>
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                <div className="mb-5 flex items-center gap-3">
                  <div className="rounded-full bg-sky-50 p-2 text-sky-700">
                    <Globe size={18} />
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold text-slate-900">{messages.user.webSearch}</h3>
                    <p className="text-sm text-slate-500">{messages.user.webSearchDescription}</p>
                  </div>
                </div>

                <div className="space-y-4">
                  <label className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={formState.defaultEnableWebSearch}
                      onChange={(event) => setField('defaultEnableWebSearch', event.target.checked)}
                      className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span>{messages.user.defaultEnableWebSearch}</span>
                  </label>
                  <p className="text-xs text-slate-500">{messages.user.defaultEnableWebSearchHelp}</p>

                  <label className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={formState.allowResearchProfileUpdates}
                      onChange={(event) => setField('allowResearchProfileUpdates', event.target.checked)}
                      className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span>{messages.user.allowResearchProfileUpdates}</span>
                  </label>
                  <p className="text-xs text-slate-500">{messages.user.allowResearchProfileUpdatesHelp}</p>
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                <div className="flex items-start gap-3">
                  <div className="rounded-full bg-slate-100 p-2 text-slate-700">
                    <MapPinned size={18} />
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold text-slate-900">{messages.user.sessionInteractionTitle}</h3>
                    <p className="mt-2 text-sm leading-6 text-slate-600">
                      {messages.user.sessionInteractionDescription}
                    </p>
                  </div>
                </div>
              </div>

              <div className="rounded-2xl border border-sky-200 bg-sky-50/70 p-6 shadow-sm">
                <div className="flex items-start gap-3">
                  <div className="rounded-full bg-white p-2 text-sky-700 shadow-sm">
                    <Sparkles size={18} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <h3 className="text-lg font-semibold text-slate-900">{messages.user.modelApiSettingsTitle}</h3>
                    <p className="mt-2 text-sm leading-6 text-slate-600">
                      {messages.user.modelApiSettingsDescription}
                    </p>
                    <button
                      type="button"
                      onClick={onOpenModelSettings}
                      className="mt-4 rounded-lg border border-sky-200 bg-white px-4 py-2 text-sm font-medium text-sky-700 transition-colors hover:bg-sky-100"
                    >
                      {messages.user.openModelApiSettings}
                    </button>
                  </div>
                </div>
              </div>

              <div className="flex justify-end">
                <button
                  onClick={handleSave}
                  disabled={isSaving}
                  className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-3 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <Save size={16} />
                  <span>{isSaving ? messages.user.saving : messages.user.saveUserSettings}</span>
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
