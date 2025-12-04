"use client";

import { useState, useEffect, useRef } from 'react';
import { Character, RootState, Message, ChatSession } from '@/types';
import { useDispatch, useSelector } from 'react-redux';
import { setCharacter, addMessage, setMessages, setLoading, setError, clearChat, setChatSession, updateChatSession } from '@/store/chatSlice';
import ChatWindow from '@/components/ChatWindow';
import SessionSettings from '@/components/SessionSettings';
import { apiService, getAuthToken, removeAuthToken } from '@/utils/api';
import { Settings, User, LogOut, Clock } from 'lucide-react';

interface ChatInterfaceProps {
  characterId?: string;
  initialSessionId?: string | null;
  onBack?: () => void;
  onSessionUpdate?: () => void;
}

export default function ChatInterface({
  characterId,
  initialSessionId,
  onSessionUpdate
}: ChatInterfaceProps) {
  const [showSessionSettings, setShowSessionSettings] = useState(false);
  const [hasStartedConversation, setHasStartedConversation] = useState(false);
  const [currentUser, setCurrentUser] = useState<string | null>(null);
  const [chatSessionId, setChatSessionId] = useState<string | null>(initialSessionId || null);

  const [pendingSettings, setPendingSettings] = useState<Partial<ChatSession>>({
    worldTime: "Current time",
    userPersona: "Li, An Overwhelmed Underwriting Manager",
    enableWebSearch: false,
    outputLanguage: "English",
    additionalContext: ""
  });

  const dispatch = useDispatch();
  const character = useSelector((state: RootState) => state.chat.character);
  const chatSession = useSelector((state: RootState) => state.chat.chatSession);

  useEffect(() => {
    const token = getAuthToken();
    if (token) {
      setCurrentUser('demo_user');
    }
  }, []);

  useEffect(() => {
    const loadCharacter = async () => {
      // Same character, Performance Optimization
      if (character && (!characterId || character.id === characterId)) {
        return;
      }

      dispatch(setLoading(true));
      try {
        let serverCharacter;

        if (characterId) {
          const response = await apiService.getCharacter(characterId);
          if (response.data) {
            serverCharacter = response.data;
          } else {
            throw new Error("Character not found");
          }
        }
        else {
          const response = await apiService.getCharacters();
          if (response.data && response.data.length > 0) {
            serverCharacter = response.data[0];
          }
        }

        if (serverCharacter) {
          dispatch(setCharacter(serverCharacter));
        } else {
          console.error("Fatal Error: Character not found in database.");
        }
      } catch (error) {
        console.error("Failed to load character:", error);
        dispatch(setError(error instanceof Error ? error.message : 'Failed to load character'));
      } finally {
        dispatch(setLoading(false));
      }
    };

    loadCharacter();
  }, [dispatch, character, characterId]);

  useEffect(() => {
    const loadChatHistory = async () => {
      if (!initialSessionId) {
        dispatch(clearChat());
        dispatch(setChatSession(null));
        setChatSessionId(null);
        setHasStartedConversation(false);
        setPendingSettings({
          worldTime: "Current time",
          userPersona: "Li, An Overwhelmed Underwriting Manager",
          enableWebSearch: false,
          outputLanguage: "English",
          additionalContext: ""
        });
        return;
      }

      dispatch(clearChat());
      dispatch(setLoading(true));

      setChatSessionId(initialSessionId);

      try {

        const [messagesRes, sessionRes] = await Promise.all([
          apiService.getMessages(initialSessionId),
          apiService.getChatSession(initialSessionId)
        ]);

        if (messagesRes.data && messagesRes.data.length > 0) {
          const formattedMessages = messagesRes.data.map(msg => ({
            id: String(msg.id),
            content: msg.content,
            role: msg.role,
            timestamp: msg.timestamp,
            fileUri: msg.file_uri || undefined,
            fileName: msg.file_uri ? msg.file_uri.split('/').pop() : undefined
          }));

          dispatch(setMessages(formattedMessages));
          setHasStartedConversation(true);
        } else {
          setHasStartedConversation(false);
        }

        if (sessionRes.data) {

          dispatch(setChatSession(sessionRes.data));
        }

      } catch (err) {
        console.error("Failed to load chat history:", err);
        dispatch(setError("Failed to load history"));
      } finally {
        dispatch(setLoading(false));
      }
    };

    loadChatHistory();
  }, [initialSessionId, dispatch]);

  const handleSendMessage = async (userInput: string) => {
    if (!character) return;

    let messageToSend: string;
    const isFirstMessage = !hasStartedConversation;

    if (isFirstMessage) {
      messageToSend = generateCharacterPrompt(character);
      setHasStartedConversation(true);
    } else {
      if (!userInput) return;
      messageToSend = userInput;
    }

    const userMessage: Message = {
      id: Date.now().toString(),
      content: messageToSend,
      role: 'user' as const,
      timestamp: new Date().toISOString()
    };
    dispatch(addMessage(userMessage));

    dispatch(setLoading(true));
    dispatch(setError(null));

    try {
      const requestData: any = {
        message: messageToSend,
        character_id: character.id,
        chat_session_id: chatSessionId || undefined,
      };

      if (!chatSessionId) {
        Object.assign(requestData, {
          world_time: pendingSettings.worldTime,
          user_persona: pendingSettings.userPersona,
          enable_web_search: pendingSettings.enableWebSearch,
          output_language: pendingSettings.outputLanguage,
          additional_context: pendingSettings.additionalContext
        });
      }

      const response = await apiService.sendMessage(requestData);

      if (response.error) {
        throw new Error(response.error);
      }

      if (response.data?.ai_message) {
        const rawAiMessage = response.data.ai_message;
        const formattedAiMessage: Message = {
          id: String(rawAiMessage.id),
          content: rawAiMessage.content,
          role: rawAiMessage.role,
          timestamp: rawAiMessage.timestamp,
          fileUri: rawAiMessage.file_uri || undefined,
          fileName: rawAiMessage.file_uri ? rawAiMessage.file_uri.split('/').pop() : undefined
        };
        dispatch(addMessage(formattedAiMessage));

        if (response.data?.chat_session_id) {
          setChatSessionId(response.data.chat_session_id);

          apiService.getChatSession(response.data.chat_session_id).then(res => {
            if (res.data) {
              dispatch(setChatSession(res.data as ChatSession));
              setPendingSettings({
                worldTime: res.data.worldTime,
                userPersona: res.data.userPersona,
                enableWebSearch: res.data.enableWebSearch,
                outputLanguage: res.data.outputLanguage,
                additionalContext: res.data.additionalContext
              });
            }
          });

          if (onSessionUpdate) {
            onSessionUpdate();

            setTimeout(() => {
              onSessionUpdate();
            }, 1500);
          }
        }
      }
    } catch (error) {
      console.error('Error sending message:', error);
      const errorMessageContent = error instanceof Error ? error.message : 'Failed to get a response';
      dispatch(setError(errorMessageContent));

      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        content: `Sorry, I encountered an error: ${errorMessageContent}`,
        role: 'assistant' as const,
        timestamp: new Date().toISOString(),
      };
      dispatch(addMessage(errorMessage));
    } finally {
      dispatch(setLoading(false));
    }
  };

  const generateCharacterPrompt = (character: Character): string => {
    const promptSections: string[] = [];

    if (character.name || character.description || character.personality || character.appearance) {
      promptSections.push(`=== CHARACTER IDENTITY ===`);
      if (character.name && character.name.trim() && !character.disabled.name) {
        promptSections.push(`Name: ${character.name}`);
      }
      if (character.description && character.description.trim() && !character.disabled.description) {
        promptSections.push(`Description: ${character.description}`);
      }
      if (character.personality && character.personality.trim() && !character.disabled.personality) {
        promptSections.push(`Personality: ${character.personality}`);
      }
      if (character.appearance && character.appearance.trim() && !character.disabled.appearance) {
        promptSections.push(`Appearance: ${character.appearance}`);
      }
      if (character.affiliation && character.affiliation.trim()) {
        promptSections.push(`Affiliation: ${character.affiliation}`);
      }
      promptSections.push('');
    }

    promptSections.push(`Please provide your initial greeting based on your character settings.`);

    return promptSections.join('\n');
  };

  const handleSaveSessionSettings = async (sessionData: Partial<ChatSession>) => {
    if (chatSessionId) {
      dispatch(setLoading(true));
      dispatch(setError(null));

      try {
        const response = await apiService.updateChatSession(chatSessionId, sessionData);
        if (response.error) throw new Error(response.error);
        if (response.data) {
          dispatch(updateChatSession(response.data));
        }
        setShowSessionSettings(false);
      } catch (error) {
        console.error('Error saving session settings:', error);
        dispatch(setError(error instanceof Error ? error.message : 'Failed to save session settings'));
      } finally {
        dispatch(setLoading(false));
      }
    }
    else {
      setPendingSettings(prev => ({ ...prev, ...sessionData }));

      dispatch(updateChatSession(sessionData));

      setShowSessionSettings(false);
    }
  };

  const handleCancelSessionSettings = () => {
    setShowSessionSettings(false);
  };

  const handleLogout = () => {
    removeAuthToken();
    setCurrentUser(null);
  };

  return (
    <div className="flex flex-col h-full">
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center space-x-4">

          <div className="w-10 h-10 bg-blue-100 rounded-full flex items-center justify-center overflow-hidden">
            {character?.avatarUrl ? (
              <img src={character.avatarUrl} alt={character.name} className="w-full h-full object-cover" />
            ) : (
              <span className="text-blue-600 font-bold">
                {character?.name?.charAt(0) || 'C'}
              </span>
            )}
          </div>
          <div>
            <h2 className="font-semibold text-gray-800">{character?.name || 'Loading...'}</h2>
            <p className="text-sm text-gray-500 truncate">{(() => {
              const text = character?.description || 'AI Assistant';
              const match = text.match(/^.*?[.。]/);
              return (match ? match[0] : text).trim();
            })()}</p>
          </div>
        </div>

        <div className="flex items-center space-x-2">
          {currentUser && (
            <div className="flex items-center space-x-2 text-sm text-gray-600">
              <User size={16} />
              <span>{currentUser}</span>
            </div>
          )}

          <button
            onClick={() => setShowSessionSettings(true)}
            className="p-2 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded-full transition-colors"
            title="Session Settings"
          >
            <Settings className="w-5 h-5" />
          </button>

          {currentUser && (
            <button
              onClick={handleLogout}
              className="p-2 rounded-lg hover:bg-gray-100 text-gray-600 transition-colors"
              title="Logout"
            >
              <LogOut size={18} />
            </button>
          )}
        </div>
      </header>

      <div className="flex-1 overflow-hidden">
        <ChatWindow
          onSendMessage={handleSendMessage}
          isLoading={useSelector((state: RootState) => state.chat.isLoading)}
          isFirstMessage={!hasStartedConversation}
        />
      </div>

      {showSessionSettings && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
            <SessionSettings
              chatSession={chatSessionId ? chatSession : {
                ...pendingSettings,
                id: '',
                title: '',
                character: character!,
                createdAt: '',
                updatedAt: ''
              } as ChatSession}
              onSave={handleSaveSessionSettings}
              onCancel={handleCancelSessionSettings}
            />
          </div>
        </div>
      )}
    </div>
  );
}
