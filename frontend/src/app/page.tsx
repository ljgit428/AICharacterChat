"use client";

import { useState, useEffect } from 'react';
import { Character, RootState } from '@/types';
import { useDispatch, useSelector } from 'react-redux';
import { setCharacter, addMessage, setLoading, setError } from '@/store/chatSlice';
import ChatWindow from '@/components/ChatWindow';
import CharacterSettings from '@/components/CharacterSettings';
import { apiService } from '@/utils/api';

export default function Home() {
  const [showSettings, setShowSettings] = useState(false);
  const dispatch = useDispatch();
  const character = useSelector((state: RootState) => state.chat.character);

  useEffect(() => {
    // Load default character if none exists
    if (!character) {
      const defaultCharacter: Character = {
        id: 'default',
        name: 'Default Character',
        description: 'A friendly AI companion ready to chat with you.',
        personality: 'Helpful, cheerful, and curious.',
        appearance: 'A friendly digital companion with a warm smile.',
      };
      dispatch(setCharacter(defaultCharacter));
    }
  }, [character, dispatch]);

  const handleSendMessage = async (message: string) => {
    if (!message.trim() || !character) return;

    // Add user message
    const userMessage = {
      id: Date.now().toString(),
      content: message,
      role: 'user' as const,
      timestamp: new Date(),
    };
    
    dispatch(addMessage(userMessage));
    dispatch(setLoading(true));
    dispatch(setError(null));

    try {
      // Send message to backend
      const response = await apiService.sendMessage({
        message,
        character_id: character.id,
      });

      if (response.error) {
        throw new Error(response.error);
      }

      // Add AI response
      if (response.data?.ai_message) {
        dispatch(addMessage(response.data.ai_message));
      }
    } catch (error) {
      console.error('Error sending message:', error);
      dispatch(setError(error instanceof Error ? error.message : 'Failed to send message'));
      
      // Add error message
      const errorMessage = {
        id: (Date.now() + 1).toString(),
        content: 'Sorry, I encountered an error. Please try again.',
        role: 'assistant' as const,
        timestamp: new Date(),
      };
      dispatch(addMessage(errorMessage));
    } finally {
      dispatch(setLoading(false));
    }
  };

  const handleSaveCharacter = async (characterData: Character) => {
    try {
      // Save character to backend
      const response = await apiService.createCharacter(characterData);
      
      if (response.error) {
        throw new Error(response.error);
      }

      dispatch(setCharacter(characterData));
      setShowSettings(false);
    } catch (error) {
      console.error('Error saving character:', error);
      dispatch(setError(error instanceof Error ? error.message : 'Failed to save character'));
    }
  };

  const handleCancelSettings = () => {
    setShowSettings(false);
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
            <button
              onClick={() => setShowSettings(true)}
              className="bg-blue-500 text-white px-4 py-2 rounded-lg hover:bg-blue-600 transition-colors"
            >
              Character Settings
            </button>
          </div>
        </header>

        {/* Main Content */}
        <div className="flex-1 grid grid-cols-1 lg:grid-cols-3 gap-4 overflow-hidden">
          {/* Chat Window - Takes 2/3 width on large screens */}
          <div className="lg:col-span-2">
            <ChatWindow onSendMessage={handleSendMessage} isLoading={false} />
          </div>

          {/* Character Info - Takes 1/3 width on large screens */}
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <h2 className="text-lg font-semibold mb-4">Character</h2>
            <div className="text-gray-600">
              <p className="mb-2">
                <strong>Name:</strong> <span className="text-gray-800">Default Character</span>
              </p>
              <p className="mb-2">
                <strong>Description:</strong> <span className="text-gray-800">A friendly AI companion ready to chat with you.</span>
              </p>
              <p className="mb-2">
                <strong>Personality:</strong> <span className="text-gray-800">Helpful, cheerful, and curious.</span>
              </p>
              <p>
                <strong>Appearance:</strong> <span className="text-gray-800">A friendly digital companion with a warm smile.</span>
              </p>
            </div>
          </div>
        </div>

        {/* Settings Modal */}
        {showSettings && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
              <CharacterSettings
                onSave={handleSaveCharacter}
                onCancel={handleCancelSettings}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
