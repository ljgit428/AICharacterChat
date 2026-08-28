"""Filesystem backends for the local ``list_memory_files`` / ``read_memory_file`` tools.

The chat pipeline and the character-draft pipeline share the same tool specs but
read from different sources:

- ``CharacterMemoryFilesystem`` reads the persisted Memory Explorer VFS for a
  saved ``Character`` (schema/wiki/raw layers, knowledge assets, transcripts).
- ``StagedUploadMemoryFilesystem`` reads the files the user just uploaded while
  creating a character, *before* the character row exists.

Both expose the same two methods so ``tasks._execute_local_memory_tool`` stays
backend-agnostic.
"""
from __future__ import annotations

import os
from typing import Any

from ..models import AttachmentKind
from ..soul import list_memory_explorer_path, read_memory_explorer_file, sanitize_memory_relative_path


class CharacterMemoryFilesystem:
    """Wraps the saved-character Memory Explorer VFS."""

    def __init__(self, character) -> None:
        self.character = character

    def list_memory_files(self, path_prefix: str = "", recursive: bool = False, max_entries: int = 40) -> dict:
        return list_memory_explorer_path(
            self.character,
            path_prefix=path_prefix,
            recursive=recursive,
            max_entries=max_entries,
        )

    def read_memory_file(self, path: str, max_chars: int = 6000) -> dict:
        return read_memory_explorer_file(self.character, path=path, max_chars=max_chars)


class StagedUploadMemoryFilesystem:
    """Lists/reads freshly uploaded character files (pre-save) as a browsable tree.

    Each upload is a dict::

        {
            "name": "dialogue.txt",
            "relative_path": "Momotalk/mari/scene_1.txt",   # optional folder group path
            "kind": "text" | "image",
            "mime_type": "text/plain",
            "content": "…",          # text content for text files, '' otherwise
            "file_url": "…",
        }

    The relative path preserves the uploaded folder-group hierarchy under
    ``UPLOAD_ROOT``; uploads without one land directly in ``UPLOAD_ROOT``.
    Same-named files from different folders are disambiguated with a ``__N``
    suffix instead of silently overwriting each other.
    """

    UPLOAD_ROOT = "raw/character_setup/uploads"

    def __init__(self, uploads: list[dict[str, Any]]) -> None:
        self.uploads = list(uploads or [])
        self._by_path: dict[str, dict[str, Any]] = {}
        used_paths: set[str] = set()
        for index, upload in enumerate(self.uploads):
            name = upload.get("relative_path") or upload.get("name") or f"upload-{index + 1}"
            rel_path = sanitize_memory_relative_path(name)
            stem, ext = os.path.splitext(rel_path)
            dedupe_index = 2
            while rel_path in used_paths:
                rel_path = f"{stem}__{dedupe_index}{ext}"
                dedupe_index += 1
            used_paths.add(rel_path)
            upload["_path"] = f"{self.UPLOAD_ROOT}/{rel_path}"
            self._by_path[upload["_path"]] = upload

    @staticmethod
    def _safe_name(name: str) -> str:
        normalized = os.path.basename((name or "").strip()) or "uploaded-file"
        return normalized.replace("\\", "_").replace("/", "_")

    def _entry(self, upload: dict[str, Any]) -> dict[str, Any]:
        kind = upload.get("kind") or AttachmentKind.TEXT
        content = upload.get("content") or ""
        return {
            "path": upload["_path"],
            "entry_type": "file",
            "layer": "raw",
            "title": os.path.basename(upload["_path"]),
            "kind": kind,
            "read_hint": "Original file uploaded while creating this character.",
            "is_locked": True,
            "can_user_edit": False,
            "can_auto_update": False,
            "updated_at": "",
            "manageable": False,
            "asset_id": None,
            "preview_kind": "image" if kind == AttachmentKind.IMAGE else "text",
            "size_hint": len(content),
        }

    @staticmethod
    def _clamp_max_entries(max_entries: int) -> int:
        try:
            return max(1, min(int(max_entries or 40), 200))
        except (TypeError, ValueError):
            return 40

    def _directory_entries(self) -> dict[str, dict[str, Any]]:
        directories: dict[str, dict[str, Any]] = {}
        for upload in self.uploads:
            parts = upload["_path"].split("/")
            for depth in range(len(self.UPLOAD_ROOT.split("/")) + 1, len(parts)):
                directory_path = "/".join(parts[:depth])
                directories.setdefault(directory_path, {
                    "path": directory_path,
                    "entry_type": "directory",
                    "layer": "raw",
                    "title": parts[depth - 1],
                    "kind": "directory",
                    "read_hint": "Folder of the uploaded reference file group.",
                    "is_locked": True,
                    "can_user_edit": False,
                    "can_auto_update": False,
                    "updated_at": "",
                    "manageable": False,
                    "asset_id": None,
                })
        return directories

    def list_memory_files(self, path_prefix: str = "", recursive: bool = False, max_entries: int = 40) -> dict:
        safe_max_entries = self._clamp_max_entries(max_entries)

        normalized_prefix = (path_prefix or "").strip().strip("/")
        file_entries = [self._entry(upload) for upload in self.uploads]
        directory_entries = list(self._directory_entries().values())

        def matches(path: str) -> bool:
            if not normalized_prefix:
                return True
            return path == normalized_prefix or path.startswith(f"{normalized_prefix}/")

        entries = [
            *[entry for entry in directory_entries if matches(entry["path"])],
            *[entry for entry in file_entries if matches(entry["path"])],
        ]
        if not recursive and normalized_prefix:
            # Mirror the explorer semantics: browsing a folder lists its direct
            # children only; the folder itself is not part of its own listing.
            entries = [
                entry for entry in entries
                if entry["path"] != normalized_prefix
                and entry["path"].rsplit("/", 1)[0] == normalized_prefix
            ]

        truncated = len(entries) > safe_max_entries
        return {
            "path_prefix": normalized_prefix or "/",
            "entries": sorted(entries, key=lambda item: (item["entry_type"] != "directory", item["path"]))[:safe_max_entries],
            "error": "",
            "truncated": truncated,
        }

    def build_directory_index(self) -> str:
        """Render a compact tree listing for prompt injection so the model can
        see the whole file group without spending tool calls on browsing."""
        lines: list[str] = []
        for upload in sorted(self.uploads, key=lambda item: item["_path"]):
            size_hint = len(upload.get("content") or "")
            suffix = f" ({size_hint} chars)" if size_hint else ""
            lines.append(f"- {upload['_path']}{suffix}")
        return "\n".join(lines)

    def read_memory_file(self, path: str, max_chars: int = 6000) -> dict:
        try:
            safe_max_chars = max(200, min(int(max_chars or 6000), 12000))
        except (TypeError, ValueError):
            safe_max_chars = 6000

        normalized_path = (path or "").strip().strip("/")
        upload = self._by_path.get(normalized_path)
        if upload is None:
            return {"path": normalized_path, "error": "File not found in staged uploads."}

        kind = upload.get("kind") or AttachmentKind.TEXT
        content = upload.get("content") or ""
        truncated = len(content) > safe_max_chars
        return {
            "path": normalized_path,
            "layer": "raw",
            "title": os.path.basename(normalized_path),
            "kind": kind,
            "read_hint": "Original file uploaded while creating this character.",
            "content": content[:safe_max_chars],
            "truncated": truncated,
            "manageable": False,
            "asset_id": None,
            "preview_kind": "image" if kind == AttachmentKind.IMAGE else "text",
            "file_url": upload.get("file_url", ""),
            "mime_type": upload.get("mime_type", ""),
        }
