interface ApiResponse<T> {
  data?: T;
  error?: string;
}

import { Character, ChatSession, KnowledgeAsset, MemoryEntry, MemoryExplorerEntry, MemoryExplorerFile, MemoryNarrative, MemorySnapshot, Message, MessageAttachment, ResearchPayload, TokenUsage, ToolCallInfo, UserProfile } from '@/types';
import { ModelConfig, ModelProvider, ModelRoleAssignments, ModelRoleKey, TtsAudioOutput, TtsEngine, TtsEngineTestResult, TtsServiceSettings, TtsVoiceModel, UploadConvertRequest, WebSearchConfig, WebSearchProvider, WebSearchTestResult } from '@/types';
import { API_BASE_URL, MEDIA_BASE_URL } from '@/constants';
import { DEFAULT_LOCALE, normalizeLocale } from '@/i18n/messages';

interface ApiCharacter {
  id: number;
  name: string;
  description: string;
  user_address: string;
  scenario: string;
  example_dialogue: string;
  personality: string;
  appearance: string;
  response_guidelines: string;
  avatar_url: string;
  enable_web_search?: boolean | null;
  file: string;
  affiliation: string;
  disabled_states?: {
    name: boolean;
    description: boolean;
    personality: boolean;
    appearance: boolean;
    response_guidelines: boolean;
    file: boolean;
  };
}

interface ApiSession {
  id: number;
  title: string;
  character: number | ApiCharacter;
  last_response_latency_ms?: number | null;
  is_private_mode?: boolean;
  origin?: string;
  created_at: string;
  updated_at: string;
}

interface ApiModelConfig {
  id: number;
  name: string;
  provider: ModelProvider;
  model_name: string;
  api_key: string;
  base_url?: string;
  context_window?: number | null;
  created_at: string;
  updated_at: string;
}

interface ApiMessage {
  id: string;
  content: string;
  role: 'user' | 'assistant';
  timestamp: string;
  chat_session?: string;
  sender_id?: string;
  sender_name?: string;
  sender_avatar_url?: string;
  sender_type?: 'user' | 'character' | 'system';
  research_payload?: {
    query?: string;
    provider?: string;
    items?: Array<{
      title?: string;
      url?: string;
      snippet?: string;
      domain?: string;
      source?: string;
    }>;
    error?: string;
  };
  thinking?: string | null;
  raw_reasoning?: string | null;
  steps?: Array<{
    kind: 'thinking' | 'tool';
    text?: string;
    raw_text?: string;
    tool?: string;
    arguments?: Record<string, unknown>;
  }>;
  tool_calls?: Array<{
    tool: string;
    arguments?: Record<string, unknown>;
  }>;
  token_usage?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
    cached_tokens?: number;
  } | null;
  /** 增量落库状态：''=已完成；streaming/interrupted=未完成（见 Message.status）。 */
  status?: string;
  file_uri?: string | null;
  file_name?: string | null;
  file_preview_url?: string | null;
  file_type?: string | null;
  file_mime_type?: string | null;
  attachments?: ApiMessageAttachment[];
}

interface ApiMessageAttachment {
  file_uri?: string | null;
  file_name?: string | null;
  file_preview_url?: string | null;
  file_type?: string | null;
  file_mime_type?: string | null;
}

interface ApiMemoryExplorerEntry {
  path: string;
  entry_type: 'file' | 'directory';
  layer: string;
  title: string;
  kind: string;
  read_hint: string;
  is_locked: boolean;
  can_user_edit: boolean;
  can_auto_update: boolean;
  updated_at: string;
  manageable?: boolean;
  asset_id?: string | number | null;
  preview_kind?: 'text' | 'image' | 'binary' | 'directory' | string;
  child_count?: number;
  size_hint?: number;
}

interface ApiMemoryExplorerListResponse {
  path_prefix: string;
  entries: ApiMemoryExplorerEntry[];
  error?: string;
  truncated?: boolean;
}

interface ApiMemoryExplorerFile {
  path: string;
  layer: string;
  title: string;
  kind: string;
  read_hint: string;
  content: string;
  truncated?: boolean;
  manageable?: boolean;
  asset_id?: string | number | null;
  preview_kind?: 'text' | 'image' | 'binary' | string;
  file_url?: string | null;
  mime_type?: string | null;
  error?: string;
  offset?: number;
  next_offset?: number | null;
  total_chars?: number;
  has_more?: boolean;
}

interface ApiKnowledgeAsset {
  id: string | number;
  file_url?: string | null;
  file_name: string;
  file_type: string;
  file_mime_type?: string | null;
  created_at: string;
  updated_at: string;
}

interface ApiKnowledgeAssetUploadResponse {
  assets: ApiKnowledgeAsset[];
}

interface ApiUserProfile {
  id: number;
  avatar_url?: string;
  preferred_name: string;
  pronouns: string;
  bio: string;
  default_enable_web_search: boolean;
  timezone: string;
  interface_language: string;
  share_local_time: boolean;
  share_location: boolean;
  location_precision: 'region' | 'city' | 'exact';
  location_label: string;
  location_latitude: number | null;
  location_longitude: number | null;
  share_weather: boolean;
  auto_sync_timezone: boolean;
  auto_sync_location: boolean;
  preferred_relationship_style: string;
  preferred_reply_length: 'short' | 'medium' | 'long';
  preferred_proactivity: 'low' | 'normal' | 'high';
  preferred_emotional_intensity: 'low' | 'normal' | 'high';
  allow_long_term_memory: boolean;
  allow_preference_inference: boolean;
  allow_research_profile_updates: boolean;
  blocked_topics: string;
  created_at: string;
  updated_at: string;
}

export interface DetectedLocation {
  ok: boolean;
  source?: string;
  fallback_egress?: boolean;
  country?: string;
  region?: string;
  city?: string;
  timezone?: string;
  latitude?: number | null;
  longitude?: number | null;
  reason?: 'private_network' | 'unavailable';
}

interface ApiWebSearchConfig {
  id?: number;
  provider: WebSearchProvider;
  api_key: string;
  max_results: number;
  created_at?: string;
  updated_at?: string;
}

function normalizeResearchPayload(payload?: ApiMessage['research_payload']): ResearchPayload | null {
  if (!payload) {
    return null;
  }

  return {
    query: payload.query || '',
    provider: payload.provider || '',
    items: (payload.items || [])
      .filter((item) => item?.url)
      .map((item) => ({
        title: item?.title || item?.url || 'Untitled',
        url: item?.url || '',
        snippet: item?.snippet || '',
        domain: item?.domain || '',
        source: item?.source || '',
      })),
    error: payload.error || '',
  };
}

function normalizeMessage(apiData: ApiMessage): Message {
  const attachments = normalizeMessageAttachments(apiData);
  const primaryAttachment = attachments[0];

  return {
    id: String(apiData.id),
    content: apiData.content,
    role: apiData.role,
    timestamp: apiData.timestamp,
    senderId: apiData.sender_id,
    senderName: apiData.sender_name,
    senderAvatarUrl: apiData.sender_avatar_url,
    senderType: apiData.sender_type,
    researchPayload: normalizeResearchPayload(apiData.research_payload),
    thinking: apiData.thinking || '',
    rawReasoning: apiData.raw_reasoning || '',
    steps: Array.isArray(apiData.steps) ? apiData.steps : undefined,
    toolCalls: normalizeToolCalls(apiData.tool_calls),
    tokenUsage: normalizeTokenUsage(apiData.token_usage),
    status: apiData.status || '',
    attachments,
    fileUri: primaryAttachment?.fileUri || apiData.file_uri || undefined,
    fileName: primaryAttachment?.fileName || apiData.file_name || undefined,
    filePreviewUrl: primaryAttachment?.filePreviewUrl || apiData.file_preview_url || undefined,
    fileType: primaryAttachment?.fileType || apiData.file_type || undefined,
    fileMimeType: primaryAttachment?.fileMimeType || apiData.file_mime_type || undefined,
  };
}

function normalizeToolCalls(apiData?: ApiMessage['tool_calls']): ToolCallInfo[] {
  return (apiData || [])
    .filter((call) => call?.tool)
    .map((call) => ({
      tool: call.tool,
      arguments: call.arguments || {},
    }));
}

export function normalizeTokenUsage(apiData?: ApiMessage['token_usage']): TokenUsage | null {
  if (!apiData) {
    return null;
  }

  const promptTokens = apiData.prompt_tokens ?? 0;
  const completionTokens = apiData.completion_tokens ?? 0;
  if (!promptTokens && !completionTokens && !apiData.total_tokens) {
    return null;
  }

  return {
    promptTokens,
    completionTokens,
    totalTokens: apiData.total_tokens ?? (promptTokens + completionTokens),
    cachedTokens: Math.min(apiData.cached_tokens ?? 0, promptTokens),
  };
}

function normalizeMessageAttachments(apiData: ApiMessage): MessageAttachment[] {
  const rawAttachments = apiData.attachments?.length
    ? apiData.attachments
    : (apiData.file_name || apiData.file_uri || apiData.file_preview_url || apiData.file_type || apiData.file_mime_type)
      ? [{
          file_uri: apiData.file_uri,
          file_name: apiData.file_name,
          file_preview_url: apiData.file_preview_url,
          file_type: apiData.file_type,
          file_mime_type: apiData.file_mime_type,
        }]
      : [];

  return rawAttachments.map((attachment) => ({
    fileUri: attachment.file_uri || undefined,
    fileName: attachment.file_name || undefined,
    filePreviewUrl: attachment.file_preview_url || undefined,
    fileType: attachment.file_type || undefined,
    fileMimeType: attachment.file_mime_type || undefined,
  }));
}

function normalizeMemoryExplorerEntry(apiData: ApiMemoryExplorerEntry): MemoryExplorerEntry {
  return {
    path: apiData.path,
    entryType: apiData.entry_type,
    layer: apiData.layer,
    title: apiData.title,
    kind: apiData.kind,
    readHint: apiData.read_hint || '',
    isLocked: apiData.is_locked,
    canUserEdit: apiData.can_user_edit,
    canAutoUpdate: apiData.can_auto_update,
    updatedAt: apiData.updated_at,
    manageable: apiData.manageable,
    assetId: apiData.asset_id != null ? String(apiData.asset_id) : undefined,
    previewKind: apiData.preview_kind,
    childCount: apiData.child_count,
    sizeHint: apiData.size_hint,
  };
}

function normalizeMemoryExplorerFile(apiData: ApiMemoryExplorerFile): MemoryExplorerFile {
  const fileUrl = apiData.file_url
    ? (apiData.file_url.startsWith('http') ? apiData.file_url : `${MEDIA_BASE_URL}${apiData.file_url}`)
    : undefined;
  return {
    path: apiData.path,
    layer: apiData.layer,
    title: apiData.title,
    kind: apiData.kind,
    readHint: apiData.read_hint || '',
    content: apiData.content || '',
    truncated: apiData.truncated,
    manageable: apiData.manageable,
    assetId: apiData.asset_id != null ? String(apiData.asset_id) : undefined,
    previewKind: apiData.preview_kind,
    fileUrl,
    mimeType: apiData.mime_type || undefined,
    error: apiData.error,
    offset: apiData.offset,
    nextOffset: apiData.next_offset ?? undefined,
    totalChars: apiData.total_chars,
    hasMore: apiData.has_more,
  };
}

function normalizeKnowledgeAsset(apiData: ApiKnowledgeAsset): KnowledgeAsset {
  const fileUrl = apiData.file_url
    ? (apiData.file_url.startsWith('http') ? apiData.file_url : `${MEDIA_BASE_URL}${apiData.file_url}`)
    : undefined;
  return {
    id: String(apiData.id),
    fileUrl,
    fileName: apiData.file_name || '',
    fileType: apiData.file_type || '',
    fileMimeType: apiData.file_mime_type || undefined,
    createdAt: apiData.created_at,
    updatedAt: apiData.updated_at,
  };
}

function normalizeCharacter(apiData: ApiCharacter): Character {
  return {
    id: String(apiData.id),
    name: apiData.name,
    description: apiData.description,
    userAddress: apiData.user_address || '',
    scenario: apiData.scenario || '',
    exampleDialogue: apiData.example_dialogue || '',
    personality: apiData.personality,
    appearance: apiData.appearance,
    affiliation: apiData.affiliation,
    responseGuidelines: apiData.response_guidelines,
    avatarUrl: apiData.avatar_url || undefined,
    fileUrl: apiData.file ? (apiData.file.startsWith('http') ? apiData.file : `${MEDIA_BASE_URL}${apiData.file}`) : undefined,
    disabled: {
      name: apiData.disabled_states?.name || false,
      description: apiData.disabled_states?.description || false,
      personality: apiData.disabled_states?.personality || false,
      appearance: apiData.disabled_states?.appearance || false,
      responseGuidelines: apiData.disabled_states?.response_guidelines || false,
      file: apiData.disabled_states?.file || false,
    }
  };
}

function normalizeModelConfig(apiData: ApiModelConfig): ModelConfig {
  return {
    id: String(apiData.id),
    name: apiData.name,
    provider: apiData.provider,
    modelName: apiData.model_name,
    apiKey: apiData.api_key,
    baseUrl: apiData.base_url || '',
    contextWindow: apiData.context_window ?? null,
    createdAt: apiData.created_at,
    updatedAt: apiData.updated_at,
  };
}

function normalizeSession(
  apiData: ApiSession,
  characterData?: ApiCharacter,
): ChatSession {
  let character: Character;

  if (typeof apiData.character === 'number') {
    if (!characterData) {
      throw new Error('Character data is required when character is an ID');
    }
    character = normalizeCharacter(characterData);
  } else {
    character = normalizeCharacter(apiData.character as ApiCharacter);
  }

  return {
    id: String(apiData.id),
    title: apiData.title,
    lastResponseLatencyMs: apiData.last_response_latency_ms ?? null,
    character,
    isPrivateMode: apiData.is_private_mode ?? false,
    origin: apiData.origin || 'topic',
    createdAt: apiData.created_at,
    updatedAt: apiData.updated_at,
  };
}

function normalizeUserProfile(apiData: ApiUserProfile): UserProfile {
  return {
    id: String(apiData.id),
    avatarUrl: apiData.avatar_url
      ? (apiData.avatar_url.startsWith('http') ? apiData.avatar_url : `${MEDIA_BASE_URL}${apiData.avatar_url}`)
      : undefined,
    preferredName: apiData.preferred_name || '',
    pronouns: apiData.pronouns || '',
    bio: apiData.bio || '',
    defaultEnableWebSearch: apiData.default_enable_web_search,
    timezone: apiData.timezone || 'UTC',
    interfaceLanguage: normalizeLocale(apiData.interface_language || DEFAULT_LOCALE),
    shareLocalTime: apiData.share_local_time,
    shareLocation: apiData.share_location,
    locationPrecision: apiData.location_precision || 'city',
    locationLabel: apiData.location_label || '',
    locationLatitude: apiData.location_latitude ?? null,
    locationLongitude: apiData.location_longitude ?? null,
    shareWeather: apiData.share_weather,
    autoSyncTimezone: apiData.auto_sync_timezone,
    autoSyncLocation: apiData.auto_sync_location,
    preferredRelationshipStyle: apiData.preferred_relationship_style || '',
    preferredReplyLength: apiData.preferred_reply_length || 'medium',
    preferredProactivity: apiData.preferred_proactivity || 'normal',
    preferredEmotionalIntensity: apiData.preferred_emotional_intensity || 'normal',
    allowLongTermMemory: apiData.allow_long_term_memory,
    allowPreferenceInference: apiData.allow_preference_inference,
    allowResearchProfileUpdates: apiData.allow_research_profile_updates,
    blockedTopics: apiData.blocked_topics || '',
    createdAt: apiData.created_at,
    updatedAt: apiData.updated_at,
  };
}

interface ApiTtsServiceSettings {
  default_provider: string;
  genie_url: string;
  gptsovits_url: string;
  indextts_url: string;
}

interface ApiTtsVoiceEmotion {
  name: string;
  ref_audio_path?: string;
  ref_audio_text?: string;
  ref_audio_language?: string;
}

interface ApiTtsVoiceModel {
  id: number;
  name: string;
  engine: string;
  model_version: string;
  language: string;
  voice_name: string;
  onnx_model_dir: string;
  ref_audio_path: string;
  ref_audio_text: string;
  ref_audio_language: string;
  emotions?: ApiTtsVoiceEmotion[];
  conversion_status: string;
  conversion_error: string;
  created_at?: string;
  updated_at?: string;
}

function normalizeTtsServiceSettings(apiData: ApiTtsServiceSettings): TtsServiceSettings {
  return {
    defaultProvider: (apiData.default_provider || '') as TtsServiceSettings['defaultProvider'],
    genieUrl: apiData.genie_url || '',
    gptsovitsUrl: apiData.gptsovits_url || '',
    indexttsUrl: apiData.indextts_url || '',
  };
}

function normalizeTtsVoiceModel(apiData: ApiTtsVoiceModel): TtsVoiceModel {
  return {
    id: apiData.id,
    name: apiData.name,
    engine: (apiData.engine || 'genie') as TtsVoiceModel['engine'],
    modelVersion: apiData.model_version || '',
    language: apiData.language || '',
    voiceName: apiData.voice_name || '',
    onnxModelDir: apiData.onnx_model_dir || '',
    refAudioPath: apiData.ref_audio_path || '',
    refAudioText: apiData.ref_audio_text || '',
    refAudioLanguage: apiData.ref_audio_language || '',
    emotions: (apiData.emotions || []).map((emotion) => ({
      name: emotion.name || '',
      refAudioPath: emotion.ref_audio_path || '',
      refAudioText: emotion.ref_audio_text || '',
      refAudioLanguage: emotion.ref_audio_language || '',
    })),
    conversionStatus: (apiData.conversion_status || '') as TtsVoiceModel['conversionStatus'],
    conversionError: apiData.conversion_error || '',
    createdAt: apiData.created_at,
    updatedAt: apiData.updated_at,
  };
}

interface ApiTtsAudioOutput {
  id: number;
  character_id?: number | null;
  character_name?: string;
  text: string;
  emotion: string;
  provider: string;
  audio_url?: string | null;
  content_type?: string;
  processing_ms?: number | null;
  first_byte_ms?: number | null;
  created_at?: string;
}

function normalizeTtsAudioOutput(apiData: ApiTtsAudioOutput): TtsAudioOutput {
  return {
    id: apiData.id,
    characterId: apiData.character_id ?? null,
    characterName: apiData.character_name || '',
    text: apiData.text || '',
    emotion: apiData.emotion || '',
    provider: apiData.provider || '',
    audioUrl: apiData.audio_url || '',
    contentType: apiData.content_type || 'audio/wav',
    processingMs: apiData.processing_ms ?? null,
    firstByteMs: apiData.first_byte_ms ?? null,
    createdAt: apiData.created_at || '',
  };
}

function normalizeWebSearchConfig(apiData: ApiWebSearchConfig): WebSearchConfig {
  return {
    id: apiData.id ? String(apiData.id) : undefined,
    provider: apiData.provider || 'tavily',
    apiKey: apiData.api_key || '',
    maxResults: apiData.max_results ?? 5,
    createdAt: apiData.created_at,
    updatedAt: apiData.updated_at,
  };
}

export const setAuthToken = (token: string) => {
  localStorage.setItem('authToken', token);
};

export const getAuthToken = () => {
  return localStorage.getItem('authToken');
};

export const removeAuthToken = () => {
  localStorage.removeItem('authToken');
};

interface SendMessageRequest {
  message: string;
  character_id: string;
  chat_session_id?: string;
  start_conversation?: boolean;
  origin?: 'topic' | 'chat';
  attachment?: File | null;
  attachments?: File[];
}

export interface AsrTranscription {
  text: string;
  language?: string;
  processing_ms?: number;
  model_load_ms?: number;
}

export interface AsrReadiness {
  available: boolean;
  installed: boolean;
  loaded: boolean;
  provider: string;
  model: string;
  device: string;
  compute_type: string;
  hint: string;
}

export interface TtsReadiness {
  provider: string;
  configured: boolean;
  reachable: boolean;
  available: boolean;
  label: string;
  hint: string;
  providers: Array<{ key: string; label: string }>;
}

interface CreateModelConfigRequest {
  name: string;
  provider: ModelProvider;
  model_name: string;
  api_key: string;
  base_url?: string;
  context_window?: number | null;
  is_default?: boolean;
}

interface CreateCharacterRequest {
  name: string;
  description: string;
  user_address?: string;
  scenario?: string;
  example_dialogue?: string;
  personality: string;
  appearance: string;
  response_guidelines: string;
  file_url?: string;
  clear_file?: boolean;
  disabled_states?: {
    name: boolean;
    description: boolean;
    personality: boolean;
    appearance: boolean;
    response_guidelines: boolean;
    file: boolean;
  };
}

interface CreateSessionRequest {
  character: string;
  title?: string;
}

interface UpdateUserProfileRequest {
  avatar_url?: string;
  preferred_name?: string;
  pronouns?: string;
  bio?: string;
  default_enable_web_search?: boolean;
  timezone?: string;
  interface_language?: string;
  share_local_time?: boolean;
  share_location?: boolean;
  location_precision?: 'region' | 'city' | 'exact';
  location_label?: string;
  location_latitude?: number | null;
  location_longitude?: number | null;
  share_weather?: boolean;
  auto_sync_timezone?: boolean;
  auto_sync_location?: boolean;
  preferred_relationship_style?: string;
  preferred_reply_length?: 'short' | 'medium' | 'long';
  preferred_proactivity?: 'low' | 'normal' | 'high';
  preferred_emotional_intensity?: 'low' | 'normal' | 'high';
  allow_long_term_memory?: boolean;
  allow_preference_inference?: boolean;
  allow_research_profile_updates?: boolean;
  blocked_topics?: string;
}

interface UpdateWebSearchConfigRequest {
  provider?: WebSearchProvider;
  api_key?: string;
  max_results?: number;
}

interface StreamChunkEvent {
  type: 'delta';
  content: string;
}

interface StreamSessionEvent {
  type: 'session';
  chat_session_id: number;
  user_message?: ApiMessage | null;
  is_greeting?: boolean;
}

interface StreamDoneEvent {
  type: 'done';
  message_id: number;
  content: string;
  tts_segments?: { emotion?: string; text: string }[];
  timestamp: string;
  latency_ms?: number;
  provider?: ModelProvider;
  model_name?: string;
  research_payload?: ApiMessage['research_payload'];
  thinking?: string | null;
  raw_reasoning?: string | null;
  steps?: ApiMessage['steps'];
  tool_calls?: ApiMessage['tool_calls'];
  token_usage?: ApiMessage['token_usage'];
}

interface StreamThinkingEvent {
  type: 'thinking';
  content: string;
}

interface StreamToolEvent {
  type: 'tool';
  tool: string;
  arguments?: Record<string, unknown>;
}

interface StreamErrorEvent {
  type: 'error';
  error: string;
}

type StreamMessageEvent = StreamChunkEvent | StreamSessionEvent | StreamDoneEvent | StreamThinkingEvent | StreamToolEvent | StreamErrorEvent;

function buildApiUrl(endpoint: string): string {
  const normalizedEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;

  if (!/^https?:\/\//.test(API_BASE_URL)) {
    return `${API_BASE_URL}${normalizedEndpoint}`;
  }

  const [path, queryString] = normalizedEndpoint.split('?');
  const directBackendPath = path.endsWith('/') ? path : `${path}/`;
  return `${API_BASE_URL}${directBackendPath}${queryString ? `?${queryString}` : ''}`;
}

class ApiService {
  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<ApiResponse<T>> {
    try {
      const token = getAuthToken();
      const headers: Record<string, string> = {};

      if (options.headers) {
        Object.entries(options.headers).forEach(([key, value]) => {
          if (typeof value === 'string') {
            headers[key] = value;
          }
        });
      }

      if (!(options.body instanceof FormData)) {
        headers['Content-Type'] = 'application/json';
      }

      if (token) {
        headers['Authorization'] = `Token ${token}`;
      }

      const response = await fetch(buildApiUrl(endpoint), {
        headers,
        ...options,
      });

      if (response.status === 204) {
        return { data: undefined };
      }

      const contentType = response.headers.get('Content-Type') || '';
      const data = contentType.includes('application/json')
        ? await response.json()
        : await response.text();

      if (!response.ok) {
        const validationMessage = typeof data === 'object' && data
          ? Object.entries(data)
              .map(([key, value]) => {
                if (Array.isArray(value)) {
                  return `${key}: ${value.join(', ')}`;
                }
                if (typeof value === 'string') {
                  return `${key}: ${value}`;
                }
                return '';
              })
              .filter(Boolean)
              .join(' ')
          : '';
        const errorMessage = typeof data === 'string'
          ? data
          : data.detail || data.error || validationMessage || 'API Request Failed';
        throw new Error(errorMessage);
      }

      return { data };
    } catch (error) {
      console.error('API request failed:', error);
      return { error: error instanceof Error ? error.message : 'Unknown error' };
    }
  }

  async getCharacters(): Promise<ApiResponse<Character[]>> {
    const response = await this.request<ApiCharacter[]>('/characters');
    if (response.data) {
      return { data: response.data.map(normalizeCharacter) };
    }
    return { data: undefined };
  }

  async createCharacter(character: CreateCharacterRequest, file?: File): Promise<ApiResponse<Character>> {
    const formData = new FormData();
    Object.entries(character).forEach(([key, value]) => {
      if (value !== undefined) {
        if (key === 'disabled_states' && typeof value === 'object') {
          formData.append(key, JSON.stringify(value));
        } else if (typeof value === 'boolean') {
          formData.append(key, String(value));
        } else {
          formData.append(key, value as string);
        }
      }
    });
    if (file) {
      formData.append('file', file);
    }

    const response = await this.request<ApiCharacter>('/characters', { method: 'POST', body: formData });
    if (response.data) {
      return { data: normalizeCharacter(response.data) };
    }
    return { data: undefined };
  }

  async getCharacter(id: string): Promise<ApiResponse<Character>> {
    const response = await this.request<ApiCharacter>(`/characters/${id}`);
    if (response.data) {
      return { data: normalizeCharacter(response.data) };
    }
    return { data: undefined };
  }

  async updateCharacter(id: string, character: Partial<CreateCharacterRequest>, file?: File): Promise<ApiResponse<Character>> {
    const formData = new FormData();
    Object.entries(character).forEach(([key, value]) => {
      if (value !== undefined) {
        if (key === 'disabled_states' && typeof value === 'object') {
          formData.append(key, JSON.stringify(value));
        } else if (typeof value === 'boolean') {
          formData.append(key, String(value));
        } else {
          formData.append(key, value as string);
        }
      }
    });
    if (file) {
      formData.append('file', file);
    }

    const response = await this.request<ApiCharacter>(`/characters/${id}`, { method: 'PATCH', body: formData });
    if (response.data) {
      return { data: normalizeCharacter(response.data) };
    }
    return { data: undefined };
  }

  async getChatSessions(characterId?: string, origin?: 'topic' | 'chat'): Promise<ApiResponse<ChatSession[]>> {
    const queryParams: string[] = [];
    if (characterId) queryParams.push(`character_id=${characterId}`);
    if (origin) queryParams.push(`origin=${origin}`);
    const params = queryParams.length ? `?${queryParams.join('&')}` : '';
    const response = await this.request<ApiSession[]>(`/sessions${params}`);

    if (response.data) {
      const sessions: ChatSession[] = [];

      for (const sessionData of response.data) {
        if (typeof sessionData.character === 'number') {
          const charResponse = await this.getCharacter(String(sessionData.character));
          if (charResponse.data) {
            const apiChar: ApiCharacter = {
              id: sessionData.character,
              name: charResponse.data.name,
              description: charResponse.data.description,
              user_address: charResponse.data.userAddress,
              scenario: charResponse.data.scenario,
              example_dialogue: charResponse.data.exampleDialogue,
              personality: charResponse.data.personality,
              appearance: charResponse.data.appearance,
              affiliation: charResponse.data.affiliation,
                response_guidelines: charResponse.data.responseGuidelines,
                avatar_url: '',
                file: charResponse.data.fileUrl || '',
                disabled_states: {
                  name: charResponse.data.disabled.name,
                description: charResponse.data.disabled.description,
                personality: charResponse.data.disabled.personality,
                appearance: charResponse.data.disabled.appearance,
                response_guidelines: charResponse.data.disabled.responseGuidelines,
                  file: charResponse.data.disabled.file,
                }
            };
            sessions.push(normalizeSession(sessionData, apiChar));
          }
        } else {
          sessions.push(normalizeSession(sessionData));
        }
      }

      return { data: sessions };
    }
    return { data: undefined };
  }

  async createChatSession(characterId: string, title?: string, settings?: Partial<CreateSessionRequest>): Promise<ApiResponse<ChatSession>> {
    const requestData: CreateSessionRequest = {
      character: characterId,
      title,
      ...settings
    };

    const response = await this.request<ApiSession>('/sessions', {
      method: 'POST',
      body: JSON.stringify(requestData),
    });

    if (response.data) {
      if (typeof response.data.character === 'object') {
        return { data: normalizeSession(response.data) };
      } else {
        const charResponse = await this.getCharacter(characterId);
        if (charResponse.data) {
          const apiChar: ApiCharacter = {
            id: parseInt(characterId),
            name: charResponse.data.name,
            description: charResponse.data.description,
            user_address: charResponse.data.userAddress,
            scenario: charResponse.data.scenario,
            example_dialogue: charResponse.data.exampleDialogue,
            personality: charResponse.data.personality,
            affiliation: charResponse.data.affiliation,
            appearance: charResponse.data.appearance,
            response_guidelines: charResponse.data.responseGuidelines,
            avatar_url: '',
            file: charResponse.data.fileUrl || '',
            disabled_states: {
              name: charResponse.data.disabled.name,
              description: charResponse.data.disabled.description,
              personality: charResponse.data.disabled.personality,
              appearance: charResponse.data.disabled.appearance,
              response_guidelines: charResponse.data.disabled.responseGuidelines,
              file: charResponse.data.disabled.file,
            }
          };
          return { data: normalizeSession(response.data, apiChar) };
        }
      }
    }
    return { data: undefined };
  }

  async getChatSession(id: string): Promise<ApiResponse<ChatSession>> {
    const response = await this.request<ApiSession>(`/sessions/${id}`);

    if (response.data) {
      if (typeof response.data.character === 'object') {
        return { data: normalizeSession(response.data) };
      } else {
        const charResponse = await this.getCharacter(String(response.data.character));
        if (charResponse.data) {
          const apiChar: ApiCharacter = {
            id: parseInt(String(response.data.character)),
            name: charResponse.data.name,
            description: charResponse.data.description,
            user_address: charResponse.data.userAddress,
            scenario: charResponse.data.scenario,
            example_dialogue: charResponse.data.exampleDialogue,
            personality: charResponse.data.personality,
            affiliation: charResponse.data.affiliation,
            appearance: charResponse.data.appearance,
            response_guidelines: charResponse.data.responseGuidelines,
            avatar_url: '',
            file: charResponse.data.fileUrl || '',
            disabled_states: {
              name: charResponse.data.disabled.name,
              description: charResponse.data.disabled.description,
              personality: charResponse.data.disabled.personality,
              appearance: charResponse.data.disabled.appearance,
              response_guidelines: charResponse.data.disabled.responseGuidelines,
              file: charResponse.data.disabled.file,
            }
          };
          return { data: normalizeSession(response.data, apiChar) };
        }
      }
    }
    return { data: undefined };
  }

  async updateChatSession(id: string, data: Partial<ChatSession>): Promise<ApiResponse<ChatSession>> {
    const backendData: Record<string, unknown> = {
      title: data.title,
    };

    if (data.character) {
      backendData.character = data.character.id;
    }

    const response = await this.request<ApiSession>(`/sessions/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(backendData),
    });

    if (response.data) {
      return { data: normalizeSession(response.data) };
    }
    return { data: undefined };
  }

  async deleteChatSession(id: string): Promise<ApiResponse<void>> {
    return this.request(`/sessions/${id}`, {
      method: 'DELETE',
    });
  }

  async getMessages(chatSessionId: string): Promise<ApiResponse<Message[]>> {
    const response = await this.request<ApiMessage[]>(`/messages?chat_session_id=${chatSessionId}`);
    if (response.data) {
      return { data: response.data.map(normalizeMessage) };
    }
    return { data: undefined };
  }

  async transcribeAudio(
    audio: Blob,
    options?: { language?: string; signal?: AbortSignal },
  ): Promise<ApiResponse<AsrTranscription>> {
    const { language, signal } = options || {};
    const formData = new FormData();
    const extension = audio.type.includes('ogg') ? 'ogg' : audio.type.includes('wav') ? 'wav' : 'webm';
    formData.append('audio', new File([audio], `speech.${extension}`, { type: audio.type || 'audio/wav' }));
    if (language) {
      formData.append('language', language);
    }
    return this.request('/chat/asr', { method: 'POST', body: formData, signal });
  }

  async getAsrReadiness(): Promise<ApiResponse<AsrReadiness>> {
    return this.request('/chat/asr_readiness');
  }

  async getTtsReadiness(): Promise<ApiResponse<TtsReadiness>> {
    return this.request('/chat/tts_readiness');
  }

  /** 实时模式语音合成：返回音频 Blob（wav）。失败抛错，错误信息可直接展示。
   *  传 characterId 时使用该角色在"语音模型"区块配置的专属音色；
   *  传 emotion 时使用该角色情感组里对应情感的参考音频。 */
  async synthesizeSpeech(
    text: string,
    options?: { provider?: string; characterId?: string; emotion?: string },
  ): Promise<Blob> {
    const token = getAuthToken();
    const response = await fetch(buildApiUrl('/chat/tts'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Token ${token}` } : {}),
      },
      body: JSON.stringify({
        text,
        ...(options?.provider ? { provider: options.provider } : {}),
        ...(options?.characterId ? { character_id: options.characterId } : {}),
        ...(options?.emotion ? { emotion: options.emotion } : {}),
      }),
    });
    if (!response.ok) {
      let message = `TTS failed (${response.status})`;
      try {
        const data = await response.json();
        if (data?.error) message = data.error;
      } catch {
        // 非 JSON 错误体，保留默认信息
      }
      throw new Error(message);
    }
    return response.blob();
  }

  async sendMessage(data: SendMessageRequest): Promise<ApiResponse<{ ai_message: ApiMessage; chat_session_id?: string }>> {
    const attachments = data.attachments?.length
      ? data.attachments
      : data.attachment
        ? [data.attachment]
        : [];

    const requestData = attachments.length
      ? (() => {
          const formData = new FormData();
          formData.append('message', data.message);
          formData.append('character_id', data.character_id);
          if (data.chat_session_id) formData.append('chat_session_id', data.chat_session_id);
          if (data.start_conversation !== undefined) formData.append('start_conversation', String(data.start_conversation));
          if (data.origin) formData.append('origin', data.origin);
          attachments.forEach((attachment) => formData.append('attachments', attachment));
          return formData;
        })()
      : JSON.stringify({
          message: data.message,
          character_id: parseInt(data.character_id),
          chat_session_id: data.chat_session_id ? parseInt(data.chat_session_id) : undefined,
          start_conversation: data.start_conversation,
          origin: data.origin,
        });

    return this.request('/chat/send_message', {
      method: 'POST',
      body: requestData,
    });
  }

  async streamMessage(
    data: SendMessageRequest,
    handlers: {
      onEvent: (event: StreamMessageEvent) => void;
    },
    options?: { signal?: AbortSignal }
  ): Promise<ApiResponse<{ chat_session_id?: string }> & { aborted?: boolean }> {
    try {
      const token = getAuthToken();
      const attachments = data.attachments?.length
        ? data.attachments
        : data.attachment
          ? [data.attachment]
          : [];
      const hasAttachment = attachments.length > 0;
      const body = hasAttachment
        ? (() => {
            const formData = new FormData();
            formData.append('message', data.message);
            formData.append('character_id', data.character_id);
            if (data.chat_session_id) formData.append('chat_session_id', data.chat_session_id);
            if (data.start_conversation !== undefined) formData.append('start_conversation', String(data.start_conversation));
            if (data.origin) formData.append('origin', data.origin);
            attachments.forEach((attachment) => formData.append('attachments', attachment));
            return formData;
          })()
        : JSON.stringify({
            message: data.message,
            character_id: parseInt(data.character_id),
            chat_session_id: data.chat_session_id ? parseInt(data.chat_session_id) : undefined,
            start_conversation: data.start_conversation,
            origin: data.origin,
          });

      const response = await fetch(buildApiUrl('/chat/stream_message'), {
        method: 'POST',
        headers: {
          ...(hasAttachment ? {} : { 'Content-Type': 'application/json' }),
          ...(token ? { Authorization: `Token ${token}` } : {}),
        },
        body,
        signal: options?.signal,
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(errorText || 'Streaming request failed');
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error('Streaming response body is not available');
      }

      const decoder = new TextDecoder();
      let buffer = '';
      let chatSessionId: string | undefined;
      // 收到 done 即终止本轮读取：后端 done 后连接可能不立刻关闭，
      // 继续 reader.read() 会挂起，导致 isLoading 无法复位（停止按钮/“正在输入”卡死）。
      let turnFinished = false;

      const handleEvent = (event: StreamMessageEvent) => {
        if (event.type === 'session') {
          chatSessionId = String(event.chat_session_id);
        }
        handlers.onEvent(event);
        if (event.type === 'done' || event.type === 'error') {
          turnFinished = true;
        }
      };

      while (!turnFinished) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) {
            continue;
          }
          handleEvent(JSON.parse(trimmed) as StreamMessageEvent);
          if (turnFinished) {
            break;
          }
        }

        // 尾部没有换行符的完整事件（尤其 done）也必须立即处理，
        // 否则会被误判为"不完整行"留在 buffer，循环继续 read() 挂起。
        if (!turnFinished && buffer.trim()) {
          try {
            handleEvent(JSON.parse(buffer.trim()) as StreamMessageEvent);
            buffer = '';
          } catch {
            // 不完整 JSON，等待后续数据块补齐。
          }
        }
      }

      return { data: { chat_session_id: chatSessionId } };
    } catch (error) {
      if (options?.signal?.aborted) {
        // Deliberate stop (natural-chat spec §3.3): not an error. Whatever
        // content already streamed stays on screen via the caller.
        return { data: {}, aborted: true };
      }
      console.error('Streaming request failed:', error);
      return { error: error instanceof Error ? error.message : 'Unknown error' };
    }
  }

  async login(username: string, password: string): Promise<ApiResponse<{ token: string; user_id: number; username: string }>> {
    return this.request('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
  }

  async register(username: string, password: string, email?: string): Promise<ApiResponse<{ token: string; user_id: number; username: string }>> {
    return this.request('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username, password, email }),
    });
  }

  async logout(): Promise<ApiResponse<{ message: string }>> {
    return this.request('/auth/logout', {
      method: 'POST',
    });
  }

  async uploadImage(file: File): Promise<ApiResponse<{ uri: string; name: string }>> {
    const formData = new FormData();
    formData.append('file', file);

    try {
      const token = getAuthToken();
      const headers: Record<string, string> = {};
      if (token) {
        headers['Authorization'] = `Token ${token}`;
      }

      const response = await fetch(buildApiUrl('/upload'), {
        method: 'POST',
        headers,
        body: formData,
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
      }

      const data = await response.json();
      return { data: { uri: data.url || data.uri, name: file.name } };
    } catch (error) {
      console.error('API image upload failed:', error);
      return { error: error instanceof Error ? error.message : 'Unknown error' };
    }
  }

  async generateAIResponse(messageId: string, characterId: string): Promise<ApiResponse<ApiMessage>> {
    return this.request('/chat/generate_ai_response', {
      method: 'POST',
      body: JSON.stringify({ message_id: messageId, character_id: characterId }),
    });
  }

  async getModelConfigs(): Promise<ApiResponse<ModelConfig[]>> {
    const response = await this.request<ApiModelConfig[]>('/model-configs');
    if (response.data) {
      return { data: response.data.map(normalizeModelConfig) };
    }
    return { data: undefined };
  }

  async getUserProfile(): Promise<ApiResponse<UserProfile>> {
    const response = await this.request<ApiUserProfile>('/user-profile/me');
    if (response.data) {
      return { data: normalizeUserProfile(response.data) };
    }
    return { data: undefined };
  }

  async updateUserProfile(data: UpdateUserProfileRequest): Promise<ApiResponse<UserProfile>> {
    const response = await this.request<ApiUserProfile>('/user-profile/me', {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
    if (response.data) {
      return { data: normalizeUserProfile(response.data) };
    }
    return { data: undefined };
  }

  async detectLocation(lang?: string): Promise<ApiResponse<DetectedLocation>> {
    const query = lang ? `?lang=${encodeURIComponent(lang)}` : '';
    return this.request<DetectedLocation>(`/user-profile/detect-location${query}`);
  }

  async getModelConfig(id: string): Promise<ApiResponse<ModelConfig>> {
    const response = await this.request<ApiModelConfig>(`/model-configs/${id}`);
    if (response.data) {
      return { data: normalizeModelConfig(response.data) };
    }
    return { data: undefined };
  }

  async createModelConfig(data: CreateModelConfigRequest): Promise<ApiResponse<ModelConfig>> {
    const response = await this.request<ApiModelConfig>('/model-configs', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    if (response.data) {
      return { data: normalizeModelConfig(response.data) };
    }
    return { data: undefined };
  }

  async updateModelConfig(id: string, data: Partial<CreateModelConfigRequest>): Promise<ApiResponse<ModelConfig>> {
    const response = await this.request<ApiModelConfig>(`/model-configs/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
    if (response.data) {
      return { data: normalizeModelConfig(response.data) };
    }
    return { data: undefined };
  }

  async deleteModelConfig(id: string): Promise<ApiResponse<void>> {
    return this.request(`/model-configs/${id}`, {
      method: 'DELETE',
    });
  }

  async getModelRoles(): Promise<ApiResponse<ModelRoleAssignments>> {
    const response = await this.request<Record<string, ApiModelConfig | null>>('/model-roles/');
    if (response.data) {
      const roles = { text: null, image: null, audio: null, video: null } as ModelRoleAssignments;
      (Object.keys(roles) as ModelRoleKey[]).forEach((role) => {
        const value = response.data?.[role];
        roles[role] = value ? normalizeModelConfig(value) : null;
      });
      return { data: roles };
    }
    return { data: undefined };
  }

  async updateModelRoles(
    assignments: Partial<Record<ModelRoleKey, string | null>>
  ): Promise<ApiResponse<ModelRoleAssignments>> {
    const response = await this.request<Record<string, ApiModelConfig | null>>('/model-roles/', {
      method: 'PUT',
      body: JSON.stringify(assignments),
    });
    if (response.data) {
      const roles = { text: null, image: null, audio: null, video: null } as ModelRoleAssignments;
      (Object.keys(roles) as ModelRoleKey[]).forEach((role) => {
        const value = response.data?.[role];
        roles[role] = value ? normalizeModelConfig(value) : null;
      });
      return { data: roles };
    }
    return { data: undefined };
  }

  async probeProviderModels(params: {
    provider: ModelProvider;
    baseUrl?: string;
    apiKey?: string;
  }): Promise<ApiResponse<{ models: string[] }>> {
    return this.request<{ models: string[] }>('/model-catalog/probe/', {
      method: 'POST',
      body: JSON.stringify({
        provider: params.provider,
        base_url: params.baseUrl || '',
        api_key: params.apiKey || '',
      }),
    });
  }

  async listSoulFiles(characterId: string, pathPrefix = '', recursive = true): Promise<ApiResponse<MemoryExplorerEntry[]>> {
    const query = new URLSearchParams();
    if (pathPrefix) {
      query.set('path_prefix', pathPrefix);
    }
    query.set('recursive', String(recursive));
    query.set('max_entries', '200');
    const response = await this.request<ApiMemoryExplorerListResponse>(`/characters/${characterId}/soul_files?${query.toString()}`);
    if (response.data) {
      return { data: (response.data.entries || []).map(normalizeMemoryExplorerEntry) };
    }
    return { data: undefined };
  }

  async getWebSearchConfig(): Promise<ApiResponse<WebSearchConfig>> {
    const response = await this.request<ApiWebSearchConfig>('/web-search-config/me');
    if (response.data) {
      return { data: normalizeWebSearchConfig(response.data) };
    }
    return { data: undefined };
  }

  async updateWebSearchConfig(data: UpdateWebSearchConfigRequest): Promise<ApiResponse<WebSearchConfig>> {
    const response = await this.request<ApiWebSearchConfig>('/web-search-config/me', {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
    if (response.data) {
      return { data: normalizeWebSearchConfig(response.data) };
    }
    return { data: undefined };
  }

  async testWebSearchConfig(query: string): Promise<ApiResponse<WebSearchTestResult>> {
    const response = await this.request<ApiMessage['research_payload']>('/web-search-config/test', {
      method: 'POST',
      body: JSON.stringify({ query }),
    });
    if (response.data) {
      return { data: normalizeResearchPayload(response.data) || { query, provider: '', items: [], error: '' } };
    }
    return { data: undefined };
  }

  // ------------------------------------------------------------------
  // 语音设置：用户级引擎配置 + 音色库（角色经 tts_config.voice_model_id 引用）
  // ------------------------------------------------------------------

  async getTtsSettings(): Promise<ApiResponse<TtsServiceSettings>> {
    const response = await this.request<ApiTtsServiceSettings>('/tts-settings/me');
    if (response.data) {
      return { data: normalizeTtsServiceSettings(response.data) };
    }
    return { data: undefined };
  }

  async updateTtsSettings(data: Partial<TtsServiceSettings>): Promise<ApiResponse<TtsServiceSettings>> {
    const response = await this.request<ApiTtsServiceSettings>('/tts-settings/me', {
      method: 'PATCH',
      body: JSON.stringify({
        default_provider: data.defaultProvider,
        genie_url: data.genieUrl,
        gptsovits_url: data.gptsovitsUrl,
        indextts_url: data.indexttsUrl,
      }),
    });
    if (response.data) {
      return { data: normalizeTtsServiceSettings(response.data) };
    }
    return { data: undefined };
  }

  async testTtsEngine(engine: TtsEngine): Promise<ApiResponse<TtsEngineTestResult>> {
    return this.request<TtsEngineTestResult>('/tts-settings/test', {
      method: 'POST',
      body: JSON.stringify({ engine }),
    });
  }

  async listTtsVoiceModels(): Promise<ApiResponse<TtsVoiceModel[]>> {
    const response = await this.request<ApiTtsVoiceModel[]>('/tts-voice-models');
    if (response.data) {
      return { data: response.data.map(normalizeTtsVoiceModel) };
    }
    return { data: undefined };
  }

  async createTtsVoiceModel(
    data: Omit<TtsVoiceModel, 'id' | 'conversionStatus' | 'conversionError' | 'createdAt' | 'updatedAt'>,
  ): Promise<ApiResponse<TtsVoiceModel>> {
    const response = await this.request<ApiTtsVoiceModel>('/tts-voice-models', {
      method: 'POST',
      body: JSON.stringify({
        name: data.name,
        engine: data.engine,
        model_version: data.modelVersion,
        language: data.language,
        voice_name: data.voiceName,
        onnx_model_dir: data.onnxModelDir,
        ref_audio_path: data.refAudioPath,
        ref_audio_text: data.refAudioText,
        ref_audio_language: data.refAudioLanguage,
        emotions: data.emotions.map((emotion) => ({
          name: emotion.name,
          ref_audio_path: emotion.refAudioPath,
          ref_audio_text: emotion.refAudioText,
          ref_audio_language: emotion.refAudioLanguage,
        })),
      }),
    });
    if (response.data) {
      return { data: normalizeTtsVoiceModel(response.data) };
    }
    return { data: undefined };
  }

  async updateTtsVoiceModel(id: number, data: Partial<TtsVoiceModel>): Promise<ApiResponse<TtsVoiceModel>> {
    const response = await this.request<ApiTtsVoiceModel>(`/tts-voice-models/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({
        name: data.name,
        engine: data.engine,
        model_version: data.modelVersion,
        language: data.language,
        voice_name: data.voiceName,
        onnx_model_dir: data.onnxModelDir,
        ref_audio_path: data.refAudioPath,
        ref_audio_text: data.refAudioText,
        ref_audio_language: data.refAudioLanguage,
        ...(data.emotions
          ? {
              emotions: data.emotions.map((emotion) => ({
                name: emotion.name,
                ref_audio_path: emotion.refAudioPath,
                ref_audio_text: emotion.refAudioText,
                ref_audio_language: emotion.refAudioLanguage,
              })),
            }
          : {}),
      }),
    });
    if (response.data) {
      return { data: normalizeTtsVoiceModel(response.data) };
    }
    return { data: undefined };
  }

  async deleteTtsVoiceModel(id: number): Promise<ApiResponse<void>> {
    return this.request(`/tts-voice-models/${id}`, { method: 'DELETE' });
  }

  async uploadTtsRefAudio(file: File): Promise<ApiResponse<{ path: string; name: string }>> {
    const formData = new FormData();
    formData.append('file', file);
    const response = await this.request<{ path: string; name: string }>('/tts-voice-models/upload_ref_audio/', {
      method: 'POST',
      body: formData,
    });
    if (response.data) {
      return { data: response.data };
    }
    return { data: undefined };
  }

  async uploadTtsOnnxDir(
    files: File[],
    relativePaths: string[],
    name: string,
  ): Promise<ApiResponse<{ path: string; name: string }>> {
    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));
    relativePaths.forEach((rel) => formData.append('relative_paths[]', rel));
    if (name) {
      formData.append('name', name);
    }
    const response = await this.request<{ path: string; name: string }>('/tts-voice-models/upload_onnx_dir/', {
      method: 'POST',
      body: formData,
    });
    if (response.data) {
      return { data: response.data };
    }
    return { data: undefined };
  }

  async uploadConvertVoiceModel(data: UploadConvertRequest): Promise<ApiResponse<TtsVoiceModel>> {
    const formData = new FormData();
    formData.append('ckpt', data.ckpt);
    formData.append('pth', data.pth);
    if (data.refAudio) {
      formData.append('ref_audio', data.refAudio);
    }
    if (data.name) {
      formData.append('name', data.name);
    }
    if (data.language) {
      formData.append('language', data.language);
    }
    if (data.modelVersion) {
      formData.append('model_version', data.modelVersion);
    }
    if (data.refAudioText) {
      formData.append('ref_audio_text', data.refAudioText);
    }
    const response = await this.request<ApiTtsVoiceModel>('/tts-voice-models/upload_convert', {
      method: 'POST',
      body: formData,
    });
    if (response.data) {
      return { data: normalizeTtsVoiceModel(response.data) };
    }
    return { data: undefined };
  }

  async pollTtsConversionStatus(voiceModelId: number): Promise<ApiResponse<TtsVoiceModel>> {
    const response = await this.request<ApiTtsVoiceModel>(`/tts-voice-models/${voiceModelId}/conversion_status`);
    if (response.data) {
      return { data: normalizeTtsVoiceModel(response.data) };
    }
    return { data: undefined };
  }

  // 音频输出：已合成语音的历史记录（浏览/删除）。
  async listTtsAudioOutputs(characterId?: string | number): Promise<ApiResponse<TtsAudioOutput[]>> {
    const query = characterId != null && String(characterId) !== ''
      ? `?character_id=${encodeURIComponent(String(characterId))}`
      : '';
    const response = await this.request<ApiTtsAudioOutput[]>(`/tts-audio-outputs${query}`);
    if (response.data) {
      return { data: (response.data || []).map(normalizeTtsAudioOutput) };
    }
    return { data: undefined };
  }

  async deleteTtsAudioOutput(id: number): Promise<ApiResponse<void>> {
    return this.request(`/tts-audio-outputs/${id}`, { method: 'DELETE' });
  }

  async readSoulFile(characterId: string, path: string, offset = 0): Promise<ApiResponse<MemoryExplorerFile>> {
    const query = new URLSearchParams({ path, max_chars: '12000' });
    if (offset > 0) {
      query.set('offset', String(offset));
    }
    const response = await this.request<ApiMemoryExplorerFile>(`/characters/${characterId}/soul_file?${query.toString()}`);
    if (response.data) {
      return { data: normalizeMemoryExplorerFile(response.data) };
    }
    return { data: undefined };
  }

  async uploadKnowledgeAssets(
    characterId: string,
    files: File[],
    relativePaths?: string[],
  ): Promise<ApiResponse<KnowledgeAsset[]>> {
    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));
    if (relativePaths && relativePaths.length === files.length) {
      formData.append('relative_paths', JSON.stringify(relativePaths));
    }

    const response = await this.request<ApiKnowledgeAssetUploadResponse>(`/characters/${characterId}/knowledge_assets`, {
      method: 'POST',
      body: formData,
    });
    if (response.data) {
      return { data: (response.data.assets || []).map(normalizeKnowledgeAsset) };
    }
    return { data: undefined };
  }

  async listKnowledgeAssets(characterId: string): Promise<ApiResponse<KnowledgeAsset[]>> {
    const response = await this.request<{ assets?: ApiKnowledgeAsset[] }>(`/characters/${characterId}/knowledge_assets`);
    if (response.data) {
      return { data: (response.data.assets || []).map(normalizeKnowledgeAsset) };
    }
    return { data: undefined };
  }

  async deleteKnowledgeAsset(characterId: string, assetId: string): Promise<ApiResponse<void>> {
    return this.request(`/characters/${characterId}/knowledge_assets/${assetId}`, {
      method: 'DELETE',
    });
  }

  // ---------------------------------------------------------------- memory

  async getCharacterMemory(characterId: string): Promise<ApiResponse<MemorySnapshot>> {
    const response = await this.request<{
      sections: Array<{ section: string; items: Array<{ short_id: string; section: string; description: string; description_history?: unknown[]; created_at: string | null; updated_at: string | null }> }>;
      wiki_markdown: string;
      count: number;
    }>(`/characters/${characterId}/memory`);
    if (!response.data) {
      return { data: undefined };
    }
    const sections = (response.data.sections || []).map((section) => ({
      section: section.section,
      items: (section.items || []).map((item) => ({
        shortId: item.short_id,
        section: item.section,
        description: item.description,
        descriptionHistory: (item.description_history || []) as MemoryEntry['descriptionHistory'],
        createdAt: item.created_at || '',
        updatedAt: item.updated_at || '',
      })),
    }));
    return {
      data: {
        sections,
        wikiMarkdown: response.data.wiki_markdown || '',
        count: response.data.count || 0,
      },
    };
  }

  async getMemoryNarrative(characterId: string): Promise<ApiResponse<MemoryNarrative>> {
    const response = await this.request<{
      narrative: string;
      truncated: boolean;
      count: number;
      last_updated: string | null;
    }>(`/characters/${characterId}/memory/narrative`);
    if (!response.data) {
      return { data: undefined };
    }
    return {
      data: {
        narrative: response.data.narrative || '',
        truncated: Boolean(response.data.truncated),
        count: response.data.count || 0,
        lastUpdated: response.data.last_updated,
      },
    };
  }

  async getWebSearchReadiness(characterId?: string): Promise<ApiResponse<{ enabled: boolean; configured: boolean }>> {
    const query = characterId ? `?character=${encodeURIComponent(characterId)}` : '';
    return this.request<{ enabled: boolean; configured: boolean }>(`/web-search-config/readiness${query}`);
  }

  async createMemoryEntry(characterId: string, section: string, description: string, reason?: string): Promise<ApiResponse<MemoryEntry>> {
    const response = await this.request<{
      short_id: string;
      section: string;
      description: string;
      description_history?: unknown[];
      created_at: string | null;
      updated_at: string | null;
    }>(`/characters/${characterId}/memory`, {
      method: 'POST',
      body: JSON.stringify({ section, description, reason: reason || '' }),
    });
    if (!response.data) {
      return { data: undefined };
    }
    return { data: _memoryItemFromApi(response.data) };
  }

  async updateMemoryEntry(characterId: string, shortId: string, description: string, section?: string, reason?: string): Promise<ApiResponse<MemoryEntry>> {
    const response = await this.request<{
      short_id: string;
      section: string;
      description: string;
      description_history?: unknown[];
      created_at: string | null;
      updated_at: string | null;
    }>(`/characters/${characterId}/memory/${shortId}`, {
      method: 'PATCH',
      body: JSON.stringify({ description, section, reason: reason || '' }),
    });
    if (!response.data) {
      return { data: undefined };
    }
    return { data: _memoryItemFromApi(response.data) };
  }

  async deleteMemoryEntry(characterId: string, shortId: string, reason?: string): Promise<ApiResponse<void>> {
    return this.request(`/characters/${characterId}/memory/${shortId}`, {
      method: 'DELETE',
      body: JSON.stringify({ reason: reason || '' }),
    });
  }

  async mergeMemoryEntries(characterId: string, id1: string, id2: string, content: string, section: string, reason?: string): Promise<ApiResponse<MemoryEntry>> {
    const response = await this.request<{
      short_id: string;
      section: string;
      description: string;
      description_history?: unknown[];
      created_at: string | null;
      updated_at: string | null;
    }>(`/characters/${characterId}/memory/merge`, {
      method: 'POST',
      body: JSON.stringify({ id1, id2, content, section, reason: reason || '' }),
    });
    if (!response.data) {
      return { data: undefined };
    }
    return { data: _memoryItemFromApi(response.data) };
  }

  async wipeCharacterMemory(characterId: string): Promise<ApiResponse<{ deleted: number }>> {
    return this.request(`/characters/${characterId}/memory`, {
      method: 'DELETE',
    });
  }

  async setSessionPrivateMode(sessionId: string, isPrivateMode: boolean): Promise<ApiResponse<ChatSession>> {
    const response = await this.request<ApiSession>(`/sessions/${sessionId}`, {
      method: 'PATCH',
      body: JSON.stringify({ is_private_mode: isPrivateMode }),
    });
    if (!response.data) {
      return { data: undefined };
    }
    return { data: normalizeSession(response.data) };
  }
}

function _memoryItemFromApi(api: {
  short_id: string;
  section: string;
  description: string;
  description_history?: unknown[];
  created_at: string | null;
  updated_at: string | null;
}): MemoryEntry {
  return {
    shortId: api.short_id,
    section: api.section,
    description: api.description,
    descriptionHistory: (api.description_history || []) as MemoryEntry['descriptionHistory'],
    createdAt: api.created_at || '',
    updatedAt: api.updated_at || '',
  };
}

export const apiService = new ApiService();

export type {
  ApiCharacter,
  ApiSession,
  ApiMessage,
  ApiModelConfig,
  ApiWebSearchConfig,
  CreateCharacterRequest,
  CreateSessionRequest,
  CreateModelConfigRequest,
  UpdateUserProfileRequest,
  UpdateWebSearchConfigRequest,
  SendMessageRequest,
  StreamMessageEvent,
};
