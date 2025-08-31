const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';

interface ApiResponse<T> {
  data?: T;
  error?: string;
}

interface SendMessageRequest {
  message: string;
  character_id: string;
  chat_session_id?: string;
}

interface CreateCharacterRequest {
  name: string;
  description: string;
  personality: string;
  appearance: string;
}

class ApiService {
  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<ApiResponse<T>> {
    try {
      const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        headers: {
          'Content-Type': 'application/json',
          ...options.headers,
        },
        ...options,
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      return { data };
    } catch (error) {
      console.error('API request failed:', error);
      return { error: error instanceof Error ? error.message : 'Unknown error' };
    }
  }

  // Character API
  async getCharacters(): Promise<ApiResponse<any[]>> {
    return this.request('/characters');
  }

  async createCharacter(character: CreateCharacterRequest): Promise<ApiResponse<any>> {
    return this.request('/characters', {
      method: 'POST',
      body: JSON.stringify(character),
    });
  }

  async getCharacter(id: string): Promise<ApiResponse<any>> {
    return this.request(`/characters/${id}`);
  }

  async updateCharacter(id: string, character: CreateCharacterRequest): Promise<ApiResponse<any>> {
    return this.request(`/characters/${id}`, {
      method: 'PUT',
      body: JSON.stringify(character),
    });
  }

  // Chat Session API
  async getChatSessions(characterId?: string): Promise<ApiResponse<any[]>> {
    const params = characterId ? `?character_id=${characterId}` : '';
    return this.request(`/sessions${params}`);
  }

  async createChatSession(characterId: string, title?: string): Promise<ApiResponse<any>> {
    return this.request('/sessions', {
      method: 'POST',
      body: JSON.stringify({ character: characterId, title }),
    });
  }

  async getChatSession(id: string): Promise<ApiResponse<any>> {
    return this.request(`/sessions/${id}`);
  }

  // Message API
  async getMessages(chatSessionId: string): Promise<ApiResponse<any[]>> {
    return this.request(`/messages?chat_session_id=${chatSessionId}`);
  }

  async sendMessage(data: SendMessageRequest): Promise<ApiResponse<any>> {
    return this.request('/chat/send_message/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // Utility methods
  async generateAIResponse(messageId: string, characterId: string): Promise<ApiResponse<any>> {
    return this.request('/chat/generate_ai_response', {
      method: 'POST',
      body: JSON.stringify({ message_id: messageId, character_id: characterId }),
    });
  }
}

export const apiService = new ApiService();