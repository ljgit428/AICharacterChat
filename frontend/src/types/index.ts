export interface ResearchItem {
  title: string;
  url: string;
  snippet: string;
  domain?: string;
  source?: string;
}

export interface ResearchPayload {
  query?: string;
  provider?: string;
  items: ResearchItem[];
  error?: string;
}

export interface MemoryExplorerEntry {
  path: string;
  entryType: 'file' | 'directory';
  layer: 'schema' | 'wiki' | 'raw' | string;
  title: string;
  kind: string;
  readHint: string;
  isLocked: boolean;
  canUserEdit: boolean;
  canAutoUpdate: boolean;
  updatedAt: string;
  manageable?: boolean;
  assetId?: string;
  previewKind?: 'text' | 'image' | 'binary' | 'directory' | string;
  childCount?: number;
  sizeHint?: number;
}

export interface MemoryExplorerFile {
  path: string;
  layer: 'schema' | 'wiki' | 'raw' | string;
  title: string;
  kind: string;
  readHint: string;
  content: string;
  truncated?: boolean;
  manageable?: boolean;
  assetId?: string;
  previewKind?: 'text' | 'image' | 'binary' | string;
  fileUrl?: string;
  mimeType?: string;
  error?: string;
  offset?: number;
  nextOffset?: number;
  totalChars?: number;
  hasMore?: boolean;
}

export interface KnowledgeAsset {
  id: string;
  fileUrl?: string;
  fileName: string;
  fileType: string;
  fileMimeType?: string;
  createdAt: string;
  updatedAt: string;
}

export interface ToolCallInfo {
  tool: string;
  arguments?: Record<string, unknown>;
}

export interface TokenUsage {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  cachedTokens: number;
}

export interface Message {
  id: string;
  content: string;
  role: 'user' | 'assistant';
  timestamp: string;
  senderId?: string;
  senderName?: string;
  senderAvatarUrl?: string;
  senderType?: 'user' | 'character' | 'system';
  researchPayload?: ResearchPayload | null;
  thinking?: string;
  /** 双段思维链协议中模型的原生推理块（RAW_REASONING），角色心声在 thinking。 */
  rawReasoning?: string;
  toolCalls?: ToolCallInfo[];
  /** 后端返回的情感分段（【情感】标记解析产物），供逐句 TTS 继承语气。 */
  ttsSegments?: Array<{ emotion?: string; text?: string | null }>;
  tokenUsage?: TokenUsage | null;
  attachments?: MessageAttachment[];
  fileUri?: string;
  fileName?: string;
  filePreviewUrl?: string;
  fileType?: string;
  fileMimeType?: string;
}

export interface MessageAttachment {
  fileUri?: string;
  fileName?: string;
  filePreviewUrl?: string;
  fileType?: string;
  fileMimeType?: string;
}

export interface Character {
  id: string;
  name: string;
  description: string;
  userAddress: string;
  scenario: string;
  exampleDialogue: string;
  personality: string;
  appearance: string;
  responseGuidelines: string;
  avatarUrl?: string;
  /** 角色级联网搜索三态开关：null/undefined = 跟随用户全局设置 */
  enableWebSearch?: boolean | null;
  /** 角色级语音模型配置（引擎/模型版本/音色名/ONNX 目录/参考音频/情感组），空 = 跟随全局 */
  ttsConfig?: Record<string, unknown> | null;
  fileUrl?: string;
  filePreviewUrl?: string;
  affiliation: string;
  disabled: {
    name: boolean;
    description: boolean;
    personality: boolean;
    appearance: boolean;
    responseGuidelines: boolean;
    file: boolean;
  };
}

export type ModelProvider = 'gemini' | 'openai_compatible' | 'anthropic';
export type WebSearchProvider = 'tavily';

/** 模型角色槽位：text 必填，image/audio/video 可空（空=该类附件不做 AI 解读） */
export type ModelRoleKey = 'text' | 'image' | 'audio' | 'video';

export interface ModelConfig {
  id: string;
  name: string;
  provider: ModelProvider;
  modelName: string;
  apiKey: string;
  baseUrl?: string;
  contextWindow?: number | null;
  createdAt: string;
  updatedAt: string;
}

export type ModelRoleAssignments = Record<ModelRoleKey, ModelConfig | null>;

export type TtsEngine = 'genie' | 'gptsovits' | 'indextts';

export type TtsConversionStatus = '' | 'pending' | 'converting' | 'ready' | 'failed';

// 设置页「语音设置」里登记的音色；角色通过 tts_config.voice_model_id 引用。
export interface TtsVoiceEmotionConfig {
  name: string;
  refAudioPath: string;
  refAudioText: string;
  refAudioLanguage: string;
}

export interface TtsVoiceModel {
  id: number;
  name: string;
  engine: TtsEngine;
  modelVersion: string;
  language: string;
  voiceName: string;
  onnxModelDir: string;
  refAudioPath: string;
  refAudioText: string;
  refAudioLanguage: string;
  emotions: TtsVoiceEmotionConfig[];
  conversionStatus: TtsConversionStatus;
  conversionError: string;
  createdAt?: string;
  updatedAt?: string;
}

// 用户级 TTS 引擎服务设置；空字段 = 跟随环境变量默认。
export interface TtsServiceSettings {
  defaultProvider: TtsEngine | '';
  genieUrl: string;
  gptsovitsUrl: string;
  indexttsUrl: string;
}

export interface TtsEngineTestResult {
  ok: boolean;
  hint: string;
}

// 一条已保存的语音输出（「音频输出」浏览页）：每次 /chat/tts 合成落盘的记录。
export interface TtsAudioOutput {
  id: number;
  characterId?: number | null;
  characterName?: string;
  text: string;
  emotion: string;
  provider: string;
  audioUrl: string;
  contentType: string;
  processingMs: number | null;
  firstByteMs: number | null;
  createdAt: string;
}

export interface UploadConvertRequest {
  ckpt: File;
  pth: File;
  refAudio?: File;
  name?: string;
  language?: string;
  modelVersion?: string;
  refAudioText?: string;
}

export interface WebSearchConfig {
  id?: string;
  provider: WebSearchProvider;
  apiKey: string;
  maxResults: number;
  createdAt?: string;
  updatedAt?: string;
}

export interface WebSearchTestResult {
  query?: string;
  provider?: string;
  items: ResearchItem[];
  error?: string;
}

export type LocationPrecision = 'region' | 'city' | 'exact';
export type ReplyLengthPreference = 'short' | 'medium' | 'long';
export type PreferenceLevel = 'low' | 'normal' | 'high';

export interface UserProfile {
  id: string;
  avatarUrl?: string;
  preferredName: string;
  pronouns: string;
  bio: string;
  defaultEnableWebSearch: boolean;
  timezone: string;
  interfaceLanguage: string;
  shareLocalTime: boolean;
  shareLocation: boolean;
  locationPrecision: LocationPrecision;
  locationLabel: string;
  locationLatitude: number | null;
  locationLongitude: number | null;
  shareWeather: boolean;
  autoSyncTimezone: boolean;
  autoSyncLocation: boolean;
  preferredRelationshipStyle: string;
  preferredReplyLength: ReplyLengthPreference;
  preferredProactivity: PreferenceLevel;
  preferredEmotionalIntensity: PreferenceLevel;
  allowLongTermMemory: boolean;
  allowPreferenceInference: boolean;
  allowResearchProfileUpdates: boolean;
  blockedTopics: string;
  createdAt: string;
  updatedAt: string;
}

export interface ChatSession {
  id: string;
  title: string;
  lastResponseLatencyMs?: number | null;
  isPrivateMode?: boolean;
  origin?: string;
  character: Character;
  createdAt: string;
  updatedAt: string;
}

export interface MemoryHistoryEntry {
  old_desc: string;
  new_desc: string;
  old_section?: string;
  new_section?: string;
  old_time?: string;
  new_time?: string;
  reason?: string;
  merged_from?: string;
}

export interface MemoryEntry {
  shortId: string;
  section: string;
  description: string;
  descriptionHistory?: MemoryHistoryEntry[];
  createdAt: string;
  updatedAt: string;
}

export interface MemorySectionGroup {
  section: string;
  items: MemoryEntry[];
}

export interface MemorySnapshot {
  sections: MemorySectionGroup[];
  wikiMarkdown: string;
  count: number;
}

export interface MemoryNarrative {
  narrative: string;
  truncated: boolean;
  count: number;
  lastUpdated: string | null;
}

export interface ChatState {
  messages: Message[];
  /** 会话消息缓存：sessionId → 上次加载的消息。切换回会话时第一帧直接渲染，无加载占位。 */
  messagesBySession: Record<string, Message[]>;
  character: Character | null;
  chatSession: ChatSession | null;
  isLoading: boolean;
  error: string | null;
}

export interface RootState {
  chat: ChatState;
}
