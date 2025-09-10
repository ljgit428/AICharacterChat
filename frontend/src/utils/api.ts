const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';
console.log('API_BASE_URL:', API_BASE_URL);

interface ApiResponse<T> {
  data?: T;
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
  file_uri?: string;
}

interface CreateCharacterRequest {
  name: string;
  description: string;
  personality: string;
  appearance: string;
  // --- ▼▼▼ 核心修正 ▼▼▼ ---
  response_guidelines: string; // 将驼峰式改为蛇形式
  // --- ▲▲▲ 修正结束 ▲▲▲ ---
  file_url?: string;
  clear_file?: boolean;
}

class ApiService {
  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<ApiResponse<T>> {
    try {
      const token = getAuthToken();
      const headers: Record<string, string> = {};
      
      // Add any existing headers from options
      if (options.headers) {
        Object.entries(options.headers).forEach(([key, value]) => {
          if (typeof value === 'string') {
            headers[key] = value;
          }
        });
      }
      
      // Only set Content-Type if the body is not FormData (for file uploads)
      if (!(options.body instanceof FormData)) {
        headers['Content-Type'] = 'application/json';
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

      // Handle cases where the response might be empty (e.g., a 204 No Content)
      if (response.status === 204) {
        return { data: undefined };
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
  async getCharacters(): Promise<ApiResponse<any[]>> {
    return this.request('/characters/');
  }

  async createCharacter(character: CreateCharacterRequest, file?: File): Promise<ApiResponse<any>> {
    const formData = new FormData();
    Object.entries(character).forEach(([key, value]) => {
      if (value !== undefined) {
        if (typeof value === 'boolean') {
          formData.append(key, String(value));
        } else {
          formData.append(key, value);
        }
      }
    });
    if (file) {
      formData.append('file', file);
    }

    return this.request('/characters/', {
      method: 'POST',
      body: formData,
    });
  }

  async getCharacter(id: string): Promise<ApiResponse<any>> {
    return this.request(`/characters/${id}/`);
  }

  // Allow partial updates
  async updateCharacter(id: string, character: Partial<CreateCharacterRequest>, file?: File): Promise<ApiResponse<any>> {
    const formData = new FormData();
    Object.entries(character).forEach(([key, value]) => {
      if (value !== undefined) {
        if (typeof value === 'boolean') {
          formData.append(key, String(value));
        } else {
          formData.append(key, value);
        }
      }
    });
    if (file) {
      formData.append('file', file);
    }

    return this.request(`/characters/${id}/`, {
      method: 'PUT',
      body: formData,
    });
  }

  // Chat Session API
  async getChatSessions(characterId?: string): Promise<ApiResponse<any[]>> {
    const params = characterId ? `?character_id=${characterId}` : '';
    return this.request(`/sessions/${params}`);
  }

  async createChatSession(characterId: string, title?: string): Promise<ApiResponse<any>> {
    return this.request('/sessions/', {
      method: 'POST',
      body: JSON.stringify({ character: characterId, title }),
    });
  }

  async getChatSession(id: string): Promise<ApiResponse<any>> {
    return this.request(`/sessions/${id}/`);
  }

  // Message API
  async getMessages(chatSessionId: string): Promise<ApiResponse<any[]>> {
    return this.request(`/messages/?chat_session_id=${chatSessionId}`);
  }

  async sendMessage(data: SendMessageRequest): Promise<ApiResponse<any>> {
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

  async uploadImage(file: File): Promise<ApiResponse<{ uri: string; name: string }>> {
    const formData = new FormData();
    formData.append('file', file);

    // IMPORTANT: When using fetch with FormData, DO NOT set the 'Content-Type' header.
    // The browser will automatically set it to 'multipart/form-data' with the correct boundary.
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

  // Utility methods
  async generateAIResponse(messageId: string, characterId: string): Promise<ApiResponse<any>> {
    return this.request('/chat/generate_ai_response', {
      method: 'POST',
      body: JSON.stringify({ message_id: messageId, character_id: characterId }),
    });
  }
}

export const apiService = new ApiService();