"use client";

import { useEffect, useRef } from 'react';
import Image from 'next/image';
import { Message, RootState } from '@/types';
import { useSelector } from 'react-redux';
import ImageMagnifier from './ImageMagnifier';

interface ChatWindowProps {
  onSendMessage: (message: string) => void;
  isLoading: boolean;
  isFirstMessage: boolean;
  stagedFile: { name: string; uri: string; type: string; previewUrl?: string } | null;
  onStagedFileRemove: () => void;
  onFileUploadClick: () => void;
  isChatUploading: boolean;
}

export default function ChatWindow({
  onSendMessage,
  isLoading,
  isFirstMessage,
  stagedFile,
  onStagedFileRemove,
  onFileUploadClick,
  isChatUploading
}: ChatWindowProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messages = useSelector((state: RootState) => state.chat.messages);
  
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleKeyPress = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (isFirstMessage) return; // Ignore Enter key before conversation starts

      const textarea = e.target as HTMLTextAreaElement;
      const message = textarea.value.trim();
      if (message) {
        onSendMessage(message);
        textarea.value = '';
      }
    }
  };

  const formatTimestamp = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  return (
    <div className="flex flex-col h-full bg-gray-50 rounded-lg border border-gray-200">
      {/* Messages Container */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 ? (
          <div className="flex items-center justify-center h-full text-gray-500">
            <div className="text-center">
              <div className="text-4xl mb-4">👋</div>
              <p>Click &quot;Start&quot; below to begin the conversation!</p>
            </div>
          </div>
        ) : (
          messages.map((message: Message) => (
            <div
              key={message.id}
              className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-xs lg:max-w-md px-4 py-2 rounded-lg ${
                  message.role === 'user'
                    ? 'bg-blue-500 text-white'
                    : 'bg-white border border-gray-200 text-gray-800'
                }`}
              >
                <div className="flex items-center space-x-2 mb-1">
                  {message.role === 'assistant' && (
                    <div className="w-2 h-2 bg-green-500 rounded-full"></div>
                  )}
                  <span className="text-xs font-medium">
                    {message.role === 'user' ? 'You' : 'Character'}
                  </span>
                  <span className="text-xs opacity-70">
                    {formatTimestamp(message.timestamp)}
                  </span>
                </div>
                
                {/* --- vvv 修改：渲染图片预览或通用文件附件 vvv --- */}
                {message.filePreviewUrl ? (
                  <div className="mt-2">
                    <ImageMagnifier
                      src={message.filePreviewUrl}
                      alt={message.fileName || 'Attached image'}
                      className="max-w-full h-auto rounded-lg"
                      width={200}
                      height={200}
                    />
                  </div>
                ) : message.fileUri && (
                  <div className={`mt-2 p-2 rounded-lg flex items-center space-x-2 ${message.role === 'user' ? 'bg-blue-400' : 'bg-gray-100'}`}>
                    <svg className={`w-5 h-5 flex-shrink-0 ${message.role === 'user' ? 'text-white' : 'text-gray-600'}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"></path></svg>
                    <span className={`text-xs truncate ${message.role === 'user' ? 'text-white' : 'text-gray-700'}`}>
                      {message.fileName || 'Attached File'}
                    </span>
                  </div>
                )}
                {/* --- ^^^ 修改结束 ^^^ --- */}

                {/* Only show content if it exists */}
                {message.content && (
                  <p className="text-sm whitespace-pre-wrap mt-1">{message.content}</p>
                )}
              </div>
            </div>
          ))
        )}
        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-white border border-gray-200 rounded-lg px-4 py-2">
              <div className="flex items-center space-x-2">
                <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
                <span className="text-sm text-gray-600">Character is typing...</span>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="border-t border-gray-200 p-4">
        {/* Show uploading indicator */}
        {isChatUploading && (
           <div className="mb-2 p-2 bg-gray-100 rounded-lg text-sm text-gray-600">
             Uploading file...
           </div>
        )}
        
        {/* Show staged file */}
        {stagedFile && !isChatUploading && (
          <div className="mb-2 p-2 bg-blue-100 rounded-lg relative">
            {stagedFile.previewUrl ? (
              <div>
                <ImageMagnifier
                  src={stagedFile.previewUrl}
                  alt="Preview"
                  className="max-h-32 rounded-md mx-auto"
                  width={128}
                  height={128}
                />
                <p className="text-center text-xs text-blue-800 mt-1 truncate">{stagedFile.name}</p>
              </div>
            ) : (
              <div className="flex items-center justify-between text-blue-800 text-sm">
                <div className="flex items-center space-x-2 truncate">
                  <svg className="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"></path></svg>
                  <span className="truncate">{stagedFile.name}</span>
                </div>
                <button onClick={onStagedFileRemove} className="font-bold text-lg leading-none">&times;</button>
              </div>
            )}
          </div>
        )}
        
        <div className="flex space-x-2">
          {/* File upload button */}
          <button
            onClick={onFileUploadClick}
            className="p-2 border border-gray-300 rounded-lg hover:bg-gray-100 disabled:opacity-50"
            disabled={isLoading || isFirstMessage || isChatUploading}
          >
            <svg className="w-6 h-6 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"></path></svg>
          </button>
          <textarea
            className="flex-1 border border-gray-300 rounded-lg px-3 py-2 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100"
            placeholder={isFirstMessage ? "Click 'Start' to begin." : "Type your message..."}
            rows={2}
            onKeyDown={handleKeyPress}
            disabled={isLoading || isFirstMessage}
          />
          <button
            className="bg-blue-500 text-white px-4 py-2 rounded-lg hover:bg-blue-600 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
            // MODIFICATION: Simplified onClick logic
            onClick={() => {
              const textarea = document.querySelector('textarea') as HTMLTextAreaElement;
              onSendMessage(textarea.value.trim()); // Pass the content, handleSendMessage will ignore it if it's the first message
              textarea.value = '';
            }}
            disabled={isLoading}
          >
            {isFirstMessage ? 'Start' : 'Send'}
          </button>
        </div>
        <p className="text-xs text-gray-500 mt-2">
          Press Enter to send, Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}