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
  const [hasStartedConversation, setHasStartedConversation] = useState(false);
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
      timestamp: new Date(),
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

  // Helper function to generate character prompt based on available data
  const generateCharacterPrompt = (character: Character, userMessage: string): string => {
    const promptSections: string[] = [];

    // Character Identity section (always include if name exists)
    if (character.name && character.name.trim()) {
      promptSections.push(`=== CHARACTER IDENTITY ===`);
      promptSections.push(`Character Name: ${character.name}`);
      promptSections.push(`Role: You are ${character.name}, an AI companion designed for engaging conversation.`);
      promptSections.push('');
    }

    // Character Description section (only if has meaningful content)
    if (character.description && character.description.trim() && character.description !== 'A friendly AI companion ready to chat with you.') {
      promptSections.push(`=== CHARACTER DESCRIPTION ===`);
      promptSections.push(`Background: ${character.description}`);
      promptSections.push('');
    }

    // Personality Traits section (only if has meaningful content)
    if (character.personality && character.personality.trim() && character.personality !== 'Helpful, cheerful, and curious.') {
      promptSections.push(`=== PERSONALITY TRAITS ===`);
      promptSections.push(`Personality: ${character.personality}`);
      promptSections.push('');
    }

    // Physical Appearance section (only if has meaningful content)
    if (character.appearance && character.appearance.trim() && character.appearance !== 'A friendly digital companion with a warm smile.') {
      promptSections.push(`=== PHYSICAL APPEARANCE ===`);
      promptSections.push(`Appearance: ${character.appearance}`);
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
            <ChatWindow
              onSendMessage={handleSendMessage}
              isLoading={false}
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
    </div>
  );
}
