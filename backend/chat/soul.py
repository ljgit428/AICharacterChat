import os

from django.db import DatabaseError

from .models import AttachmentKind, UserProfile


MEMORY_LAYER_DESCRIPTIONS = {
    "schema": "Rules, invariants, and update policy.",
    "wiki": "Curated long-term knowledge and growing user-model memory.",
    "raw": "Original uploaded files and other source evidence.",
}

WIKI_MEMORY_PATH = "wiki/memory.md"


def bootstrap_soul_documents(character):
    return []


def apply_session_updates_to_soul(character, chat_session, update_bundle, research_context=None, source_refs=None):
    return None


def _clean_text(value):
    return (value or "").strip()


def _join_sections(sections):
    return "\n\n".join(section for section in sections if section and section.strip()).strip()


def _safe_file_url(file_obj):
    if not file_obj:
        return ""
    try:
        return file_obj.url
    except ValueError:
        return ""


def _get_character_knowledge_assets(character):
    assets = list(character.knowledge_assets.all())
    if assets:
        return assets

    if not character.file:
        return []

    legacy_name = os.path.basename(character.file.name or "")
    return [{
        "file_name": legacy_name,
        "file_path": getattr(character.file, "path", ""),
        "file_url": _safe_file_url(character.file),
        "attachment_kind": AttachmentKind.TEXT,
        "attachment_mime_type": "text/plain",
        "attachment_text_content": "",
        "created_at": "",
        "updated_at": "",
        "is_legacy": True,
    }]


def _get_asset_name(asset):
    if isinstance(asset, dict):
        return asset.get("file_name", "") or "uploaded-file"
    return asset.attachment_name or os.path.basename(asset.file.name or "") or "uploaded-file"


def _get_asset_path(asset):
    if isinstance(asset, dict):
        return asset.get("file_path", "")
    return asset.file.path if getattr(asset, "file", None) else ""


def _get_asset_url(asset):
    if isinstance(asset, dict):
        return asset.get("file_url", "")
    return _safe_file_url(getattr(asset, "file", None))


def _get_asset_kind(asset):
    if isinstance(asset, dict):
        return asset.get("attachment_kind", AttachmentKind.TEXT) or AttachmentKind.TEXT
    return asset.attachment_kind or AttachmentKind.TEXT


def _get_asset_mime_type(asset):
    if isinstance(asset, dict):
        return asset.get("attachment_mime_type", "")
    return asset.attachment_mime_type or ""


def _get_asset_inline_text(asset):
    if isinstance(asset, dict):
        return asset.get("attachment_text_content", "")
    return asset.attachment_text_content or ""


def _get_asset_updated_at(asset):
    if isinstance(asset, dict):
        return asset.get("updated_at", "") or ""
    updated_at = getattr(asset, "updated_at", None)
    return updated_at.isoformat() if updated_at else ""


def _get_asset_id(asset):
    if isinstance(asset, dict):
        return asset.get("id")
    return getattr(asset, "id", None)


def _decode_uploaded_text(raw_bytes):
    for encoding in ("utf-8-sig", "utf-8", "utf-16"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace")


def _read_text_content(file_path, inline_text=""):
    content = _clean_text(inline_text)
    if content:
        return content

    if not file_path:
        return ""

    try:
        with open(file_path, "rb") as uploaded_file:
            return _clean_text(_decode_uploaded_text(uploaded_file.read()))
    except OSError:
        return ""


def _format_reference_file_line(asset):
    name = _get_asset_name(asset)
    kind = _get_asset_kind(asset)
    mime_type = _get_asset_mime_type(asset)
    suffix = f" [{kind}]" if kind else ""
    if mime_type:
        suffix += f" {mime_type}"
    return f"- {name}{suffix}".rstrip()


def _normalize_prompt_locale(value):
    normalized = (value or "").strip().lower()
    if normalized in {"zh", "zh-cn", "chinese", "simplified chinese"}:
        return "zh-CN"
    return "en-US"


def _get_character_prompt_locale(character):
    profile = UserProfile.objects.filter(user=character.created_by).only("interface_language").first()
    if not profile:
        return "en-US"
    return _normalize_prompt_locale(profile.interface_language)


def _get_system_prompt_preview_copy(locale):
    if locale == "zh-CN":
        return {
            "identity": "身份",
            "name": "名字",
            "untitled_character": "未命名角色",
            "affiliation": "所属",
            "reference_files": "参考文件",
            "no_reference_files": "暂无已上传的参考文件。",
            "core_brief": "核心简介",
            "no_core_brief": "暂无核心简介。",
            "user_address": "对用户的称呼",
            "user_address_line": lambda value: f"称呼用户为“{value}”。",
            "personality": "性格",
            "appearance": "外观",
            "scenario": "场景",
            "response_guidelines": "回复准则",
            "example_dialogue": "示例对话",
        }

    return {
        "identity": "Identity",
        "name": "Name",
        "untitled_character": "Untitled character",
        "affiliation": "Affiliation",
        "reference_files": "Reference Files",
        "no_reference_files": "No uploaded reference files yet.",
        "core_brief": "Core Brief",
        "no_core_brief": "No core brief yet.",
        "user_address": "User Address",
        "user_address_line": lambda value: f'Calls the user "{value}".',
        "personality": "Personality",
        "appearance": "Appearance",
        "scenario": "Scenario",
        "response_guidelines": "Response Guidelines",
        "example_dialogue": "Example Dialogue",
    }


def build_character_system_prompt_preview(character):
    copy = _get_system_prompt_preview_copy(_get_character_prompt_locale(character))
    identity_lines = [
        f"## {copy['identity']}",
        f"{copy['name']}: {character.name.strip() or copy['untitled_character']}",
    ]
    if _clean_text(character.affiliation):
        identity_lines.append(f"{copy['affiliation']}: {character.affiliation.strip()}")

    reference_assets = _get_character_knowledge_assets(character)
    reference_file_lines = (
        [f"## {copy['reference_files']}", *[_format_reference_file_line(asset) for asset in reference_assets]]
        if reference_assets
        else [f"## {copy['reference_files']}", f"- {copy['no_reference_files']}"]
    )

    return _join_sections([
        "\n".join(identity_lines),
        f"## {copy['core_brief']}\n{_clean_text(character.description) or copy['no_core_brief']}",
        (
            f"## {copy['user_address']}\n{copy['user_address_line'](character.user_address.strip())}"
            if _clean_text(character.user_address)
            else ""
        ),
        f"## {copy['personality']}\n{character.personality.strip()}" if _clean_text(character.personality) else "",
        f"## {copy['appearance']}\n{character.appearance.strip()}" if _clean_text(character.appearance) else "",
        f"## {copy['scenario']}\n{character.scenario.strip()}" if _clean_text(character.scenario) else "",
        (
            f"## {copy['response_guidelines']}\n{character.response_guidelines.strip()}"
            if _clean_text(character.response_guidelines)
            else ""
        ),
        (
            f"## {copy['example_dialogue']}\n{character.example_dialogue.strip()}"
            if _clean_text(character.example_dialogue)
            else ""
        ),
        "\n".join(reference_file_lines),
    ])


def build_character_setup_markdown(character):
    preview = _clean_text(character.system_prompt_preview)
    if preview:
        return preview
    return build_character_system_prompt_preview(character)


def _render_uploaded_index(character):
    assets = _get_character_knowledge_assets(character)
    if not assets:
        return "# Uploaded Knowledge Index\n- No uploaded reference files yet."
    return "\n".join(["# Uploaded Knowledge Index", *[_format_reference_file_line(asset) for asset in assets]])


def _render_uploaded_background_text(character):
    assets = _get_character_knowledge_assets(character)
    sections = []
    for asset in assets:
        if _get_asset_kind(asset) != AttachmentKind.TEXT:
            continue

        file_name = _get_asset_name(asset)
        suffix = os.path.splitext(file_name.lower())[1]
        if suffix not in {".txt", ".md", ".markdown", ".json"}:
            continue

        content = _read_text_content(_get_asset_path(asset), _get_asset_inline_text(asset))
        if not content:
            continue
        sections.append(f"## {file_name}\n{content}")

    if not sections:
        return "# Uploaded Background Text\nNo uploaded background text yet."

    return _join_sections([
        "# Uploaded Background Text",
        "Treat these as user-provided source material for voice, backstory, and reference details.",
        *sections,
    ])


def _render_uploaded_visual_references(character):
    assets = _get_character_knowledge_assets(character)
    lines = []
    for asset in assets:
        if _get_asset_kind(asset) != AttachmentKind.IMAGE:
            continue
        line = f"- {_get_asset_name(asset)}"
        file_url = _get_asset_url(asset)
        if file_url:
            line += f": {file_url}"
        lines.append(line)

    if not lines:
        return "# Visual References\nNo uploaded image references yet."

    return _join_sections([
        "# Visual References",
        "These images are direct character reference assets. Inspect them when the runtime model supports vision.",
        "\n".join(lines),
    ])


def build_character_prompt_context(character):
    return {
        "soul": build_character_setup_markdown(character),
        "backstory": _join_sections([
            "# Character Backstory",
            f"## Background\n{character.description.strip()}" if _clean_text(character.description) else "",
            f"## Affiliation\n{character.affiliation.strip()}" if _clean_text(character.affiliation) else "",
        ]),
        "example_dialogue": _join_sections([
            "# Example Dialogue",
            character.example_dialogue or "No example dialogue yet.",
        ]),
        "uploaded_index": _render_uploaded_index(character),
        "uploaded_background": _render_uploaded_background_text(character),
        "uploaded_visual_refs": _render_uploaded_visual_references(character),
    }


def _safe_memory_asset_name(name):
    normalized = os.path.basename((name or "").strip()) or "uploaded-file"
    return normalized.replace("\\", "_").replace("/", "_")


def _parent_memory_path(path):
    if not path or "/" not in path:
        return ""
    return path.rsplit("/", 1)[0]


def _iter_message_attachments(message):
    attachments = list(message.attachments.all())
    if attachments:
        return attachments
    if getattr(message, "attachment", None):
        return [message]
    return []


def _format_attachment_summary(attachment):
    attachment_kind = getattr(attachment, "attachment_kind", "") or AttachmentKind.TEXT
    attachment_name = getattr(attachment, "attachment_name", "") or os.path.basename(getattr(getattr(attachment, "file", None), "name", "") or "")
    attachment_mime_type = getattr(attachment, "attachment_mime_type", "") or ""
    text_content = _clean_text(getattr(attachment, "attachment_text_content", "") or "")

    lines = [f"- Attachment: {attachment_name or 'uploaded-file'} [{attachment_kind}]".rstrip()]
    if attachment_mime_type:
        lines.append(f"  MIME type: {attachment_mime_type}")
    if attachment_kind == AttachmentKind.TEXT and text_content:
        lines.append(f"  Text content: {_truncate_raw_text(text_content, 1200)}")
    return "\n".join(lines)


def _truncate_raw_text(content, limit):
    normalized = (content or "").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def _render_raw_chat_session(chat_session):
    header = [
        f"# Raw Chat Session {chat_session.id}",
        f"Title: {chat_session.title or f'Chat with {chat_session.character.name}'}",
        f"Character: {chat_session.character.name}",
        f"User: {chat_session.user.username}",
        f"Created At: {chat_session.created_at.isoformat() if chat_session.created_at else ''}",
        f"Updated At: {chat_session.updated_at.isoformat() if chat_session.updated_at else ''}",
    ]

    message_sections = []
    for message in chat_session.messages.all():
        role_label = "User" if message.role == "user" else chat_session.character.name
        timestamp = message.timestamp.isoformat() if message.timestamp else ""
        section_lines = [f"## {timestamp} {role_label}".strip()]
        section_lines.append((message.content or "").strip() or "(empty)")

        for attachment in _iter_message_attachments(message):
            attachment_summary = _format_attachment_summary(attachment)
            if attachment_summary:
                section_lines.append(attachment_summary)

        message_sections.append("\n".join(section_lines).strip())

    if not message_sections:
        message_sections.append("No messages have been recorded in this session yet.")

    return "\n\n".join(header + message_sections).strip()


def _has_research_payload(message):
    payload = getattr(message, "research_payload", None) or {}
    return bool(
        payload.get("query")
        or payload.get("provider")
        or payload.get("items")
        or payload.get("error")
        or payload.get("user_preferences")
        or payload.get("character_growth")
        or payload.get("knowledge_updates")
    )


def _render_research_payload_markdown(payload):
    payload = payload or {}
    lines = ["# Web Search Result"]
    if payload.get("query"):
        lines.append(f"Query: {payload['query']}")
    if payload.get("provider"):
        lines.append(f"Provider: {payload['provider']}")

    items = payload.get("items") or []
    if items:
        lines.append("")
        lines.append("## Results")
        for item in items:
            lines.append(f"- [{item.get('title', 'Untitled')}]({item.get('url', '')})")
            if item.get("snippet"):
                lines.append(f"  - {item['snippet']}")
            if item.get("domain"):
                lines.append(f"  - Domain: {item['domain']}")

    if payload.get("error"):
        lines.append("")
        lines.append(f"Error: {payload['error']}")

    summary_sections = []
    if payload.get("user_preferences"):
        summary_sections.append(f"## User Preferences\n{payload['user_preferences']}")
    if payload.get("character_growth"):
        summary_sections.append(f"## Character Growth\n{payload['character_growth']}")
    if payload.get("knowledge_updates"):
        summary_sections.append(f"## Knowledge Updates\n{payload['knowledge_updates']}")

    if summary_sections:
        lines.append("")
        lines.extend(summary_sections)

    return "\n".join(lines).strip()


def _build_memory_explorer_records(character):
    records = [{
        "entry_type": "file",
        "record_type": "schema_soul",
        "path": "schema/soul.md",
        "layer": "schema",
        "title": "soul.md",
        "kind": "markdown",
        "read_hint": "Final character setup and runtime-facing system prompt source.",
        "is_locked": True,
        "can_user_edit": False,
        "can_auto_update": True,
        "updated_at": character.updated_at.isoformat() if character.updated_at else "",
        "size_hint": len(build_character_setup_markdown(character)),
    }]

    # Inject the per-character long-term memory file as `wiki/memory.md`. It
    # is rendered from CharacterMemoryItem rows by the new memory package.
    _add_wiki_memory_record(records, character)

    used_paths = {record["path"] for record in records}
    chat_sessions = character.chat_sessions.select_related("user", "character").prefetch_related("messages__attachments").order_by("created_at")

    for chat_session in chat_sessions:
        session_prefix = f"raw/chat_sessions/session_{chat_session.id}"
        records.append({
            "entry_type": "file",
            "record_type": "raw_chat_transcript",
            "path": f"{session_prefix}/transcript.md",
            "layer": "raw",
            "title": "transcript.md",
            "kind": "markdown",
            "read_hint": "Original conversation transcript for this chat session.",
            "is_locked": True,
            "can_user_edit": False,
            "can_auto_update": False,
            "updated_at": chat_session.updated_at.isoformat() if chat_session.updated_at else "",
            "session_id": chat_session.id,
            "size_hint": sum(len((message.content or "").strip()) for message in chat_session.messages.all()),
        })

        attachment_names_in_session = set()
        for message in chat_session.messages.all():
            if _has_research_payload(message):
                path = f"{session_prefix}/web_search/turn_{message.id}.md"
                records.append({
                    "entry_type": "file",
                    "record_type": "raw_web_search",
                    "path": path,
                    "layer": "raw",
                    "title": f"turn_{message.id}.md",
                    "kind": "markdown",
                    "read_hint": "Stored search result payload captured for this assistant turn.",
                    "is_locked": True,
                    "can_user_edit": False,
                    "can_auto_update": False,
                    "updated_at": message.timestamp.isoformat() if message.timestamp else "",
                    "message_id": message.id,
                    "size_hint": len(_render_research_payload_markdown(message.research_payload)),
                })

            for attachment in _iter_message_attachments(message):
                file_obj = getattr(attachment, "file", None)
                if not file_obj:
                    continue

                base_name = _safe_memory_asset_name(
                    getattr(attachment, "attachment_name", "") or os.path.basename(file_obj.name or "")
                )
                alias_path = f"{session_prefix}/attachments/{base_name}"
                stem, ext = os.path.splitext(base_name)
                dedupe_index = 2
                while alias_path in attachment_names_in_session:
                    alias_path = f"{session_prefix}/attachments/{stem}__{dedupe_index}{ext}"
                    dedupe_index += 1
                attachment_names_in_session.add(alias_path)
                used_paths.add(alias_path)

                text_content = _clean_text(getattr(attachment, "attachment_text_content", "") or "")
                records.append({
                    "entry_type": "file",
                    "record_type": "raw_attachment",
                    "path": alias_path,
                    "layer": "raw",
                    "title": os.path.basename(alias_path),
                    "kind": getattr(attachment, "attachment_kind", "") or AttachmentKind.TEXT,
                    "read_hint": "Original session attachment captured during the conversation.",
                    "is_locked": True,
                    "can_user_edit": False,
                    "can_auto_update": False,
                    "updated_at": getattr(attachment, "updated_at", None).isoformat() if getattr(attachment, "updated_at", None) else "",
                    "attachment_kind": getattr(attachment, "attachment_kind", "") or AttachmentKind.TEXT,
                    "attachment_mime_type": getattr(attachment, "attachment_mime_type", "") or "",
                    "file_path": file_obj.path,
                    "file_url": _safe_file_url(file_obj),
                    "inline_text": text_content,
                    "size_hint": len(text_content) or len(os.path.basename(file_obj.name or "")),
                })

    setup_prefix = "raw/character_setup/uploads"
    for asset_index, asset in enumerate(_get_character_knowledge_assets(character), start=1):
        base_name = _safe_memory_asset_name(_get_asset_name(asset) or f"upload-{asset_index}")
        alias_path = f"{setup_prefix}/{base_name}"
        stem, ext = os.path.splitext(base_name)
        dedupe_index = 2
        while alias_path in used_paths:
            alias_path = f"{setup_prefix}/{stem}__{dedupe_index}{ext}"
            dedupe_index += 1
        used_paths.add(alias_path)

        inline_text = _get_asset_inline_text(asset)
        records.append({
            "entry_type": "file",
            "record_type": "raw_character_setup_upload",
            "path": alias_path,
            "layer": "raw",
            "title": os.path.basename(alias_path),
            "kind": _get_asset_kind(asset) or "file",
            "read_hint": "Original file uploaded while creating or editing the character.",
            "is_locked": True,
            "can_user_edit": False,
            "can_auto_update": False,
            "updated_at": _get_asset_updated_at(asset),
            "attachment_kind": _get_asset_kind(asset),
            "attachment_mime_type": _get_asset_mime_type(asset),
            "file_path": _get_asset_path(asset),
            "file_url": _get_asset_url(asset),
            "inline_text": inline_text,
            "size_hint": len(inline_text) or len(os.path.basename(alias_path)),
            "manageable": not isinstance(asset, dict),
            "asset_id": _get_asset_id(asset),
        })

    return sorted(records, key=lambda item: item["path"])


def _add_wiki_memory_record(records, character):
    """Inject the synthetic wiki/memory.md record (SonettoHer's memory.yaml)."""
    from .memory.interface import LongTermMemoryInterface

    markdown = LongTermMemoryInterface.render_wiki_markdown(character)
    last_updated_iso = ""
    try:
        from django.db.models import Max
        from .models import CharacterMemoryItem

        agg = CharacterMemoryItem.objects.filter(character=character).aggregate(
            latest=Max("updated_at")
        )
        latest = agg.get("latest")
        if latest:
            last_updated_iso = latest.isoformat()
    except (DatabaseError, CharacterMemoryItem.DoesNotExist):
        last_updated_iso = character.updated_at.isoformat() if character.updated_at else ""

    records.append({
        "entry_type": "file",
        "record_type": "wiki_long_term_memory",
        "path": "wiki/memory.md",
        "layer": "wiki",
        "title": "memory.md",
        "kind": "markdown",
        "read_hint": (
            "Per-character long-term memory (auto-written by the Celery worker "
            "after every turn; mirror of SonettoHer's memory.yaml). Edit individual "
            "entries on the /memory page."
        ),
        "is_locked": True,
        "can_user_edit": False,
        "can_auto_update": True,
        "updated_at": last_updated_iso,
        "size_hint": len(markdown),
    })


def _serialize_memory_explorer_entry(record):
    preview_kind = "text"
    if record["entry_type"] == "directory":
        preview_kind = "directory"
    elif record.get("attachment_kind") == AttachmentKind.IMAGE or record.get("kind") == AttachmentKind.IMAGE:
        preview_kind = "image"
    elif record.get("attachment_kind") not in {"", None, AttachmentKind.TEXT}:
        preview_kind = "binary"

    data = {
        "path": record["path"],
        "entry_type": record["entry_type"],
        "layer": record.get("layer", ""),
        "title": record.get("title", ""),
        "kind": record.get("kind", ""),
        "read_hint": record.get("read_hint", ""),
        "is_locked": record.get("is_locked", False),
        "can_user_edit": record.get("can_user_edit", False),
        "can_auto_update": record.get("can_auto_update", False),
        "updated_at": record.get("updated_at", ""),
        "manageable": record.get("manageable", False),
        "asset_id": record.get("asset_id"),
        "preview_kind": preview_kind,
    }
    if record["entry_type"] == "directory":
        data["child_count"] = record.get("child_count", 0)
    if record["entry_type"] == "file":
        data["size_hint"] = record.get("size_hint", 0)
    return data


def get_memory_explorer_entries(character):
    return [
        _serialize_memory_explorer_entry(record)
        for record in _build_memory_explorer_records(character)
    ]


def list_memory_explorer_path(character, path_prefix="", recursive=False, max_entries=40):
    normalized_prefix = (path_prefix or "").strip().strip("/")
    try:
        safe_max_entries = max(1, min(int(max_entries or 40), 200))
    except (TypeError, ValueError):
        safe_max_entries = 40

    records = _build_memory_explorer_records(character)
    file_records = {record["path"]: record for record in records}
    directory_records = {}

    for layer, description in MEMORY_LAYER_DESCRIPTIONS.items():
        directory_records[layer] = {
            "entry_type": "directory",
            "path": layer,
            "layer": layer,
            "title": layer,
            "kind": "directory",
            "read_hint": description,
            "is_locked": True,
            "can_user_edit": False,
            "can_auto_update": False,
            "updated_at": "",
        }

    for record in records:
        parts = record["path"].split("/")
        for depth in range(2, len(parts)):
            directory_path = "/".join(parts[:depth])
            directory_records.setdefault(
                directory_path,
                {
                    "entry_type": "directory",
                    "path": directory_path,
                    "layer": parts[0],
                    "title": parts[depth - 1],
                    "kind": "directory",
                    "read_hint": MEMORY_LAYER_DESCRIPTIONS.get(parts[0], ""),
                    "is_locked": True,
                    "can_user_edit": False,
                    "can_auto_update": False,
                    "updated_at": "",
                },
            )

    if normalized_prefix and normalized_prefix not in file_records and normalized_prefix not in directory_records:
        return {
            "path_prefix": normalized_prefix,
            "entries": [],
            "error": "Path not found in memory explorer.",
            "truncated": False,
        }

    entries = []
    if normalized_prefix in file_records:
        entries = [file_records[normalized_prefix]]
    else:
        for record in directory_records.values():
            if record["path"] == normalized_prefix:
                continue
            if recursive:
                if not normalized_prefix or record["path"].startswith(f"{normalized_prefix}/"):
                    entries.append(record)
            elif _parent_memory_path(record["path"]) == normalized_prefix:
                entries.append(record)
        for record in records:
            if recursive:
                if not normalized_prefix or record["path"].startswith(f"{normalized_prefix}/"):
                    entries.append(record)
            elif _parent_memory_path(record["path"]) == normalized_prefix:
                entries.append(record)

    sorted_entries = sorted(entries, key=lambda item: (item["entry_type"] != "directory", item["path"]))
    limited_entries = sorted_entries[:safe_max_entries]
    for record in directory_records.values():
        record["child_count"] = sum(
            1
            for candidate in records
            if _parent_memory_path(candidate["path"]) == record["path"]
        ) + sum(
            1
            for candidate in directory_records.values()
            if candidate["path"] != record["path"] and _parent_memory_path(candidate["path"]) == record["path"]
        )

    return {
        "path_prefix": normalized_prefix or "/",
        "entries": [_serialize_memory_explorer_entry(record) for record in limited_entries],
        "error": "",
        "truncated": len(sorted_entries) > len(limited_entries),
    }


def _read_record_content(record):
    attachment_kind = record.get("attachment_kind", AttachmentKind.TEXT)
    if attachment_kind == AttachmentKind.TEXT:
        content = _read_text_content(record.get("file_path", ""), record.get("inline_text", ""))
        if content:
            return content

    content_lines = [
        f"File name: {record.get('title', '')}",
        f"Attachment kind: {attachment_kind or 'file'}",
    ]
    if record.get("attachment_mime_type"):
        content_lines.append(f"MIME type: {record['attachment_mime_type']}")
    if record.get("file_url"):
        content_lines.append(f"File URL: {record['file_url']}")
    return "\n".join(content_lines)


def read_memory_explorer_file(character, path, max_chars=6000):
    normalized_path = (path or "").strip().strip("/")
    try:
        safe_max_chars = max(200, min(int(max_chars or 6000), 12000))
    except (TypeError, ValueError):
        safe_max_chars = 6000

    for record in _build_memory_explorer_records(character):
        if record["path"] != normalized_path:
            continue

        if record["record_type"] == "schema_soul":
            content = build_character_setup_markdown(character)
        elif record["record_type"] == "wiki_long_term_memory":
            from .memory.interface import LongTermMemoryInterface
            content = LongTermMemoryInterface.render_wiki_markdown(character)
        elif record["record_type"] == "raw_chat_transcript":
            chat_session = (
                character.chat_sessions.select_related("user", "character")
                .prefetch_related("messages__attachments")
                .filter(id=record.get("session_id"))
                .first()
            )
            content = _render_raw_chat_session(chat_session) if chat_session else ""
        elif record["record_type"] == "raw_web_search":
            message = character.messages.filter(id=record.get("message_id")).first()
            content = _render_research_payload_markdown(getattr(message, "research_payload", {}) if message else {})
        else:
            content = _read_record_content(record)

        truncated = len(content) > safe_max_chars
        return {
            "path": normalized_path,
            "layer": record.get("layer", ""),
            "title": record.get("title", ""),
            "kind": record.get("kind", ""),
            "read_hint": record.get("read_hint", ""),
            "content": content[:safe_max_chars],
            "truncated": truncated,
            "manageable": record.get("manageable", False),
            "asset_id": record.get("asset_id"),
            "preview_kind": (
                "image"
                if record.get("attachment_kind") == AttachmentKind.IMAGE or record.get("kind") == AttachmentKind.IMAGE
                else "binary"
                if record.get("attachment_kind") not in {"", None, AttachmentKind.TEXT}
                else "text"
            ),
            "file_url": record.get("file_url", ""),
            "mime_type": record.get("attachment_mime_type", ""),
        }

    return {
        "path": normalized_path,
        "error": "File not found in memory explorer.",
    }


def build_memory_explorer_manifest(character):
    entries = get_memory_explorer_entries(character)
    groups = {"schema": [], "wiki": [], "raw": []}
    for entry in entries:
        groups.setdefault(entry["layer"], []).append(entry)

    lines = [
        "Top-level memory layers:",
        "- schema/: rules, invariants, and update permissions.",
        "- wiki/: retained compatibility layer for curated memory semantics.",
        "- raw/: original uploaded source files and evidence.",
    ]

    for layer in ("schema", "wiki", "raw"):
        layer_entries = groups.get(layer) or []
        if not layer_entries:
            continue
        lines.append(f"{layer.upper()} FILES:")
        for entry in layer_entries:
            lines.append(f"- {entry['path']}: {entry.get('read_hint', '').strip()}".rstrip())

    return "\n".join(lines)
