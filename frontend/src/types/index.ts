export interface Message {
  id: string;
  content: string;
  role: 'user' | 'assistant';
  timestamp: string; // Using ISO string instead of Date object for Redux serialization
}

export interface CharacterFile {
  id: string;
  original_filename: string;
  gemini_file_ref: string;
  uploaded_at: string;
}

export interface Character {
  id: string;
  name: string;
  description: string;
  personality: string;
  appearance: string;
  disabled: {
    name: boolean;
    description: boolean;
    personality: boolean;
    appearance: boolean;
  };
  background_files?: CharacterFile[]; // Make it optional for backward compatibility
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