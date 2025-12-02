"use client";

import { useState } from 'react';
import { ChatSession } from '@/types';
import { X, Save, Clock, User, Search, Languages, FileText } from 'lucide-react';

interface SessionSettingsProps {
  chatSession: ChatSession | null;
  onSave: (sessionData: Partial<ChatSession>) => void;
  onCancel: () => void;
}

export default function SessionSettings({ chatSession, onSave, onCancel }: SessionSettingsProps) {
  const [sessionData, setSessionData] = useState<Partial<ChatSession>>({
    worldTime: chatSession?.worldTime || 'Current time',
    userPersona: chatSession?.userPersona || '',
    enableWebSearch: chatSession?.enableWebSearch || true,
    outputLanguage: chatSession?.outputLanguage || 'English',
    additionalContext: chatSession?.additionalContext || '',
  });

  const handleInputChange = (field: keyof Partial<ChatSession>, value: string | boolean) => {
    setSessionData(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const handleSave = () => {
    onSave(sessionData);
  };

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold text-gray-800">Session Settings</h2>
        <button
          onClick={onCancel}
          className="p-2 rounded-lg hover:bg-gray-100 text-gray-600 transition-colors"
        >
          <X size={20} />
        </button>
      </div>

      <div className="space-y-6">
        <div className="space-y-2">
          <label className="flex items-center text-sm font-medium text-gray-700">
            <Clock size={16} className="mr-2" />
            World Time
          </label>
          <input
            type="text"
            value={sessionData.worldTime || ''}
            onChange={(e) => handleInputChange('worldTime', e.target.value)}
            placeholder="e.g. Dec 11, 2025 6:30PM"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
          <p className="text-xs text-gray-500">Set the simulated time for this conversation</p>
        </div>

        <div className="space-y-2">
          <label className="flex items-center text-sm font-medium text-gray-700">
            <User size={16} className="mr-2" />
            User Persona
          </label>
          <input
            type="text"
            value={sessionData.userPersona || ''}
            onChange={(e) => handleInputChange('userPersona', e.target.value)}
            placeholder="e.g. Sensei, Friend, Stranger"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
          <p className="text-xs text-gray-500">Define your role in this conversation</p>
        </div>

        <div className="space-y-2">
          <label className="flex items-center text-sm font-medium text-gray-700">
            <Search size={16} className="mr-2" />
            Enable Web Search
          </label>
          <div className="flex items-center">
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={sessionData.enableWebSearch || false}
                onChange={(e) => handleInputChange('enableWebSearch', e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
            </label>
            <span className="ml-3 text-sm text-gray-600">
              {sessionData.enableWebSearch ? 'Enabled' : 'Disabled'}
            </span>
          </div>
          <p className="text-xs text-gray-500">Allow AI to search the internet for information</p>
        </div>

        <div className="space-y-2">
          <label className="flex items-center text-sm font-medium text-gray-700">
            <Languages size={16} className="mr-2" />
            Output Language
          </label>
          <select
            value={sessionData.outputLanguage || 'English'}
            onChange={(e) => handleInputChange('outputLanguage', e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="English">English</option>
            <option value="Simplified Chinese">Simplified Chinese</option>
            <option value="Traditional Chinese">Traditional Chinese</option>
            <option value="Japanese">Japanese</option>
          </select>
          <p className="text-xs text-gray-500">Language for AI responses</p>
        </div>

        <div className="space-y-2">
          <label className="flex items-center text-sm font-medium text-gray-700">
            <FileText size={16} className="mr-2" />
            Additional Context
          </label>
          <textarea
            value={sessionData.additionalContext || ''}
            onChange={(e) => handleInputChange('additionalContext', e.target.value)}
            placeholder="Additional instructions or context for this session..."
            rows={4}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
          <p className="text-xs text-gray-500">Special instructions for this conversation</p>
        </div>
      </div>

      <div className="flex justify-end space-x-3 mt-8">
        <button
          onClick={onCancel}
          className="px-4 py-2 text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={handleSave}
          className="px-4 py-2 text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors flex items-center"
        >
          <Save size={16} className="mr-2" />
          Save Settings
        </button>
      </div>
    </div>
  );
}