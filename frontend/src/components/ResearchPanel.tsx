"use client";

import { useMemo } from "react";
import { useSelector } from "react-redux";
import { ExternalLink, Globe, X } from "lucide-react";
import { RootState, ResearchPayload } from "@/types";
import { useI18n } from "@/i18n/provider";

function sectionHasContent(value?: string | null) {
  return Boolean(value && value.trim());
}

interface ResearchPanelProps {
  onClose?: () => void;
}

export default function ResearchPanel({ onClose }: ResearchPanelProps = {}) {
  const { messages } = useI18n();
  const chatMessages = useSelector((state: RootState) => state.chat.messages);

  const payload: ResearchPayload | null = useMemo(() => {
    for (let index = chatMessages.length - 1; index >= 0; index -= 1) {
      const message = chatMessages[index];
      if (message.role === "assistant" && message.researchPayload) {
        return message.researchPayload;
      }
    }
    return null;
  }, [chatMessages]);

  const items = payload?.items || [];

  const hasContent = items.length > 0 || sectionHasContent(payload?.error);

  return (
    <aside className="flex h-full min-h-0 w-full flex-col overflow-hidden rounded-[1.75rem] border border-slate-200/80 bg-white/90 shadow-[0_24px_80px_rgba(15,23,42,0.08)] backdrop-blur">
      <div className="border-b border-slate-200/80 bg-[linear-gradient(180deg,rgba(248,250,252,0.95),rgba(255,255,255,0.92))] px-4 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <div className="rounded-full bg-blue-100 p-2 text-blue-600">
              <Globe size={16} />
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-slate-900">{messages.research.title}</h3>
              <p className="mt-1 text-xs leading-5 text-slate-500">{messages.research.subtitle}</p>
            </div>
          </div>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-slate-600 transition-colors hover:bg-slate-200 hover:text-slate-900"
              title={messages.chat.toggleResearchPanel}
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-4">
        {!hasContent ? (
          <div className="flex flex-1 items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">
            {messages.research.empty}
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
              <Globe size={14} />
              <span>{messages.research.webFindings}</span>
            </div>
            {payload?.query && (
              <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
                {messages.research.query}: <span className="font-medium text-slate-700">{payload.query}</span>
              </div>
            )}
            {payload?.error && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
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
    </aside>
  );
}
