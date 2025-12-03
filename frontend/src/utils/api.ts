const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';


interface ApiResponse<T> {
  data?: T;
  error?: string;
}

import { Character, ChatSession } from '@/types';

interface ApiCharacter {
  id: number;
  name: string;
  description: string;
  personality: string;
  appearance: string;
  response_guidelines: string;
  avatar_url: string;
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
  user_persona: string;
  world_time?: string;
  enable_web_search?: boolean;
  output_language?: string;
  additional_context?: string;
  created_at: string;
  updated_at: string;
}

interface ApiMessage {
  id: string;
  content: string;
  role: 'user' | 'assistant';
  timestamp: string;
  chat_session?: string;
  file_uri?: string;
}

function normalizeCharacter(apiData: ApiCharacter): Character {
  const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL?.replace('/api', '') || 'http://localhost:8000';

  return {
    id: String(apiData.id),
    name: apiData.name,
    description: apiData.description,
    personality: apiData.personality,
    appearance: apiData.appearance,
    affiliation: apiData.affiliation,
    responseGuidelines: apiData.response_guidelines,
    avatarUrl: apiData.avatar_url || undefined,
    fileUrl: apiData.file ? (apiData.file.startsWith('http') ? apiData.file : `${apiBaseUrl}${apiData.file}`) : undefined,
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

function normalizeSession(apiData: ApiSession, characterData?: ApiCharacter): ChatSession {
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
    userPersona: apiData.user_persona,
    worldTime: apiData.world_time,
    enableWebSearch: apiData.enable_web_search,
    outputLanguage: apiData.output_language,
    additionalContext: apiData.additional_context,
    character,
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
  file_uri?: string;
  world_time?: string;
  user_persona?: string;
  enable_web_search?: boolean;
  output_language?: string;
  additional_context?: string;
}

interface CreateCharacterRequest {
  name: string;
  description: string;
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
  user_persona?: string;
  world_time?: string;
  enable_web_search?: boolean;
  output_language?: string;
  additional_context?: string;
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

      const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        headers,
        ...options,
      });

      if (response.status === 204) {
        return { data: undefined };
      }

      const data = await response.json();

      return { data };
    } catch (error) {
      console.error('API request failed:', error);
      return { error: error instanceof Error ? error.message : 'Unknown error' };
    }
  }

  async getCharacters(): Promise<ApiResponse<Character[]>> {
    const response = await this.request<ApiCharacter[]>('/characters/');
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

    const response = await this.request<ApiCharacter>('/characters/', { method: 'POST', body: formData });
    if (response.data) {
      return { data: normalizeCharacter(response.data) };
    }
    return { data: undefined };
  }

  async getCharacter(id: string): Promise<ApiResponse<Character>> {
    const response = await this.request<ApiCharacter>(`/characters/${id}/`);
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

    const response = await this.request<ApiCharacter>(`/characters/${id}/`, { method: 'PATCH', body: formData });
    if (response.data) {
      return { data: normalizeCharacter(response.data) };
    }
    return { data: undefined };
  }

  async getChatSessions(characterId?: string): Promise<ApiResponse<ChatSession[]>> {
    const params = characterId ? `?character_id=${characterId}` : '';
    const response = await this.request<ApiSession[]>(`/sessions/${params}`);

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

    const response = await this.request<ApiSession>('/sessions/', {
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
    const response = await this.request<ApiSession>(`/sessions/${id}/`);

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
      user_persona: data.userPersona,
      world_time: data.worldTime,
      enable_web_search: data.enableWebSearch,
      output_language: data.outputLanguage,
      additional_context: data.additionalContext,
    };

    if (data.character) {
      backendData.character = data.character.id;
    }

    const response = await this.request<ApiSession>(`/sessions/${id}/`, {
      method: 'PATCH',
      body: JSON.stringify(backendData),
    });

    if (response.data) {
      return { data: normalizeSession(response.data) };
    }
    return { data: undefined };
  }

  async deleteChatSession(id: string): Promise<ApiResponse<void>> {
    return this.request(`/sessions/${id}/`, {
      method: 'DELETE',
    });
  }

  async getMessages(chatSessionId: string): Promise<ApiResponse<ApiMessage[]>> {
    return this.request(`/messages/?chat_session_id=${chatSessionId}`);
  }

  async sendMessage(data: SendMessageRequest): Promise<ApiResponse<{ ai_message: ApiMessage; chat_session_id?: string }>> {
    const requestData = {
      message: data.message,
      character_id: parseInt(data.character_id),
      chat_session_id: data.chat_session_id ? parseInt(data.chat_session_id) : undefined,
      file_uri: data.file_uri,
      world_time: data.world_time,
      user_persona: data.user_persona,
      enable_web_search: data.enable_web_search,
      output_language: data.output_language,
      additional_context: data.additional_context
    };
    return this.request('/chat/send_message/', {
      method: 'POST',
      body: JSON.stringify(requestData),
    });
  }

  async login(username: string, password: string): Promise<ApiResponse<{ token: string; user_id: number; username: string }>> {
    return this.request('/auth/login/', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
  }

  async register(username: string, password: string, email?: string): Promise<ApiResponse<{ token: string; user_id: number; username: string }>> {
    return this.request('/auth/register/', {
      method: 'POST',
      body: JSON.stringify({ username, password, email }),
    });
  }

  async logout(): Promise<ApiResponse<{ message: string }>> {
    return this.request('/auth/logout/', {
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

      const response = await fetch(`${API_BASE_URL}/files/upload/`, {
        method: 'POST',
        headers,
        body: formData,
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
      }

      const data = await response.json();
      return { data };
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
}

export const apiService = new ApiService();

export type { ApiCharacter, ApiSession, ApiMessage, CreateCharacterRequest, CreateSessionRequest, SendMessageRequest };