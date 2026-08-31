"""Asset log projection: ``CharacterKnowledgeAsset`` rows are a materialized
view of the ``AssetEvent`` log.

Write-through on every attach/detach; a best-effort rebuild replays attached
events. Physical files are external resources — a detach deletes the asset
file, and a rebuild can only re-copy a file while its pending staging copy
still exists (attached events normally move the file out of pending, so the
rebuild is primarily a consistency check for recently-attached assets).
"""
from __future__ import annotations

import os

from django.conf import settings
from django.core.files.base import File as DjangoFile
from django.core.files.storage import default_storage
from django.db import transaction

from ..models import AssetEvent, AssetEventType, Character, CharacterKnowledgeAsset


class AssetFileMissingError(Exception):
    """Raised when an attach cannot find the pending staging file."""


def _pending_file_path(upload_event: AssetEvent) -> str | None:
    """Resolve the pending storage path recorded on an uploaded event."""
    data = upload_event.data or {}
    file_path = data.get('file_path') or ''
    if not file_path:
        return None
    # Guard against traversal / absolute paths; must live under MEDIA_ROOT.
    normalized = os.path.normpath(os.path.join(settings.MEDIA_ROOT, file_path))
    media_root = os.path.normpath(settings.MEDIA_ROOT)
    try:
        if os.path.commonpath([media_root, normalized]) != media_root:
            return None
    except ValueError:
        return None
    return normalized


def _upload_event_for(event: AssetEvent) -> AssetEvent | None:
    upload_id = (event.data or {}).get('upload_event_id')
    if not upload_id:
        return None
    return AssetEvent.objects.filter(
        id=upload_id,
        user=event.user,
        event_type=AssetEventType.UPLOADED,
    ).first()


def project_event(event: AssetEvent) -> CharacterKnowledgeAsset | None:
    """Apply one asset event to the projection. Returns the affected asset row
    for attach, ``None`` otherwise."""
    if event.event_type == AssetEventType.ATTACHED:
        return _project_attached(event)
    if event.event_type == AssetEventType.DETACHED:
        _project_detached(event)
    return None


def _project_attached(event: AssetEvent, *, rebuild: bool = False) -> CharacterKnowledgeAsset:
    if event.character is None:
        raise AssetFileMissingError('asset/attached event without a character')

    upload_event = _upload_event_for(event)
    if upload_event is None:
        raise AssetFileMissingError(
            f'asset/attached {event.id} references missing asset/uploaded event'
        )
    if CharacterKnowledgeAsset.objects.filter(upload_event_id=upload_event.id).exists():
        raise AssetFileMissingError(
            f'asset/uploaded {upload_event.id} is already attached'
        )

    data = upload_event.data or {}
    file_name = (data.get('file_name') or '').strip() or 'uploaded-file'
    payload = event.data or {}

    # Rebuild path: a previous attach already moved the file into the asset
    # storage; the pending copy is gone. If the committed asset file still
    # exists on disk (queryset bulk-delete does not remove files), reference
    # it directly instead of re-copying.
    if rebuild:
        committed = os.path.join(settings.MEDIA_ROOT, f'character_knowledge_assets/{file_name}')
        if os.path.exists(committed):
            asset = CharacterKnowledgeAsset(
                character=event.character,
                attachment_name=file_name,
                attachment_mime_type=data.get('attachment_mime_type') or '',
                attachment_kind=data.get('attachment_kind') or '',
                attachment_text_content=data.get('attachment_text_content') or '',
                sort_order=payload.get('sort_order', 0),
                upload_event_id=upload_event.id,
            )
            asset.file.name = os.path.relpath(committed, settings.MEDIA_ROOT)
            asset.save()
            return asset

    source_path = _pending_file_path(upload_event)
    if not source_path or not os.path.exists(source_path):
        raise AssetFileMissingError(
            f'Pending staging file for upload {upload_event.id} is missing: '
            f'{source_path or "(no path)"}'
        )

    asset = CharacterKnowledgeAsset(
        character=event.character,
        attachment_name=file_name,
        attachment_mime_type=data.get('attachment_mime_type') or '',
        attachment_kind=data.get('attachment_kind') or '',
        attachment_text_content=data.get('attachment_text_content') or '',
        sort_order=payload.get('sort_order', 0),
        upload_event_id=upload_event.id,
    )
    with open(source_path, 'rb') as source_file:
        django_file = DjangoFile(source_file, name=file_name)
        asset.file.save(file_name, django_file, save=False)
        asset.save()
    # The staging copy is consumed by the attach: keep disk usage single.
    default_storage.delete(upload_event.data.get('file_path') or '')
    return asset


def _project_detached(event: AssetEvent) -> None:
    data = event.data or {}
    # 优先通过 data.asset_id 定位行（支持历史/直建资产）；回退 upload_event_id。
    asset = None
    asset_id = data.get('asset_id')
    if asset_id is not None:
        try:
            asset = CharacterKnowledgeAsset.objects.get(
                id=int(asset_id),
                character=event.character,
            )
        except (CharacterKnowledgeAsset.DoesNotExist, TypeError, ValueError):
            pass
    if asset is None:
        upload_event = _upload_event_for(event)
        if upload_event is not None:
            asset = CharacterKnowledgeAsset.objects.filter(
                upload_event_id=upload_event.id,
                character=event.character,
            ).first()
    if asset is None:
        return
    if asset.file:
        asset.file.delete(save=False)
    asset.delete()


def rebuild_character_assets(character: Character) -> list[CharacterKnowledgeAsset]:
    """Best-effort rebuild of a character's asset projection from the log.

    Only attached events whose staging file is still present can be restored;
    others are skipped with a warning-level expectation (detached/expired
    events already deleted their files).
    """
    with transaction.atomic():
        CharacterKnowledgeAsset.objects.filter(character=character).delete()
        restored: list[CharacterKnowledgeAsset] = []
        attached_events = (
            AssetEvent.objects.filter(
                character=character,
                event_type=AssetEventType.ATTACHED,
            ).order_by('id')
        )
        for event in attached_events:
            try:
                asset = _project_attached(event, rebuild=True)
            except AssetFileMissingError:
                continue
            restored.append(asset)
    return restored
