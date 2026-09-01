import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { current } from 'immer';
import { ChatState, Message, Character, ChatSession, ToolCallInfo, AgentStep } from '@/types';

// 会话消息缓存持久化到 sessionStorage：页面刷新、话题/聊天模式切换、
// 重进聊天页后第一帧仍直接渲染历史钉底，切换过程无感知。SSR 环境跳过。
const MESSAGES_CACHE_KEY = 'prismate.messagesBySession.v1';

function hydrateMessagesCache(): Record<string, Message[]> {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.sessionStorage.getItem(MESSAGES_CACHE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, Message[]>;
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function persistMessagesCache(cache: Record<string, Message[]>) {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.setItem(MESSAGES_CACHE_KEY, JSON.stringify(cache));
  } catch {
    // 配额超限等写入失败不影响主流程（下次历史加载会重写）
  }
}

const initialState: ChatState = {
  messages: [],
  messagesBySession: hydrateMessagesCache(),
  character: null,
  chatSession: null,
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
    upsertMessage: (state, action: PayloadAction<Message>) => {
      const index = state.messages.findIndex((message) => message.id === action.payload.id);
      if (index >= 0) {
        state.messages[index] = action.payload;
        return;
      }
      state.messages.push(action.payload);
    },
    appendToMessage: (state, action: PayloadAction<{ id: string; content: string }>) => {
      const target = state.messages.find((message) => message.id === action.payload.id);
      if (target) {
        target.content += action.payload.content;
      }
    },
    appendToMessageThinking: (state, action: PayloadAction<{ id: string; content: string }>) => {
      const target = state.messages.find((message) => message.id === action.payload.id);
      if (target) {
        target.thinking = (target.thinking || '') + action.payload.content;
      }
    },
    appendToMessageToolCall: (state, action: PayloadAction<{ id: string; toolCall: ToolCallInfo }>) => {
      const target = state.messages.find((message) => message.id === action.payload.id);
      if (target) {
        target.toolCalls = [...(target.toolCalls || []), action.payload.toolCall];
      }
    },
    // 流式时间线：按"思考 · 第 N 轮 / 工具"逐步更新占位消息的 steps，
    // 生成过程中就能按序看到一个个步骤（不再只有 done 之后才出现完整列表）。
    updateMessageSteps: (state, action: PayloadAction<{ id: string; steps: AgentStep[] }>) => {
      const target = state.messages.find((message) => message.id === action.payload.id);
      if (target) {
        target.steps = action.payload.steps;
      }
    },
    removeMessage: (state, action: PayloadAction<string>) => {
      state.messages = state.messages.filter((message) => message.id !== action.payload);
    },
    // 原位替换：乐观消息换成服务端持久化消息时保持列表顺序，找不到时退化为追加。
    replaceMessage: (state, action: PayloadAction<{ id: string; message: Message }>) => {
      const index = state.messages.findIndex((message) => message.id === action.payload.id);
      if (index >= 0) {
        state.messages[index] = action.payload.message;
        return;
      }
      state.messages.push(action.payload.message);
    },
    setLoading: (state, action: PayloadAction<boolean>) => {
      state.isLoading = action.payload;
    },
    setError: (state, action: PayloadAction<string | null>) => {
      state.error = action.payload;
    },
    setCharacter: (state, action: PayloadAction<Character | null>) => {
      state.character = action.payload;
    },
    setChatSession: (state, action: PayloadAction<ChatSession | null>) => {
      state.chatSession = action.payload;
    },
    updateChatSession: (state, action: PayloadAction<Partial<ChatSession>>) => {
      if (state.chatSession) {
        state.chatSession = { ...state.chatSession, ...action.payload };
      }
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
    // 会话消息缓存（clearChat 不清除）：切回会话时第一帧直接渲染历史，
    // 并写穿到 sessionStorage 供刷新/模式切换后使用。
    cacheMessages: (state, action: PayloadAction<{ sessionId: string; messages: Message[] }>) => {
      state.messagesBySession[action.payload.sessionId] = action.payload.messages;
      persistMessagesCache(current(state.messagesBySession) as Record<string, Message[]>);
    },
  },
});

export const {
  setMessages,
  addMessage,
  upsertMessage,
  appendToMessage,
  appendToMessageThinking,
  appendToMessageToolCall,
  updateMessageSteps,
  removeMessage,
  replaceMessage,
  setLoading,
  setError,
  setCharacter,
  setChatSession,
  updateChatSession,
  updateCharacter,
  clearChat,
  cacheMessages,
} = chatSlice.actions;

export default chatSlice.reducer;
