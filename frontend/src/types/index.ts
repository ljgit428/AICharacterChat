export interface Message {
  id: string;
  content: string;
  role: 'user' | 'assistant';
  timestamp: string; // Using ISO string instead of Date object for Redux serialization
}

export interface Character {
  id: string;
  name: string;
  description: string;
  personality: string;
  appearance: string;
  responseGuidelines: string; // 添加响应指南字段
  disabled: {
    name: boolean;
    description: boolean;
    personality: boolean;
    appearance: boolean;
    responseGuidelines: boolean; // 添加响应指南的disabled开关
  };
}

export interface ChatState {
  messages: Message[];
  character: Character | null;
  isLoading: boolean;
  error: string | null;
}

export interface RootState {
  chat: ChatState;
}