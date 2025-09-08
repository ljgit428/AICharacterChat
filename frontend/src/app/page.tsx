"use client";

import { useState, useEffect, useRef } from 'react';
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
  const [chatSessionId, setChatSessionId] = useState<string | null>(null);
  
  // For chat file upload
  const [stagedFile, setStagedFile] = useState<{ name: string; uri: string } | null>(null);
  const [isChatUploading, setIsChatUploading] = useState(false);
  const chatFileInputRef = useRef<HTMLInputElement>(null);
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
        // 添加响应指南的默认值
        responseGuidelines: `Instructions:
- Respond consistently with your character's traits and background
- Maintain character voice throughout the conversation
- Be engaging and responsive to user input
- Stay true to Default Character's established character`,
        disabled: {
          name: false,
          description: false,
          personality: false,
          appearance: false,
          responseGuidelines: false, // 添加响应指南的disabled开关
          file: false,
        },
      };
      dispatch(setCharacter(defaultCharacter));
    }
  }, [character, dispatch]);

  const handleSendMessage = async (userInput: string) => {
    if (!character) return;

    let messageToSend: string;
    const isFirstMessage = !hasStartedConversation;

    if (isFirstMessage) {
      // On the first message, the content sent is the generated character prompt.
      messageToSend = generateCharacterPrompt(character);
      setHasStartedConversation(true);
    } else {
      // On subsequent messages, if the input is empty, do nothing.
      if (!userInput) return;
      messageToSend = userInput;
    }

    // Always add the message that will be sent to the UI.
    // On the first run, this will be the settings prompt.
    // On subsequent runs, it will be the user's typed message.
    const userMessage: Message = {
      id: Date.now().toString(),
      content: messageToSend,
      role: 'user' as const,
      timestamp: new Date().toISOString(),
      fileUri: isFirstMessage ? undefined : stagedFile?.uri,
    };
    dispatch(addMessage(userMessage));

    dispatch(setLoading(true));
    dispatch(setError(null));

    try {
      // Send the prepared message to the backend
      const response = await apiService.sendMessage({
        message: messageToSend,
        character_id: character.id,
        chat_session_id: chatSessionId || undefined,
        file_uri: isFirstMessage ? undefined : stagedFile?.uri,
      });

      // Clear the staged file after successful send
      setStagedFile(null);

      if (response.error) {
        throw new Error(response.error);
      }

      // Add AI response after normalizing it
      if (response.data?.ai_message) {
        const rawAiMessage = response.data.ai_message;
        const formattedAiMessage: Message = {
          id: String(rawAiMessage.id),
          content: rawAiMessage.content,
          role: rawAiMessage.role,
          timestamp: rawAiMessage.timestamp,
        };
        dispatch(addMessage(formattedAiMessage));
        
        if (response.data?.chat_session_id) {
          setChatSessionId(response.data.chat_session_id);
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

  // MODIFICATION: Removed `userMessage` parameter. This prompt now only contains settings.
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
      promptSections.push('');
    }

    if (character.responseGuidelines && character.responseGuidelines.trim() && !character.disabled.responseGuidelines) {
      promptSections.push(`=== RESPONSE GUIDELINES ===`);
      promptSections.push(character.responseGuidelines);
      promptSections.push('');
    }

    if (promptSections.length > 0) {
      promptSections.push(`=== RESPONSE GUIDELINES ===`);
      promptSections.push(`Instructions:`);
      promptSections.push(`- Respond consistently with your character's traits and background.`);
      promptSections.push(`- Maintain your character voice throughout the conversation.`);
      promptSections.push(`- Your first response should be an engaging greeting or opening line that invites conversation.`);
      promptSections.push('');
    }

    // REMOVED: The "USER MESSAGE" section has been completely removed from this initial prompt.
    promptSections.push(`Please provide your initial greeting based on your character settings.`);

    return promptSections.join('\n');
  };

  const handleSaveCharacter = async (characterData: Character, file?: File) => {
    dispatch(setLoading(true));
    dispatch(setError(null));

    try {
      let response;
      // Use String() to ensure characterData.id is always a string for the check
      if (characterData.id && !String(characterData.id).startsWith('temp-')) {
        response = await apiService.updateCharacter(String(characterData.id), {
          name: characterData.name,
          description: characterData.description,
          personality: characterData.personality,
          appearance: characterData.appearance,
          responseGuidelines: characterData.responseGuidelines,
          file_url: characterData.fileUrl,
        }, file);
      } else {
        response = await apiService.createCharacter({
          name: characterData.name,
          description: characterData.description,
          personality: characterData.personality,
          appearance: characterData.appearance,
          responseGuidelines: characterData.responseGuidelines,
          file_url: characterData.fileUrl,
        }, file);
      }
      
      if (response.error) {
        throw new Error(response.error);
      }

      // --- vvv 核心修正：确保存入Redux的ID永远是字符串 vvv ---
      const serverResponseData = response.data;
      
      // Get the ID from the server response and explicitly convert it to a string.
      const finalId = serverResponseData.id ? String(serverResponseData.id) : characterData.id;

      // Create the final character object for the Redux store
      const savedCharacter: Character = {
        ...characterData,
        id: finalId, // Now it's guaranteed to be a string
        // The backend returns snake_case, so we need to map it back if needed,
        // or just rely on the data we already have on the frontend.
        // Using characterData is safer here.
        name: serverResponseData.name || characterData.name,
        description: serverResponseData.description || characterData.description,
        personality: serverResponseData.personality || characterData.personality,
        appearance: serverResponseData.appearance || characterData.appearance,
        fileUrl: serverResponseData.file_url || characterData.fileUrl,
        responseGuidelines: serverResponseData.response_guidelines || characterData.responseGuidelines,
      };
      
      dispatch(setCharacter(savedCharacter));
      // --- ^^^ 核心修正结束 ^^^ ---
      
      dispatch(clearChat());
      setHasStartedConversation(false);
      setChatSessionId(null);
      setShowSettings(false);
    } catch (error) {
      console.error('Error saving character:', error);
      dispatch(setError(error instanceof Error ? error.message : 'Failed to save character'));
    } finally {
      dispatch(setLoading(false));
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

  // Handle chat file upload
  const handleChatFileSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setIsChatUploading(true);
    const response = await apiService.uploadImage(file);
    setIsChatUploading(false);

    if (response.data) {
      setStagedFile({ name: file.name, uri: response.data.uri });
    } else {
      alert(`File upload failed: ${response.error}`);
    }
    // Clear the input value to allow re-uploading the same file
    if (chatFileInputRef.current) {
      chatFileInputRef.current.value = "";
    }
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
            // Pass new props for file upload
            stagedFile={stagedFile}
            onStagedFileRemove={() => setStagedFile(null)}
            onFileUploadClick={() => chatFileInputRef.current?.click()}
            isChatUploading={isChatUploading}
          />
        </div>
        
        {/* Hidden file input for chat uploads */}
        <input
          type="file"
          ref={chatFileInputRef}
          className="hidden"
          onChange={handleChatFileSelect}
        />

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
