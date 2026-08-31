"use client";

import Image from 'next/image';
import { useEffect, useRef, useState } from 'react';
import { UserProfile } from '@/types';
import { apiService } from '@/utils/api';
import type { DetectedLocation } from '@/utils/api';
import { MEDIA_BASE_URL } from '@/constants';
import { SUPPORTED_UI_LOCALES, type SupportedLocale } from '@/i18n/messages';
import { useI18n } from '@/i18n/provider';
import AvatarCropper from '@/components/AvatarCropper';
import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  Globe,
  Save,
  Shield,
  Upload,
  UserRound,
} from 'lucide-react';

interface UserSettingsPanelProps {
  profile: UserProfile | null;
  loading: boolean;
  error?: string | null;
  onRefresh: () => Promise<void>;
}

type UserProfileFormState = {
  avatarUrl: string;
  preferredName: string;
  bio: string;
  defaultEnableWebSearch: boolean;
  timezone: string;
  interfaceLanguage: SupportedLocale;
  shareLocalTime: boolean;
  shareLocation: boolean;
  locationPrecision: 'region' | 'city' | 'exact';
  locationLabel: string;
  shareWeather: boolean;
  autoSyncTimezone: boolean;
  autoSyncLocation: boolean;
  allowLongTermMemory: boolean;
  allowPreferenceInference: boolean;
  blockedTopics: string;
};

const DEFAULT_FORM_STATE: UserProfileFormState = {
  avatarUrl: '',
  preferredName: '',
  bio: '',
  defaultEnableWebSearch: false,
  timezone: 'UTC',
  interfaceLanguage: SUPPORTED_UI_LOCALES[0].value,
  shareLocalTime: true,
  shareLocation: true,
  locationPrecision: 'city',
  locationLabel: '',
  shareWeather: true,
  autoSyncTimezone: true,
  autoSyncLocation: true,
  allowLongTermMemory: true,
  allowPreferenceInference: true,
  blockedTopics: '',
};

function getBrowserTimezone() {
  if (typeof window === 'undefined') {
    return '';
  }

  return Intl.DateTimeFormat().resolvedOptions().timeZone || '';
}

function formatTimezonePreview(timezone: string, locale: string, now: Date) {
  const normalizedTimezone = timezone.trim();
  if (!normalizedTimezone) {
    return '';
  }

  try {
    return new Intl.DateTimeFormat(locale, {
      dateStyle: 'full',
      timeStyle: 'medium',
      timeZone: normalizedTimezone,
    }).format(now);
  } catch {
    return '';
  }
}

function composeLocationLabel(location: DetectedLocation, precision: 'region' | 'city' | 'exact') {
  const country = (location.country || '').trim();
  const region = (location.region || '').trim();
  const city = (location.city || '').trim();

  if (precision === 'region') {
    return country;
  }
  if (precision === 'city') {
    if (country && city && city !== country) {
      return `${country} · ${city}`;
    }
    return city || region || country;
  }
  return [country, region, city].filter(Boolean).join(' · ');
}

function toFormState(profile: UserProfile | null): UserProfileFormState {
  if (!profile) {
    return DEFAULT_FORM_STATE;
  }

  return {
    avatarUrl: profile.avatarUrl || '',
    preferredName: profile.preferredName || '',
    bio: profile.bio || '',
    defaultEnableWebSearch: profile.defaultEnableWebSearch,
    timezone: profile.timezone || 'UTC',
    interfaceLanguage: (profile.interfaceLanguage as SupportedLocale) || SUPPORTED_UI_LOCALES[0].value,
    shareLocalTime: profile.shareLocalTime,
    shareLocation: profile.shareLocation,
    locationPrecision: profile.locationPrecision || 'city',
    locationLabel: profile.locationLabel || '',
    shareWeather: profile.shareWeather,
    autoSyncTimezone: profile.autoSyncTimezone ?? true,
    autoSyncLocation: profile.autoSyncLocation ?? true,
    allowLongTermMemory: profile.allowLongTermMemory,
    allowPreferenceInference: profile.allowPreferenceInference,
    blockedTopics: profile.blockedTopics || '',
  };
}

export default function UserSettingsPanel({
  profile,
  loading,
  error: externalError,
  onRefresh,
}: UserSettingsPanelProps) {
  const { messages, setLocale } = useI18n();
  const [formState, setFormState] = useState<UserProfileFormState>(DEFAULT_FORM_STATE);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [browserTimezone, setBrowserTimezone] = useState('');
  const [detectingLocation, setDetectingLocation] = useState(false);
  const [detectStatus, setDetectStatus] = useState<{ kind: 'info' | 'warning'; text: string } | null>(null);
  const [autoAlignNotices, setAutoAlignNotices] = useState<Array<{ kind: 'success' | 'warning'; text: string }>>([]);
  const [detectedCoords, setDetectedCoords] = useState<{ latitude: number | null; longitude: number | null } | null>(null);
  const [clockNow, setClockNow] = useState(() => Date.now());
  const [avatarCropSrc, setAvatarCropSrc] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const autoAlignedProfileKeyRef = useRef<string | null>(null);

  // 时区预览用秒级实时时钟，直观展示「自动对齐」后的本地时间。
  useEffect(() => {
    const timer = window.setInterval(() => setClockNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    setFormState(toFormState(profile));
    // profile 刷新（保存/自动对齐落库）后重置，避免把旧坐标反复带回保存请求。
    setDetectedCoords(null);
  }, [profile]);

  useEffect(() => {
    setBrowserTimezone(getBrowserTimezone());
  }, []);

  // 关闭位置分享时天气必然失效（后端也会清空位置提示），这里同步取消勾选；
  // 位置开着但提示暂未填充时保留勾选，等自动检测或手动填写补上即可。
  useEffect(() => {
    if (!formState.shareLocation && formState.shareWeather) {
      setFormState((prev) => ({ ...prev, shareWeather: false }));
    }
  }, [formState.shareLocation, formState.shareWeather]);

  // 「自动对齐」：每次加载到新的 profile 时跑一次（开关关闭或已对齐时为空操作）。
  // 写入走 PATCH 单字段并在完成后 onRefresh，避免整表覆盖用户未保存的编辑。
  useEffect(() => {
    if (!profile || !browserTimezone) {
      return;
    }
    const profileKey = `${profile.id}:${profile.updatedAt}`;
    if (autoAlignedProfileKeyRef.current === profileKey) {
      return;
    }
    autoAlignedProfileKeyRef.current = profileKey;

    const pushNotice = (kind: 'success' | 'warning', text: string) => {
      setAutoAlignNotices((prev) => [...prev, { kind, text }]);
    };
    const reasonText = (reason?: string) =>
      reason === 'private_network'
        ? messages.user.locationReasonPrivate
        : messages.user.locationReasonUnavailable;
    let changed = false;

    const runAlignment = async () => {
      if (profile.autoSyncTimezone && browserTimezone !== profile.timezone) {
        try {
          const response = await apiService.updateUserProfile({ timezone: browserTimezone });
          if (!response.error) {
            pushNotice('success', messages.user.autoTimezoneAligned.replace('{timezone}', browserTimezone));
            changed = true;
          }
        } catch {
          // 自动对齐失败不打断流程，时区仍可手动填写或用「使用当前时区」按钮。
        }
      }

      if (profile.autoSyncLocation && profile.shareLocation) {
        setDetectingLocation(true);
        try {
          const response = await apiService.detectLocation(profile.interfaceLanguage);
          const detected = response.data;
          if (detected?.ok) {
            const label = composeLocationLabel(detected, profile.locationPrecision);
            if (label && label !== profile.locationLabel) {
              const saveResponse = await apiService.updateUserProfile({
                share_location: true,
                location_precision: profile.locationPrecision,
                location_label: label,
                location_latitude: detected.latitude ?? null,
                location_longitude: detected.longitude ?? null,
              });
              if (!saveResponse.error) {
                let noticeText = messages.user.locationAutoUpdated.replace('{value}', label);
                const coords = formatCoords(detected.latitude, detected.longitude);
                if (coords) {
                  noticeText += messages.user.locationCoordsSuffix.replace('{coords}', coords);
                }
                if (detected.fallback_egress) {
                  noticeText += ` ${messages.user.locationEgressNote}`;
                }
                pushNotice('success', noticeText);
                changed = true;
              }
            }
          } else {
            const reason = reasonText(detected?.reason);
            pushNotice('warning', messages.user.locationDetectFailed.replace('{reason}', reason));
          }
        } catch {
          pushNotice('warning', messages.user.locationDetectFailed.replace('{reason}', messages.user.locationReasonUnavailable));
        } finally {
          setDetectingLocation(false);
        }
      }

      if (changed) {
        await onRefresh();
      }
    };

    void runAlignment();
  }, [profile, browserTimezone, messages, onRefresh]);

  const setField = <K extends keyof UserProfileFormState>(field: K, value: UserProfileFormState[K]) => {
    setFormState((prev) => ({ ...prev, [field]: value }));
  };

  const timezonePreview = formatTimezonePreview(formState.timezone, formState.interfaceLanguage, new Date(clockNow));
  const hasLocationHint = formState.shareLocation && Boolean(formState.locationLabel.trim());

  const formatCoords = (latitude?: number | null, longitude?: number | null) => {
    if (latitude == null || longitude == null) {
      return '';
    }
    return `${latitude.toFixed(2)}, ${longitude.toFixed(2)}`;
  };

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

  // 手动检测只填入表单，点「保存用户设置」后生效；自动写入仅发生在开启
  // 自动对齐开关后的进入设置页时。
  const handleDetectLocation = async () => {
    setDetectingLocation(true);
    setDetectStatus(null);

    try {
      const response = await apiService.detectLocation(formState.interfaceLanguage);
      const detected = response.data;

      if (!detected?.ok) {
        const reason = detected?.reason === 'private_network'
          ? messages.user.locationReasonPrivate
          : messages.user.locationReasonUnavailable;
        setDetectStatus({
          kind: 'warning',
          text: messages.user.locationDetectFailed.replace('{reason}', reason),
        });
        return;
      }

      const label = composeLocationLabel(detected, formState.locationPrecision);
      if (label) {
        setField('locationLabel', label);
      }
      if (detected.latitude != null && detected.longitude != null) {
        setDetectedCoords({ latitude: detected.latitude, longitude: detected.longitude });
      }
      let statusText = detected.timezone
        ? messages.user.locationDetectedWithTimezone
          .replace('{value}', label)
          .replace('{timezone}', detected.timezone)
        : messages.user.locationDetected.replace('{value}', label);
      const coords = formatCoords(detected.latitude, detected.longitude);
      if (coords) {
        statusText += messages.user.locationCoordsSuffix.replace('{coords}', coords);
      }
      if (detected.fallback_egress) {
        statusText += ` ${messages.user.locationEgressNote}`;
      }
      setDetectStatus({ kind: 'info', text: statusText });
    } catch {
      setDetectStatus({
        kind: 'warning',
        text: messages.user.locationDetectFailed.replace('{reason}', messages.user.locationReasonUnavailable),
      });
    } finally {
      setDetectingLocation(false);
    }
  };

  const handleSave = async () => {
    if (formState.shareLocation && !formState.locationLabel.trim()) {
      setError(messages.user.locationHintRequired);
      return;
    }

    setIsSaving(true);
    setError(null);

    try {
      const response = await apiService.updateUserProfile({
        avatar_url: formState.avatarUrl.trim(),
        preferred_name: formState.preferredName.trim(),
        bio: formState.bio.trim(),
        default_enable_web_search: formState.defaultEnableWebSearch,
        timezone: formState.timezone.trim(),
        interface_language: formState.interfaceLanguage,
        share_local_time: formState.shareLocalTime,
        share_location: formState.shareLocation,
        location_precision: formState.locationPrecision,
        location_label: formState.locationLabel.trim(),
        location_latitude: detectedCoords?.latitude,
        location_longitude: detectedCoords?.longitude,
        share_weather: formState.shareWeather,
        auto_sync_timezone: formState.autoSyncTimezone,
        auto_sync_location: formState.autoSyncLocation,
        allow_long_term_memory: formState.allowLongTermMemory,
        allow_preference_inference: formState.allowPreferenceInference,
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
      <div className="mx-auto max-w-3xl px-6 py-8 md:px-10">
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

        {autoAlignNotices.length > 0 && (
          <div className="mb-6 space-y-2">
            {autoAlignNotices.map((notice, index) => (
              <div
                key={`${notice.kind}-${index}`}
                className={`flex items-center gap-2 rounded-xl border px-4 py-3 text-sm ${
                  notice.kind === 'warning'
                    ? 'border-amber-200 bg-amber-50 text-amber-800'
                    : 'border-emerald-200 bg-emerald-50 text-emerald-800'
                }`}
              >
                {notice.kind === 'warning' ? <AlertCircle size={16} /> : <CheckCircle2 size={16} />}
                <span>{notice.text}</span>
              </div>
            ))}
          </div>
        )}

        {loading ? (
          <div className="rounded-2xl border border-slate-200 bg-white px-5 py-10 text-sm text-slate-500 shadow-sm">
            {messages.user.loading}
          </div>
        ) : (
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
                  <label className="mb-1.5 block text-sm font-medium text-slate-700">{messages.user.shortBio}</label>
                  <textarea
                    value={formState.bio}
                    onChange={(event) => setField('bio', event.target.value)}
                    rows={4}
                    placeholder={messages.user.shortBioPlaceholder}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                  />
                </div>

                <div>
                  <label className="mb-1.5 block text-sm font-medium text-slate-700">{messages.user.interfaceLanguage}</label>
                  <select
                    value={formState.interfaceLanguage}
                    onChange={(event) => setField('interfaceLanguage', event.target.value as SupportedLocale)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                  >
                    {SUPPORTED_UI_LOCALES.map((language) => (
                      <option key={language.value} value={language.value}>{language.nativeLabel} / {language.englishLabel}</option>
                    ))}
                  </select>
                  <p className="mt-2 text-xs text-slate-500">{messages.user.interfaceLanguageHelp}</p>
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
                  <label className="mt-3 flex items-center gap-2 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={formState.autoSyncTimezone}
                      onChange={(event) => setField('autoSyncTimezone', event.target.checked)}
                      className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span>{messages.user.autoSyncTimezone}</span>
                  </label>
                  <p className="text-xs text-slate-500">{messages.user.autoSyncTimezoneHelp}</p>
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
                  <div className="space-y-4 rounded-xl border border-slate-200 bg-slate-50/60 p-4">
                    <div>
                      <label className="mb-1.5 block text-sm font-medium text-slate-700">{messages.user.locationPrecision}</label>
                      <select
                        value={formState.locationPrecision}
                        onChange={(event) => setField('locationPrecision', event.target.value as UserProfileFormState['locationPrecision'])}
                        className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                      >
                        <option value="region">{messages.user.region}</option>
                        <option value="city">{messages.user.city}</option>
                        <option value="exact">{messages.user.exact}</option>
                      </select>
                    </div>

                    <div>
                      <div className="mb-1.5 flex items-center justify-between gap-3">
                        <label className="block text-sm font-medium text-slate-700">{messages.user.locationHint}</label>
                        <button
                          type="button"
                          onClick={handleDetectLocation}
                          disabled={detectingLocation}
                          className="text-xs font-medium text-blue-700 transition-colors hover:text-blue-800 disabled:cursor-not-allowed disabled:text-slate-400"
                        >
                          {detectingLocation ? messages.user.detectingLocation : messages.user.detectLocation}
                        </button>
                      </div>
                      <input
                        type="text"
                        value={formState.locationLabel}
                        onChange={(event) => setField('locationLabel', event.target.value)}
                        placeholder={messages.user.locationHintPlaceholder}
                        className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                      />
                      <label className="mt-3 flex items-center gap-2 text-sm text-slate-700">
                        <input
                          type="checkbox"
                          checked={formState.autoSyncLocation}
                          onChange={(event) => setField('autoSyncLocation', event.target.checked)}
                          className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                        />
                        <span>{messages.user.autoSyncLocation}</span>
                      </label>
                      <p className="mt-1 text-xs text-slate-500">{messages.user.autoSyncLocationHelp}</p>
                      {detectStatus ? (
                        <p className={`mt-2 text-xs ${detectStatus.kind === 'warning' ? 'text-amber-700' : 'text-emerald-700'}`}>
                          {detectStatus.text}
                        </p>
                      ) : null}
                      <p className="mt-2 text-xs text-slate-500">{messages.user.locationHintHelp}</p>
                    </div>
                  </div>
                )}

                <div>
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
                  <p className={`mt-2 text-xs ${hasLocationHint ? 'text-slate-500' : 'text-amber-700'}`}>
                    {hasLocationHint
                      ? messages.user.shareWeatherHelpEnabled.replace('{location}', formState.locationLabel.trim())
                      : messages.user.shareWeatherHelpDisabled}
                  </p>
                </div>
              </div>
            </div>

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
              </div>
            </div>

            <div className="sticky bottom-4 z-10 flex justify-end">
              <button
                onClick={handleSave}
                disabled={isSaving}
                className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-3 text-sm font-medium text-white shadow-lg transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Save size={16} />
                <span>{isSaving ? messages.user.saving : messages.user.saveUserSettings}</span>
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
