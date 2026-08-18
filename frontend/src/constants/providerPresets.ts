import type { ModelProvider, ModelRoleKey } from '@/types';

/** 厂商预设目录：设置页自动填充 baseUrl，并给各角色槽位提供推荐模型提示。
 *  纯静态数据——新增厂商只需加一条，不涉及任何调用逻辑。
 */
export interface ProviderPreset {
  id: string;
  label: string;
  /** 该厂商走哪种 API 通道 */
  apiType: ModelProvider;
  /** 预填的 baseUrl（openai_compatible/anthropic 用；gemini 忽略） */
  defaultBaseUrl: string;
  /** 获取 API Key 的入口，方便用户直达 */
  keyUrl?: string;
  /** 各角色槽位的推荐模型提示（仅展示，不强制） */
  roleHints?: Partial<Record<ModelRoleKey, string>>;
}

export const PROVIDER_PRESETS: ProviderPreset[] = [
  {
    id: 'openai',
    label: 'OpenAI',
    apiType: 'openai_compatible',
    defaultBaseUrl: 'https://api.openai.com/v1',
    keyUrl: 'https://platform.openai.com/api-keys',
    roleHints: { text: 'gpt-4.1 / gpt-4o-mini', image: 'gpt-4o / gpt-4.1', video: 'gpt-4o' },
  },
  {
    id: 'anthropic',
    label: 'Anthropic (Claude)',
    apiType: 'anthropic',
    defaultBaseUrl: 'https://api.anthropic.com',
    keyUrl: 'https://console.anthropic.com/settings/keys',
    roleHints: { text: 'claude-sonnet-4-5 / claude-opus-4-1', image: 'claude-sonnet-4-5（仅图片）' },
  },
  {
    id: 'gemini',
    label: 'Google Gemini',
    apiType: 'gemini',
    defaultBaseUrl: '',
    keyUrl: 'https://aistudio.google.com/apikey',
    roleHints: { text: 'gemini-2.0-flash', image: 'gemini-2.0-flash', audio: 'gemini-2.0-flash', video: 'gemini-2.0-flash' },
  },
  {
    id: 'deepseek',
    label: 'DeepSeek',
    apiType: 'openai_compatible',
    defaultBaseUrl: 'https://api.deepseek.com/v1',
    keyUrl: 'https://platform.deepseek.com/api_keys',
    roleHints: { text: 'deepseek-chat / deepseek-reasoner' },
  },
  {
    id: 'dashscope',
    label: '阿里云百炼（通义 Qwen）',
    apiType: 'openai_compatible',
    defaultBaseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    keyUrl: 'https://bailian.console.aliyun.com/',
    roleHints: {
      text: 'qwen3-max / qwen-plus',
      image: 'qwen-vl-max / qwen3-vl-plus',
      audio: 'qwen3-omni / qwen2-audio',
      video: 'qwen-vl-max / qwen3-vl-plus',
    },
  },
  {
    id: 'zhipu',
    label: '智谱 GLM',
    apiType: 'openai_compatible',
    defaultBaseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    keyUrl: 'https://open.bigmodel.cn/usercenter/apikeys',
    roleHints: { text: 'glm-4.7', image: 'glm-4.6v', video: 'glm-4.6v' },
  },
  {
    id: 'moonshot',
    label: '月之暗面 Kimi',
    apiType: 'openai_compatible',
    defaultBaseUrl: 'https://api.moonshot.cn/v1',
    keyUrl: 'https://platform.moonshot.cn/console/api-keys',
    roleHints: { text: 'kimi-k2.5' },
  },
  {
    id: 'minimax',
    label: 'MiniMax',
    apiType: 'openai_compatible',
    defaultBaseUrl: 'https://api.minimaxi.com/v1',
    keyUrl: 'https://platform.minimaxi.com/user-center/basic-information/interface-key',
    roleHints: { text: 'MiniMax-M2', image: 'MiniMax-M3（图片/视频）', video: 'MiniMax-M3' },
  },
  {
    id: 'openrouter',
    label: 'OpenRouter（聚合平台）',
    apiType: 'openai_compatible',
    defaultBaseUrl: 'https://openrouter.ai/api/v1',
    keyUrl: 'https://openrouter.ai/keys',
    roleHints: { text: '任意厂商模型均可', image: 'google/gemini-2.0-flash', audio: 'google/gemini-2.0-flash' },
  },
  {
    id: 'siliconflow',
    label: '硅基流动 SiliconFlow',
    apiType: 'openai_compatible',
    defaultBaseUrl: 'https://api.siliconflow.cn/v1',
    keyUrl: 'https://cloud.siliconflow.cn/account/ak',
    roleHints: { text: 'deepseek-ai/DeepSeek-V3', image: 'Qwen/Qwen2.5-VL-72B-Instruct' },
  },
  {
    id: 'groq',
    label: 'Groq',
    apiType: 'openai_compatible',
    defaultBaseUrl: 'https://api.groq.com/openai/v1',
    keyUrl: 'https://console.groq.com/keys',
  },
  {
    id: 'xai',
    label: 'xAI Grok',
    apiType: 'openai_compatible',
    defaultBaseUrl: 'https://api.x.ai/v1',
    keyUrl: 'https://console.x.ai',
  },
  {
    id: 'ollama',
    label: 'Ollama（本地）',
    apiType: 'openai_compatible',
    defaultBaseUrl: 'http://localhost:11434/v1',
    roleHints: { image: 'qwen2.5vl / llava（本地视觉模型）' },
  },
  {
    id: 'lmstudio',
    label: 'LM Studio（本地）',
    apiType: 'openai_compatible',
    defaultBaseUrl: 'http://localhost:1234/v1',
  },
  {
    id: 'custom',
    label: '自定义（任意 OpenAI 兼容）',
    apiType: 'openai_compatible',
    defaultBaseUrl: '',
  },
];

/** 根据 provider + baseUrl 反查预设（用于编辑已有配置时回显厂商）。 */
export function matchProviderPreset(provider: ModelProvider, baseUrl: string): ProviderPreset | null {
  const normalized = (baseUrl || '').trim().replace(/\/+$/, '');
  if (normalized) {
    const byUrl = PROVIDER_PRESETS.find(
      (preset) => preset.defaultBaseUrl && normalized === preset.defaultBaseUrl.replace(/\/+$/, '')
    );
    if (byUrl) return byUrl;
  }
  if (provider === 'gemini') return PROVIDER_PRESETS.find((preset) => preset.id === 'gemini') || null;
  if (provider === 'anthropic') return PROVIDER_PRESETS.find((preset) => preset.id === 'anthropic') || null;
  return null;
}
