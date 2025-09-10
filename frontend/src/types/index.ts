export interface Message {
  id: string;
  content: string;
  role: 'user' | 'assistant';
  timestamp: string; // Using ISO string instead of Date object for Redux serialization
  fileUri?: string; // Add fileUri field
  fileName?: string; // 新增：用于显示文件名
  filePreviewUrl?: string; // 新增：用于图片预览
}

export interface Character {
  id: string;
  name: string;
  description: string;
  personality: string;
  appearance: string;
  responseGuidelines: string; // 添加响应指南字段
  fileUrl?: string; // The file URL
  filePreviewUrl?: string; // For UI preview only
  disabled: {
    name: boolean;
    description: boolean;
    personality: boolean;
    appearance: boolean;
    responseGuidelines: boolean; // 添加响应指南的disabled开关
    file: boolean; // Add file disabled switch
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