"use client";

import { useState } from 'react';
import { Character, RootState } from '@/types';
import { useDispatch, useSelector } from 'react-redux';
import { setCharacter, updateCharacter } from '@/store/chatSlice';

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
  });

  const dispatch = useDispatch();
  const currentCharacter = useSelector((state: RootState) => state.chat.character);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value
    }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const updatedCharacter = {
      ...formData,
      id: character?.id || Date.now().toString(),
    };
    
    if (character) {
      dispatch(updateCharacter(updatedCharacter));
    } else {
      dispatch(setCharacter(updatedCharacter));
    }
    
    onSave(updatedCharacter);
  };

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6 h-full">
      <h2 className="text-xl font-bold mb-4">
        {character ? 'Edit Character' : 'Create New Character'}
      </h2>
      
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Character Name
          </label>
          <input
            type="text"
            name="name"
            value={formData.name}
            onChange={handleInputChange}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Enter character name"
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Description
          </label>
          <textarea
            name="description"
            value={formData.description}
            onChange={handleInputChange}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            rows={3}
            placeholder="Describe your character"
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Personality
          </label>
          <textarea
            name="personality"
            value={formData.personality}
            onChange={handleInputChange}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            rows={4}
            placeholder="Describe your character's personality"
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Appearance
          </label>
          <textarea
            name="appearance"
            value={formData.appearance}
            onChange={handleInputChange}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            rows={3}
            placeholder="Describe your character's appearance"
            required
          />
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