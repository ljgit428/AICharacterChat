"use client";

import { PictureInPicture2, X } from "lucide-react";

/**
 * 实时模式字幕：用户语音转写 + 角色回复的实时文本。
 *
 * 两种呈现：
 * - SubtitleBar：悬浮在聊天 UI 底部之外的字幕条；
 * - SubtitleContent：纯内联样式，可被渲染进 Document Picture-in-Picture
 *   置顶小窗（浏览器不支持时由调用方降级为字幕条）。
 */

interface SubtitleContentProps {
  userText: string;
  assistantText: string;
  /** pip 模式下使用更紧凑的排版。 */
  pip?: boolean;
}

export function SubtitleContent({ userText, assistantText, pip }: SubtitleContentProps) {
  if (!userText && !assistantText) {
    return (
      <div style={{ padding: pip ? "18px 20px" : undefined, color: "#94a3b8", fontSize: 13 }}>
        …
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {userText && (
        <p style={{
          margin: 0,
          fontSize: pip ? 14 : 12,
          lineHeight: 1.5,
          color: "#cbd5e1",
        }}>
          {userText}
        </p>
      )}
      {assistantText && (
        <p style={{
          margin: 0,
          fontSize: pip ? 20 : 17,
          lineHeight: 1.55,
          fontWeight: 600,
          color: "#f8fafc",
          maxHeight: pip ? 84 : 120,
          overflow: "hidden",
        }}>
          {assistantText}
        </p>
      )}
    </div>
  );
}

interface SubtitleBarProps {
  userText: string;
  assistantText: string;
  popLabel: string;
  closeLabel: string;
  onPopOut: () => void;
  onClose: () => void;
}

export default function SubtitleBar({
  userText,
  assistantText,
  popLabel,
  closeLabel,
  onPopOut,
  onClose,
}: SubtitleBarProps) {
  return (
    <div className="pointer-events-auto absolute bottom-4 left-1/2 z-20 w-[min(720px,92%)] -translate-x-1/2">
      <div className="rounded-[1.25rem] border border-white/15 bg-slate-950/85 px-5 py-3 shadow-[0_18px_50px_rgba(15,23,42,0.35)] backdrop-blur">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <SubtitleContent userText={userText} assistantText={assistantText} />
          </div>
          <div className="flex flex-shrink-0 items-center gap-1">
            <button
              type="button"
              onClick={onPopOut}
              className="rounded-lg p-1.5 text-white/60 transition-colors hover:bg-white/10 hover:text-white"
              title={popLabel}
            >
              <PictureInPicture2 size={14} />
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg p-1.5 text-white/60 transition-colors hover:bg-white/10 hover:text-white"
              title={closeLabel}
            >
              <X size={14} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
