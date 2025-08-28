import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { ChatState, Message, Character } from '@/types';

const initialState: ChatState = {
  messages: [],
  character: null,
  isLoading: false,
  error: null,
};

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
} = chatSlice.actions;

export default chatSlice.reducer;