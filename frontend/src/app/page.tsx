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
  const [stagedFile, setStagedFile] = useState<{ name: string; uri: string; type: string; previewUrl?: string } | null>(null);
  const [isChatUploading, setIsChatUploading] = useState(false);
  const chatFileInputRef = useRef<HTMLInputElement>(null);
  const dispatch = useDispatch();
  const character = useSelector((state: RootState) => state.chat.character);

  // Clean up Object URLs to prevent memory leaks
  useEffect(() => {
    // This cleanup function now ONLY runs when the component unmounts.
    // The empty dependency array [] ensures this.
    return () => {
      if (stagedFile?.previewUrl) {
          URL.revokeObjectURL(stagedFile.previewUrl);
      }
    };
  }, []); // <-- Crucially, this is now empty

  // Check for existing token on mount
  useEffect(() => {
    const token = getAuthToken();
    if (token) {
      // For demo purposes, we'll assume the user is logged in
      // In a real app, you might want to validate the token with the backend
      setCurrentUser('demo_user');
    }
  }, []);

  // --- ▼▼▼ 请用下面的代码块【替换】您现有的【所有】与加载角色相关的 useEffect ▼▼▼ ---
  // ---    这将是唯一负责初始化角色的 useEffect    ---
  useEffect(() => {
    /**
     * 在应用启动时加载或创建角色。
     * 1. 尝试从后端获取角色。
     * 2. 如果成功获取，则设置为当前角色。
     * 3. 如果未获取到 (数据库为空)，则创建并保存一个默认角色到数据库，
     *    然后使用从后端返回的数据设置当前角色。
     */
    const loadOrCreateCharacter = async () => {
      // 如果Redux中已有角色，说明初始化已完成，直接返回
      if (character) {
          return;
      }
        
      dispatch(setLoading(true));
      try {
        const response = await apiService.getCharacters();

        if (response.data && response.data.length > 0) {
          // --- 场景1: 成功从数据库加载现有角色 ---
          const serverCharacter = response.data[0];
          console.log("Successfully loaded character from DB:", serverCharacter.id);
          const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL?.replace('/api', '');
          
          const formattedCharacter: Character = {
            id: String(serverCharacter.id),
            name: serverCharacter.name,
            description: serverCharacter.description,
            personality: serverCharacter.personality,
            appearance: serverCharacter.appearance,
            responseGuidelines: serverCharacter.response_guidelines,
            fileUrl: serverCharacter.file ? `${apiBaseUrl}${serverCharacter.file}` : undefined,
            // --- ▼▼▼ 核心修正：从后端加载 disabled_states ▼▼▼ ---
            disabled: serverCharacter.disabled_states || { name: false, description: false, personality: false, appearance: false, responseGuidelines: false, file: false },
            // --- ▲▲▲ 修正结束 ▲▲▲ ---
          };
          dispatch(setCharacter(formattedCharacter));

        } else {
          // --- 场景2: 数据库为空，需要创建并保存默认角色 ---
          console.log("No character in DB. Creating the original default character...");
          
          const defaultCharacterData = {
            name: 'Default Character',
            description: 'A friendly AI companion ready to chat with you.',
            personality: 'Helpful, cheerful, and curious.',
            appearance: 'A friendly digital companion with a warm smile.',
            response_guidelines: `Instructions:
- Respond consistently with your character's traits and background
- Maintain character voice throughout the conversation
- Be engaging and responsive to user input
- Stay true to Default Character's established character`,
          };
          
          const createResponse = await apiService.createCharacter(defaultCharacterData);
          
          if (createResponse.data) {
              const newCharacterFromServer = createResponse.data;
              console.log("Default character created and saved in DB with ID:", newCharacterFromServer.id);
              const newCharacter: Character = {
                id: String(newCharacterFromServer.id),
                name: newCharacterFromServer.name,
                description: newCharacterFromServer.description,
                personality: newCharacterFromServer.personality,
                appearance: newCharacterFromServer.appearance,
                responseGuidelines: newCharacterFromServer.response_guidelines,
                fileUrl: undefined, // 新创建的角色没有文件
                // --- ▼▼▼ 核心修正：从新创建的角色中获取 disabled_states ▼▼▼ ---
                disabled: newCharacterFromServer.disabled_states,
                // --- ▲▲▲ 修正结束 ▲▲▲ ---
              };
              dispatch(setCharacter(newCharacter));
          } else {
              throw new Error(createResponse.error || "Failed to create default character.");
          }
        }
      } catch (error) {
          console.error("Failed to load or create character:", error);
          dispatch(setError(error instanceof Error ? error.message : 'Failed to initialize character'));
      } finally {
          dispatch(setLoading(false));
      }
    };

    loadOrCreateCharacter();
  }, [dispatch, character]); // 依赖中加入character确保不会重复执行
  // --- ▲▲▲ 替换结束 ▲▲▲ ---

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
    // --- ▼▼▼ 核心修正：动态获取文件名 ▼▼▼ ---
    const userMessage: Message = {
      id: Date.now().toString(),
      content: messageToSend,
      role: 'user' as const,
      timestamp: new Date().toISOString(),
      fileUri: isFirstMessage ? character?.fileUrl : stagedFile?.uri,
      // 如果是第一条消息，就从 character.fileUrl 中解析文件名
      // 否则，使用聊天时临时上传的文件名
      fileName: isFirstMessage
        ? character?.fileUrl?.split('/').pop() || 'Character File'
        : stagedFile?.name,
      filePreviewUrl: isFirstMessage ? character?.fileUrl : stagedFile?.previewUrl,
      fileType: isFirstMessage ? undefined : stagedFile?.type,
    };
    // --- ▲▲▲ 修正结束 ▲▲▲ ---
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

      // --- ▼▼▼ 核心修正：移除过早的URL销毁逻辑 ▼▼▼ ---
      // 之前这里的代码过早地销毁了 blob URL，导致放大功能失效。
      // if (stagedFile?.previewUrl) {
      //   URL.revokeObjectURL(stagedFile.previewUrl);
      // }
      
      // 我们仍然需要在发送后清空已暂存的文件状态
      setStagedFile(null);
      // --- ▲▲▲ 修正结束 ▲▲▲ ---

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

    // REMOVED: The "USER MESSAGE" section has been completely removed from this initial prompt.
    promptSections.push(`Please provide your initial greeting based on your character settings.`);

    return promptSections.join('\n');
  };

  // --- ▼▼▼ 请用下面的代码块【替换】您现有的 handleSaveCharacter 函数，以优化判断逻辑 ▼▼▼ ---
  const handleSaveCharacter = async (characterData: Character, file?: File) => {
    dispatch(setLoading(true));
    dispatch(setError(null));

    try {
      const originalCharacter = character;
      const shouldClearFile = !!(originalCharacter?.fileUrl && !characterData.fileUrl && !file);

      const payload = {
        name: characterData.name,
        description: characterData.description,
        personality: characterData.personality,
        appearance: characterData.appearance,
        response_guidelines: characterData.responseGuidelines,
        clear_file: shouldClearFile,
        // --- ▼▼▼ 核心修正：将 disabled 状态发送到后端 ▼▼▼ ---
        // 我们将其命名为 disabled_states 以匹配后端模型
        disabled_states: characterData.disabled,
        // --- ▲▲▲ 修正结束 ▲▲▲ ---
      };

      let response;
      // 优化判断：如果Redux中已有角色且有ID，则更新；否则，创建。
      if (character && character.id) {
        response = await apiService.updateCharacter(String(character.id), payload, file);
      } else {
        response = await apiService.createCharacter(payload, file);
      }
      
      if (response.error) {
        throw new Error(response.error);
      }

      const serverResponseData = response.data;
      const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL?.replace('/api', '');
      
      const savedCharacter: Character = {
        ...characterData,
        id: String(serverResponseData.id),
        name: serverResponseData.name,
        description: serverResponseData.description,
        personality: serverResponseData.personality,
        appearance: serverResponseData.appearance,
        fileUrl: serverResponseData.file ? `${apiBaseUrl}${serverResponseData.file}` : undefined,
        responseGuidelines: serverResponseData.response_guidelines,
        // --- ▼▼▼ 核心修正：使用从服务器返回的、已保存的 disabled_states 更新UI ▼▼▼ ---
        disabled: serverResponseData.disabled_states,
        // --- ▲▲▲ 修正结束 ▲▲▲ ---
      };
      
      dispatch(setCharacter(savedCharacter));
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
  // --- ▲▲▲ 替换结束 ▲▲▲ ---

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

    // --- ▼▼▼ 在这里添加代码 ▼▼▼ ---
    // If a file was already staged, revoke its preview URL first
    if (stagedFile?.previewUrl) {
      URL.revokeObjectURL(stagedFile.previewUrl);
    }
    // --- ▲▲▲ 添加结束 ▲▲▲ ---

    // If it's an image, create a local preview URL
    let previewUrl: string | undefined;
    if (file.type.startsWith('image/')) {
      previewUrl = URL.createObjectURL(file);
    }

    setIsChatUploading(true);
    const response = await apiService.uploadImage(file);
    setIsChatUploading(false);

    if (response.data) {
      setStagedFile({
        name: file.name,
        uri: response.data.name,
        type: file.type,
        previewUrl: previewUrl
      });
    } else {
      alert(`File upload failed: ${response.error}`);
      // If upload failed, ensure to clean up the created preview URL
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
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
            onStagedFileRemove={() => {
              // --- ▼▼▼ 修改这里的逻辑 ▼▼▼ ---
              if (stagedFile?.previewUrl) {
                URL.revokeObjectURL(stagedFile.previewUrl);
              }
              setStagedFile(null);
              // --- ▲▲▲ 修改结束 ▲▲▲ ---
            }}
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
