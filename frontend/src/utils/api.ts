const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';
console.log('API_BASE_URL:', API_BASE_URL);

interface ApiResponse<T> {
  data?: T;
  error?: string;
}

// Import types from the types file
import { Character, Message } from '@/types';

interface ChatSession {
  id: string;
  character: Character;
  title: string;
  user: { id: string; username: string; email?: string }; // Basic user type
}

interface ChatResponse {
  user_message: Message;
  ai_message?: Message;
  chat_session_id: string;
  status?: string;
}

interface AIResponse {
  success: boolean;
  message_id?: number;
  content?: string;
  error?: string;
}

// Token management
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
}

// This interface is no longer needed since we use FormData now
// interface CreateCharacterRequest {
//   name: string;
//   description: string;
//   personality: string;
//   appearance: string;
// }

class ApiService {
  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<ApiResponse<T>> {
    try {
      const token = getAuthToken();
      const headers: Record<string, string> = {}; // 初始化为空
      
      // 如果 body 不是 FormData，才设置 Content-Type
      if (!(options.body instanceof FormData)) {
        headers['Content-Type'] = 'application/json';
      }
      
      // Add any existing headers from options
      if (options.headers) {
        Object.entries(options.headers).forEach(([key, value]) => {
          if (typeof value === 'string') {
            headers[key] = value;
          }
        });
      }
      
      if (token) {
        headers['Authorization'] = `Token ${token}`;
      }
      
      console.log('API Request:', {
        url: `${API_BASE_URL}${endpoint}`,
        options: {
          ...options,
          headers,
        }
      });
      
      const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        headers,
        ...options,
      });

      console.log('API Response:', {
        status: response.status,
        statusText: response.statusText,
        headers: Object.fromEntries(response.headers.entries()),
        url: response.url
      });

      if (!response.ok) {
        const errorText = await response.text();
        console.error('API Response Error:', errorText);
        throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
      }

      const data = await response.json();
      console.log('API Response Data:', data);
      return { data };
    } catch (error) {
      console.error('API request failed:', error);
      return { error: error instanceof Error ? error.message : 'Unknown error' };
    }
  }

  // Character API
  async getCharacters(): Promise<ApiResponse<Character[]>> {
    return this.request('/characters/');
  }

  async createCharacter(character: FormData): Promise<ApiResponse<Character>> {
    return this.request('/characters/', {
      method: 'POST',
      body: character,
    });
  }

  async getCharacter(id: string): Promise<ApiResponse<Character>> {
    return this.request(`/characters/${id}/`);
  }

  async updateCharacter(id: string, character: FormData): Promise<ApiResponse<Character>> {
    return this.request(`/characters/${id}/`, {
      method: 'PUT',
      body: character,
    });
  }

  // Chat Session API
  async getChatSessions(characterId?: string): Promise<ApiResponse<ChatSession[]>> {
    const params = characterId ? `?character_id=${characterId}` : '';
    return this.request(`/sessions/${params}`);
  }

  async createChatSession(characterId: string, title?: string): Promise<ApiResponse<ChatSession>> {
    return this.request('/sessions/', {
      method: 'POST',
      body: JSON.stringify({ character: characterId, title }),
    });
  }

  async getChatSession(id: string): Promise<ApiResponse<ChatSession>> {
    return this.request(`/sessions/${id}/`);
  }

  // Message API
  async getMessages(chatSessionId: string): Promise<ApiResponse<Message[]>> {
    return this.request(`/messages/?chat_session_id=${chatSessionId}`);
  }

  async sendMessage(data: SendMessageRequest): Promise<ApiResponse<ChatResponse>> {
    // Convert character_id to number for the backend
    const requestData = {
      ...data,
      character_id: parseInt(data.character_id)
    };
    return this.request('/chat/send_message/', {
      method: 'POST',
      body: JSON.stringify(requestData),
    });
  }

  // Authentication methods
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

  // Utility methods
  async generateAIResponse(messageId: string, characterId: string): Promise<ApiResponse<AIResponse>> {
    return this.request('/chat/generate_ai_response', {
      method: 'POST',
      body: JSON.stringify({ message_id: messageId, character_id: characterId }),
    });
  }
}

export const apiService = new ApiService();