"use client";

import { useSearchParams } from 'next/navigation';
import CreateCharacterForm from '@/components/CreateCharacterForm';

export default function CreateCharacterPage() {
  const searchParams = useSearchParams();
  const characterId = searchParams.get('id');

  return <CreateCharacterForm characterId={characterId || undefined} />;
}