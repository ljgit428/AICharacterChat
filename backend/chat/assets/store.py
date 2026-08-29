"""AssetStore: the service that owns the character-reference asset event log.

Every asset lifecycle step is an append-only ``AssetEvent``: upload (staged,
with TTL), attach (bound to a character), detach (removed), expire (abandoned
staging). ``CharacterKnowledgeAsset`` rows are the write-through projection
(``chat.assets.projection``). Uploads are authenticated and size-limited;
abandoned staging files are reclaimed lazily (on every upload) and via the
``clean_stale_uploads`` management command.
"""
from __future__ import annotations

import os
import uuid
from datetime import timedelta
from typing import Any, Iterable

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from ..attachments import (
    MAX_STAGING_TEXT_BYTES,
    extract_text_attachment_content,
    guess_attachment_kind,
    validate_attachment_size,
)
from ..models import (
    AssetEvent,
    AssetEventType,
    AttachmentKind,
    Character,
    CharacterKnowledgeAsset,
    User,
)
from . import projection
from .types import (
    attached_payload,
    detached_payload,
    expired_payload,
    sha256_file,
    uploaded_payload,
)


def _upload_ttl() -> timedelta:
    days = getattr(settings, 'ASSET_UPLOAD_TTL_DAYS', 7)
    try:
        return timedelta(days=max(1, int(days)))
    except (TypeError, ValueError):
        return timedelta(days=7)


def _collect_upload_event_ids(event_type: str) -> set[int]:
    """Return the set of ``data.upload_event_id`` values from events of a type.

    Reads the JSONB key into Python (avoiding PostgreSQL's JSONB-vs-bigint
    comparison error that ``data__upload_event_id__in`` triggers).
    """
    collected: set[int] = set()
    rows = (
        AssetEvent.objects.filter(event_type=event_type)
        .values_list('data__upload_event_id', flat=True)
    )
    for value in rows:
        if value is None:
            continue
        try:
            collected.add(int(value))
        except (TypeError, ValueError):
            continue
    return collected


class AssetStore:
    """Service for the character-reference asset event log."""

    # ------------------------------------------------------------------
    #  upload

    @staticmethod
    def upload(user: User, file_obj, relative_path: str = '') -> tuple[AssetEvent, dict]:
        """Stage one uploaded file as an ``asset/uploaded`` event.

        Saves the file under ``uploads/pending/<user>/<uuid>/<name>`` with a
        TTL and returns ``(event, metadata)``. Reclaims stale staging files
        lazily. ``relative_path`` preserves the user's folder-group hierarchy
        in the display name.
        """
        kind, mime_type = guess_attachment_kind(file_obj)
        if kind not in {AttachmentKind.TEXT, AttachmentKind.IMAGE}:
            raise ValueError('Only text files and images are supported for character reference uploads.')
        # 语料文件放宽到 MAX_STAGING_TEXT_BYTES；聊天附件仍走 2MB 默认上限。
        validate_attachment_size(file_obj, kind, max_text_bytes=MAX_STAGING_TEXT_BYTES)
        text_content = extract_text_attachment_content(file_obj) if kind == AttachmentKind.TEXT else ''
        file_obj.seek(0)

        safe_name = os.path.basename(relative_path or file_obj.name or 'uploaded_file')
        storage_name = f"uploads/pending/{user.pk}/{uuid.uuid4().hex}/{safe_name}"
        saved_name = default_storage.save(storage_name, file_obj)
        absolute_path = os.path.join(settings.MEDIA_ROOT, saved_name)
        size = 0
        sha = ''
        try:
            size = os.path.getsize(absolute_path)
            sha = sha256_file(absolute_path)
        except OSError:
            pass

        display_name = (relative_path or '').strip() or safe_name
        payload = uploaded_payload(
            file_name=display_name,
            file_path=saved_name,
            attachment_kind=kind,
            attachment_mime_type=mime_type,
            attachment_text_content=text_content,
            size=size,
            sha256=sha,
        )

        with transaction.atomic():
            event = AssetEvent.objects.create(
                user=user,
                event_type=AssetEventType.UPLOADED,
                data=payload,
                expires_at=timezone.now() + _upload_ttl(),
            )

        # Lazy reclamation: reuse this request to sweep other users' expired
        # staging files. Never blocks the upload on a failed sweep.
        try:
            AssetStore.expire_stale()
        except Exception:  # noqa: BLE001
            pass

        metadata = {
            'upload_id': event.id,
            'name': display_name,
            'relative_path': display_name,
            'kind': kind,
            'mime_type': mime_type,
        }
        return event, metadata

    # ------------------------------------------------------------------
    #  attach / detach

    @staticmethod
    def attach(character: Character, upload_event_ids: Iterable[int]) -> list[CharacterKnowledgeAsset]:
        """Bind staged uploads to a character (append ``asset/attached`` +
        projection). Raises on missing/unowned/already-attached uploads rather
        than silently dropping them."""
        upload_ids = list(upload_event_ids)
        if not upload_ids:
            return []

        uploads = list(
            AssetEvent.objects.filter(
                id__in=upload_ids,
                user=character.created_by,
                event_type=AssetEventType.UPLOADED,
            )
        )
        found = {u.id for u in uploads}
        missing = [str(i) for i in upload_ids if i not in found]
        if missing:
            raise projection.AssetFileMissingError(
                f'Pending uploads not found or not owned by this user: {", ".join(missing)}'
            )

        next_sort_order = (
            character.knowledge_assets.order_by('-sort_order').values_list('sort_order', flat=True).first() or 0
        )
        assets: list[CharacterKnowledgeAsset] = []
        for index, upload_event in enumerate(sorted(uploads, key=lambda e: e.id), start=1):
            with transaction.atomic():
                event = AssetEvent.objects.create(
                    user=character.created_by,
                    character=character,
                    event_type=AssetEventType.ATTACHED,
                    data=attached_payload(
                        upload_event_id=upload_event.id,
                        sort_order=next_sort_order + index,
                    ),
                )
                asset = projection.project_event(event)
            assets.append(asset)
        return assets

    @staticmethod
    def detach(character: Character, asset_ids: Iterable[int], reason: str = '') -> int:
        """Remove assets from a character (append ``asset/detached`` +
        projection). Returns the number of detached assets."""
        ids = list(asset_ids)
        if not ids:
            return 0
        assets = list(character.knowledge_assets.filter(id__in=ids))
        count = 0
        for asset in assets:
            upload_event_id = asset.upload_event_id
            with transaction.atomic():
                event = AssetEvent.objects.create(
                    user=character.created_by,
                    character=character,
                    event_type=AssetEventType.DETACHED,
                    data=detached_payload(
                        upload_event_id=upload_event_id or 0,
                        asset_id=asset.id,
                        reason=reason,
                    ),
                )
                projection.project_event(event)
            count += 1
        return count

    # ------------------------------------------------------------------
    #  reads

    @staticmethod
    def pending_uploads(user: User, *, upload_ids: Iterable[int] | None = None) -> list[AssetEvent]:
        """Unattached, unexpired upload events for a user (optionally filtered
        by id). These feed the draft-generation memory filesystem."""
        qs = AssetEvent.objects.filter(
            user=user,
            event_type=AssetEventType.UPLOADED,
        )
        if upload_ids:
            qs = qs.filter(id__in=list(upload_ids))

        upload_ids_set = set(qs.values_list('id', flat=True))
        if not upload_ids_set:
            return []

        # Collect upload_event_ids from attached/expired events (Python-side,
        # avoiding JSONB vs bigint type mismatch in PostgreSQL).
        attached_upload_ids = _collect_upload_event_ids(AssetEventType.ATTACHED)
        expired_upload_ids = _collect_upload_event_ids(AssetEventType.EXPIRED)

        return [
            e for e in qs.order_by('id')
            if e.id not in attached_upload_ids
            and e.id not in expired_upload_ids
            and (not e.expires_at or e.expires_at > timezone.now())
        ]

    @staticmethod
    def event_payload_map(user: User, upload_ids: Iterable[int]) -> dict[int, dict[str, Any]]:
        """Map upload event id → metadata for draft generation (kind/content)."""
        uploads = AssetStore.pending_uploads(user, upload_ids=upload_ids)
        return {e.id: (e.data or {}) for e in uploads}

    # ------------------------------------------------------------------
    #  reclamation

    @staticmethod
    def expire_stale(*, now=None) -> int:
        """Close expired, unattached uploads with ``asset/expired`` and delete
        their staging files. Returns the number expired."""
        now = now or timezone.now()
        stale_uploads = AssetEvent.objects.filter(
            event_type=AssetEventType.UPLOADED,
            expires_at__lt=now,
        )
        attached_upload_ids = _collect_upload_event_ids(AssetEventType.ATTACHED)
        expired_upload_ids = _collect_upload_event_ids(AssetEventType.EXPIRED)

        count = 0
        for upload_event in stale_uploads.iterator():
            if upload_event.id in attached_upload_ids or upload_event.id in expired_upload_ids:
                continue
            with transaction.atomic():
                AssetEvent.objects.create(
                    user=upload_event.user,
                    event_type=AssetEventType.EXPIRED,
                    data=expired_payload(
                        upload_event_id=upload_event.id,
                        reason='staging TTL elapsed',
                    ),
                )
                default_storage.delete((upload_event.data or {}).get('file_path') or '')
            count += 1
        return count
