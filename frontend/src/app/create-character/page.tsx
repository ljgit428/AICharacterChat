"use client";

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import CreateCharacterSimplifiedForm from '@/components/CreateCharacterSimplifiedForm';

function CreateCharacterPageContent() {
  const searchParams = useSearchParams();
  const characterId = searchParams.get('id');

  return (
    <div className="min-h-screen bg-slate-50">
      <CreateCharacterSimplifiedForm characterId={characterId || undefined} />
    </div>
  );
}

export default function CreateCharacterPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-slate-50" />}>
      <CreateCharacterPageContent />
    </Suspense>
  );
}
