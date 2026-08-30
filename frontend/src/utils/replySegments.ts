/**
 * 角色回复的"句段"单一数据源：展示（单一大气泡内的句子 span）与语音合成
 * （逐句 TTS、卡拉OK高亮）共用同一份分句结果，保证高亮索引与播放索引对齐。
 */

/** 后端 done 事件返回的情感分段（由【情感】标记解析而来）。 */
export interface TtsSegmentInfo {
  emotion?: string;
  text?: string | null;
}

/** 展示与合成的最小单元：原样保留空格与换行，emotion 为所在后端分段的情感。 */
export interface SpeechSegment {
  text: string;
  emotion?: string;
}

const SENTENCE_DELIMITERS = new Set(['。', '！', '？', '!', '?', '…', '\n']);
/** 句末标点后紧跟的收尾符号并入本句，避免「你好！」的引号掉到下一句开头。 */
const CLOSERS = new Set(['」', '』', '\u201C', '\u201D', '\u2018', '\u2019', '）', ')', '】', '>', '…', '~', '～', '♪']);

/**
 * 按中英标点与换行切句；标点、空白原样保留在句内（配合 whitespace-pre-wrap
 * 渲染时空行/缩进不丢）。纯空白的碎片并入上一句，避免渲染出空 span。
 */
export function splitIntoSentences(text: string): string[] {
  const sentences: string[] = [];
  let current = '';
  const chars = Array.from(text);
  for (let i = 0; i < chars.length; i += 1) {
    const char = chars[i];
    current += char;
    if (SENTENCE_DELIMITERS.has(char)) {
      // 连续标点（如 ?!、！！！）与收尾符号（引号/括号）都并入本句。
      while (i + 1 < chars.length && (CLOSERS.has(chars[i + 1]) || SENTENCE_DELIMITERS.has(chars[i + 1]))) {
        i += 1;
        current += chars[i];
      }
      const previous = sentences[sentences.length - 1];
      if (previous !== undefined && !current.trim()) {
        sentences[sentences.length - 1] = previous + current;
      } else {
        sentences.push(current);
      }
      current = '';
    }
  }
  if (current) {
    const previous = sentences[sentences.length - 1];
    if (previous !== undefined && !current.trim()) {
      sentences[sentences.length - 1] = previous + current;
    } else {
      sentences.push(current);
    }
  }
  return sentences;
}

/**
 * 把一条完整回复切成交试听/合成用的句段：
 * - 后端返回 tts_segments 时，按出现顺序在原文中定位各分段的区间，
 *   句子落在哪个区间就继承该段的情感（匹配不上的句子走默认情感）。
 * - 没有分段时直接按标点切句，全部默认情感。
 */
export function buildSpeechSegments(content: string, ttsSegments?: TtsSegmentInfo[] | null): SpeechSegment[] {
  const sentences = splitIntoSentences(content);
  if (!ttsSegments || ttsSegments.length === 0) {
    return sentences.map((text) => ({ text }));
  }

  // 各情感分段在原文中的 [start, end) 区间（分段按顺序出现，用游标顺序查找）。
  const spans: Array<{ start: number; end: number; emotion?: string }> = [];
  let spanCursor = 0;
  for (const segment of ttsSegments) {
    const text = (segment?.text || '').trim();
    if (!text) continue;
    const start = content.indexOf(text, spanCursor);
    if (start === -1) continue;
    spans.push({ start, end: start + text.length, emotion: segment.emotion || undefined });
    spanCursor = start + text.length;
  }

  // 句子定位用独立游标，避免被上面分段查找推进过的游标影响。
  let searchFrom = 0;
  return sentences.map((text) => {
    const start = content.indexOf(text, searchFrom);
    const sentenceStart = start === -1 ? searchFrom : start;
    if (start !== -1) searchFrom = start + text.length;
    const hit = spans.find((span) => sentenceStart >= span.start && sentenceStart < span.end);
    return { text, emotion: hit?.emotion };
  });
}
