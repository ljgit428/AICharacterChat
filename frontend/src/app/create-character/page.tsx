"use client";

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import CreateCharacterSimplifiedForm from '@/components/CreateCharacterSimplifiedForm';

function CreateCharacterPageContent() {
  const searchParams = useSearchParams();
  const characterId = searchParams.get('id');

  return <CreateCharacterSimplifiedForm characterId={characterId || undefined} />;
}

export default function CreateCharacterPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-white" />}>
      <CreateCharacterPageContent />
    </Suspense>
  );
}
