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
  requirement: string;
  disabled: {
    name: boolean;
    description: boolean;
    personality: boolean;
    appearance: boolean;
    requirement?: boolean; // Make it optional for backward compatibility
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

export interface Requirements {
  languagePreference: {
    youShouldAlwaysSpeakAndThinkIn: string;
  };
  markDownRules: {
    allResponsesMustShow: string;
    toolUse: string;
  };
  toolUse: {
    youHaveAccessTo: string;
    toolUseFormatting: string;
    examples: string;
  };
  modes: {
    architect: string;
    code: string;
    ask: string;
    debug: string;
    orchestrator: string;
  };
  rules: {
    projectBaseDirectory: string;
    filePaths: string;
    youCannot: string;
    beforeUsingThe: string;
    whenDecidingIf: string;
    onceYouveCompleted: string;
    theUserMayProvide: string;
    languagePreference: string;
  };
  customInstructions: {
    languagePreference: string;
  };
}