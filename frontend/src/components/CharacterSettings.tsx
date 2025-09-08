"use client";

import { useState, useEffect } from 'react';
import { Character, RootState } from '@/types';
import { useDispatch, useSelector } from 'react-redux';
import { setCharacter, updateCharacter } from '@/store/chatSlice';
import FileDropzone from './FileDropzone';
import { apiService } from '@/utils/api';

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
  const [fileName, setFileName] = useState<string | null>(character?.filePreviewUrl || null);
  const [isUploading, setIsUploading] = useState(false);

  // Clean up the object URL to prevent memory leaks
  useEffect(() => {
    return () => {
      if (fileName && fileName.startsWith('blob:')) {
        URL.revokeObjectURL(fileName);
      }
    };
  }, [fileName]);

  const dispatch = useDispatch();
  const currentCharacter = useSelector((state: RootState) => state.chat.character);

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
  };

  const handleFileRemove = () => {
    setSelectedFile(null);
    setFileName(null);
    // That's it. No need to modify formData here.
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

    let finalFileUrl = character?.fileUrl;

    // If a new file has been selected, upload it
    if (selectedFile) {
      const response = await apiService.uploadImage(selectedFile);
      if (response.data?.uri) {
        finalFileUrl = response.data.uri;
      } else {
        console.error("Image upload failed:", response.error);
        alert("Error: Could not upload the file. Please try again.");
        setIsUploading(false);
        return; // Stop the submission process
      }
    } else if (!fileName) {
      // If the file was removed, ensure the URL is cleared
      finalFileUrl = undefined;
    }

    const updatedCharacter: Character = {
      ...character,
      ...formData,
      id: character?.id || Date.now().toString(),
      fileUrl: finalFileUrl,
      filePreviewUrl: fileName || undefined,
    };
    
    // The onSave prop now handles the actual API call to save the character
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