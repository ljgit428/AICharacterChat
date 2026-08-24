"""DB-backed wrapper for ``CharacterMemoryItem`` and ``MemoryAuditLog``.

Mirrors SonettoHere's ``memory_manager.py`` + ``MemoryManager`` + ``MemoryItem``
semantics: id + section + description + per-entry history. We prefix the model
with ``Character`` because the AI's many characters each have their own
``memory.yaml`` equivalent.
"""
from __future__ import annotations

import secrets
from typing import Any

from django.db import transaction
from django.utils import timezone as django_timezone

from ..models import (
    Character,
    CharacterMemoryItem,
    MemoryAuditAction,
    MemoryAuditLog,
    MemoryAuditSource,
    Message,
)
from .constants import PRIORITY_SECTIONS, RELATIONSHIP_SECTION


class MemoryItemNotFoundError(Exception):
    """Raised when an update/merge/delete targets a missing short_id."""


def _now_iso() -> str:
    return django_timezone.now().isoformat()


def _new_short_id() -> str:
    """4-byte hex id, matching SonettoHere's ``secrets.token_hex(4)``."""
    return secrets.token_hex(4)


class MemoryManager:
    """DB-backed CRUD facade for a single character's memory items."""

    description_limit = 200  # characters (Chinese counts as one)

    def __init__(self, character: Character) -> None:
        self.character = character

    # ------------------------------------------------------------------ read

    def list_items(self) -> list[CharacterMemoryItem]:
        return list(
            CharacterMemoryItem.objects
            .filter(character=self.character)
            .order_by("section", "short_id")
        )

    def get_item(self, short_id: str) -> CharacterMemoryItem:
        try:
            return CharacterMemoryItem.objects.get(character=self.character, short_id=short_id)
        except CharacterMemoryItem.DoesNotExist as exc:
            raise MemoryItemNotFoundError(short_id) from exc

    # ---------------------------------------------------------------- create

    def create_item(
        self,
        *,
        section: str,
        description: str,
        source_message: Message | None = None,
        reason: str = "",
        source: str = MemoryAuditSource.CELERY_WORKER,
    ) -> CharacterMemoryItem:
        section = (section or "").strip()
        description = (description or "").strip()
        if not section:
            raise ValueError("section is required")
        if not description:
            raise ValueError("description is required")
        if len(description) > self.description_limit:
            raise ValueError(
                f"description exceeds {self.description_limit} characters (got {len(description)}); "
                "split into multiple shorter entries instead."
            )
        # Memory v2 §4.2 hard constraint: 「关系」 holds exactly one entry. If the
        # extraction model ignores the prompt rule and creates a second one,
        # silently redirect this call into an update of the existing entry so
        # the version history (and thus the growth timeline) stays in one place.
        if section == RELATIONSHIP_SECTION:
            existing = (
                CharacterMemoryItem.objects
                .filter(character=self.character, section=RELATIONSHIP_SECTION)
                .order_by("-updated_at", "-id")
                .first()
            )
            if existing is not None:
                redirect_reason = (reason or "").strip() or "关系更新"
                return self.update_item(
                    short_id=existing.short_id,
                    description=description,
                    reason=f"{redirect_reason}（auto-redirect: single-entry section）",
                    source_message=source_message,
                    source=source,
                )
        with transaction.atomic():
            short_id = self._unique_short_id()
            item = CharacterMemoryItem.objects.create(
                character=self.character,
                short_id=short_id,
                section=section[:64],
                description=description,
                description_history=[],
            )
            MemoryAuditLog.objects.create(
                character=self.character,
                chat_session=source_message.chat_session if source_message else None,
                message=source_message,
                action=MemoryAuditAction.CREATE,
                entry_short_id=short_id,
                before_description="",
                after_description=description,
                reason=reason,
                source=source,
            )
        return item

    # ---------------------------------------------------------------- update

    def update_item(
        self,
        *,
        short_id: str,
        description: str,
        reason: str,
        section: str | None = None,
        source_message: Message | None = None,
        source: str = MemoryAuditSource.CELERY_WORKER,
    ) -> CharacterMemoryItem:
        description = (description or "").strip()
        if not description:
            raise ValueError("description cannot be empty")
        if len(description) > self.description_limit:
            raise ValueError(
                f"description exceeds {self.description_limit} characters (got {len(description)}); "
                "split into multiple shorter entries instead."
            )
        with transaction.atomic():
            item = self.get_item(short_id)
            old_desc, old_section, old_time = item.description, item.section, _now_iso()
            new_section = (section or item.section).strip()[:64] or item.section
            if new_section == RELATIONSHIP_SECTION and old_section != RELATIONSHIP_SECTION:
                clash = (
                    CharacterMemoryItem.objects
                    .filter(character=self.character, section=RELATIONSHIP_SECTION)
                    .exclude(short_id=short_id)
                    .exists()
                )
                if clash:
                    raise ValueError(
                        "「关系」 section already holds its single entry; update that entry "
                        "instead of moving another one into it."
                    )
            history = list(item.description_history or [])
            history.append({
                "old_desc": old_desc,
                "new_desc": description,
                "old_section": old_section if old_section != new_section else "",
                "new_section": new_section if old_section != new_section else "",
                "old_time": old_time,
                "new_time": _now_iso(),
                "reason": (reason or "").strip(),
            })
            item.description = description
            item.section = new_section
            item.description_history = history
            item.save(update_fields=["description", "section", "description_history", "updated_at"])
            MemoryAuditLog.objects.create(
                character=self.character,
                chat_session=source_message.chat_session if source_message else None,
                message=source_message,
                action=MemoryAuditAction.UPDATE,
                entry_short_id=short_id,
                before_description=old_desc,
                after_description=description,
                reason=reason,
                source=source,
            )
        return item

    # ---------------------------------------------------------------- delete

    def delete_item(
        self,
        *,
        short_id: str,
        reason: str,
        source_message: Message | None = None,
        source: str = MemoryAuditSource.CELERY_WORKER,
    ) -> str:
        with transaction.atomic():
            item = self.get_item(short_id)
            removed_desc = item.description
            MemoryAuditLog.objects.create(
                character=self.character,
                chat_session=source_message.chat_session if source_message else None,
                message=source_message,
                action=MemoryAuditAction.DELETE,
                entry_short_id=short_id,
                before_description=removed_desc,
                after_description="",
                reason=reason,
                source=source,
            )
            item.delete()
        return removed_desc

    # ---------------------------------------------------------------- merge

    def merge_items(
        self,
        *,
        id1: str,
        id2: str,
        content: str,
        section: str,
        reason: str,
        source_message: Message | None = None,
        source: str = MemoryAuditSource.CELERY_WORKER,
    ) -> CharacterMemoryItem:
        content = (content or "").strip()
        section = (section or "").strip()[:64]
        if not content or not section:
            raise ValueError("merge requires both content and section")
        if len(content) > self.description_limit:
            raise ValueError(
                f"merged description exceeds {self.description_limit} characters (got {len(content)}); "
                "keep both entries instead."
            )
        if id1 == id2:
            raise ValueError("merge requires two distinct ids")
        if section == RELATIONSHIP_SECTION:
            clash = (
                CharacterMemoryItem.objects
                .filter(character=self.character, section=RELATIONSHIP_SECTION)
                .exclude(short_id=id1)
                .exclude(short_id=id2)
                .exists()
            )
            if clash:
                raise ValueError(
                    "「关系」 section already holds its single entry; merge into that "
                    "entry instead of producing a second one."
                )
        with transaction.atomic():
            primary = self.get_item(id1)
            secondary = self.get_item(id2)
            old_primary_desc, old_primary_section = primary.description, primary.section
            combined_history = list(primary.description_history or []) + list(secondary.description_history or [])
            combined_history.append({
                "old_desc": old_primary_desc,
                "new_desc": content,
                "old_section": old_primary_section if old_primary_section != section else "",
                "new_section": section if old_primary_section != section else "",
                "old_time": _now_iso(),
                "new_time": _now_iso(),
                "reason": (reason or "").strip(),
                "merged_from": id2,
            })
            primary.description = content
            primary.section = section
            primary.description_history = combined_history
            primary.save(update_fields=["description", "section", "description_history", "updated_at"])
            MemoryAuditLog.objects.create(
                character=self.character,
                chat_session=source_message.chat_session if source_message else None,
                message=source_message,
                action=MemoryAuditAction.MERGE,
                entry_short_id=id1,
                before_description=f"{old_primary_desc} [+ merged: {secondary.description}]",
                after_description=content,
                reason=reason,
                source=source,
            )
            secondary.delete()
        return primary

    # ------------------------------------------------------ rendering helpers

    def render_narrative(self) -> str:
        """Compose a single markdown blob for prompt injection (mirror of
        SonettoHer's ``_format_narrative``)."""
        narrative, _truncated = self.get_prompt_memory()
        return narrative

    def get_prompt_memory(self, *, budget_chars: int | None = None) -> tuple[str, bool]:
        """Single entry point for prompt-side memory (memory v2 §3.2).

        Returns ``(narrative, truncated)``. Priority sections
        (:data:`~.constants.PRIORITY_SECTIONS`) are always included in full;
        remaining sections contribute newest-first until ``budget_chars`` is
        exhausted — items that no longer fit are dropped whole, never cut
        mid-sentence. ``budget_chars=None`` means unlimited.
        """
        from django.utils import timezone as django_timezone

        items = self.list_items()
        if not items:
            return "", False

        by_section: dict[str, list[CharacterMemoryItem]] = {}
        for item in items:
            by_section.setdefault(item.section, []).append(item)

        def _recency(item: CharacterMemoryItem):
            return item.updated_at or item.created_at or django_timezone.now()

        priority_present = [s for s in PRIORITY_SECTIONS if s in by_section]
        remaining_sections = sorted(
            (s for s in by_section if s not in PRIORITY_SECTIONS),
            key=lambda s: max(_recency(i) for i in by_section[s]),
            reverse=True,
        )

        header = "# Long-Term Memory (User Model)"
        lines: list[str] = [header]
        used = len(header)
        truncated = False

        for section in priority_present + remaining_sections:
            section_lines = ["", f"## {section}"]
            section_cost = sum(len(line) for line in section_lines)
            for item in sorted(by_section[section], key=_recency, reverse=True):
                entry = f"- {item.description}"
                projected = used + section_cost + len(entry) + 1
                if budget_chars is not None and section not in PRIORITY_SECTIONS and projected > budget_chars:
                    truncated = True
                    continue
                section_lines.append(entry)
                section_cost += len(entry) + 1
            if len(section_lines) > 2:
                lines.extend(section_lines)
                used += section_cost

        return "\n".join(lines).strip() + "\n", truncated

    def render_wiki_markdown(self) -> str:
        """Render ``wiki/memory.md`` for the existing MemoryExplorer VFS."""
        items = self.list_items()
        if not items:
            return (
                "# Long-Term Memory (User Model)\n\n"
                "No durable memories recorded yet.\n"
            )
        last_updated = max((item.updated_at for item in items), default=None)
        lines = [
            "# Long-Term Memory (User Model)",
            "",
            f"_Last updated: {last_updated.isoformat() if last_updated else 'never'}_",
            "",
        ]
        by_section: dict[str, list[CharacterMemoryItem]] = {}
        section_order: list[str] = []
        for item in items:
            if item.section not in by_section:
                by_section[item.section] = []
                section_order.append(item.section)
            by_section[item.section].append(item)
        for section in section_order:
            lines.append(f"## {section}")
            for item in by_section[section]:
                lines.append(f"- {item.description}")
            lines.append("")
        lines.append("---")
        lines.append(
            f"{len(items)} entries across {len(by_section)} sections. "
            "Auto-written after every AI turn. Edit in the /memory page."
        )
        return "\n".join(lines).strip() + "\n"

    def grouped(self) -> dict[str, list[dict[str, Any]]]:
        """Mirror of SonettoHere ``MemoryManager.get_memories_grouped()``."""
        items = self.list_items()
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            groups.setdefault(item.section, []).append({
                "short_id": item.short_id,
                "description": item.description,
                "history": list(item.description_history or []),
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            })
        return {
            "sections": [
                {"section": section, "items": sorted(items_in_section, key=lambda x: x["updated_at"], reverse=True)}
                for section, items_in_section in sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)
            ]
        }

    # -------------------------------------------------------------- helpers

    def _unique_short_id(self) -> str:
        existing = set(
            CharacterMemoryItem.objects
            .filter(character=self.character)
            .values_list("short_id", flat=True)
        )
        for _ in range(8):
            candidate = _new_short_id()
            if candidate not in existing:
                return candidate
        raise RuntimeError("Could not allocate a unique short_id for a new memory item")
