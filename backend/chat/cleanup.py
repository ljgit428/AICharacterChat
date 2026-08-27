"""删除角色时清理关联的磁盘文件。

数据库行由外键 CASCADE 级联删除（会话、消息、知识资产、记忆条目等），
但 FileField / URL 字段对应的实体文件不会自动删除，需要在此显式清理：

- 头像（avatar_url 是 URL 字段，需要解析回本地存储路径）
- Character.file
- CharacterKnowledgeAsset.file
- Message.attachment / MessageAttachment.file

Gemini 云端文件（gemini_file_name）自带 48 小时 TTL 会自行过期，与单个知识
资产删除时的行为一致，不在此清理。
"""
from __future__ import annotations

import logging
import os
from typing import Optional
from urllib.parse import unquote, urlparse

from django.conf import settings
from django.core.files.storage import default_storage

from .models import Message, MessageAttachment

logger = logging.getLogger(__name__)


def _resolve_local_media_path(file_url: Optional[str]) -> Optional[str]:
    """把本地媒体 URL（可能是绝对 URL）解析为 MEDIA_ROOT 下的文件路径。

    外部 URL 或已不存在的本地文件返回 None，避免误删。
    """
    if not file_url:
        return None

    parsed_url = urlparse(file_url)
    relative_path = unquote(parsed_url.path).lstrip('/')
    media_url_path = urlparse(settings.MEDIA_URL).path.lstrip('/')
    if media_url_path and relative_path.startswith(media_url_path):
        relative_path = relative_path[len(media_url_path):].lstrip('/')
    elif relative_path.startswith('media/'):
        relative_path = relative_path[6:]

    file_path = os.path.normpath(os.path.join(settings.MEDIA_ROOT, relative_path))
    media_root = os.path.normpath(settings.MEDIA_ROOT)
    try:
        if os.path.commonpath([media_root, file_path]) != media_root:
            return None
    except ValueError:
        return None

    return file_path if os.path.exists(file_path) else None


def cleanup_character_files(character) -> None:
    """删除该角色拥有的全部磁盘文件，必须在 ``character.delete()`` 之前调用。

    此时关联行尚未被 CASCADE 删除，可以收集到所有 FileField 的名字。
    单个文件删除失败只记日志，不阻断角色删除。
    """
    file_names: list[str] = []

    avatar_path = _resolve_local_media_path(character.avatar_url)
    if avatar_path:
        # 存储按相对 MEDIA_ROOT 的名字操作，直接删绝对路径依赖
        # os.path.join 的覆盖语义，可读性差；先换算成相对名。
        file_names.append(os.path.relpath(avatar_path, settings.MEDIA_ROOT))

    if character.file:
        file_names.append(character.file.name)

    file_names.extend(
        name
        for name in character.knowledge_assets.values_list('file', flat=True)
        if name
    )
    file_names.extend(
        name
        for name in Message.objects.filter(
            chat_session__character=character,
        ).exclude(attachment='').values_list('attachment', flat=True)
        if name
    )
    file_names.extend(
        name
        for name in MessageAttachment.objects.filter(
            message__chat_session__character=character,
        ).exclude(file='').values_list('file', flat=True)
        if name
    )

    for name in file_names:
        try:
            default_storage.delete(name)
        except Exception:  # noqa: BLE001
            logger.warning('Failed to delete file %s for character %s', name, character.pk)
