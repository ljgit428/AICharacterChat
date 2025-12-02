"use client";

import { useState, useRef, useCallback, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useMutation, useQuery, gql } from '@apollo/client';
import { useDispatch } from 'react-redux';
import { setCharacter } from '@/store/chatSlice';
import {
  Upload,
  Sparkles,
  Save,
  Image as ImageIcon,
  Wand2,
  Loader2,
  Tag,
  FileText,
  PenTool,
  ArrowRight,
  User,
  ArrowLeft
} from 'lucide-react';

const GENERATE_DRAFT = gql`
  mutation GenerateDraft($imageUrl: String, $textContext: String) {
    generateCharacterDraft(imageUrl: $imageUrl, textContext: $textContext) {
      name
      description
      personality
      appearance
      affiliation
      firstMessage
      scenario
      tags
    }
  }
`;

const CREATE_CHARACTER = gql`
  mutation CreateCharacter($input: CharacterInput!) {
    createCharacter(input: $input) {
      id
      name
    }
  }
`;

const GET_CHARACTER = gql`
  query GetCharacter($id: ID!) {
    character(id: $id) {
      id
      name
      description
      personality
      appearance
      firstMessage
      scenario
      exampleDialogue
      affiliation
      tags
      avatarUrl
    }
  }
`;

const UPDATE_CHARACTER = gql`
  mutation UpdateCharacter($id: ID!, $input: CharacterInput!) {
    updateCharacter(id: $id, input: $input) {
      id
      name
    }
  }
`;

export default function CreateCharacterForm({ characterId }: { characterId?: string }) {
  const router = useRouter();
  const dispatch = useDispatch();

  const isEditMode = !!characterId;

  const [activeTab, setActiveTab] = useState<'auto' | 'manual'>(
    isEditMode ? 'manual' : 'auto'
  );
  const [form, setForm] = useState({
    name: '',
    description: '',
    personality: '',
    appearance: '',
    affiliation: '',
    firstMessage: '',
    scenario: '',
    exampleDialogue: '',
    tags: '',
    avatarUrl: ''
  });

  // Input state exclusive to Auto Mode
  const [autoInputText, setAutoInputText] = useState('');
  const [autoFile, setAutoFile] = useState<{ file: File, url: string, type: 'image' | 'file' } | null>(null);
  const [autoTargetName, setAutoTargetName] = useState('');

  // Drag and drop state
  const [isDragging, setIsDragging] = useState(false);

  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [generateDraft, { loading: aiLoading }] = useMutation(GENERATE_DRAFT);
  const [createCharacter, { loading: saveLoading }] = useMutation(CREATE_CHARACTER);
  const [updateCharacter] = useMutation(UPDATE_CHARACTER);

  const { data, loading } = useQuery(GET_CHARACTER, {
    variables: { id: characterId },
    skip: !isEditMode,
  });

  useEffect(() => {
    if (data?.character) {
      const char = data.character;
      setForm({
        name: char.name || '',
        description: char.description || '',
        personality: char.personality || '',
        appearance: char.appearance || '',
        firstMessage: char.firstMessage || '',
        scenario: char.scenario || '',
        exampleDialogue: char.exampleDialogue || '',
        affiliation: char.affiliation || '',
        tags: Array.isArray(char.tags) ? char.tags.join(', ') : '',
        avatarUrl: char.avatarUrl || ''
      });
      setActiveTab('manual');
    }
  }, [data]);


  // Core upload logic (Extracted for shared use by Drop and Click)
  const processFileUpload = async (file: File, isAutoMode: boolean) => {
    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch('http://localhost:8000/api/upload/', { method: 'POST', body: formData });
      if (!res.ok) throw new Error("Upload failed");
      const data = await res.json();

      if (isAutoMode) {
        const isImage = file.type.startsWith('image/');
        setAutoFile({ file, url: data.url, type: isImage ? 'image' : 'file' });
        if (isImage) {
          setForm(prev => ({ ...prev, avatarUrl: data.url }));
        }
      } else {
        setForm(prev => ({ ...prev, avatarUrl: data.url }));
      }
    } catch (err) {
      console.error(err);
      alert("Upload failed");
    } finally {
      setUploading(false);
    }
  };

  // Handle click upload (Input Change)
  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>, isAutoMode: boolean = false) => {
    const file = e.target.files?.[0];
    if (file) {
      processFileUpload(file, isAutoMode);
    }
  };

  // --- Drag & Drop Events ---
  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const onDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  }, []);

  const onDrop = useCallback((e: React.DragEvent, isAutoMode: boolean) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const file = e.dataTransfer.files?.[0];
    if (file) {
      processFileUpload(file, isAutoMode);
    }
  }, []);

  // Core logic: AI generation and navigation
  const handleAiGenerate = async () => {
    if (!autoFile && !autoInputText.trim()) {
      alert("Please upload a file or enter a description.");
      return;
    }

    // Construct combined prompt
    let combinedContext = "";
    if (autoTargetName.trim()) {
      combinedContext += `TARGET CHARACTER NAME: ${autoTargetName.trim()}\n(Please focus ONLY on extracting details for this specific character from the provided file/text.)\n\n`;
    }
    combinedContext += `ADDITIONAL CONTEXT/STORY:\n${autoInputText}`;

    try {
      // Call AI
      const { data } = await generateDraft({
        variables: {
          imageUrl: autoFile?.url || "",
          textContext: combinedContext
        }
      });

      const draft = data.generateCharacterDraft;

      // In backend/chat/graphql/schema.py, we defined that when there's an error, it returns name="Generation Failed"
      if (draft.name === "Generation Failed") {

        alert(`AI Generation Failed:\n\n${draft.description}`);

        return;
      }

      setForm(prev => ({
        ...prev,
        name: draft.name && draft.name !== "Unknown" ? draft.name : (autoTargetName || prev.name),
        description: draft.description || prev.description,

        personality: draft.personality || prev.personality,
        appearance: draft.appearance || prev.appearance,
        affiliation: draft.affiliation || prev.affiliation,

        firstMessage: draft.firstMessage || prev.firstMessage,
        scenario: draft.scenario || prev.scenario,
        tags: draft.tags ? draft.tags.join(', ') : prev.tags,
        avatarUrl: (autoFile?.type === 'image' ? autoFile.url : prev.avatarUrl)
      }));

      setActiveTab('manual');

    } catch (err: any) {
      console.error("AI Generation Error", err);
      alert(`Request Error: ${err.message}`);
    }
  };

  const handleSave = async () => {
    if (!form.name.trim() || !form.description.trim()) {
      alert("Name and Description are required fields.");
      return;
    }

    if (form.name === "Generation Failed") {
      alert("Cannot save character with generation errors.");
      return;
    }

    try {
      const input = {
        name: form.name,
        description: form.description,
        personality: form.personality,
        appearance: form.appearance,
        affiliation: form.affiliation,
        avatarUrl: form.avatarUrl || "",
        firstMessage: form.firstMessage || "",
        scenario: form.scenario || "",
        exampleDialogue: form.exampleDialogue || "",
        tags: form.tags.split(/[,，]/).map(t => t.trim()).filter(Boolean)
      };

      if (isEditMode) {
        await updateCharacter({ variables: { id: characterId, input } });
      } else {
        await createCharacter({ variables: { input } });
      }

      window.location.href = '/';

    } catch (err: any) {
      console.error(err);
      alert(`Save failed: ${err.message}`);
    }
  };

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">

      <div className="flex flex-col md:flex-row justify-between items-center mb-8 gap-4">
        <div className="flex items-center">
          {isEditMode && (
            <button
              onClick={() => router.back()}
              className="group flex items-center justify-center w-10 h-10 rounded-full hover:bg-gray-100 transition-colors -ml-2 mr-1"
              title="Back"
            >
              <ArrowLeft className="w-5 h-5 text-gray-400 group-hover:text-gray-800 transition-colors" strokeWidth={2.5} />
            </button>
          )}
          <div>
            <h1 className="text-3xl font-bold text-gray-800 tracking-tight">
              {isEditMode ? 'Edit Character' : 'Character Studio'}
            </h1>
            <p className="text-gray-500 text-sm mt-1">
              {isEditMode ? 'Update your companion details' : 'Create your AI companion'}
            </p>
          </div>
        </div>

        <div className="bg-gray-100 p-1 rounded-xl flex items-center shadow-inner">
          <button
            onClick={() => setActiveTab('auto')}
            className={`flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 ${activeTab === 'auto'
              ? 'bg-white text-purple-700 shadow-sm ring-1 ring-black/5'
              : 'text-gray-500 hover:text-gray-700'
              }`}
          >
            <Sparkles size={16} />
            AI Auto-Create
          </button>
          <button
            onClick={() => setActiveTab('manual')}
            className={`flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 ${activeTab === 'manual'
              ? 'bg-white text-blue-700 shadow-sm ring-1 ring-black/5'
              : 'text-gray-500 hover:text-gray-700'
              }`}
          >
            <PenTool size={16} />
            Manual Edit
          </button>
        </div>
      </div>

      {activeTab === 'auto' && (
        <div className="animate-in fade-in slide-in-from-bottom-4 duration-300">
          <div className="bg-gradient-to-br from-purple-50 to-white p-8 rounded-3xl border border-purple-100 shadow-lg text-center max-w-3xl mx-auto">

            <div className="mb-8">
              <div className="w-16 h-16 bg-purple-100 text-purple-600 rounded-full flex items-center justify-center mx-auto mb-4">
                <Wand2 size={32} />
              </div>
              <h2 className="text-2xl font-bold text-gray-800">Magic Generation</h2>
              <p className="text-gray-600 mt-2 max-w-md mx-auto">
                Upload a character reference image, a novel chapter, or just describe your idea. AI will extract the details for you.
              </p>
            </div>

            <div className="space-y-6 text-left">
              <div
                onDragOver={onDragOver}
                onDragLeave={onDragLeave}
                onDrop={(e) => onDrop(e, true)}
                onClick={() => fileInputRef.current?.click()}
                className={`
                  border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all duration-200 ease-in-out
                  flex flex-col items-center justify-center min-h-[160px]
                  ${isDragging
                    ? 'border-purple-600 bg-purple-100 scale-[1.02]'
                    : autoFile
                      ? 'border-purple-500 bg-purple-50'
                      : 'border-gray-300 hover:border-purple-400 hover:bg-gray-50 bg-white'
                  }
                `}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  className="hidden"
                  onChange={(e) => handleFileInputChange(e, true)}
                />

                {uploading ? (
                  <div className="flex flex-col items-center text-purple-600 animate-pulse">
                    <Loader2 className="animate-spin mb-3" size={32} />
                    <span className="font-medium">Uploading file...</span>
                  </div>
                ) : autoFile ? (
                  <div className="flex flex-col items-center gap-3">
                    {autoFile.type === 'image' ? (
                      <div className="relative group">
                        <img src={autoFile.url} className="w-24 h-24 object-cover rounded-xl shadow-md" />
                        <div className="absolute inset-0 bg-black/40 rounded-xl flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity text-white text-xs font-medium">Change</div>
                      </div>
                    ) : (
                      <div className="w-20 h-20 bg-gray-100 rounded-xl flex items-center justify-center">
                        <FileText size={40} className="text-gray-400" />
                      </div>
                    )}
                    <div>
                      <p className="font-bold text-gray-800 truncate max-w-[200px]">{autoFile.file.name}</p>
                      <p className="text-xs text-purple-600 font-medium mt-1">Ready for analysis</p>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-col items-center gap-3 pointer-events-none">
                    <div className={`p-4 rounded-full ${isDragging ? 'bg-purple-200 text-purple-700' : 'bg-gray-100 text-gray-400'} transition-colors`}>
                      <Upload size={28} />
                    </div>
                    <div className="space-y-1">
                      <p className={`font-medium ${isDragging ? 'text-purple-700' : 'text-gray-600'}`}>
                        {isDragging ? "Drop it like it's hot!" : "Click or Drag & Drop to upload"}
                      </p>
                      <p className="text-xs text-gray-400">Image, PDF, or TXT</p>
                    </div>
                  </div>
                )}
              </div>

              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-2 flex items-center gap-2">
                  <User size={16} className="text-purple-600" />
                  Target Character Name (Optional)
                </label>
                <input
                  className="w-full px-4 py-3 bg-white border border-gray-200 rounded-xl focus:ring-2 focus:ring-purple-500/20 focus:border-purple-500 outline-none shadow-sm transition-all"
                  placeholder="e.g. Eden (If the file contains multiple characters)"
                  value={autoTargetName}
                  onChange={(e) => setAutoTargetName(e.target.value)}
                />
                <p className="text-xs text-gray-400 mt-1 ml-1">
                  Specify which character the AI should focus on from the uploaded file.
                </p>
              </div>

              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-2">Additional Context / Instructions</label>
                <textarea
                  className="w-full p-4 bg-white border border-gray-200 rounded-xl focus:ring-2 focus:ring-purple-500/20 focus:border-purple-500 outline-none h-32 resize-none shadow-sm"
                  placeholder="e.g. Focus on her sarcastic personality. (Or paste raw text here if no file uploaded)"
                  value={autoInputText}
                  onChange={(e) => setAutoInputText(e.target.value)}
                />
              </div>

              <button
                onClick={handleAiGenerate}
                disabled={aiLoading || uploading}
                className="w-full py-4 bg-gray-900 text-white rounded-xl font-bold text-lg hover:bg-black transition-transform active:scale-[0.99] shadow-xl flex items-center justify-center gap-2 disabled:opacity-70"
              >
                {aiLoading ? (
                  <>
                    <Loader2 className="animate-spin" /> Analyzing...
                  </>
                ) : (
                  <>
                    <Sparkles className="text-purple-400" /> Analyze & Generate Parameters
                  </>
                )}
              </button>
            </div>

          </div>
        </div>
      )}

      {activeTab === 'manual' && (
        <div className="animate-in fade-in slide-in-from-bottom-4 duration-300 grid grid-cols-1 lg:grid-cols-3 gap-8">

          <div className="lg:col-span-1 space-y-6">
            <div className="bg-white p-6 rounded-2xl border border-gray-200 shadow-sm text-center">
              <div className="w-40 h-40 bg-gray-100 rounded-full mx-auto mb-4 overflow-hidden relative group cursor-pointer border-4 border-white shadow-md">
                {form.avatarUrl ? (
                  <img src={form.avatarUrl} className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-gray-300">
                    <ImageIcon size={40} />
                  </div>
                )}
                <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <Upload className="text-white" />
                </div>
                <input
                  ref={fileInputRef}
                  type="file"
                  className="hidden"
                  onChange={(e) => handleFileInputChange(e, false)}
                />
              </div>
              <p className="text-sm text-gray-500">Click image to change avatar</p>
            </div>

            <div className="bg-blue-50 p-6 rounded-2xl border border-blue-100">
              <h3 className="font-bold text-blue-800 mb-3 flex items-center gap-2">
                <Sparkles size={18} />
                AI-Powered Tips
              </h3>
              <ul className="text-sm text-blue-700 space-y-2">
                <li className="flex items-start gap-2">
                  <ArrowRight size={14} className="mt-0.5 flex-shrink-0" />
                  <span>Generated from AI? Review and tweak the details for perfection.</span>
                </li>
                <li className="flex items-start gap-2">
                  <ArrowRight size={14} className="mt-0.5 flex-shrink-0" />
                  <span>Add specific personality traits in the description.</span>
                </li>
                <li className="flex items-start gap-2">
                  <ArrowRight size={14} className="mt-0.5 flex-shrink-0" />
                  <span>Use tags to help users discover your character.</span>
                </li>
              </ul>
            </div>
          </div>

          <div className="lg:col-span-2 space-y-6">
            <div className="bg-white p-8 rounded-2xl border border-gray-200 shadow-sm">
              <h2 className="text-xl font-bold text-gray-800 mb-6 flex items-center gap-2">
                <PenTool size={20} className="text-blue-600" />
                Character Details
              </h2>

              <div className="space-y-6">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="space-y-2">
                    <label className="text-sm font-bold text-gray-700">Name <span className="text-red-500">*</span></label>
                    <input
                      value={form.name}
                      onChange={e => setForm({ ...form, name: e.target.value })}
                      className="w-full px-4 py-2 bg-gray-50 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none"
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-bold text-gray-700">Affiliation</label>
                    <input
                      value={form.affiliation}
                      onChange={e => setForm({ ...form, affiliation: e.target.value })}
                      placeholder="e.g. UA High School"
                      className="w-full px-4 py-2 bg-gray-50 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="space-y-2">
                    <label className="text-sm font-bold text-gray-700">Personality</label>
                    <textarea
                      value={form.personality}
                      onChange={e => setForm({ ...form, personality: e.target.value })}
                      className="w-full px-4 py-2 bg-gray-50 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none h-24 resize-none"
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-bold text-gray-700">Appearance</label>
                    <textarea
                      value={form.appearance}
                      onChange={e => setForm({ ...form, appearance: e.target.value })}
                      className="w-full px-4 py-2 bg-gray-50 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none h-24 resize-none"
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <label className="text-sm font-bold text-gray-700">Description / Background <span className="text-red-500">*</span></label>
                  <textarea
                    value={form.description}
                    onChange={e => setForm({ ...form, description: e.target.value })}
                    className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none h-32 transition-all"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-bold text-gray-700">Tags</label>
                  <input
                    value={form.tags}
                    onChange={e => setForm({ ...form, tags: e.target.value })}
                    className="w-full px-4 py-2 bg-gray-50 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none transition-all"
                  />
                </div>
              </div>

              <div className="mt-8 flex gap-4 justify-end">
                <button
                  onClick={() => router.push('/')}
                  className="flex items-center gap-2 bg-gray-500 text-white px-8 py-3 rounded-xl font-medium hover:bg-gray-600 transition-colors disabled:opacity-70 disabled:cursor-not-allowed"
                  type="button"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={saveLoading}
                  className="flex items-center gap-2 bg-blue-600 text-white px-8 py-3 rounded-xl font-medium hover:bg-blue-700 transition-colors shadow-lg shadow-blue-200 disabled:opacity-70 disabled:cursor-not-allowed"
                >
                  {saveLoading ? <Loader2 className="animate-spin" /> : <Save size={18} />}
                  {isEditMode ? 'Update Character' : 'Save Character'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}