"use client";

import { useRouter } from "next/navigation";
import { useI18n } from "@/i18n/provider";

export type WorkspaceMode = "topic" | "chat";

export default function ModeSwitch({ active }: { active: WorkspaceMode }) {
  const router = useRouter();
  const { messages } = useI18n();

  const buttonBase =
    "whitespace-nowrap rounded-full px-3.5 py-1.5 text-xs font-medium transition-colors";

  return (
    <div
      className="flex flex-shrink-0 items-center gap-0.5 rounded-full bg-white/80 p-1 ring-1 ring-slate-200"
      role="tablist"
      aria-label={messages.shell.modeSwitchLabel}
    >
      <button
        type="button"
        role="tab"
        aria-selected={active === "topic"}
        onClick={() => router.push("/")}
        className={`${buttonBase} ${
          active === "topic"
            ? "bg-slate-900 text-white shadow-sm"
            : "text-slate-500 hover:text-slate-900"
        }`}
      >
        {messages.shell.modeTopic}
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={active === "chat"}
        onClick={() => router.push("/chat")}
        className={`${buttonBase} ${
          active === "chat"
            ? "bg-slate-900 text-white shadow-sm"
            : "text-slate-500 hover:text-slate-900"
        }`}
      >
        {messages.shell.modeChat}
      </button>
    </div>
  );
}
