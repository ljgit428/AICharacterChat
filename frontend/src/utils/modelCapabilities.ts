import type { ModelConfig, ModelRoleAssignments, ModelRoleKey } from '@/types';

export type AttachmentKind = 'text' | 'image' | 'audio' | 'video';

/**
 * 附件由哪个通道处理（与后端三档路由一致）：
 * - analyzed: 对应角色槽位已配置，由槽位模型转述给文本模型
 * - native:   槽位为空但文本模型提供商原生支持该媒体
 * - unavailable: 均不满足，附件保留但模型会说明无法解读
 */
export type MediaHandlingMode = 'analyzed' | 'native' | 'unavailable';

export interface AttachmentSupport {
  text: 'native';
  image: MediaHandlingMode;
  audio: MediaHandlingMode;
  video: MediaHandlingMode;
}

const MEDIA_ROLE_BY_KIND: Record<Exclude<AttachmentKind, 'text'>, ModelRoleKey> = {
  image: 'image',
  audio: 'audio',
  video: 'video',
};

/** 槽位为空时，按提供商事实原生支持媒体（Claude 仅图片；OpenAI 兼容生态无法确定，不做猜测）。 */
const NATIVE_MEDIA_PROVIDERS: Partial<Record<ModelConfig['provider'], AttachmentKind[]>> = {
  gemini: ['image', 'audio', 'video'],
  anthropic: ['image'],
};

export function getAttachmentAvailability(
  roleAssignments?: ModelRoleAssignments | null,
  textConfig?: ModelConfig | null
): AttachmentSupport {
  const result: AttachmentSupport = { text: 'native', image: 'unavailable', audio: 'unavailable', video: 'unavailable' };
  const nativeKinds = (textConfig && NATIVE_MEDIA_PROVIDERS[textConfig.provider]) || [];

  (Object.keys(MEDIA_ROLE_BY_KIND) as Exclude<AttachmentKind, 'text'>[]).forEach((kind) => {
    if (roleAssignments?.[MEDIA_ROLE_BY_KIND[kind]]) {
      result[kind] = 'analyzed';
    } else if (nativeKinds.includes(kind)) {
      result[kind] = 'native';
    }
  });

  return result;
}

// 与后端 guess_attachment_kind 对齐：.webm 是视频容器（后端经 mimetypes 判为 video/webm）
const VIDEO_FILE_EXTENSIONS = ['.mp4', '.webm', '.mov', '.mkv', '.avi', '.m4v'];
const AUDIO_FILE_EXTENSIONS = ['.mp3', '.wav', '.ogg', '.oga', '.m4a', '.aac', '.flac'];

export function classifyAttachmentFile(file: File): AttachmentKind | null {
  const mimeType = file.type.toLowerCase();
  const fileName = file.name.toLowerCase();

  if (mimeType.startsWith('image/')) {
    return 'image';
  }

  if (
    mimeType.startsWith('video/') ||
    VIDEO_FILE_EXTENSIONS.some((extension) => fileName.endsWith(extension))
  ) {
    return 'video';
  }

  if (
    mimeType.startsWith('audio/') ||
    AUDIO_FILE_EXTENSIONS.some((extension) => fileName.endsWith(extension))
  ) {
    return 'audio';
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
