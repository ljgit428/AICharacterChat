"use client";

import { useState, useEffect, useRef, DragEvent } from 'react';
import { Character, CharacterFile, RootState } from '@/types';
import { useDispatch, useSelector } from 'react-redux';
import { setCharacter, updateCharacter, saveCharacter } from '@/store/chatSlice';
import { apiService } from '@/utils/api';

interface CharacterSettingsProps {
  character?: Character;
  onSave: (character: Character) => void;
  onCancel: () => void;
}

export default function CharacterSettings({ character, onSave, onCancel }: CharacterSettingsProps) {
  const [formData, setFormData] = useState({
    name: character?.name || '',
    description: character?.description || '',
    personality: character?.personality || '',
    appearance: character?.appearance || '',
    requirement: character?.requirement || '',
    disabled: character?.disabled || {
      name: false,
      description: false,
      personality: false,
      appearance: false,
      requirement: false,
    },
  });

  // Manage new selected files (for upload)
  const [newFiles, setNewFiles] = useState<File[]>([]);
  // Manage existing files (for display and deletion)
  const [existingFiles, setExistingFiles] = useState<CharacterFile[]>(character?.background_files || []);

  // New state for tracking drag status to provide visual feedback
  const [isDragging, setIsDragging] = useState(false);
  
  // Create a ref to reference the file input element
  const fileInputRef = useRef<HTMLInputElement>(null);

  const dispatch = useDispatch();
  const currentCharacter = useSelector((state: RootState) => state.chat.character);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value
    }));
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      // Append new files to the list
      setNewFiles(prev => [...prev, ...Array.from(e.target.files!)]);
    }
  };

  // New drag event handlers
  const handleDragEnter = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };
  
  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault(); // This is key to allowing a drop
    e.stopPropagation();
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      // Add dropped files to our file list
      setNewFiles(prev => [...prev, ...Array.from(files)]);
    }
  };

  const handleRemoveNewFile = (fileToRemove: File) => {
    setNewFiles(prev => prev.filter(file => file !== fileToRemove));
    
    // Reset the file input value to clear the native file selection
    // This clears the browser's internal file selection state (e.g., "2 files selected" text)
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };
  
  const handleRemoveExistingFile = async (fileToRemove: CharacterFile) => {
    if (!character?.id) return;
    try {
      // Call the new delete API
      await apiService.deleteCharacterFile(character.id, fileToRemove.id);
      // Remove from UI state
      setExistingFiles(prev => prev.filter(file => file.id !== fileToRemove.id));
    } catch (error) {
      console.error("Failed to delete file:", error);
      // You could add a user notification here
    }
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

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    
    // Create FormData for API call
    const characterFormData = new FormData();
    characterFormData.append('name', formData.name);
    characterFormData.append('description', formData.description);
    characterFormData.append('personality', formData.personality);
    characterFormData.append('appearance', formData.appearance);
    characterFormData.append('requirement', formData.requirement);
    
    // Add all new selected files
    // Note: backend key is 'background_documents' (plural)
    newFiles.forEach(file => {
      characterFormData.append('background_documents', file);
    });
    
    // Create character object for Redux store
    const characterObject = {
      ...formData,
      id: character?.id || Date.now().toString(),
      disabled: formData.disabled,
      background_files: existingFiles
    };
    
    // Dispatch the thunk instead of directly calling API
    dispatch(saveCharacter({
      id: character?.id,
      formData: characterFormData
    }) as any);
    
    // Optimistically update the UI
    if (character) {
      dispatch(updateCharacter(characterObject));
    } else {
      dispatch(setCharacter(characterObject));
    }
    
    onSave(characterObject);
  };

  // Create a function to trigger the hidden file input
  const handleDropZoneClick = () => {
    fileInputRef.current?.click();
  };

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6 h-full w-[200%]">
      <h2 className="text-xl font-bold mb-4">
        {character ? 'Edit Character' : 'Create New Character'}
      </h2>
      
      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Left Column - Basic Character Information */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="space-y-4">
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
          </div>

          {/* Right Column - Response Guidelines and Background Documents */}
          <div className="space-y-6">
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-sm font-medium text-gray-700">
                  Response Guidelines
                </label>
                <button
                  type="button"
                  onClick={() => handleDisableToggle('requirement')}
                  className={`px-2 py-1 text-xs rounded ${
                    formData.disabled.requirement
                      ? 'bg-red-100 text-red-800 hover:bg-red-200'
                      : 'bg-green-100 text-green-800 hover:bg-green-200'
                  } transition-colors`}
                >
                  {formData.disabled.requirement ? 'Enable' : 'Disable'}
                </button>
              </div>
              <textarea
                name="requirement"
                value={formData.requirement}
                onChange={handleInputChange}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                rows={6}
                placeholder="Enter response guidelines for your character"
                required={!formData.disabled.requirement}
                disabled={formData.disabled.requirement}
              />
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-sm font-medium text-gray-700">
                  Background Documents
                </label>
              </div>
              {/* File list display */}
              <div className="space-y-2 mt-2">
                {/* Existing files */}
                {existingFiles.map(file => (
                  <div key={file.id} className="flex items-center justify-between bg-gray-100 p-2 rounded">
                    <span className="text-sm text-gray-700">{file.original_filename}</span>
                    <button
                      type="button"
                      onClick={() => handleRemoveExistingFile(file)}
                      className="text-red-500 hover:text-red-700 font-bold"
                    >
                      &times;
                    </button>
                  </div>
                ))}
                {/* New selected files */}
                {newFiles.map((file, index) => (
                  <div key={index} className="flex items-center justify-between bg-blue-50 p-2 rounded">
                    <span className="text-sm text-blue-700">{file.name}</span>
                    <button
                      type="button"
                      onClick={() => handleRemoveNewFile(file)}
                      className="text-red-500 hover:text-red-700 font-bold"
                    >
                      &times;
                    </button>
                  </div>
                ))}
              </div>
              
              {/* New modern drag-and-drop upload area */}
              <div
                className={`mt-2 p-6 border-2 border-dashed rounded-lg text-center cursor-pointer transition-colors
                  ${isDragging ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400'}`}
                onDragEnter={handleDragEnter}
                onDragLeave={handleDragLeave}
                onDragOver={handleDragOver}
                onDrop={handleDrop}
                onClick={handleDropZoneClick} // Clicking the area also opens file selector
              >
                <p className="text-gray-500">
                  {isDragging ? 'Drop files here' : 'Drag & Drop files here, or click to select'}
                </p>
                {/* Hidden native file input */}
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept=".txt,.pdf,.doc,.docx"
                  onChange={handleFileChange}
                  className="hidden"
                />
              </div>
            </div>
          </div>
        </div>

        <div className="flex space-x-3 pt-4">
          <button
            type="submit"
            className="bg-blue-500 text-white px-4 py-2 rounded-lg hover:bg-blue-600 transition-colors"
          >
            {character ? 'Update Character' : 'Create Character'}
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