"use client";

import { useState, useEffect } from 'react';
import { useDispatch } from 'react-redux';
import { useSearchParams, useRouter } from 'next/navigation';
import {
  Home,
  Zap,
  Clock,
  LayoutGrid,
  PlusCircle,
  Settings,
  FileText,
  ChevronRight,
  ChevronLeft,
  Menu,
  MessageSquare,
  ArrowRight,
  Trash2,
} from 'lucide-react';
import CharacterGallery from '@/components/CharacterGallery';
import CreateCharacterForm from '@/components/CreateCharacterForm';
import ChatInterface from '@/components/ChatInterface';
import { clearChat } from '@/store/chatSlice';
import { apiService } from '@/utils/api';

type ViewState = 'home' | 'playground' | 'history_all' | 'characters' | 'create';

interface ChatHistoryItem {
  id: string;
  title: string;
  characterId: string;
  characterName?: string;
  created_at: string;
  updated_at: string;
}

export default function AIStudioLayout() {
  const [currentView, setCurrentView] = useState<ViewState>('playground');
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [selectedCharacterId, setSelectedCharacterId] = useState<string | null>(null);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [recentChats, setRecentChats] = useState<ChatHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [historyPage, setHistoryPage] = useState(1);
  const ITEMS_PER_PAGE = 10;

  const dispatch = useDispatch();
  
  const searchParams = useSearchParams();
  const router = useRouter();
  const autoSelectId = searchParams.get('select');

  useEffect(() => {
    if (autoSelectId) {
      setSelectedCharacterId(autoSelectId);
      setCurrentView('playground');
      setSelectedSessionId(null);
      dispatch(clearChat());
      
      router.replace('/');
    }
  }, [autoSelectId, dispatch, router]);

  const fetchChatSessions = async () => {
    try {
      setLoading(true);
      const response = await apiService.getChatSessions();

      if (response.error) {
        setError(response.error);
        return;
      }

      if (response.data) {
        const formattedChats: ChatHistoryItem[] = (response.data as unknown as import('@/types').ChatSession[]).map((session) => {
          const charId = session.character?.id || '';

          return {
            id: session.id,
            title: session.title || `Chat #${session.id}`,
            characterId: charId,
            characterName: session.character?.name || '',
            created_at: session.createdAt,
            updated_at: session.updatedAt
          };
        });

        const sortedSessions = formattedChats
          .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());

        setRecentChats(sortedSessions);
      }
    } catch (err) {
      console.error('Failed to fetch chat sessions:', err);
      setError('Failed to load conversation history');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchChatSessions();
  }, []);

  const handleSelectCharacter = (idOrObject: string | any) => {
    let safeId = '';

    if (typeof idOrObject === 'object' && idOrObject !== null) {
      safeId = idOrObject.id ? String(idOrObject.id) : '';
    } else {
      safeId = String(idOrObject || '');
    }
    if (safeId === '[object Object]' || !safeId) {
      console.error("Critical Error: Invalid Character ID received in select:", idOrObject);
      return;
    }
    dispatch(clearChat());
    setSelectedCharacterId(safeId);
    setSelectedSessionId(null);
    setCurrentView('playground');
  };

  const handleBackToGallery = () => {
    setSelectedCharacterId(null);
    setCurrentView('playground');
  };

  const handleSelectHistoryItem = (characterId: string | any, sessionId: string) => {
    let safeCharId = '';
    if (characterId && typeof characterId === 'object') {
      safeCharId = characterId.id ? String(characterId.id) : '';
    } else {
      safeCharId = String(characterId || '');
    }
    if (safeCharId === '[object Object]' || !safeCharId) {
      console.warn("Invalid ID passed to history select, attempting recovery from list...", characterId);
      const chat = recentChats.find(c => c.id === sessionId);
      if (chat && chat.characterId && chat.characterId !== '[object Object]') {
        safeCharId = chat.characterId;
      }
    }
    if (!safeCharId || safeCharId === '[object Object]') {
      console.error("Cannot load session: Character ID is invalid.");
      setError("Error: Could not identify character for this session.");
      return;
    }

    setSelectedCharacterId(safeCharId);
    setSelectedSessionId(String(sessionId));
    setCurrentView('playground');
  };

  const handleHistoryClick = (sessionId: string) => {
    if (recentChats.length > 0) {
      const chat = recentChats.find(c => c.id === sessionId);
      if (chat) {
        handleSelectHistoryItem(chat.characterId, sessionId);
      }
    }
  };

  const handleDeleteSession = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    if (!window.confirm('Are you sure you want to delete this conversation history?')) {
      return;
    }

    try {
      await apiService.deleteChatSession(sessionId);
      const response = await apiService.getChatSessions();

      if (response.data) {
        const formattedChats: ChatHistoryItem[] = (response.data as unknown as import('@/types').ChatSession[]).map((session) => {
          const charId = session.character?.id || '';

          return {
            id: session.id,
            title: session.title || `Chat #${session.id}`,
            characterId: charId,
            characterName: session.character?.name || '',
            created_at: session.createdAt,
            updated_at: session.updatedAt
          };
        });

        const sortedSessions = formattedChats
          .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());
        setRecentChats(sortedSessions);
      }
    } catch (error) {
      console.error("Failed to delete session:", error);
      alert("Failed to delete session");
    }
  };

  return (
    <div className="flex h-screen w-full bg-white text-gray-700 font-sans">
      <aside
        className={`${isSidebarOpen ? 'w-[280px]' : 'w-0'} transition-all duration-300 ease-in-out flex-shrink-0 bg-white border-r border-gray-200 flex flex-col overflow-hidden`}
      >
        <div className="h-16 flex items-center px-4 border-b border-gray-100 flex-shrink-0">
          <div className="font-semibold text-xl text-gray-800 tracking-tight flex items-center gap-2">
            <span className="text-blue-600 text-2xl">✦</span> AI Character Studio
          </div>
        </div>
        <div className="flex-1 overflow-y-auto py-4 px-3 space-y-6">
          <div className="space-y-1">
            <NavItem
              icon={<Home size={18} />}
              label="Home"
              active={currentView === 'home'}
              onClick={() => setCurrentView('home')}
            />
          </div>
          <div>
            <div className="mb-1">
              <NavItem
                icon={<Zap size={18} />}
                label="Playground"
                active={currentView === 'playground'}
                onClick={() => {
                  setCurrentView('playground');
                  setSelectedCharacterId(null);
                  setSelectedSessionId(null);
                }}
                isPrimary
              />
            </div>
            <div className="ml-4 border-l border-gray-200 pl-2 mt-2 space-y-1">
              {loading && (
                <div className="px-3 py-2 text-sm text-gray-500">
                  Loading conversation history...
                </div>
              )}
              {error && (
                <div className="px-3 py-2 text-sm text-red-500">
                  {error}
                </div>
              )}
              {!loading && !error && recentChats.length > 0 && recentChats.slice(0, 5).map(chat => (
                <div key={chat.id} className="group relative flex items-center">
                  <button
                    onClick={() => handleSelectHistoryItem(chat.characterId, chat.id)}
                    className={`w-full text-left px-3 py-1.5 text-sm rounded truncate transition-colors flex items-center gap-2 pr-8 ${selectedSessionId === chat.id && currentView === 'playground'
                      ? 'bg-blue-50 text-blue-700 font-medium'
                      : 'text-gray-500 hover:text-gray-900 hover:bg-gray-100'
                      }`}
                    title={chat.title}
                  >
                    <MessageSquare size={14} className={`flex-shrink-0 ${selectedSessionId === chat.id ? 'text-blue-600' : 'opacity-70'}`} />
                    <span className="truncate">{chat.title}</span>
                  </button>
                  <button
                    onClick={(e) => handleDeleteSession(e, chat.id)}
                    className="absolute right-1 p-1 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded opacity-0 group-hover:opacity-100 transition-all"
                    title="Delete chat"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              ))}
              <button
                onClick={() => {
                  setCurrentView('history_all');
                  setSelectedSessionId(null);
                }}
                className={`w-full text-left px-3 py-2 text-sm font-medium rounded transition-colors flex items-center gap-2 group mt-1 ${currentView === 'history_all'
                  ? 'bg-blue-50 text-blue-700'
                  : 'text-gray-600 hover:text-blue-600 hover:bg-blue-50'
                  }`}
              >
                <span>View all history</span>
                <ArrowRight size={14} className={`transition-opacity ${currentView === 'history_all' ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`} />
              </button>
            </div>
          </div>
          <div>
            <div className="space-y-1">
              <NavItem
                icon={<PlusCircle size={18} />}
                label="New Character"
                active={currentView === 'create'}
                onClick={() => setCurrentView('create')}
              />
            </div>
          </div>

        </div>
      </aside>
      <main className="flex-1 flex flex-col h-full overflow-hidden relative bg-white">
        {!isSidebarOpen && (
          <div className="absolute top-4 left-4 z-10">
            <button onClick={() => setIsSidebarOpen(true)} className="p-2 bg-gray-100 rounded-md hover:bg-gray-200">
              <Menu size={20} />
            </button>
          </div>
        )}
        <header className="h-14 border-b border-gray-100 flex items-center justify-between px-4 flex-shrink-0">
          <div className="flex items-center gap-3">
            <button onClick={() => setIsSidebarOpen(!isSidebarOpen)} className="text-gray-500 hover:text-gray-800 transition-colors">
              <Menu size={20} />
            </button>
            <div className="text-sm font-medium text-gray-600">
              {currentView === 'playground' && 'Playground / Chat'}
              {currentView === 'create' && 'Build / Create New'}
              {currentView === 'history_all' && 'History / All'}
            </div>
          </div>
          <div className="text-xs text-gray-400">v0.0.5.3</div>
        </header>
        <div className="flex-1 overflow-hidden relative">
          {renderContent(currentView)}
        </div>
      </main>
    </div>
  );

  function renderContent(view: ViewState) {
    switch (view) {
      case 'playground':
        return selectedCharacterId ? (
          <div className="h-full flex flex-col">
            <ChatInterface
              characterId={selectedCharacterId}
              initialSessionId={selectedSessionId}
              onBack={handleBackToGallery}
              onSessionUpdate={fetchChatSessions}
            />
          </div>
        ) : (
          <div className="h-full overflow-y-auto">
            <CharacterGallery onSelect={handleSelectCharacter} />
          </div>
        );

      case 'create':
        return (
          <div className="h-full overflow-y-auto">
            <div className="max-w-5xl mx-auto py-8 px-6">
              <CreateCharacterForm />
            </div>
          </div>
        );

      case 'history_all':
        const totalPages = Math.ceil(recentChats.length / ITEMS_PER_PAGE);
        const startIndex = (historyPage - 1) * ITEMS_PER_PAGE;
        const currentHistoryItems = recentChats.slice(startIndex, startIndex + ITEMS_PER_PAGE);

        return (
          <div className="h-full overflow-y-auto bg-gray-50">
            <div className="p-6 md:p-10 max-w-6xl mx-auto">
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h2 className="text-2xl font-bold text-gray-800">Chat History</h2>
                  <p className="text-sm text-gray-500 mt-1">Manage your past conversations</p>
                </div>
                <button
                  onClick={() => {
                    fetchChatSessions();
                    setHistoryPage(1);
                  }}
                  className="px-4 py-2 bg-white border border-gray-300 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors shadow-sm"
                >
                  Refresh List
                </button>
              </div>

              {loading ? (
                <div className="flex justify-center py-20">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900"></div>
                </div>
              ) : recentChats.length > 0 ? (
                <>
                  <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden mb-6">
                    <div className="divide-y divide-gray-100">
                      {currentHistoryItems.map((chat) => (
                        <div
                          key={chat.id}
                          onClick={() => handleSelectHistoryItem(chat.characterId, chat.id)}
                          className="group flex items-center justify-between p-4 hover:bg-blue-50/50 transition-colors cursor-pointer"
                        >
                          <div className="flex items-center gap-4 min-w-0 flex-1 mr-4">
                            <div className="w-10 h-10 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center flex-shrink-0">
                              <MessageSquare size={20} />
                            </div>
                            <div className="min-w-0">
                              <h3 className="font-medium text-gray-900 truncate group-hover:text-blue-700 transition-colors">
                                {chat.title}
                              </h3>
                              <div className="flex items-center text-xs text-gray-500 mt-0.5 gap-2">
                                <span>ID: {chat.id}</span>
                                <span className="w-1 h-1 rounded-full bg-gray-300"></span>
                                <span>Character ID: {chat.characterId}</span>
                              </div>
                            </div>
                          </div>
                          <div className="flex items-center gap-4 flex-shrink-0">
                            <div className="text-right hidden sm:block">
                              <div className="text-sm text-gray-600 font-medium">
                                {chat.updated_at && !isNaN(new Date(chat.updated_at).getTime())
                                  ? new Date(chat.updated_at).toLocaleDateString()
                                  : 'Unknown Date'}
                              </div>
                              <div className="text-xs text-gray-400">
                                {chat.updated_at && !isNaN(new Date(chat.updated_at).getTime())
                                  ? new Date(chat.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                                  : ''}
                              </div>
                            </div>
                            <div className="flex items-center gap-2 border-l border-gray-100 pl-4">
                              <button
                                onClick={(e) => handleDeleteSession(e, chat.id)}
                                className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                                title="Delete conversation"
                              >
                                <Trash2 size={18} />
                              </button>
                              <div className="text-gray-300 group-hover:text-blue-400 transition-colors">
                                <ArrowRight size={20} />
                              </div>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {totalPages > 1 && (
                    <div className="flex items-center justify-center gap-2">
                      <button
                        onClick={() => setHistoryPage(p => Math.max(1, p - 1))}
                        disabled={historyPage === 1}
                        className="p-2 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        <ChevronLeft size={20} />
                      </button>

                      <span className="px-4 text-sm text-gray-600 font-medium">
                        Page {historyPage} of {totalPages}
                      </span>

                      <button
                        onClick={() => setHistoryPage(p => Math.min(totalPages, p + 1))}
                        disabled={historyPage === totalPages}
                        className="p-2 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        <ChevronRight size={20} />
                      </button>
                    </div>
                  )}
                </>
              ) : (
                <div className="text-gray-500 text-center py-20 bg-white rounded-xl border border-dashed border-gray-200">
                  <div className="w-16 h-16 bg-gray-50 rounded-full flex items-center justify-center mx-auto mb-4">
                    <MessageSquare size={32} className="text-gray-400" />
                  </div>
                  <p className="text-lg font-medium text-gray-900">No conversation history</p>
                  <p className="text-sm mt-1 max-w-sm mx-auto">Start chatting with characters in the Playground, and your conversations will appear here.</p>
                  <button
                    onClick={() => setCurrentView('playground')}
                    className="mt-6 px-6 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-medium shadow-sm"
                  >
                    Go to Playground
                  </button>
                </div>
              )}
            </div>
          </div >
        );

      case 'home':
        return (
          <div className="flex flex-col items-center justify-center h-full text-center space-y-6 p-8">
            <div className="w-16 h-16 bg-blue-100 text-blue-600 rounded-2xl flex items-center justify-center mb-4">
              <Zap size={32} />
            </div>
            <h1 className="text-3xl font-bold text-gray-800">Welcome to AI Character Studio</h1>
            <p className="text-gray-500 max-w-md">
              Build, customize, and chat with advanced AI characters. Start by creating a character or jumping into the playground.
            </p>
            <div className="flex gap-4 mt-4">
              <button onClick={() => setCurrentView('create')} className="px-6 py-3 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors">
                Create Character
              </button>
              <button onClick={() => setCurrentView('playground')} className="px-6 py-3 bg-white border border-gray-300 text-gray-700 rounded-lg font-medium hover:bg-gray-50 transition-colors">
                Go to Playground
              </button>
            </div>
          </div>
        );

      default:
        return <CharacterGallery onSelect={handleSelectCharacter} />;
    }
  }
}

function NavItem({
  icon,
  label,
  active = false,
  onClick,
  isPrimary = false
}: {
  icon: React.ReactNode,
  label: string,
  active?: boolean,
  onClick: () => void,
  isPrimary?: boolean
}) {
  return (
    <button
      onClick={onClick}
      className={`
        w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all duration-200
        ${active
          ? 'bg-blue-50 text-blue-700'
          : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
        }
        ${isPrimary && active ? 'bg-blue-100/50' : ''}
      `}
    >
      <span className={active ? 'text-blue-600' : 'text-gray-400'}>{icon}</span>
      <span>{label}</span>
    </button>
  );
}

function SectionHeader({ label }: { label: string }) {
  return (
    <div className="px-3 mb-2 mt-6 flex items-center justify-between group cursor-pointer">
      <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">{label}</span>
    </div>
  );
}