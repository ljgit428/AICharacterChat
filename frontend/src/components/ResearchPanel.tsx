"use client";

import { Message, ResearchPayload } from '@/types';
import { ExternalLink, Globe } from 'lucide-react';
import { useI18n } from '@/i18n/provider';

interface ResearchPanelProps {
  latestAssistantMessage: Message | null;
}

function sectionHasContent(value?: string | null) {
  return Boolean(value && value.trim());
}

export default function ResearchPanel({ latestAssistantMessage }: ResearchPanelProps) {
  const { messages } = useI18n();
  const payload: ResearchPayload | null = latestAssistantMessage?.researchPayload || null;
  const items = payload?.items || [];

  const hasContent =
    items.length > 0 ||
    sectionHasContent(payload?.error);

  return (
    <div className="border-b border-slate-200 bg-gradient-to-br from-slate-50 via-white to-blue-50/70 px-6 py-4">
      <div className="mb-3 flex items-center gap-2">
        <div className="rounded-full bg-blue-100 p-2 text-blue-600">
          <Globe size={16} />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-slate-900">{messages.research.title}</h3>
          <p className="text-xs text-slate-500">
            {messages.research.subtitle}
          </p>
        </div>
      </div>

      {!hasContent ? (
        <div className="rounded-xl border border-dashed border-slate-200 bg-white/70 px-4 py-4 text-sm text-slate-500">
          {messages.research.empty}
        </div>
      ) : (
        <div className="rounded-xl border border-slate-200 bg-white/90 p-4 shadow-sm">
          <div className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-800">
            <Globe size={14} />
            <span>{messages.research.webFindings}</span>
          </div>
          {payload?.query && (
            <div className="mb-3 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
              {messages.research.query}: <span className="font-medium text-slate-700">{payload.query}</span>
            </div>
          )}
          {payload?.error && (
            <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
              {payload.error}
            </div>
          )}
          <div className="space-y-3">
            {items.map((item) => (
              <a
                key={item.url}
                href={item.url}
                target="_blank"
                rel="noreferrer"
                className="block rounded-lg border border-slate-200 px-3 py-3 transition-colors hover:border-blue-200 hover:bg-blue-50/50"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-slate-900">{item.title}</div>
                    <div className="mt-1 truncate text-xs text-slate-500">{item.domain || item.url}</div>
                  </div>
                  <ExternalLink size={14} className="mt-0.5 shrink-0 text-slate-400" />
                </div>
                {item.snippet && (
                  <p className="mt-2 text-sm leading-6 text-slate-600">{item.snippet}</p>
                )}
              </a>
            ))}
            {items.length === 0 && !payload?.error && (
              <div className="rounded-lg border border-dashed border-slate-200 px-3 py-4 text-sm text-slate-500">
                {messages.research.noWebResult}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
