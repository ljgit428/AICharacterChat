/**
 * 角色长回复按自然段落拆分为多个气泡：空行分隔的块（markdown 段落/列表）。
 * 整段保持原样（不切句），气泡之间留小间距，配合每段喇叭/下载按钮。
 * 与渲染共用同一逻辑：ChatInterface 用它预合成每段音频，ImmersiveChatWindow 用它分段渲染。
 */
export function splitReplyParagraphs(text: string): string[] {
  const parts = text
    .split(/\n\s*\n/)
    .map((part) => part.trim())
    .filter(Boolean);
  return parts.length ? parts : [text.trim()];
}
