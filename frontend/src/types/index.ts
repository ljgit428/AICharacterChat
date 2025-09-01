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