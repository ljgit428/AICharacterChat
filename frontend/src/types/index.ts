export interface Message {
  id: string;
  content: string;
  role: 'user' | 'assistant';
  timestamp: string;
  fileUri?: string;
  fileName?: string;
  filePreviewUrl?: string;
  fileType?: string;
}

export interface Character {
  id: string;
  name: string;
  description: string;
  personality: string;
  appearance: string;
  responseGuidelines: string;
  avatarUrl?: string;
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

export interface ChatSession {
  id: string;
  title: string;
  worldTime?: string;
  userPersona?: string;
  enableWebSearch?: boolean;
  outputLanguage?: string;
  additionalContext?: string;
  character: Character;
  createdAt: string;
  updatedAt: string;
}

export interface ChatState {
  messages: Message[];
  character: Character | null;
  chatSession: ChatSession | null;
  isLoading: boolean;
  error: string | null;
}

export interface RootState {
  chat: ChatState;
}