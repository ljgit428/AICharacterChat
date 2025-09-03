import { createSlice, PayloadAction, createAsyncThunk } from '@reduxjs/toolkit';
import { ChatState, Message, Character } from '@/types';
import { apiService } from '@/utils/api';

const initialState: ChatState = {
  messages: [],
  character: null,
  isLoading: false,
  error: null,
};

// Async thunk for saving character
export const saveCharacter = createAsyncThunk(
  'chat/saveCharacter',
  async ({ id, formData }: { id?: string; formData: FormData }, { rejectWithValue }) => {
    try {
      let response;
      if (id) {
        response = await apiService.updateCharacter(id, formData);
      } else {
        response = await apiService.createCharacter(formData);
      }

      if (response.error) {
        throw new Error(response.error);
      }

      return response.data;
    } catch (error: any) {
      return rejectWithValue(error.message || 'Failed to save character');
    }
  }
);

const chatSlice = createSlice({
  name: 'chat',
  initialState,
  reducers: {
    setMessages: (state, action: PayloadAction<Message[]>) => {
      state.messages = action.payload;
    },
    addMessage: (state, action: PayloadAction<Message>) => {
      state.messages.push(action.payload);
    },
    setLoading: (state, action: PayloadAction<boolean>) => {
      state.isLoading = action.payload;
    },
    setError: (state, action: PayloadAction<string | null>) => {
      state.error = action.payload;
    },
    setCharacter: (state, action: PayloadAction<Character>) => {
      state.character = action.payload;
    },
    updateCharacter: (state, action: PayloadAction<Character>) => {
      if (state.character && state.character.id === action.payload.id) {
        state.character = action.payload;
      }
    },
    clearChat: (state) => {
      state.messages = [];
      state.error = null;
    },
    updateCharacterDisabled: (state, action: PayloadAction<{attribute: keyof Character['disabled'], disabled: boolean}>) => {
      if (state.character) {
        state.character.disabled[action.payload.attribute] = action.payload.disabled;
      }
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(saveCharacter.pending, (state) => {
        state.isLoading = true;
        state.error = null;
      })
      .addCase(saveCharacter.fulfilled, (state, action) => {
        state.isLoading = false;
        state.character = action.payload || null;
      })
      .addCase(saveCharacter.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
      });
  },
});

export const {
  setMessages,
  addMessage,
  setLoading,
  setError,
  setCharacter,
  updateCharacter,
  clearChat,
  updateCharacterDisabled,
} = chatSlice.actions;

export default chatSlice.reducer;