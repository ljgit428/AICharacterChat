"use client";

import { Eye, EyeOff, PictureInPicture2, X } from "lucide-react";

/**
 * 实时模式字幕：灰色预测字（说话中）+ 用户上一句 + 角色回复的实时文本。
 *
 * 两种呈现：
 * - SubtitleBar：悬浮在聊天 UI 底部之外的字幕条；
 * - SubtitleContent：纯内联样式，可被渲染进 Document Picture-in-Picture
 *   置顶小窗（浏览器不支持时由调用方降级为字幕条）。
 */

interface SubtitleContentProps {
  /** 灰色预测字：说话期间实时跟随，说完清空（由最终文本接管）。 */
  interimText?: string;
  userText: string;
  assistantText: string;
  /** pip 模式下使用更紧凑的排版。 */
  pip?: boolean;
}

export function SubtitleContent({ interimText, userText, assistantText, pip }: SubtitleContentProps) {
  if (!interimText && !userText && !assistantText) {
    return (
      <div style={{ padding: pip ? "18px 20px" : undefined, color: "#94a3b8", fontSize: 13 }}>
        …
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {interimText && (
        <p style={{
          margin: 0,
          fontSize: pip ? 14 : 12,
          lineHeight: 1.5,
          color: "#94a3b8",
          fontStyle: "italic",
        }}>
          {interimText}
        </p>
      )}
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
  interimText?: string;
  userText: string;
  assistantText: string;
  popLabel: string;
  closeLabel: string;
  /** 预测字开关（Owl「刷新间隔」机制的 UI 化）。 */
  previewEnabled: boolean;
  previewToggleOnLabel: string;
  previewToggleOffLabel: string;
  previewTitleOn: string;
  previewTitleOff: string;
  onTogglePreview: () => void;
  onPopOut: () => void;
  onClose: () => void;
}

export default function SubtitleBar({
  interimText,
  userText,
  assistantText,
  popLabel,
  closeLabel,
  previewEnabled,
  previewToggleOnLabel,
  previewToggleOffLabel,
  previewTitleOn,
  previewTitleOff,
  onTogglePreview,
  onPopOut,
  onClose,
}: SubtitleBarProps) {
  return (
    <div className="pointer-events-auto absolute bottom-4 left-1/2 z-20 w-[min(720px,92%)] -translate-x-1/2">
      <div className="rounded-[1.25rem] border border-white/15 bg-slate-950/85 px-5 py-3 shadow-[0_18px_50px_rgba(15,23,42,0.35)] backdrop-blur">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <SubtitleContent
              interimText={interimText}
              userText={userText}
              assistantText={assistantText}
            />
          </div>
          <div className="flex flex-shrink-0 items-center gap-1">
            <span
              className={`rounded-lg px-1.5 py-0.5 text-[10px] font-medium ${
                previewEnabled ? "text-emerald-300/80" : "text-white/30"
              }`}
            >
              {previewEnabled ? previewToggleOnLabel : previewToggleOffLabel}
            </span>
            <button
              type="button"
              onClick={onTogglePreview}
              className="rounded-lg p-1.5 text-white/60 transition-colors hover:bg-white/10 hover:text-white"
              title={previewEnabled ? previewTitleOn : previewTitleOff}
            >
              {previewEnabled ? <Eye size={14} /> : <EyeOff size={14} />}
            </button>
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
