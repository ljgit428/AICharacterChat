"use client";

import { useParams, useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { useI18n } from '@/i18n/provider';

export default function EditCharacterPage() {
  const { messages } = useI18n();
  const params = useParams();
  const router = useRouter();
  const characterId = params.id as string;

  useEffect(() => {

    router.push(`/create-character?id=${characterId}`);
  }, [characterId, router]);

  return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="text-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-gray-900 mx-auto"></div>
        <p className="mt-4 text-gray-600">{messages.routes.redirectingToCharacterEditor}</p>
      </div>
    </div>
  );
}
