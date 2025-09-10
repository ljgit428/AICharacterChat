"use client";

import { useState, useEffect } from 'react';
import { Character } from '@/types';
import FileDropzone from './FileDropzone';

interface CharacterSettingsProps {
  character?: Character;
  onSave: (character: Character, file?: File) => void;
  onCancel: () => void;
}

export default function CharacterSettings({ character, onSave, onCancel }: CharacterSettingsProps) {
  const [formData, setFormData] = useState({
    name: character?.name || '',
    description: character?.description || '',
    personality: character?.personality || '',
    appearance: character?.appearance || '',
    responseGuidelines: character?.responseGuidelines || '',
    disabled: character?.disabled || {
      name: false,
      description: false,
      personality: false,
      appearance: false,
      responseGuidelines: false,
      file: false,
    },
  });

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  
  // --- ▼▼▼ 核心状态管理逻辑修正 ▼▼▼ ---
  const [fileName, setFileName] = useState<string | null>(character?.fileUrl?.split('/').pop() || null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(character?.fileUrl || null); // 直接使用来自Redux的相对路径
  // --- ▲▲▲ 修正结束 ▲▲▲ ---

  // 清理临时的blob URL
  useEffect(() => {
    return () => {
      if (previewUrl && previewUrl.startsWith('blob:')) {
        URL.revokeObjectURL(previewUrl);
      }
    };
  }, [previewUrl]);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value
    }));
  };

  const handleFileSelect = (file: File) => {
    setSelectedFile(file);
    setFileName(file.name);
    
    // 如果是图片，创建本地预览URL
    if (file.type.startsWith('image/')) {
      const localPreviewUrl = URL.createObjectURL(file);
      if (previewUrl && previewUrl.startsWith('blob:')) {
        URL.revokeObjectURL(previewUrl);
      }
      setPreviewUrl(localPreviewUrl);
    } else {
      setPreviewUrl(null);
    }
  };

  const handleFileRemove = () => {
    setSelectedFile(null);
    setFileName(null);
    if (previewUrl && previewUrl.startsWith('blob:')) {
      URL.revokeObjectURL(previewUrl);
    }
    setPreviewUrl(null);
  };

  const handleDisableToggle = (attribute: keyof typeof formData.disabled) => {
    setFormData(prev => ({
      ...prev,
      disabled: {
        ...prev.disabled,
        [attribute]: !prev.disabled[attribute]
      }
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsUploading(true);
    
    const updatedCharacter: Character = {
      ...character,
      ...formData,
      id: character?.id || `temp-${Date.now()}`,
      // 当提交时，让父组件处理URL的更新
      fileUrl: character?.fileUrl, 
      filePreviewUrl: previewUrl || undefined, // 传递当前的预览URL
    };
    
    await onSave(updatedCharacter, selectedFile || undefined);
    
    setIsUploading(false);
  };

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6 h-full">
      <h2 className="text-xl font-bold mb-4">
        {character ? 'Edit Character' : 'Create New Character'}
      </h2>
      
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Image Upload Section */}
        <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Character File (Image, PDF, etc.)
            </label>
            <FileDropzone
              onFileSelect={handleFileSelect}
              onFileRemove={handleFileRemove}
              fileName={fileName}
              previewUrl={previewUrl}
            />
        </div>
        
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="block text-sm font-medium text-gray-700">
              Character Name
            </label>
            <button
              type="button"
              onClick={() => handleDisableToggle('name')}
              className={`px-2 py-1 text-xs rounded ${
                formData.disabled.name
                  ? 'bg-red-100 text-red-800 hover:bg-red-200'
                  : 'bg-green-100 text-green-800 hover:bg-green-200'
              } transition-colors`}
            >
              {formData.disabled.name ? 'Enable' : 'Disable'}
            </button>
          </div>
          <input
            type="text"
            name="name"
            value={formData.name}
            onChange={handleInputChange}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Enter character name"
            required={!formData.disabled.name}
            disabled={formData.disabled.name}
          />
        </div>

        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="block text-sm font-medium text-gray-700">
              Description
            </label>
            <button
              type="button"
              onClick={() => handleDisableToggle('description')}
              className={`px-2 py-1 text-xs rounded ${
                formData.disabled.description
                  ? 'bg-red-100 text-red-800 hover:bg-red-200'
                  : 'bg-green-100 text-green-800 hover:bg-green-200'
              } transition-colors`}
            >
              {formData.disabled.description ? 'Enable' : 'Disable'}
            </button>
          </div>
          <textarea
            name="description"
            value={formData.description}
            onChange={handleInputChange}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            rows={3}
            placeholder="Describe your character"
            required={!formData.disabled.description}
            disabled={formData.disabled.description}
          />
        </div>

        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="block text-sm font-medium text-gray-700">
              Personality
            </label>
            <button
              type="button"
              onClick={() => handleDisableToggle('personality')}
              className={`px-2 py-1 text-xs rounded ${
                formData.disabled.personality
                  ? 'bg-red-100 text-red-800 hover:bg-red-200'
                  : 'bg-green-100 text-green-800 hover:bg-green-200'
              } transition-colors`}
            >
              {formData.disabled.personality ? 'Enable' : 'Disable'}
            </button>
          </div>
          <textarea
            name="personality"
            value={formData.personality}
            onChange={handleInputChange}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            rows={4}
            placeholder="Describe your character's personality"
            required={!formData.disabled.personality}
            disabled={formData.disabled.personality}
          />
        </div>

        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="block text-sm font-medium text-gray-700">
              Appearance
            </label>
            <button
              type="button"
              onClick={() => handleDisableToggle('appearance')}
              className={`px-2 py-1 text-xs rounded ${
                formData.disabled.appearance
                  ? 'bg-red-100 text-red-800 hover:bg-red-200'
                  : 'bg-green-100 text-green-800 hover:bg-green-200'
              } transition-colors`}
            >
              {formData.disabled.appearance ? 'Enable' : 'Disable'}
            </button>
          </div>
          <textarea
            name="appearance"
            value={formData.appearance}
            onChange={handleInputChange}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            rows={3}
            placeholder="Describe your character's appearance"
            required={!formData.disabled.appearance}
            disabled={formData.disabled.appearance}
          />
        </div>

        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="block text-sm font-medium text-gray-700">
              Response Guidelines
            </label>
            <button
              type="button"
              onClick={() => handleDisableToggle('responseGuidelines')}
              className={`px-2 py-1 text-xs rounded ${
                formData.disabled.responseGuidelines
                  ? 'bg-red-100 text-red-800 hover:bg-red-200'
                  : 'bg-green-100 text-green-800 hover:bg-green-200'
              } transition-colors`}
            >
              {formData.disabled.responseGuidelines ? 'Enable' : 'Disable'}
            </button>
          </div>
          <textarea
            name="responseGuidelines"
            value={formData.responseGuidelines}
            onChange={handleInputChange}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            rows={5}
            placeholder="Enter AI response guidelines (e.g., instructions on how to behave)"
            required={!formData.disabled.responseGuidelines}
            disabled={formData.disabled.responseGuidelines}
          />
        </div>

        <div className="flex space-x-3 pt-4">
          <button
            type="submit"
            className="bg-blue-500 text-white px-4 py-2 rounded-lg hover:bg-blue-600 transition-colors disabled:opacity-50"
            disabled={isUploading}
          >
            {isUploading ? 'Uploading...' : (character ? 'Update Character' : 'Create Character')}
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="bg-gray-200 text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-300 transition-colors"
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}