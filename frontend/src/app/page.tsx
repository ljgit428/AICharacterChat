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
        },
      };
      dispatch(setCharacter(defaultCharacter));
    }
  }, [character, dispatch]);

  const handleSendMessage = async (message: string) => {
    if (!character) return;

    // 这个变量将存储最终要发送给后端AI的内容
    let messageToSendToAI = message;

    // --- 核心改动：处理第一条消息 ---
    if (!hasStartedConversation) {
      // 1. 获取角色设定部分和完整的AI提示
      const { fullPrompt, settingsPart } = generateCharacterPrompt(character, message);
      
      // 更新将要发送给AI的内容为完整提示
      messageToSendToAI = fullPrompt;

      // 2.【显示第一个气泡】：如果角色设定存在，就把它作为一条消息显示出来
      if (settingsPart) {
        const settingsMessage: Message = {
          id: Date.now().toString(),
          content: settingsPart,
          role: 'user', // 仍然是用户发出的，但内容是系统生成的设定
          timestamp: new Date().toISOString(),
        };
        dispatch(addMessage(settingsMessage));
      }
      
      setHasStartedConversation(true);
    }

    // ---【显示第二个气泡】：将用户实际输入的内容作为一条独立消息显示出来 ---
    // 这段代码对所有消息（包括第一条和后续的）都有效
    const userMessage: Message = {
      id: (Date.now() + 1).toString(), // +1确保ID唯一
      content: message, // 这里只显示用户输入的原始、干净的消息
      role: 'user' as const,
      timestamp: new Date().toISOString(),
      fileUri: stagedFile?.uri, // <--- ADD THIS LINE
    };
    dispatch(addMessage(userMessage));
    
    // --- 后续逻辑保持不变 ---
    dispatch(setLoading(true));
    dispatch(setError(null));

    try {
      // Send message to backend, now including the staged file URI
      const response = await apiService.sendMessage({
        message: messageToSendToAI,
        character_id: character.id,
        chat_session_id: chatSessionId || undefined,
        file_uri: stagedFile?.uri, // <-- Pass the file URI
      });

      // Clear the staged file after successful send
      setStagedFile(null);

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
        };
        dispatch(addMessage(formattedAiMessage));
        if (response.data?.chat_session_id) {
          setChatSessionId(response.data.chat_session_id);
        }
      }
      
    } catch (error) {
      console.error('Error sending message:', error);
      dispatch(setError(error instanceof Error ? error.message : 'Failed to send message'));
      const errorMessage = {
        id: (Date.now() + 2).toString(),
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
  const generateCharacterPrompt = (character: Character, userMessage: string): { fullPrompt: string, settingsPart: string } => {
    
    // --- 构建角色定义和响应指南部分 ---
    const characterDefinitionSections: string[] = [];

    // Character Identity section
    if (character.name || character.description || character.personality || character.appearance) {
      characterDefinitionSections.push(`=== CHARACTER IDENTITY ===`);
      
      if (character.name && character.name.trim() && !character.disabled.name) {
        characterDefinitionSections.push(`Name: ${character.name}`);
      }
      if (character.description && character.description.trim() && !character.disabled.description) {
        characterDefinitionSections.push(`Description: ${character.description}`);
      }
      if (character.personality && character.personality.trim() && !character.disabled.personality) {
        characterDefinitionSections.push(`Personality: ${character.personality}`);
      }
      if (character.appearance && character.appearance.trim() && !character.disabled.appearance) {
        characterDefinitionSections.push(`Appearance: ${character.appearance}`);
      }
      characterDefinitionSections.push('');
    }

    // Response Guidelines section (现在从 character 对象动态读取)
    if (character.responseGuidelines && character.responseGuidelines.trim() && !character.disabled.responseGuidelines) {
      characterDefinitionSections.push(`=== RESPONSE GUIDELINES ===`);
      characterDefinitionSections.push(character.responseGuidelines); // 直接使用字段内容
    }
    
    // 将角色设定部分转换为字符串
    const settingsPart = characterDefinitionSections.join('\n').trim();

    // --- 创建用户消息块 ---
    const userMessageBlock = `\n\n=== USER MESSAGE ===\nUser Input: ${userMessage}\nPlease respond to the following user message while staying in character.`;

    // --- 组合成最终的完整提示 ---
    const fullPrompt = `${settingsPart}${userMessageBlock}`;
    
    // --- 返回两个部分 ---
    return { fullPrompt, settingsPart };
  };

  const handleSaveCharacter = async (characterData: Character) => {
    dispatch(setLoading(true));
    dispatch(setError(null));

    try {
      const payload: Partial<Character> = {
          name: characterData.name,
          description: characterData.description,
          personality: characterData.personality,
          appearance: characterData.appearance,
          responseGuidelines: characterData.responseGuidelines,
          imageUri: characterData.imageUri,
      };

      let response;
      // Use String() to ensure characterData.id is always a string for the check
      if (characterData.id && !String(characterData.id).startsWith('temp-')) {
        response = await apiService.updateCharacter(String(characterData.id), payload);
      } else {
        response = await apiService.createCharacter(payload as Character);
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
        imageUri: serverResponseData.image_uri || characterData.imageUri,
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
