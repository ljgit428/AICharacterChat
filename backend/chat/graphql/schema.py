import strawberry
from typing import List, Optional
from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.files import File
from django.core.files.storage import default_storage
from django.db import transaction
import hashlib
import json
import logging
import mimetypes
import os

from .types import CharacterDraftJobType, CharacterType, ChatSessionType, CharacterInput, PrisMateDraft, _serialize_character_draft_job
from chat.attachments import extract_text_attachment_content, guess_attachment_kind, validate_attachment_size
from chat.character_reduce import (
    SINGLE_SHOT_ENABLED,
    _normalize_target_name,
    extract_character_core_excerpts,
)
from chat.cleanup import _resolve_local_media_path, cleanup_character_files
from chat.draft_jobs import start_draft_job_thread, sweep_stale_jobs
from chat.memory.filesystem import StagedUploadMemoryFilesystem
from chat.models import AttachmentKind, AssetEvent, AssetEventType, Character, CharacterDraftJob, CharacterKnowledgeAsset, ChatSession, ModelConfiguration, ModelRole, ModelRoleAssignment, UserProfile
from chat.tasks import (
    _build_memory_tool_specs,
    _extract_json_object,
    _generate_text,
    _supports_memory_tool_mode,
)

logger = logging.getLogger(__name__)
SUPPORTED_BACKGROUND_TEXT_EXTENSIONS = {'.txt', '.md', '.markdown', '.json'}
SUPPORTED_CHARACTER_REFERENCE_KINDS = {AttachmentKind.TEXT, AttachmentKind.IMAGE}


def _get_authenticated_user(info):
    user = getattr(info.context.request, 'user', None)
    if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
        raise Exception("Authentication required")
    return user


def _get_owned_character(user, character_id):
    try:
        return Character.objects.get(pk=character_id, created_by=user)
    except Character.DoesNotExist as exc:
        raise Exception("Character not found") from exc


def _get_owned_session(user, session_id):
    try:
        return ChatSession.objects.get(pk=session_id, user=user)
    except ChatSession.DoesNotExist as exc:
        raise Exception("Chat session not found") from exc


def _get_required_user_model_config(user):
    model_config = ModelRoleAssignment.get_role_config(user, ModelRole.TEXT)
    if not model_config:
        # 正常流程不会到这里（首个配置自动分配 text、PUT 禁止清空/跳过）；
        # 触发即数据状态异常，回退并留日志。
        model_config = ModelConfiguration.objects.filter(user=user).order_by('id').first()
        if model_config:
            logger.warning(
                'User %s has model configs but no text role assignment; falling back to config %s',
                user.id,
                model_config.id,
            )
    if not model_config:
        raise ValueError("Please configure your own model API before using this feature.")

    # Gemini/Anthropic 路径必须显式 api_key；openai_compatible 允许本地反代网关自鉴权，所以这里放过。
    if not model_config.api_key and model_config.provider in {'gemini', 'anthropic'}:
        raise ValueError("The default user model configuration is missing an API key.")

    return model_config


def _get_draft_runtime_config(user):
    model_config = _get_required_user_model_config(user)

    return {
        "provider": model_config.provider,
        "model_name": model_config.model_name,
        "api_key": model_config.api_key,
        "base_url": model_config.base_url,
    }


def _normalize_draft_locale(value: Optional[str]) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"zh", "zh-cn", "chinese", "simplified chinese"}:
        return "zh-CN"
    return "en-US"


def _get_draft_prompt_locale(user, locale: Optional[str] = None) -> str:
    if locale:
        return _normalize_draft_locale(locale)

    profile = UserProfile.objects.filter(user=user).only("interface_language").first()
    if not profile:
        return "en-US"

    return _normalize_draft_locale(profile.interface_language)


DRAFT_PER_FILE_CHAR_LIMIT = 8000
DRAFT_TOTAL_CHAR_LIMIT = 24000

# 参考文件数达到该阈值时，草稿生成走 reduce 流水线（分层精读 → 笔记 → 合并）
# 而不是单次 Memory Tools ReAct loop。
REDUCE_PIPELINE_MIN_FILES = 12


def _truncate_draft_contents(file_contents: List[str]) -> tuple[List[str], int]:
    """Truncate per-file and total to keep prompts from blowing up.

    Returns the kept contents in order plus the number of files that were dropped
    from the tail because of the total-char budget.
    """
    if not file_contents:
        return [], 0

    truncated: List[str] = []
    running_total = 0
    dropped_tail = 0

    for raw in file_contents:
        if not raw:
            continue
        if len(raw) > DRAFT_PER_FILE_CHAR_LIMIT:
            raw = raw[: DRAFT_PER_FILE_CHAR_LIMIT - 3].rstrip() + "..."
        if running_total + len(raw) > DRAFT_TOTAL_CHAR_LIMIT:
            dropped_tail += 1
            continue
        truncated.append(raw)
        running_total += len(raw)

    return truncated, dropped_tail


def _build_character_draft_prompt(locale: str, text_context: Optional[str], uploaded_file_contents: List[str], dropped_tail_count: int = 0) -> str:
    if locale == "zh-CN":
        prompt_sections = [
            (
                "你是一名专业的角色设计师。\n"
                "请分析提供的上下文，提取稳定的角色锚点和说话风格。\n\n"
                "只返回原始 JSON 对象，不要使用 markdown，不要添加额外说明。JSON 必须包含这些键：\n"
                "- name（字符串）：角色名\n"
                "- description（字符串）：完整的背景与概述，至少 3 句话\n"
                "- affiliation（字符串）：组织、阵营或所属\n"
                "- personality（字符串）：1~2 句话概括角色的语气 / 性格 / 价值倾向，用于快速定调\n"
                "- example_dialogue（字符串）：5 段不同的示例对话。每段格式必须是\n"
                "  \"User: <一句提问或陈述>\\nCharacter: <一句完整回答>\"\n"
                "- user_address（字符串）：角色对用户的直接称呼，从台词里高频出现的第二人称称呼归纳（如 老师/前辈/指挥官/主人）；语料中找不到明确称呼时返回空字符串\n\n"
                "- tags（字符串数组）：3 到 6 个关键词\n\n"
                "要求：\n"
                "- 优先直接从源材料提取；不要发明设定、场景、外貌、长篇 lore 总结。\n"
                "- personality 要抓\"怎么说\"，而不是\"是谁\"。\n"
                "- example_dialogue 的 5 段要覆盖：日常、提问、情绪、命令/拒绝、玩笑，每段回答不超过 2 句。\n"
                "- 找不到线索时，对应字段返回空字符串（不要编造）。\n\n"
                "待分析的上下文："
            )
        ]

        if text_context:
            prompt_sections.append(f"[用户输入上下文]\n{text_context}")

        for index, file_content_str in enumerate(uploaded_file_contents, start=1):
            prompt_sections.append(f"[上传文件内容 {index}]\n{file_content_str}")

        if dropped_tail_count:
            prompt_sections.append(
                f"[注意：上传的文件中末尾 {dropped_tail_count} 个已被截断以保护上下文窗口]"
            )

        return "\n\n".join(prompt_sections)

    prompt_sections = [
        (
            "You are an expert Character Designer.\n"
            "Analyze the provided context to extract stable character anchors and a voice style.\n\n"
            "Return ONLY a raw JSON object (no markdown formatting) with the following keys:\n"
            "- name (string): Character name\n"
            "- description (string): A comprehensive background and summary (at least 3 sentences)\n"
            "- affiliation (string): Organization or faction\n"
            "- personality (string): 1-2 sentences capturing the character's tone / demeanor / values for quick framing\n"
            "- example_dialogue (string): Exactly 5 distinct example exchanges. Each MUST follow the format\n"
            '  "User: <one short prompt or statement>\\nCharacter: <one reply of up to 2 sentences>"\n'
            "- user_address (string): how the character addresses the user, generalized from recurring direct-address terms in the dialogue (e.g. Sensei/Commander/Master); empty string if not found\n"
            "- tags (list of strings): 3-6 keywords\n"
            "\n"
            "Rules:\n"
            "- Prefer direct extraction from the source material; do NOT invent lore, appearance, scenario, or opening lines.\n"
            "- personality should capture HOW the character speaks, not WHO they are.\n"
            "- The 5 example_dialogue exchanges should cover: casual, a question, emotional, a refusal or command, and a joke.\n"
            "- If a field has no signal, return an empty string (never fabricate).\n\n"
            "Context to analyze:"
        )
    ]

    if text_context:
        prompt_sections.append(f"[User Input Context]\n{text_context}")

    for index, file_content_str in enumerate(uploaded_file_contents, start=1):
        prompt_sections.append(f"[Uploaded File Content {index}]\n{file_content_str}")

    if dropped_tail_count:
        prompt_sections.append(
            f"[Note: The last {dropped_tail_count} uploaded file(s) were truncated to protect the context window.]"
        )

    return "\n\n".join(prompt_sections)


def _is_supported_background_text_path(file_path):
    return os.path.splitext(file_path.lower())[1] in SUPPORTED_BACKGROUND_TEXT_EXTENSIONS


def _decode_text_content(raw_bytes: bytes) -> str:
    for encoding in ('utf-8-sig', 'utf-8', 'utf-16'):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode('utf-8', errors='replace')


def _read_local_text_file(file_url: Optional[str]) -> str:
    file_path = _resolve_local_media_path(file_url)
    if not file_path or not _is_supported_background_text_path(file_path):
        return ""

    try:
        with open(file_path, 'rb') as uploaded_file:
            return _decode_text_content(uploaded_file.read())
    except OSError as exc:
        logger.warning("Failed to read uploaded background text from %s: %s", file_path, exc)
        return ""


def _resolve_staged_uploads(file_urls: Optional[List[str]], file_names: Optional[List[str]] = None) -> List[dict]:
    """Resolve the just-uploaded file URLs into the staged-upload records that
    the draft Memory Tools browse. Text files carry their extracted content;
    images carry only their URL/metadata (they cannot be read as text).

    ``file_names`` runs parallel to ``file_urls`` and carries the original
    folder-group relative path (e.g. ``Momotalk/mari/scene_1.txt``) so the
    staged memory filesystem can preserve the uploaded hierarchy.

    NOTE: This legacy URL-based path is kept for backward compatibility; new
    clients pass ``upload_ids`` resolved through
    :func:`_resolve_staged_uploads_from_events` instead.
    """
    if not file_urls:
        return []

    uploads = []
    seen_urls = set()
    for index, file_url in enumerate(file_urls):
        if not file_url or file_url in seen_urls:
            continue
        seen_urls.add(file_url)

        file_path = _resolve_local_media_path(file_url)
        if not file_path:
            continue

        parallel_name = file_names[index] if file_names and index < len(file_names) else ""
        name = (parallel_name or "").strip() or os.path.basename(file_path)
        mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        if _is_supported_background_text_path(file_path):
            uploads.append({
                "name": name,
                "relative_path": name,
                "kind": AttachmentKind.TEXT,
                "mime_type": mime_type,
                "content": _read_local_text_file(file_url),
                "file_url": file_url,
            })
        elif mime_type.startswith("image/"):
            uploads.append({
                "name": name,
                "relative_path": name,
                "kind": AttachmentKind.IMAGE,
                "mime_type": mime_type,
                "content": "",
                "file_url": file_url,
            })

    return uploads


def _resolve_staged_uploads_from_events(user, upload_ids: Optional[List[str]], full_text_budget: Optional[dict] = None) -> List[dict]:
    """Resolve ``asset/uploaded`` events into staged-upload records for draft
    generation. Text content is read in full from the staging file on disk;
    the stored ``attachment_text_content`` is only a 16k chat-attachment
    preview and is used solely as a fallback when the staging file is gone.
    """
    if not upload_ids:
        return []
    from ..assets.store import AssetStore

    ids = []
    for value in upload_ids:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    if not ids:
        return []

    payload_map = AssetStore.event_payload_map(user, ids)
    return _staged_uploads_from_payloads(
        [payload_map[upload_id] for upload_id in sorted(payload_map)],
        full_text_budget,
    )


def _resolve_staged_uploads_from_assets(user, asset_ids: Optional[List[str]], full_text_budget: Optional[dict] = None) -> List[dict]:
    """Resolve attached ``CharacterKnowledgeAsset`` rows (edit mode) into
    staged-upload records for draft generation.

    Their upload events are already attached, so they cannot go through
    ``AssetStore.event_payload_map`` (which only sees pending uploads);
    the rows carry ``upload_event_id`` back to the event payload. Ownership
    is enforced via ``character__created_by``.
    """
    if not asset_ids:
        return []
    ids = []
    for value in asset_ids:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    if not ids:
        return []

    assets = (
        CharacterKnowledgeAsset.objects
        .filter(id__in=ids, character__created_by=user)
        .order_by('sort_order', 'id')
    )
    event_ids = [asset.upload_event_id for asset in assets if asset.upload_event_id]
    payload_map: dict[int, dict] = {}
    if event_ids:
        events = AssetEvent.objects.filter(
            id__in=event_ids, user=user, event_type=AssetEventType.UPLOADED,
        )
        payload_map = {event.id: (event.data or {}) for event in events}

    payloads = []
    for asset in assets:
        data = payload_map.get(asset.upload_event_id)
        if data:
            # attach 投影会把 staging 文件搬进 character_knowledge_assets/ 并
            # 删除原文件（projection._project_attached），事件载荷里的
            # file_path 在挂接后已失效；资产行的 FileField 才是现在的物理
            # 位置，全文读取必须优先用它。
            committed_name = (asset.file.name or '').strip() if asset.file else ''
            if committed_name:
                data = {**data, 'file_path': committed_name}
        elif asset.attachment_kind == AttachmentKind.TEXT and (asset.attachment_text_content or '').strip():
            # 事件溯源之前的直建资产行：没有可反查的 upload 事件，用行上
            # 字段兜底（磁盘文件仍在，全文照读；不在则退回行内预览文本）。
            data = {
                'file_path': asset.file.name or '',
                'file_name': asset.attachment_name or 'uploaded-file',
                'attachment_kind': asset.attachment_kind,
                'attachment_mime_type': asset.attachment_mime_type or 'text/plain',
                'attachment_text_content': asset.attachment_text_content,
            }
        else:
            continue
        payloads.append(data)
    return _staged_uploads_from_payloads(payloads, full_text_budget)


# 全文读取护栏：角色语料需要全文做分层计数与台词窗口提取，但一批 2000 个
# 文件全部无上限读入内存会撑爆进程。单文件超过上限保留头尾，整体预算耗尽
# 后剩余文件退回事件载荷里的 16k 预览。
DRAFT_FILE_FULL_TEXT_CHAR_LIMIT = 200_000
DRAFT_FULL_TEXT_TOTAL_CHAR_BUDGET = 40_000_000


def _read_full_staging_text(file_path: str, preview: str) -> str:
    """Read a staged upload's full text from storage, capped per file.

    Falls back to the event payload's 16k preview when the staging file is
    missing or unreadable (e.g. reclaimed after TTL mid-draft).
    """
    if not file_path:
        return preview
    try:
        with default_storage.open(file_path, 'rb') as stored_file:
            raw_bytes = stored_file.read()
    except Exception as exc:  # noqa: BLE001 - 读盘任何失败都降级到预览
        logger.warning("Failed to read full staging text from %s: %s", file_path, exc)
        return preview

    text = _decode_text_content(raw_bytes)
    if len(text) > DRAFT_FILE_FULL_TEXT_CHAR_LIMIT:
        half = DRAFT_FILE_FULL_TEXT_CHAR_LIMIT // 2
        text = text[:half].rstrip() + "\n…[中段省略]…\n" + text[-half:].lstrip()
    return text


def _staged_upload_from_payload(data: dict, full_text_budget: dict) -> dict:
    name = (data.get('file_name') or '').strip() or 'uploaded-file'
    kind = data.get('attachment_kind') or ''
    mime_type = data.get('attachment_mime_type') or 'application/octet-stream'
    file_path = data.get('file_path') or ''
    preview = data.get('attachment_text_content') or ''
    if kind == AttachmentKind.TEXT and full_text_budget['remaining'] > 0:
        content = _read_full_staging_text(file_path, preview)
        full_text_budget['remaining'] -= len(content)
    else:
        content = preview
    return {
        "name": name,
        "relative_path": name,
        "kind": kind,
        "mime_type": mime_type,
        "content": content,
        "file_url": default_storage.url(file_path) if file_path else '',
        # 上传时算好的内容哈希：批次签名的内容寻址依据（重传不失效）。
        "content_hash": (data.get('sha256') or '').strip(),
    }


def _staged_uploads_from_payloads(payloads: List[dict], full_text_budget: Optional[dict] = None) -> List[dict]:
    if full_text_budget is None:
        full_text_budget = {'remaining': DRAFT_FULL_TEXT_TOTAL_CHAR_BUDGET}
    return [_staged_upload_from_payload(data, full_text_budget) for data in payloads]


def _build_staged_upload_index_section(locale: str, directory_index: str) -> str:
    if locale == "zh-CN":
        return (
            "[上传文件目录索引]\n"
            "以下是用户本次上传的全部文件（记忆文本）及其在记忆文件系统中的路径，"
            "read_memory_file 的 path 参数必须逐字使用这些路径：\n"
            f"{directory_index}"
        )
    return (
        "[Uploaded File Directory Index]\n"
        "Below are ALL files the user uploaded this session (memory texts) and their "
        "memory-filesystem paths. The read_memory_file `path` argument must match one of "
        "these paths verbatim:\n"
        f"{directory_index}"
    )


def _build_character_draft_tool_prompt(
    locale: str,
    text_context: Optional[str],
    upload_count: int,
    directory_index: str = "",
) -> List[dict]:
    """Build the system/user messages for the tool-driven character draft.

    Unlike ``_build_character_draft_prompt``, uploaded file bodies are *not*
    inlined here. The model sees a compact directory index of the uploaded file
    group up front, then uses ``list_memory_files`` / ``read_memory_file`` to
    read on demand the files it actually needs.
    """
    index_section = _build_staged_upload_index_section(locale, directory_index) if directory_index else ""
    if locale == "zh-CN":
        system_prompt = (
            "你是一名专业的角色设计师。\n"
            "请分析提供的上下文，提取稳定的角色锚点和说话风格。\n\n"
            f"用户上传了 {upload_count} 个参考文件，它们是本角色的记忆文本，"
            "通过记忆文件系统暴露，正文不会出现在这条提示里。\n"
            "必须使用工具按需查阅文件，而不是假设内容：\n"
            "- 先看下方[上传文件目录索引]了解有哪些文件；需要浏览目录时用 list_memory_files（路径前缀 raw/character_setup/uploads）。\n"
            "- 再用 read_memory_file 只读取与角色塑造相关的文件；path 必须使用目录索引或 list 结果中的原始路径。\n"
            "- 与目标角色直接相关的文件必须完整读取；没有实际读取过的文件，不得声称知道其内容。\n\n"
            + (index_section + "\n\n" if index_section else "")
            +
            "只返回原始 JSON 对象，不要使用 markdown，不要添加额外说明。JSON 必须包含这些键：\n"
            "- name（字符串）：角色名\n"
            "- description（字符串）：完整的背景与概述，至少 3 句话\n"
            "- affiliation（字符串）：组织、阵营或所属\n"
            "- personality（字符串）：1~2 句话概括角色的语气 / 性格 / 价值倾向，用于快速定调\n"
            "- example_dialogue（字符串）：5 段不同的示例对话。每段格式必须是\n"
            "  \"User: <一句提问或陈述>\\nCharacter: <一句完整回答>\"\n"
            "- user_address（字符串）：角色对用户的直接称呼，从台词里高频出现的第二人称称呼归纳（如 老师/前辈/指挥官/主人）；语料中找不到明确称呼时返回空字符串\n\n"
            "- tags（字符串数组）：3 到 6 个关键词\n\n"
            "要求：\n"
            "- 优先直接从读取到的源材料提取；不要发明设定、场景、外貌、长篇 lore 总结。\n"
            "- personality 要抓\"怎么说\"，而不是\"是谁\"。\n"
            "- example_dialogue 的 5 段要覆盖：日常、提问、情绪、命令/拒绝、玩笑，每段回答不超过 2 句。\n"
            "- 找不到线索时，对应字段返回空字符串（不要编造）。"
        )
        user_prompt = (
            (f"[用户输入上下文]\n{text_context}" if text_context else "[用户输入上下文]\n（未提供额外上下文）")
            + "\n\n请先用工具浏览并读取你需要的上传文件，然后输出角色草稿 JSON。"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    system_prompt = (
        "You are an expert Character Designer.\n"
        "Analyze the provided context to extract stable character anchors and a voice style.\n\n"
        f"The user uploaded {upload_count} reference file(s). They are memory texts for this "
        "character, exposed through a memory filesystem; their bodies are NOT included in this prompt.\n"
        "You MUST use the tools to read files on demand instead of assuming their content:\n"
        "- Check the [Uploaded File Directory Index] below first; call list_memory_files to browse "
        "(path prefix raw/character_setup/uploads) when you need folder navigation.\n"
        "- Call read_memory_file to open only the files relevant to the character you are building; "
        "the `path` argument must be copied verbatim from the index or listing.\n"
        "- Read the files directly about the target character in full. Never claim facts about a file you have not actually read.\n\n"
        + (index_section + "\n\n" if index_section else "")
        +
        "Return ONLY a raw JSON object (no markdown formatting) with the following keys:\n"
        "- name (string): Character name\n"
        "- description (string): A comprehensive background and summary (at least 3 sentences)\n"
        "- affiliation (string): Organization or faction\n"
        "- personality (string): 1-2 sentences capturing the character's tone / demeanor / values for quick framing\n"
        "- example_dialogue (string): Exactly 5 distinct example exchanges. Each MUST follow the format\n"
        '  "User: <one short prompt or statement>\\nCharacter: <one reply of up to 2 sentences>"\n'
        "- user_address (string): how the character addresses the user, generalized from recurring direct-address terms in the dialogue (e.g. Sensei/Commander/Master); empty string if not found\n"
        "- tags (list of strings): 3-6 keywords\n"
        "\n"
        "Rules:\n"
        "- Prefer direct extraction from the source material you read; do NOT invent lore, appearance, scenario, or opening lines.\n"
        "- personality should capture HOW the character speaks, not WHO they are.\n"
        "- The 5 example_dialogue exchanges should cover: casual, a question, emotional, a refusal or command, and a joke.\n"
        "- If a field has no signal, return an empty string (never fabricate)."
    )
    user_prompt = (
        (f"[User Input Context]\n{text_context}" if text_context else "[User Input Context]\n(no extra context provided)")
        + "\n\nBrowse and read the uploaded files you need via the tools, then output the character draft JSON."
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _normalize_character_reference_inputs(input: CharacterInput) -> list[dict] | None:
    """Extract the attach/detach diff from a CharacterInput.

    Returns ``None`` when the input carries no asset changes at all (keep
    existing assets untouched). ``[]`` explicitly means "attach nothing".
    """
    attach: list[dict] = []
    if input.background_files is not None:
        for item in input.background_files:
            if getattr(item, 'upload_id', None):
                attach.append({'upload_id': int(item.upload_id), 'file_name': item.file_name or ''})
            elif getattr(item, 'uploaded_url', None):
                # 兼容旧前端：只保留 URL 没有 upload_id 的条目会被丢弃（staging
                # 裸文件机制已移除，无法可靠反解析），调用方会得到明确报错。
                attach.append({'upload_id': None, 'file_name': item.file_name or ''})
    elif input.background_file_url:
        # 兼容旧前端单文件路径；没有 upload_id 时无法绑定，交由 diff 校验报错。
        attach.append({'upload_id': None, 'file_name': input.background_file_name or ''})

    detached = list(input.detached_asset_ids or []) or []
    detached_ids = [int(i) for i in detached if str(i).strip().isdigit()]

    if not attach and not detached_ids and input.background_files is None and input.background_file_url == "":
        return None

    return {'attach': attach, 'detached': detached_ids}


def _apply_asset_diff(character, asset_diff):
    """Apply an asset diff to a character via the AssetEvent log.

    ``asset_diff`` is the output of ``_normalize_character_reference_inputs``:
    ``{'attach': [{upload_id, file_name}], 'detached': [asset_id]}``. Attaches
    are appended as ``asset/attached`` events; detaches as ``asset/detached``.
    Missing/unowned uploads raise instead of silently dropping (unlike the old
    URL-copy path).
    """
    from ..assets.store import AssetStore
    from ..assets.projection import AssetFileMissingError

    if asset_diff is None:
        return

    attach_ids = [entry['upload_id'] for entry in asset_diff['attach']]
    invalid = [entry for entry in asset_diff['attach'] if entry['upload_id'] is None]
    if invalid:
        raise AssetFileMissingError(
            'Reference files must be uploaded through the staging endpoint first '
            '(missing upload_id).'
        )
    if attach_ids:
        AssetStore.attach(character, attach_ids)
    if asset_diff['detached']:
        AssetStore.detach(character, asset_diff['detached'], reason='user edit')


def _compute_character_draft(
    user,
    draft_locale: str,
    text_context: Optional[str],
    staged_uploads: List[dict],
) -> tuple[dict, dict]:
    """Draft 生成共用核心：同步 mutation 与后台任务（draft_jobs）都走这里。

    主链路（产品决策：请求次数最少化，Map-Reduce 已从请求路径移除）：
    - 大语料（>= REDUCE_PIPELINE_MIN_FILES）且指定目标角色 → 纯规则预筛
      出角色相关片段（0 LLM）→ **1 次** LLM 请求直接出卡；输出无效时带
      提醒重试 1 次，仍失败则让任务明确失败——不回退多请求管线。
    - 少量文件 / 未指定目标角色 → Memory Tools 按需读取（模型自己挑文件，
      请求数受工具循环轮次约束）；不支持工具的 provider 走内联截断。

    返回 (draft_fields, meta)：draft_fields 键与 PrisMateDraft 字段对齐。
    模型输出不是合法 JSON 时抛 ValueError，由调用方决定呈现方式。
    """
    runtime_config = _get_draft_runtime_config(user)

    text_uploads = [
        upload for upload in staged_uploads
        if upload.get("kind") == AttachmentKind.TEXT and upload.get("content")
    ]
    if len(text_uploads) >= REDUCE_PIPELINE_MIN_FILES and SINGLE_SHOT_ENABLED:
        target_name = _normalize_target_name(text_context)
        if target_name:
            excerpts = extract_character_core_excerpts(text_uploads, target_name)
            if excerpts:
                # draft 单请求允许比聊天更长的读超时（大 prompt 的 prefill 慢）。
                draft_timeout = int(getattr(settings, 'CHARACTER_DRAFT_TIMEOUT', 180))
                prompt = _build_character_draft_prompt(draft_locale, text_context, [excerpts])

                def _single_call(prompt_text: str) -> str:
                    return _generate_text(runtime_config, prompt_text, timeout=draft_timeout)

                try:
                    raw_text = _single_call(prompt)
                except Exception as exc:  # noqa: BLE001 - 超时/网络失败自动减半预算重试
                    logger.warning(
                        'Single-shot draft request failed (%s: %s); retrying with half excerpt budget.',
                        type(exc).__name__, str(exc)[:120],
                    )
                    excerpts = extract_character_core_excerpts(
                        text_uploads, target_name, max_total_chars=max(8_000, len(excerpts) // 2),
                    )
                    prompt = _build_character_draft_prompt(draft_locale, text_context, [excerpts])
                    raw_text = _single_call(prompt)

                data = _extract_json_object(raw_text)
                if not data:
                    retry_prompt = (
                        prompt
                        + "\n\n（上一次输出无法解析，请严格只输出一个 JSON 对象，不要输出任何额外文本。）"
                    )
                    raw_text = _generate_text(runtime_config, retry_prompt, timeout=draft_timeout)
                    data = _extract_json_object(raw_text)
                if not data:
                    raw_for_preview = raw_text or ''
                    preview = raw_for_preview[:300]
                    raise ValueError(
                        "Model did not return a valid JSON object for the character draft "
                        f"(single-shot, retried once). Raw model response preview: {preview or '(empty response)'}"
                    )
                logger.info(
                    'Character draft via single-shot request (files=%s, excerpt_chars=%s).',
                    len(text_uploads), len(excerpts),
                )
                return {
                    "name": data.get("name", "Unknown"),
                    "description": data.get("description", ""),
                    "affiliation": data.get("affiliation", ""),
                    "personality": (data.get("personality") or "").strip(),
                    "appearance": (data.get("appearance") or "").strip(),
                    "user_address": (data.get("user_address") or "").strip(),
                    "tags": data.get("tags", []) or [],
                    "visual_summary": "",
                    "example_dialogue": (data.get("example_dialogue") or "").strip(),
                }, {
                    "path": "single_shot",
                    "target": target_name,
                    "files": len(text_uploads),
                    "excerpt_chars": len(excerpts),
                }
            # 预筛为空（目标角色在语料中没出现）→ 落到按需读取路径。

    use_memory_tools = bool(staged_uploads) and _supports_memory_tool_mode(runtime_config)

    if use_memory_tools:
        filesystem = StagedUploadMemoryFilesystem(staged_uploads)
        messages = _build_character_draft_tool_prompt(
            draft_locale,
            text_context,
            len(staged_uploads),
            directory_index=filesystem.build_directory_index(),
        )
        raw_text = _generate_text(
            runtime_config,
            messages,
            tools=_build_memory_tool_specs(),
            filesystem=filesystem,
        )
    else:
        raw_file_contents = [
            upload["content"]
            for upload in staged_uploads
            if upload["kind"] == AttachmentKind.TEXT and upload["content"]
        ]
        truncated_contents, dropped_tail_count = _truncate_draft_contents(raw_file_contents)
        prompt = _build_character_draft_prompt(
            draft_locale,
            text_context,
            truncated_contents,
            dropped_tail_count=dropped_tail_count,
        )
        raw_text = _generate_text(runtime_config, prompt)

    data = _extract_json_object(raw_text)
    if not data:
        # Hard fail: the prompt contract is "return ONLY a raw JSON
        # object". When the model returns prose (or nothing) the user
        # should see a clear error, not a half-populated form. The error
        # message embeds a preview of the raw model response so the user
        # can see what the proxy sent without silent degradation. The
        # parser has also written the complete text to a file in the OS
        # temp directory and logged the full path at INFO level, so the
        # backend log is the source of truth for the dump file location
        # (don't hardcode /tmp here — on Windows that path doesn't exist).
        raw_for_preview = raw_text or ''
        preview = raw_for_preview[:500]
        if len(raw_for_preview) > 500:
            preview += (
                f'... [truncated; full response was {len(raw_for_preview)} chars; '
                f'see the backend log for the parser dump file path]'
            )
        raise ValueError(
            f"Model did not return a valid JSON object for the character draft. "
            f"Raw model response preview: {preview or '(empty response)'}"
        )

    return {
        "name": data.get("name", "Unknown"),
        "description": data.get("description", ""),
        "affiliation": data.get("affiliation", ""),
        "personality": (data.get("personality") or "").strip(),
        "appearance": "",
        "user_address": (data.get("user_address") or "").strip(),
        "tags": data.get("tags", []) or [],
        "visual_summary": "",
        "example_dialogue": (data.get("example_dialogue") or "").strip(),
    }, {}


@strawberry.input
class ChatSessionInput:
    character_id: strawberry.ID
    title: Optional[str] = ""

@strawberry.type
class Mutation:
    @strawberry.mutation
    async def generate_character_draft(
        self,
        info,
        upload_ids: Optional[List[str]] = None,
        asset_ids: Optional[List[str]] = None,
        file_url: Optional[str] = None,
        file_urls: Optional[List[str]] = None,
        file_names: Optional[List[str]] = None,
        text_context: Optional[str] = None,
        locale: Optional[str] = None,
    ) -> PrisMateDraft:
        """
        Calls the user's default model configuration to analyze text and return a structured Character Draft.

        Uploaded reference files are not inlined into the prompt. When the
        runtime model supports tool calls (OpenAI-compatible / Anthropic),
        the prompt carries a compact directory index of the uploaded file
        group, and the files are exposed through the ``list_memory_files`` /
        ``read_memory_file`` tools so the model reads only what it needs.
        Gemini falls back to reading text files locally.

        ``upload_ids`` are the ``asset/uploaded`` event ids returned by the
        upload endpoint; they are resolved from the asset event log.
        ``asset_ids`` are ``CharacterKnowledgeAsset`` row ids of an existing
        character (edit mode); both can be combined to analyze new uploads
        together with already-attached reference files.
        """
        user = await sync_to_async(_get_authenticated_user)(info)

        try:
            draft_locale = await sync_to_async(_get_draft_prompt_locale)(user, locale)

            if upload_ids or asset_ids:
                full_text_budget = {'remaining': DRAFT_FULL_TEXT_TOTAL_CHAR_BUDGET}
                staged_uploads = []
                if upload_ids:
                    staged_uploads.extend(
                        await sync_to_async(_resolve_staged_uploads_from_events)(user, upload_ids, full_text_budget)
                    )
                if asset_ids:
                    staged_uploads.extend(
                        await sync_to_async(_resolve_staged_uploads_from_assets)(user, asset_ids, full_text_budget)
                    )
                if full_text_budget['remaining'] <= 0:
                    logger.warning(
                        "Draft full-text budget exhausted (%s chars); remaining files fall back to preview text.",
                        DRAFT_FULL_TEXT_TOTAL_CHAR_BUDGET,
                    )
                # uploadIds 与 assetIds 理论上不相交（新上传未挂接、已挂接的走
                # assetIds），这里按 file_url 兜底去重，防止同文件重复进管线。
                seen_urls = set()
                deduped_uploads = []
                for upload in staged_uploads:
                    dedup_key = upload.get("file_url") or upload.get("name")
                    if dedup_key in seen_urls:
                        continue
                    seen_urls.add(dedup_key)
                    deduped_uploads.append(upload)
                staged_uploads = deduped_uploads
            else:
                normalized_file_urls = []
                if file_urls:
                    normalized_file_urls.extend(file_urls)
                if file_url:
                    normalized_file_urls.append(file_url)
                staged_uploads = _resolve_staged_uploads(normalized_file_urls, file_names)

            draft_fields, _meta = await sync_to_async(_compute_character_draft)(
                user,
                draft_locale,
                text_context,
                staged_uploads,
            )
            return PrisMateDraft(**draft_fields)

        except Exception as e:
            logger.error(f"AI Generation Error: {e}")
            return PrisMateDraft(
                name="Generation Failed",
                description=f"Error generating draft: {str(e)}",
                personality="", appearance="", affiliation="",
                tags=[], visual_summary="", example_dialogue=""
            )

    @strawberry.mutation
    async def start_character_draft(
        self,
        info,
        upload_ids: Optional[List[str]] = None,
        asset_ids: Optional[List[str]] = None,
        text_context: Optional[str] = None,
        locale: Optional[str] = None,
    ) -> CharacterDraftJobType:
        """创建后台草稿任务并立即返回；前端轮询 characterDraftJob 拿进度。

        同指纹（uploadIds+assetIds+textContext+locale）的历史任务若留有
        批次笔记 checkpoint，复用到新任务上——重试/重新生成时已完成批次
        不再重复调用模型。
        """
        user = await sync_to_async(_get_authenticated_user)(info)

        @sync_to_async
        def create_job() -> CharacterDraftJob:
            sweep_stale_jobs(user)

            fingerprint_source = json.dumps(
                {
                    'upload_ids': sorted(int(i) for i in (upload_ids or []) if str(i).strip().isdigit()),
                    'asset_ids': sorted(int(i) for i in (asset_ids or []) if str(i).strip().isdigit()),
                    'text_context': text_context or '',
                    'locale': locale or '',
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            fingerprint = hashlib.sha256(fingerprint_source.encode('utf-8')).hexdigest()

            carried_checkpoint = []
            previous = (
                CharacterDraftJob.objects
                .filter(user=user, fingerprint=fingerprint)
                .exclude(checkpoint=[])
                .order_by('-id')
                .first()
            )
            if previous is not None:
                carried_checkpoint = list(previous.checkpoint or [])
                logger.info(
                    'Draft job resumes from checkpoint of job %s (%s batch notes).',
                    previous.id, len(carried_checkpoint),
                )

            with transaction.atomic():
                job = CharacterDraftJob.objects.create(
                    user=user,
                    status=CharacterDraftJob.Status.RUNNING,
                    stage='queued',
                    fingerprint=fingerprint,
                    inputs={
                        'upload_ids': upload_ids or [],
                        'asset_ids': asset_ids or [],
                        'text_context': text_context or '',
                        'locale': locale or '',
                    },
                    checkpoint=carried_checkpoint,
                )
                # 请求事务提交后再启动线程，保证线程能看到任务行。
                transaction.on_commit(lambda: start_draft_job_thread(job.id))
            return job

        job = await create_job()
        return _serialize_character_draft_job(job)

    @strawberry.mutation
    async def cancel_character_draft_job(self, info, id: strawberry.ID) -> CharacterDraftJobType:
        user = await sync_to_async(_get_authenticated_user)(info)

        @sync_to_async
        def cancel_job() -> CharacterDraftJob:
            job = CharacterDraftJob.objects.get(pk=id, user=user)
            if job.status == CharacterDraftJob.Status.RUNNING:
                # 协作式取消：runner 在批次边界检查该标记并落定 canceled。
                job.status = CharacterDraftJob.Status.CANCELING
                job.stage = 'canceling'
                job.save(update_fields=['status', 'stage', 'updated_at'])
            return job

        job = await cancel_job()
        return _serialize_character_draft_job(job)

    @strawberry.mutation
    async def create_character(self, info, input: CharacterInput) -> CharacterType:
        @sync_to_async
        def create_char_sync():
            user = _get_authenticated_user(info)
            character = Character.objects.create(
                name=input.name,
                avatar_url=input.avatar_url or "",
                description=input.description,
                user_address=input.user_address,
                personality=input.personality,
                appearance=input.appearance,
                response_guidelines=input.response_guidelines,
                scenario=input.scenario,
                example_dialogue=input.example_dialogue,
                enable_web_search=input.enable_web_search,
                tts_config=input.tts_config or {},
                affiliation=input.affiliation,
                system_prompt_preview=input.system_prompt_preview,
                tags=input.tags,
                created_by=user
            )
            _apply_asset_diff(character, _normalize_character_reference_inputs(input))
            character.save()
            return character
        character = await create_char_sync()
        return character

    @strawberry.mutation
    async def delete_character(self, info, id: strawberry.ID) -> bool:
        @sync_to_async
        def delete_sync():
            user = _get_authenticated_user(info)
            character = _get_owned_character(user, id)

            # 先删磁盘文件（头像、知识资产、消息附件），再级联删除关系行。
            cleanup_character_files(character)
            character.delete()
            return True
        return await delete_sync()

    @strawberry.mutation
    async def update_character(self, info, id: strawberry.ID, input: CharacterInput) -> CharacterType:
        @sync_to_async
        def update_char_sync():
            user = _get_authenticated_user(info)
            character = _get_owned_character(user, id)
            asset_diff = _normalize_character_reference_inputs(input)
            character.name = input.name
            character.avatar_url = input.avatar_url
            character.description = input.description
            character.user_address = input.user_address
            character.personality = input.personality
            character.appearance = input.appearance
            character.response_guidelines = input.response_guidelines
            character.scenario = input.scenario
            character.example_dialogue = input.example_dialogue
            character.affiliation = input.affiliation
            character.system_prompt_preview = input.system_prompt_preview
            character.tags = input.tags
            character.enable_web_search = input.enable_web_search
            character.tts_config = input.tts_config or {}
            _apply_asset_diff(character, asset_diff)
            character.save()
            return character
        character = await update_char_sync()
        return character

    @strawberry.mutation
    async def create_chat_session(self, info, input: ChatSessionInput) -> ChatSessionType:
        @sync_to_async
        def create_session_sync():
            user = _get_authenticated_user(info)
            character = _get_owned_character(user, input.character_id)
            _get_required_user_model_config(user)

            return ChatSession.objects.create(
                character=character,
                user=user,
                title=input.title or f"Chat with {character.name}",
            )
        return await create_session_sync()

    @strawberry.mutation
    async def update_chat_session(self, info, id: strawberry.ID, input: ChatSessionInput) -> ChatSessionType:
        @sync_to_async
        def update_session_sync():
            user = _get_authenticated_user(info)
            session = _get_owned_session(user, id)
            session.title = input.title or session.title
            session.save()
            return session
        return await update_session_sync()

@strawberry.type
class Query:
    @strawberry.django.field
    def characters(self, info) -> List[CharacterType]:
        user = _get_authenticated_user(info)
        return Character.objects.filter(created_by=user)

    @strawberry.django.field
    def character(self, info, id: strawberry.ID) -> CharacterType:
        user = _get_authenticated_user(info)
        return _get_owned_character(user, id)

    @strawberry.django.field
    def chat_sessions(self, info) -> List[ChatSessionType]:
        user = _get_authenticated_user(info)
        return ChatSession.objects.filter(user=user).order_by('-updated_at')

    @strawberry.django.field
    def chat_session(self, info, id: strawberry.ID) -> ChatSessionType:
        user = _get_authenticated_user(info)
        return _get_owned_session(user, id)

    @strawberry.field
    async def character_draft_job(self, info, id: strawberry.ID) -> CharacterDraftJobType:
        user = await sync_to_async(_get_authenticated_user)(info)

        @sync_to_async
        def load_job() -> CharacterDraftJob:
            try:
                return CharacterDraftJob.objects.get(pk=id, user=user)
            except CharacterDraftJob.DoesNotExist as exc:
                raise Exception("Draft job not found") from exc

        job = await load_job()
        return _serialize_character_draft_job(job)

    @strawberry.field
    async def my_latest_character_draft_job(self, info) -> Optional[CharacterDraftJobType]:
        """页面加载时恢复显示：返回该用户最近一次草稿任务（可空）。

        前端据此在刷新后恢复进行中任务的进度显示。
        """
        user = await sync_to_async(_get_authenticated_user)(info)

        @sync_to_async
        def load_latest_job() -> Optional[CharacterDraftJob]:
            return CharacterDraftJob.objects.filter(user=user).order_by('-id').first()

        job = await load_latest_job()
        return _serialize_character_draft_job(job) if job else None

schema = strawberry.Schema(query=Query, mutation=Mutation)
