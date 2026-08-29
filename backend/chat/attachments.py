import mimetypes
import os
from dataclasses import dataclass

from .models import AttachmentKind

TEXT_FILE_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".json",
    ".jsonl",
    ".csv",
    ".tsv",
    ".log",
    ".yaml",
    ".yml",
    ".xml",
    ".ini",
    ".cfg",
    ".conf",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".sql",
}

AUDIO_FILE_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".ogg",
    ".oga",
    ".m4a",
    ".aac",
    ".flac",
    ".webm",
}

MAX_TEXT_ATTACHMENT_BYTES = 2 * 1024 * 1024
MAX_IMAGE_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_AUDIO_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_VIDEO_ATTACHMENT_BYTES = 100 * 1024 * 1024
MAX_TEXT_ATTACHMENT_CHARS = 16000

# 角色资料暂存（AssetStore.upload）走独立上限：语料单文件远大于聊天附件，
# 2MB 的聊天上限会把剧本/小说整文件拒掉。事件载荷里仍只存 16k 预览，
# 全文在 draft 解析时从磁盘读（见 graphql/schema.py 的全文读取逻辑）。
MAX_STAGING_TEXT_BYTES = 20 * 1024 * 1024


def _format_size_limit(max_bytes):
    """Render a byte limit as a human-friendly string (e.g. '2 MB', '512 KB').

    Picks the largest unit that divides evenly into the value, falling back
    to KB with one decimal for fractional sizes. Used in user-facing error
    messages; never rounds to zero.
    """
    if max_bytes >= 1024 * 1024:
        return f"{max_bytes / (1024 * 1024):g} MB"
    if max_bytes >= 1024:
        return f"{max_bytes // 1024} KB"
    return f"{max_bytes} B"


def guess_attachment_kind(file_obj):
    file_name = getattr(file_obj, "name", "") or ""
    mime_type = getattr(file_obj, "content_type", "") or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    extension = os.path.splitext(file_name)[1].lower()

    if mime_type.startswith("image/"):
        return AttachmentKind.IMAGE, mime_type
    if mime_type.startswith("video/"):
        return AttachmentKind.VIDEO, mime_type
    if mime_type.startswith("audio/") or extension in AUDIO_FILE_EXTENSIONS:
        return AttachmentKind.AUDIO, mime_type if mime_type.startswith("audio/") else (mimetypes.guess_type(file_name)[0] or "audio/mpeg")
    if mime_type.startswith("text/") or extension in TEXT_FILE_EXTENSIONS:
        return AttachmentKind.TEXT, mime_type
    if mime_type in {"application/json", "application/xml"}:
        return AttachmentKind.TEXT, mime_type

    raise ValueError("Only text files, images, audio, and videos are supported")


def validate_attachment_size(file_obj, attachment_kind, max_text_bytes=None):
    size = getattr(file_obj, "size", 0) or 0
    limits = {
        AttachmentKind.TEXT: max_text_bytes or MAX_TEXT_ATTACHMENT_BYTES,
        AttachmentKind.IMAGE: MAX_IMAGE_ATTACHMENT_BYTES,
        AttachmentKind.AUDIO: MAX_AUDIO_ATTACHMENT_BYTES,
        AttachmentKind.VIDEO: MAX_VIDEO_ATTACHMENT_BYTES,
    }
    max_size = limits.get(attachment_kind)
    if max_size and size > max_size:
        label = {
            AttachmentKind.TEXT: "Text files",
            AttachmentKind.IMAGE: "Images",
            AttachmentKind.AUDIO: "Audio files",
            AttachmentKind.VIDEO: "Videos",
        }.get(attachment_kind, "Files")
        raise ValueError(f"{label} larger than {_format_size_limit(max_size)} are not supported")


def extract_text_attachment_content(file_obj):
    raw_bytes = file_obj.read(MAX_TEXT_ATTACHMENT_BYTES + 1)
    file_obj.seek(0)

    if len(raw_bytes) > MAX_TEXT_ATTACHMENT_BYTES:
        raw_bytes = raw_bytes[:MAX_TEXT_ATTACHMENT_BYTES]

    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "latin-1"):
        try:
            text = raw_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw_bytes.decode("utf-8", errors="replace")

    normalized = text.strip()
    if len(normalized) <= MAX_TEXT_ATTACHMENT_CHARS:
        return normalized

    return normalized[: MAX_TEXT_ATTACHMENT_CHARS - 20].rstrip() + "\n\n[Text truncated]"


@dataclass
class LegacyMessageAttachmentProxy:
    file: object
    attachment_name: str = ""
    attachment_mime_type: str = ""
    attachment_kind: str = ""
    attachment_text_content: str = ""
    sort_order: int = 0


def get_message_attachments(message):
    # 同一 message 对象上记忆化，保证发送管线内多次取附件拿到同一批实例
    # （media_analysis 等运行期属性才能跨调用保留），也避免重复查询。
    cached = getattr(message, "_cached_attachments", None)
    if cached is not None:
        return cached

    related_manager = getattr(message, "attachments", None)
    if related_manager is not None:
        prefetched = getattr(message, "_prefetched_objects_cache", {})
        if "attachments" in prefetched:
            attachments = list(prefetched["attachments"])
        else:
            attachments = list(related_manager.all())
        if attachments:
            message._cached_attachments = attachments
            return attachments

    legacy_file = getattr(message, "attachment", None)
    if not legacy_file:
        message._cached_attachments = []
        return []

    attachments = [
        LegacyMessageAttachmentProxy(
            file=legacy_file,
            attachment_name=getattr(message, "attachment_name", "") or "",
            attachment_mime_type=getattr(message, "attachment_mime_type", "") or "",
            attachment_kind=getattr(message, "attachment_kind", "") or AttachmentKind.TEXT,
            attachment_text_content=getattr(message, "attachment_text_content", "") or "",
        )
    ]
    message._cached_attachments = attachments
    return attachments


def get_primary_message_attachment(message):
    attachments = get_message_attachments(message)
    return attachments[0] if attachments else None


def describe_attachment_for_prompt(attachment, allow_text_body=False):
    if not getattr(attachment, "file", None):
        return ""

    attachment_name = getattr(attachment, "attachment_name", "") or os.path.basename(attachment.file.name or "") or "attachment"
    attachment_kind = getattr(attachment, "attachment_kind", "") or AttachmentKind.TEXT
    mime_type = getattr(attachment, "attachment_mime_type", "") or "application/octet-stream"

    if attachment_kind == AttachmentKind.TEXT:
        attachment_text = getattr(attachment, "attachment_text_content", "") or ""
        if allow_text_body and attachment_text:
            return (
                f"[Attached text file: {attachment_name}]\n"
                f"{attachment_text}"
            )
        return f"[Attached text file: {attachment_name}]"

    media_labels = {
        AttachmentKind.IMAGE: "image",
        AttachmentKind.AUDIO: "audio",
        AttachmentKind.VIDEO: "video",
    }
    media_label = media_labels.get(attachment_kind, "media")
    return f"[Attached {media_label}: {attachment_name} ({mime_type})]"
