import { ModelConfig } from '@/types';

export type AttachmentKind = 'text' | 'image' | 'video';

export type AttachmentSupportMode = 'native' | 'fallback';

export interface AttachmentSupport {
  text: AttachmentSupportMode;
  image: AttachmentSupportMode;
  video: AttachmentSupportMode;
}

const IMAGE_CAPABLE_OPENAI_MODEL_HINTS = [
  'vision',
  'llava',
  'minicpm-v',
  'internvl',
];

const IMAGE_VIDEO_OPENAI_MODEL_FAMILIES = [
  'qwen3.6-plus',
  'qwen3.5-plus',
  'qwen3.5-flash',
  'qwen3-vl',
  'qwen2.5-vl',
  'qwen-vl-max',
  'qwen-vl-plus',
];

const IMAGE_ONLY_OPENAI_MODEL_FAMILIES = [
  'gpt-4o',
  'gpt-4.1',
  'o4-mini',
  'o3',
  'qwen-vl-ocr',
];

function matchesModelFamily(modelName: string, families: string[]): boolean {
  return families.some((family) => modelName === family || modelName.startsWith(`${family}-`));
}

export function getAttachmentSupport(modelConfig?: ModelConfig | null): AttachmentSupport {
  const provider = modelConfig?.provider || '';
  const modelName = (modelConfig?.modelName || '').toLowerCase();

  if (provider === 'gemini') {
    return {
      text: 'native',
      image: 'native',
      video: 'native',
    };
  }

  if (provider === 'openai_compatible') {
    if (matchesModelFamily(modelName, IMAGE_VIDEO_OPENAI_MODEL_FAMILIES)) {
      return {
        text: 'native',
        image: 'native',
        video: 'native',
      };
    }

    if (
      matchesModelFamily(modelName, IMAGE_ONLY_OPENAI_MODEL_FAMILIES) ||
      IMAGE_CAPABLE_OPENAI_MODEL_HINTS.some((hint) => modelName.includes(hint))
    ) {
      return {
        text: 'native',
        image: 'native',
        video: 'fallback',
      };
    }
  }

  return {
    text: 'native',
    image: 'fallback',
    video: 'fallback',
  };
}

export function classifyAttachmentFile(file: File): AttachmentKind | null {
  const mimeType = file.type.toLowerCase();
  const fileName = file.name.toLowerCase();

  if (mimeType.startsWith('image/')) {
    return 'image';
  }

  if (mimeType.startsWith('video/')) {
    return 'video';
  }

  if (
    mimeType.startsWith('text/') ||
    [
      '.txt', '.md', '.markdown', '.json', '.jsonl', '.csv', '.tsv', '.log',
      '.yaml', '.yml', '.xml', '.ini', '.cfg', '.conf', '.py', '.js', '.ts',
      '.tsx', '.jsx', '.html', '.css', '.sql',
    ].some((extension) => fileName.endsWith(extension))
  ) {
    return 'text';
  }

  return null;
}
