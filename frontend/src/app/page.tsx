"use client";

import { useState, useEffect } from 'react';
import { Character, RootState, Message } from '@/types';
import { useDispatch, useSelector } from 'react-redux';
import { setCharacter, addMessage, setLoading, setError, clearChat } from '@/store/chatSlice';
import ChatWindow from '@/components/ChatWindow';
import CharacterSettings from '@/components/CharacterSettings';
import LoginModal from '@/components/LoginModal';
import { apiService, getAuthToken, removeAuthToken } from '@/utils/api';

export default function Home() {
  const [showSettings, setShowSettings] = useState(false);
  const [hasStartedConversation, setHasStartedConversation] = useState(false);
  const [showLogin, setShowLogin] = useState(false);
  const [currentUser, setCurrentUser] = useState<string | null>(null);
  const dispatch = useDispatch();
  const character = useSelector((state: RootState) => state.chat.character);

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
      };
      dispatch(setCharacter(defaultCharacter));
    }
  }, [character, dispatch]);

  const handleSendMessage = async (message: string) => {
    if (!character) return;

    // Check if this is the first message and create character settings message
    let finalMessage = message;
    if (!hasStartedConversation) {
      // Create intelligent character settings prompt based on available data
      const characterSettings = generateCharacterPrompt(character, message);
      finalMessage = characterSettings;
      setHasStartedConversation(true);
    }

    // Add user message
    const userMessage = {
      id: Date.now().toString(),
      content: finalMessage,
      role: 'user' as const,
      timestamp: new Date().toISOString(),
    };
    
    dispatch(addMessage(userMessage));
    dispatch(setLoading(true));
    dispatch(setError(null));

    try {
      // Send message to backend
      const response = await apiService.sendMessage({
        message: finalMessage,
        character_id: character.id,
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
      } else if (response.data?.status === 'processing') {
        // Task is processing, no AI response yet
        console.log('AI response is being generated...');
      } else if (response.data?.user_message) {
        // Add user message (already added, but just in case)
        console.log('User message sent:', response.data.user_message);
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

  // Helper function to generate character prompt based on available data
  const generateCharacterPrompt = (character: Character, userMessage: string): string => {
    const promptSections: string[] = [];

    // Character Identity section (always include if we have any character data)
    if (character.name || character.description || character.personality || character.appearance) {
      promptSections.push(`=== CHARACTER IDENTITY ===`);
      
      // Always include name if available
      if (character.name && character.name.trim()) {
        promptSections.push(`Name: ${character.name}`);
      }
      
      // Always include description if available
      if (character.description && character.description.trim()) {
        promptSections.push(`Description: ${character.description}`);
      }
      
      // Always include personality if available
      if (character.personality && character.personality.trim()) {
        promptSections.push(`Personality: ${character.personality}`);
      }
      
      // Always include appearance if available
      if (character.appearance && character.appearance.trim()) {
        promptSections.push(`Appearance: ${character.appearance}`);
      }
      
      promptSections.push('');
    }

    // Response Guidelines section (always include if we have any character data)
    if (promptSections.length > 0) {
      promptSections.push(`=== RESPONSE GUIDELINES ===`);
      promptSections.push(`Instructions:`);
      promptSections.push(`- Respond consistently with your character's traits and background`);
      promptSections.push(`- Maintain character voice throughout the conversation`);
      promptSections.push(`- Be engaging and responsive to user input`);
      if (character.name) {
        promptSections.push(`- Stay true to ${character.name}'s established character`);
      }
      promptSections.push('');
    }

    // User Message section (always include)
    promptSections.push(`=== USER MESSAGE ===`);
    promptSections.push(`User Input: ${userMessage}`);
    promptSections.push(`Please respond to the following user message while staying in character.`);

    return promptSections.join('\n');
  };

  const handleSaveCharacter = async (characterData: Character) => {
    try {
      // Save character to backend
      const response = await apiService.createCharacter(characterData);
      
      if (response.error) {
        throw new Error(response.error);
      }

      dispatch(setCharacter(characterData));
      dispatch(clearChat()); // Clear previous messages when character changes
      setHasStartedConversation(false); // Reset conversation state
      setShowSettings(false);
    } catch (error) {
      console.error('Error saving character:', error);
      dispatch(setError(error instanceof Error ? error.message : 'Failed to save character'));
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
        <div className="flex-1 grid grid-cols-1 lg:grid-cols-3 gap-4 overflow-hidden">
          {/* Chat Window - Takes 2/3 width on large screens */}
          <div className="lg:col-span-2">
            <ChatWindow
              onSendMessage={handleSendMessage}
              isLoading={useSelector((state: RootState) => state.chat.isLoading)}
              isFirstMessage={!hasStartedConversation}
            />
          </div>

          {/* Character Info - Takes 1/3 width on large screens */}
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <h2 className="text-lg font-semibold mb-4">Character</h2>
            <div className="text-gray-600">
              <p className="mb-2">
                <strong>Name:</strong> <span className="text-gray-800">{character?.name || 'No character set'}</span>
              </p>
              <p className="mb-2">
                <strong>Description:</strong> <span className="text-gray-800">{character?.description || 'No description'}</span>
              </p>
              <p className="mb-2">
                <strong>Personality:</strong> <span className="text-gray-800">{character?.personality || 'No personality set'}</span>
              </p>
              <p>
                <strong>Appearance:</strong> <span className="text-gray-800">{character?.appearance || 'No appearance set'}</span>
              </p>
            </div>
          </div>
        </div>

        {/* Settings Modal */}
        {showSettings && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
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
