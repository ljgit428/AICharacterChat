"""Asset event type constants and payload builders for the character-reference
asset event log (``AssetEvent``).
"""
from __future__ import annotations

import hashlib
import os
from typing import Any


def uploaded_payload(
    *,
    file_name: str,
    file_path: str,
    attachment_kind: str = '',
    attachment_mime_type: str = '',
    attachment_text_content: str = '',
    size: int = 0,
    sha256: str = '',
) -> dict:
    """Payload for an ``asset/uploaded`` event."""
    return {
        'file_path': file_path or '',
        'file_name': file_name or '',
        'attachment_kind': attachment_kind or '',
        'attachment_mime_type': attachment_mime_type or '',
        'attachment_text_content': attachment_text_content or '',
        'size': size or 0,
        'sha256': sha256 or '',
    }


def attached_payload(
    *,
    upload_event_id: int,
    sort_order: int = 0,
) -> dict:
    """Payload for an ``asset/attached`` event."""
    return {
        'upload_event_id': int(upload_event_id),
        'sort_order': int(sort_order),
    }


def detached_payload(
    *,
    upload_event_id: int,
    asset_id: int | None = None,
    reason: str = '',
) -> dict:
    """Payload for an ``asset/detached`` event.

    ``asset_id`` names the projected ``CharacterKnowledgeAsset`` row directly,
    so legacy/directly-created assets (which have no ``upload_event_id``) can
    be detached too.
    """
    return {
        'upload_event_id': int(upload_event_id),
        'asset_id': int(asset_id) if asset_id is not None else None,
        'reason': reason or '',
    }


def expired_payload(
    *,
    upload_event_id: int,
    reason: str = '',
) -> dict:
    """Payload for an ``asset/expired`` event."""
    return {
        'upload_event_id': int(upload_event_id),
        'reason': reason or '',
    }


def sha256_file(file_path: str) -> str:
    """Compute SHA-256 of a file (for deduplication and integrity)."""
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()