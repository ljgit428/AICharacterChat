"use client";

import { useState, useEffect } from 'react';
import { Character, RootState, Message } from '@/types';
import { useDispatch, useSelector } from 'react-redux';
import { setCharacter, addMessage, setLoading, setError, clearChat, saveCharacter } from '@/store/chatSlice';
import ChatWindow from '@/components/ChatWindow';
import CharacterSettings from '@/components/CharacterSettings';
import LoginModal from '@/components/LoginModal';
import { apiService, getAuthToken, removeAuthToken } from '@/utils/api';

export default function Home() {
  const [showSettings, setShowSettings] = useState(false);
  const [hasStartedConversation, setHasStartedConversation] = useState(false);
  const [showLogin, setShowLogin] = useState(false);
  const [currentUser, setCurrentUser] = useState<string | null>(null);
  const [chatSessionId, setChatSessionId] = useState<string | null>(null);
  const dispatch = useDispatch();
  const character = useSelector((state: RootState) => state.chat.character);
  const messages = useSelector((state: RootState) => state.chat.messages);

  // Check for existing token on mount
  useEffect(() => {
    const token = getAuthToken();
    if (token) {
      // For demo purposes, we'll assume the user is logged in
      // In a real app, you might want to validate the token with the backend
      setCurrentUser('demo_user');
    }
  }, []);

  useEffect(() => {
    // Load default character if none exists
    if (!character) {
      const defaultCharacter: Character = {
        id: '1',
        name: 'Default Character',
        description: 'A friendly AI companion ready to chat with you.',
        personality: 'Helpful, cheerful, and curious.',
        appearance: 'A friendly digital companion with a warm smile.',
        requirement: 'Please be helpful, accurate, and engaging in your responses. Stay in character and provide thoughtful answers to user questions.',
        disabled: {
          name: false,
          description: false,
          personality: false,
          appearance: false,
          requirement: false,
        },
      };
      dispatch(setCharacter(defaultCharacter));
    }
  }, [character, dispatch]);

  const handleSendMessage = async (message: string) => {
    if (!character) return;

    // 1. Prepare the full prompt for backend API regardless of conversation state
    const fullPromptForBackend = !hasStartedConversation
      ? generateCharacterPrompt(character, message)
      : message;

    // 2. Determine how to display messages in UI based on whether it's first conversation
    if (!hasStartedConversation) {
      // ===== First conversation: split display for debugging purposes =====

      // A. Extract only the "character identity" part from the complete prompt
      const separator = '=== USER MESSAGE ===';
      const promptParts = fullPromptForBackend.split(separator);
      const identityPart = promptParts[0].trim();

      // B. Show first bubble (character identity part) if it's not empty
      if (identityPart) {
        const identityMessage: Message = {
          id: Date.now().toString(),
          content: identityPart,
          role: 'user', // Display as user message for debugging
          timestamp: new Date().toISOString(),
        };
        dispatch(addMessage(identityMessage));
      }

      // C. (Key modification) Only show second bubble if user actually entered content
      if (message.trim()) {
        const userMessagePart: Message = {
          id: (Date.now() + 1).toString(), // Ensure unique ID
          content: message, // <-- Core: content is just the original user input
          role: 'user',
          timestamp: new Date().toISOString(),
        };
        dispatch(addMessage(userMessagePart));
      }

      // D. Update conversation state to ensure this logic only runs once
      setHasStartedConversation(true);

    } else {
      // ===== This is not the first conversation, show single user message bubble normally =====
      const userMessage: Message = {
        id: Date.now().toString(),
        content: message, // message is original user input
        role: 'user',
        timestamp: new Date().toISOString(),
      };
      dispatch(addMessage(userMessage));
    }

    // 3. Start calling API, sending the complete prompt to backend
    dispatch(setLoading(true));
    dispatch(setError(null));

    try {
      // 4. Send the complete prompt to backend
      const response = await apiService.sendMessage({
        message: fullPromptForBackend,
        character_id: character.id,
        chat_session_id: chatSessionId || undefined,
      });

      if (response.error) {
        throw new Error(response.error);
      }

      // Add AI response after normalizing it
      if (response.data?.ai_message) {
        // 1. From the backend get the raw ai_message data
        const rawAiMessage = response.data.ai_message;

        // 2. Convert it to the frontend expected Message type
        const formattedAiMessage: Message = {
          id: String(rawAiMessage.id), // Convert id to string
          content: rawAiMessage.content,
          role: rawAiMessage.role,
          timestamp: rawAiMessage.timestamp, // Backend already sends ISO string
        };

        // 3. Print it out to confirm (optional, but recommended)
        console.log('Formatted AI message to dispatch:', formattedAiMessage);

        // 4. Dispatch the formatted message to Redux store
        dispatch(addMessage(formattedAiMessage));
        
        // Save the chat session ID from the response
        if (response.data?.chat_session_id) {
          setChatSessionId(response.data.chat_session_id);
        }
      } else if (response.data?.status === 'processing') {
        // Task is processing, no AI response yet
        console.log('AI response is being generated...');
        // Start polling for the AI response
        if (response.data.chat_session_id) {
          pollForMessage(response.data.chat_session_id);
        }
      } else if (response.data?.user_message) {
        // Add user message (already added, but just in case)
        console.log('User message sent:', response.data.user_message);
        
        // Save the chat session ID from the response
        if (response.data?.chat_session_id) {
          setChatSessionId(response.data.chat_session_id);
        }
      }
    } catch (error) {
      console.error('Error sending message:', error);
      dispatch(setError(error instanceof Error ? error.message : 'Failed to send message'));
      
      // Add error message
      const errorMessage = {
        id: (Date.now() + 1).toString(),
        content: 'Sorry, I encountered an error. Please try again.',
        role: 'assistant' as const,
        timestamp: new Date().toISOString(),
      };
      dispatch(addMessage(errorMessage));
    } finally {
      dispatch(setLoading(false));
    }
  };

  // Polling function to check for AI responses
  const pollForMessage = (sessionId: string) => {
    const intervalId = setInterval(async () => {
      try {
        // Get the latest messages for this session
        const messagesResponse = await apiService.getMessages(sessionId);
        
        if (messagesResponse.data && messagesResponse.data.length > 0) {
          const lastMessage = messagesResponse.data[messagesResponse.data.length - 1];
          
          // Check if the latest message is from AI and we haven't added it yet
          // Fix type mismatch by comparing IDs as strings
          if (lastMessage && lastMessage.role === 'assistant' &&
              !messages.some((m: Message) => String(m.id) === String(lastMessage.id))) {
             
            // Found the AI response! Stop polling and add to UI
            clearInterval(intervalId);
            dispatch(addMessage(lastMessage));
            dispatch(setLoading(false));
          }
        }
      } catch (error) {
        console.error('Polling error:', error);
        clearInterval(intervalId);
        
        // Check for specific error types
        if (error instanceof Error) {
          let errorMessage = 'Sorry, I encountered an error. Please try again.';
          
          // Handle specific error cases
          if (error.message.includes('429') || error.message.includes('quota')) {
            errorMessage = 'AI service is temporarily unavailable due to quota limits. Please try again later.';
          } else if (error.message.includes('permission') || error.message.includes('API key')) {
            errorMessage = 'AI service configuration error. Please contact the administrator.';
          }
          
          // Add error message to chat
          const errorMsg: Message = {
            id: (Date.now() + 1).toString(),
            content: errorMessage,
            role: 'assistant',
            timestamp: new Date().toISOString(),
          };
          dispatch(addMessage(errorMsg));
        } else {
          // Generic error
          const errorMessage = {
            id: (Date.now() + 1).toString(),
            content: 'Sorry, I encountered an error. Please try again.',
            role: 'assistant' as const,
            timestamp: new Date().toISOString(),
          };
          dispatch(addMessage(errorMessage));
        }
        
        dispatch(setLoading(false));
      }
    }, 3000); // Poll every 3 seconds
    
    // Set a timeout to stop polling after a reasonable time (e.g., 5 minutes)
    setTimeout(() => {
      clearInterval(intervalId);
      const state = useSelector((state: RootState) => state.chat);
      if (state.isLoading) {
        dispatch(setLoading(false));
        const timeoutMessage: Message = {
          id: (Date.now() + 1).toString(),
          content: 'AI response is taking longer than expected. Please try sending your message again.',
          role: 'assistant',
          timestamp: new Date().toISOString(),
        };
        dispatch(addMessage(timeoutMessage));
      }
    }, 5 * 60 * 1000); // 5 minutes timeout
  };

  // Helper function to generate character prompt based on available data
  const generateCharacterPrompt = (character: Character, userMessage: string): string => {
    const promptSections: string[] = [];

    // Character Identity section (always include if we have any character data)
    if (character.name || character.description || character.personality || character.appearance) {
      promptSections.push(`=== CHARACTER IDENTITY ===`);
      
      // Include name if available and not disabled
      if (character.name && character.name.trim() && !character.disabled?.name) {
        promptSections.push(`Name: ${character.name}`);
      }
      
      // Include description if available and not disabled
      if (character.description && character.description.trim() && !character.disabled?.description) {
        promptSections.push(`Description: ${character.description}`);
      }
      
      // Include personality if available and not disabled
      if (character.personality && character.personality.trim() && !character.disabled?.personality) {
        promptSections.push(`Personality: ${character.personality}`);
      }
      
      // Include appearance if available and not disabled
      if (character.appearance && character.appearance.trim() && !character.disabled?.appearance) {
        promptSections.push(`Appearance: ${character.appearance}`);
      }
      
      promptSections.push('');
    }

    // Response Guidelines section (use requirement field if available and not disabled)
    if (character.requirement && character.requirement.trim() && !character.disabled?.requirement) {
      promptSections.push(`Requirement: ${character.requirement}`);
      promptSections.push('');
    }

    // User Message section
    if (userMessage && userMessage.trim()) {
      promptSections.push(`=== USER MESSAGE ===`);
      promptSections.push(`User Input: ${userMessage}`);
      promptSections.push(`Please respond to the following user message while staying in character.`);
    } else {
      // If user didn't input anything, instruct AI to start conversation
      promptSections.push(`=== USER MESSAGE ===`);
      promptSections.push(`User Input: (No input provided)`);
      promptSections.push(`Please start the conversation with a greeting in your character's voice.`);
    }

    return promptSections.join('\n');
  };

  const handleSaveCharacter = async (characterData: Character) => {
    // Create FormData for character data
    const formData = new FormData();
    formData.append('name', characterData.name);
    formData.append('description', characterData.description);
    formData.append('personality', characterData.personality);
    formData.append('appearance', characterData.appearance);
    
    // Dispatch the thunk instead of directly calling API
    const resultAction = await dispatch(saveCharacter({
      id: characterData.id,
      formData
    }) as any);

    if (resultAction.meta.requestStatus === 'fulfilled') {
      // API call successful, Redux store already updated
      dispatch(clearChat()); // Clear previous messages when character changes
      setHasStartedConversation(false); // Reset conversation state
      setChatSessionId(null); // Reset chat session ID when character changes
      setShowSettings(false);
    } else if (resultAction.meta.requestStatus === 'rejected') {
      // API call failed, Redux store already has error
      console.error('Failed to save character:', resultAction.payload);
      // Show error to user
      dispatch(setError(resultAction.payload as string));
    }
  };

  const handleCancelSettings = () => {
    setShowSettings(false);
  };

  const handleLogin = (username: string) => {
    setCurrentUser(username);
    setShowLogin(false);
  };

  const handleLogout = () => {
    removeAuthToken();
    setCurrentUser(null);
    setShowLogin(false);
  };

  const handleLoginClick = () => {
    setShowLogin(true);
  };

  return (
    <div className="min-h-screen bg-gray-100">
      <div className="container mx-auto p-4 h-screen flex flex-col">
        {/* Header */}
        <header className="bg-white shadow-sm rounded-lg mb-4 p-4">
          <div className="flex items-center justify-between">
            <h1 className="text-2xl font-bold text-gray-800">
              AI Character Chat
            </h1>
            <div className="flex items-center space-x-2">
              {currentUser ? (
                <div className="flex items-center space-x-2">
                  <span className="text-gray-600">Welcome, {currentUser}</span>
                  <button
                    onClick={handleLogout}
                    className="bg-red-500 text-white px-4 py-2 rounded-lg hover:bg-red-600 transition-colors"
                  >
                    Logout
                  </button>
                </div>
              ) : (
                <button
                  onClick={handleLoginClick}
                  className="bg-green-500 text-white px-4 py-2 rounded-lg hover:bg-green-600 transition-colors"
                >
                  Login
                </button>
              )}
              <button
                onClick={() => setShowSettings(true)}
                className="bg-blue-500 text-white px-4 py-2 rounded-lg hover:bg-blue-600 transition-colors"
              >
                Character Settings
              </button>
            </div>
          </div>
        </header>

        {/* Main Content */}
        <div className="flex-1 overflow-hidden">
          <ChatWindow
            onSendMessage={handleSendMessage}
            isLoading={useSelector((state: RootState) => state.chat.isLoading)}
            isFirstMessage={!hasStartedConversation}
          />
        </div>

        {/* Settings Modal */}
        {showSettings && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-lg shadow-xl max-w-7xl w-full max-h-[90vh] overflow-y-auto">
              <CharacterSettings
                character={character || undefined}
                onSave={handleSaveCharacter}
                onCancel={handleCancelSettings}
              />
            </div>
          </div>
        )}
      </div>

      {/* Login Modal */}
      {showLogin && (
        <LoginModal
          isOpen={showLogin}
          onClose={() => setShowLogin(false)}
          onLogin={handleLogin}
        />
      )}
    </div>
  );
}
