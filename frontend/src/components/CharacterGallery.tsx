"use client";
import { useState } from 'react';
import { useQuery, useMutation, gql } from '@apollo/client';
import { MessageCircle, MoreHorizontal, Trash2, X, Edit } from 'lucide-react';
import { useRouter } from 'next/navigation';

const GET_CHARACTERS = gql`
  query GetCharacters {
    characters {
      id
      name
      description
      avatarUrl
      tags
    }
  }
`;

const DELETE_CHARACTER = gql`
  mutation DeleteCharacter($id: ID!) {
    deleteCharacter(id: $id)
  }
`;

export default function CharacterGallery({ onSelect }: { onSelect: (id: string) => void }) {
  const { loading, error, data, refetch } = useQuery(GET_CHARACTERS, {
    fetchPolicy: 'network-only',
  });
  const router = useRouter();

  const [deleteCharacter] = useMutation(DELETE_CHARACTER);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);

  const handleMenuClick = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    setOpenMenuId(openMenuId === id ? null : id);
  };

  const handleDelete = async (e: React.MouseEvent, id: string, name: string) => {
    e.stopPropagation();
    if (confirm(`Are you sure you want to delete "${name}"? This action cannot be undone.`)) {
      try {
        const { data } = await deleteCharacter({ variables: { id } });

        if (data?.deleteCharacter === true) {
          setOpenMenuId(null);
          refetch();
        } else {
          alert("Cannot delete this character because there are existing chat histories associated with them. Please delete the chat sessions first.");
        }
      } catch (err) {
        console.error(err);
        alert("An error occurred while trying to delete.");
      }
    }
  };

  const handleEdit = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    setOpenMenuId(null);
    router.push(`/create-character?id=${id}`);
  };

  const handleBackgroundClick = () => {
    if (openMenuId) setOpenMenuId(null);
  };

  if (loading) return <div className="p-10 text-center text-gray-500">Loading characters...</div>;
  if (error) {
    console.error('GraphQL Error:', error);
    return <div className="p-10 text-center text-red-500">Error loading characters: {error.message}</div>;
  }

  const characters = data?.characters || [];

  return (
    <div className="p-8 max-w-7xl mx-auto h-full" onClick={handleBackgroundClick}>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-800">My Characters</h1>
        <p className="text-gray-500">Select a character to start chatting.</p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6 pb-20">
        {characters.map((char: { id: string; name: string; description: string; tags: string[]; avatarUrl: string | null }) => (
          <div
            key={char.id}
            onClick={() => onSelect(char.id)}
            className="group relative bg-white border border-gray-200 rounded-xl p-4 hover:border-blue-400 hover:shadow-md transition-all cursor-pointer flex flex-col h-[280px]"
          >
            <div className="flex items-start justify-between mb-4">
              <div className="w-16 h-16 rounded-full bg-gray-100 overflow-hidden border border-gray-100">
                {char.avatarUrl ? (
                  <img src={char.avatarUrl} alt={char.name} className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-2xl">🤖</div>
                )}
              </div>
              <div className="relative">
                <button
                  onClick={(e) => handleMenuClick(e, char.id)}
                  className={`p-1 rounded-full transition-colors ${openMenuId === char.id ? 'bg-gray-100 text-gray-800' : 'text-gray-300 hover:text-gray-600 hover:bg-gray-50'}`}
                >
                  {openMenuId === char.id ? <X size={20} /> : <MoreHorizontal size={20} />}
                </button>

                {openMenuId === char.id && (
                  <div className="absolute right-0 top-8 w-32 bg-white border border-gray-200 rounded-lg shadow-lg z-10 py-1 overflow-hidden animate-in fade-in zoom-in duration-200">
                    <button
                      onClick={(e) => handleEdit(e, char.id)}
                      className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2"
                    >
                      <Edit size={14} />
                      Edit
                    </button>
                    <button
                      onClick={(e) => handleDelete(e, char.id, char.name)}
                      className="w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-red-50 flex items-center gap-2"
                    >
                      <Trash2 size={14} />
                      Delete
                    </button>
                  </div>
                )}
              </div>
            </div>

            <h3 className="font-bold text-lg text-gray-900 mb-1 truncate">{char.name}</h3>
            <p className="text-sm text-gray-500 line-clamp-4 h-[80px] break-words">
              {(() => {
                const text = char.description || "";
                const match = text.match(/^.*?[.。]/);
                const result = match ? match[0] : text;
                return result.trim();
              })()}
            </p>

            <div className="mt-auto pt-4 border-t border-gray-50 flex items-center justify-between">
              <div className="flex gap-2 overflow-hidden">
                {char.tags?.slice(0, 2).map((tag: string) => (
                  <span key={tag} className="px-2 py-0.5 bg-gray-100 text-gray-600 text-xs rounded-full truncate max-w-[80px]">
                    {tag}
                  </span>
                ))}
                {char.tags?.length > 2 && (
                  <span className="text-xs text-gray-400 py-0.5">+{char.tags.length - 2}</span>
                )}
              </div>
              <div className="text-blue-600 opacity-0 group-hover:opacity-100 transition-opacity">
                <MessageCircle size={20} />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div >
  );
}
