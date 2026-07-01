"use client";

import Image from 'next/image';
import { useState } from 'react';
import { useQuery, useMutation, gql } from '@apollo/client';
import { Edit2, MessageCircle, Trash2, X } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useI18n } from '@/i18n/provider';

const GET_CHARACTERS = gql`
  query GetCharacters {
    characters {
      id
      name
      description
      userAddress
      personality
      appearance
      responseGuidelines
      scenario
      exampleDialogue
      affiliation
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

type CharacterCard = {
  id: string;
  name: string;
  description: string;
  userAddress?: string | null;
  personality?: string | null;
  appearance?: string | null;
  responseGuidelines?: string | null;
  scenario?: string | null;
  exampleDialogue?: string | null;
  affiliation?: string | null;
  avatarUrl?: string | null;
  tags?: string[];
};

function getSummary(description: string) {
  const text = (description || '').trim();
  if (!text) {
    return '';
  }

  const match = text.match(/^.*?[.!?。！？]/);
  const sentence = (match ? match[0] : text).trim();
  return sentence.length > 120 ? `${sentence.slice(0, 117)}...` : sentence;
}

function getCharacterInitial(name: string) {
  return (name || '?').trim().slice(0, 1).toUpperCase() || '?';
}

function CharacterAvatar({
  name,
  avatarUrl,
  roundedClassName,
}: {
  name: string;
  avatarUrl?: string | null;
  roundedClassName: string;
}) {
  if (!avatarUrl) {
    return (
      <div className={`flex h-full w-full items-center justify-center bg-blue-50 text-xl font-semibold text-blue-700 ${roundedClassName}`}>
        {getCharacterInitial(name)}
      </div>
    );
  }

  return (
    <Image
      src={avatarUrl}
      alt={name}
      fill
      unoptimized
      sizes="64px"
      className={`object-cover ${roundedClassName}`}
    />
  );
}

function CharacterField({ label, value }: { label: string; value?: string | null }) {
  if (!value?.trim()) {
    return null;
  }

  return (
    <div className="space-y-1.5">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-400">{label}</p>
      <p className="whitespace-pre-wrap text-sm leading-6 text-gray-700">{value.trim()}</p>
    </div>
  );
}

function CharacterDetailDialog({
  character,
  onClose,
  onChat,
  onEdit,
}: {
  character: CharacterCard;
  onClose: () => void;
  onChat: (id: string) => void;
  onEdit: (id: string) => void;
}) {
  const { messages } = useI18n();

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-3xl border border-gray-200 bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`${character.name} ${messages.gallery.details}`}
      >
        <div className="sticky top-0 z-10 flex items-start justify-between border-b border-gray-100 bg-white/95 px-6 py-5 backdrop-blur">
          <div className="flex items-start gap-4">
            <div className="relative h-16 w-16 overflow-hidden rounded-2xl border border-gray-200 bg-gray-100">
              <CharacterAvatar
                name={character.name}
                avatarUrl={character.avatarUrl}
                roundedClassName="rounded-2xl"
              />
            </div>
            <div>
              <div className="mb-2 inline-flex rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700">
                {messages.gallery.characterOverview}
              </div>
              <h2 className="text-2xl font-bold text-gray-900">{character.name}</h2>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-600">{character.description || messages.gallery.noCoreBriefYet}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-full p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700"
            type="button"
            aria-label={messages.gallery.closeDetails}
          >
            <X size={18} />
          </button>
        </div>

        <div className="space-y-6 px-6 py-6">
          <div className="rounded-2xl border border-gray-200 bg-gray-50 p-5">
            <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
              <div className="space-y-3">
                {character.affiliation?.trim() && (
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-400">{messages.gallery.affiliation}</p>
                    <p className="mt-1 text-sm text-gray-700">{character.affiliation}</p>
                  </div>
                )}
                {character.userAddress?.trim() && (
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-400">{messages.gallery.userAddress}</p>
                    <p className="mt-1 text-sm text-gray-700">{character.userAddress}</p>
                  </div>
                )}
              </div>
              <div className="flex flex-wrap gap-2 md:max-w-[40%] md:justify-end">
                {character.tags?.length ? character.tags.map((tag) => (
                  <span key={tag} className="rounded-full bg-white px-3 py-1 text-xs font-medium text-gray-600 ring-1 ring-gray-200">
                    {tag}
                  </span>
                )) : (
                  <span className="text-sm text-gray-400">{messages.gallery.noTags}</span>
                )}
              </div>
            </div>

            <div className="mt-5 flex flex-wrap gap-3">
              <button
                onClick={() => onChat(character.id)}
                className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-700"
                type="button"
              >
                <MessageCircle size={16} />
                <span>{messages.gallery.startChat}</span>
              </button>
              <button
                onClick={() => onEdit(character.id)}
                className="inline-flex items-center gap-2 rounded-xl border border-gray-200 px-4 py-2.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
                type="button"
              >
                <Edit2 size={16} />
                <span>{messages.gallery.editCoreSetup}</span>
              </button>
            </div>
          </div>

          <details className="rounded-2xl border border-gray-200 bg-white p-5">
            <summary className="cursor-pointer list-none text-base font-semibold text-gray-900">
              {messages.gallery.voiceBehavior}
            </summary>
            <div className="mt-4 space-y-5 border-t border-gray-100 pt-4">
              <CharacterField label={messages.gallery.personalityNotes} value={character.personality} />
              <CharacterField label={messages.gallery.speakingRules} value={character.responseGuidelines} />
              <CharacterField label={messages.gallery.exampleDialogue} value={character.exampleDialogue} />
            </div>
          </details>

          <details className="rounded-2xl border border-gray-200 bg-white p-5">
            <summary className="cursor-pointer list-none text-base font-semibold text-gray-900">
              {messages.gallery.worldLore}
            </summary>
            <div className="mt-4 space-y-5 border-t border-gray-100 pt-4">
              <CharacterField label={messages.gallery.scenario} value={character.scenario} />
              <CharacterField label={messages.gallery.appearance} value={character.appearance} />
            </div>
          </details>
        </div>
      </div>
    </div>
  );
}

export default function CharacterGallery({ onSelect }: { onSelect: (id: string) => void }) {
  const { messages } = useI18n();
  const { loading, error, data, refetch } = useQuery(GET_CHARACTERS, {
    fetchPolicy: 'network-only',
  });
  const router = useRouter();
  const [detailCharacterId, setDetailCharacterId] = useState<string | null>(null);

  const [deleteCharacter] = useMutation(DELETE_CHARACTER);

  const characters: CharacterCard[] = data?.characters ?? [];
  const detailCharacter = detailCharacterId
    ? characters.find((character) => character.id === detailCharacterId) ?? null
    : null;

  const handleDelete = async (event: React.MouseEvent, id: string, name: string) => {
    event.stopPropagation();
    if (confirm(messages.gallery.confirmDeleteCharacter(name))) {
      try {
        const response = await deleteCharacter({ variables: { id } });

        if (response.data?.deleteCharacter === true) {
          if (detailCharacterId === id) {
            setDetailCharacterId(null);
          }
          void refetch();
        } else {
          alert(messages.gallery.deleteCharacterBlocked);
        }
      } catch (deleteError) {
        console.error(deleteError);
        alert(messages.gallery.deleteCharacterError);
      }
    }
  };

  const handleEdit = (event: React.MouseEvent | null, id: string) => {
    event?.stopPropagation();
    router.push(`/create-character?id=${id}`);
  };

  const handleOpenDetails = (character: CharacterCard) => {
    setDetailCharacterId(character.id);
  };

  const handleStartChat = (id: string) => {
    setDetailCharacterId(null);
    onSelect(id);
  };

  if (loading) {
    return <div className="p-10 text-center text-gray-500">{messages.gallery.loadingCharacters}</div>;
  }

  if (error) {
    console.error('GraphQL Error:', error);
    return <div className="p-10 text-center text-red-500">{messages.gallery.errorLoadingCharacters}: {error.message}</div>;
  }

  return (
    <>
      <div className="mx-auto h-full max-w-7xl p-8">
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-gray-800">{messages.gallery.myCharacters}</h1>
          <p className="text-gray-500">{messages.gallery.browseEssentials}</p>
        </div>

        {characters.length === 0 && (
          <div className="mb-6 rounded-2xl border border-dashed border-gray-200 bg-white px-8 py-16 text-center text-gray-500">
            {messages.gallery.noCharactersYet}
          </div>
        )}

        <div className="grid grid-cols-1 gap-6 pb-20 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {characters.map((character) => (
            <div
              key={character.id}
              className="group flex h-[320px] flex-col rounded-2xl border border-gray-200 bg-white p-5 transition-all hover:border-blue-300 hover:shadow-md"
            >
              <button
                onClick={() => handleOpenDetails(character)}
                className="flex flex-1 flex-col text-left"
                type="button"
              >
                <div className="mb-4 flex items-start justify-between gap-3">
                  <div className="relative h-16 w-16 overflow-hidden rounded-full border border-gray-100 bg-gray-100">
                    <CharacterAvatar
                      name={character.name}
                      avatarUrl={character.avatarUrl}
                      roundedClassName="rounded-full"
                    />
                  </div>
                  <div className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">
                    {messages.gallery.character}
                  </div>
                </div>

                <h3 className="mb-1 truncate text-lg font-bold text-gray-900">{character.name}</h3>
                <p className="min-h-[72px] text-sm leading-6 text-gray-500">{getSummary(character.description) || messages.gallery.noCharacterBriefYet}</p>

                <div className="mt-4 flex min-h-[28px] flex-wrap gap-2 overflow-hidden">
                  {character.tags?.slice(0, 3).map((tag) => (
                    <span key={tag} className="max-w-[120px] truncate rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                      {tag}
                    </span>
                  ))}
                  {character.tags && character.tags.length > 3 && (
                    <span className="py-0.5 text-xs text-gray-400">+{character.tags.length - 3}</span>
                  )}
                </div>

                <span className="mt-4 text-sm font-medium text-blue-600">{messages.gallery.viewDetails}</span>
              </button>

              <div className="mt-4 flex items-center gap-2 border-t border-gray-100 pt-4">
                <button
                  onClick={() => handleStartChat(character.id)}
                  className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl bg-blue-600 px-3 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-700"
                  type="button"
                >
                  <MessageCircle size={16} />
                  <span>{messages.gallery.chat}</span>
                </button>
                <button
                  onClick={() => handleOpenDetails(character)}
                  className="inline-flex items-center justify-center rounded-xl border border-gray-200 px-3 py-2.5 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-50"
                  type="button"
                >
                  {messages.gallery.details}
                </button>
                <button
                  onClick={(event) => handleEdit(event, character.id)}
                  className="inline-flex items-center justify-center rounded-xl border border-gray-200 px-3 py-2.5 text-gray-600 transition-colors hover:bg-gray-50"
                  title={messages.gallery.editCharacter}
                  type="button"
                >
                  <Edit2 size={16} />
                </button>
                <button
                  onClick={(event) => handleDelete(event, character.id, character.name)}
                  className="inline-flex items-center justify-center rounded-xl border border-red-100 px-3 py-2.5 text-red-500 transition-colors hover:bg-red-50"
                  title={messages.gallery.deleteCharacter}
                  type="button"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {detailCharacter && (
        <CharacterDetailDialog
          character={detailCharacter}
          onClose={() => setDetailCharacterId(null)}
          onChat={handleStartChat}
          onEdit={(id) => handleEdit(null, id)}
        />
      )}
    </>
  );
}
