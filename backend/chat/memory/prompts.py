"""Prompt templates for the per-turn memory extraction agent.

Adapted from SonettoHer's ``memory/narrative.py`` (COLD_START_SYSTEM /
UPDATE_SYSTEM / memory-item rules). Rule of thumb: identical structure,
Section name instead of ``theme``, Item ID instead of UUID.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable
from zoneinfo import ZoneInfo

from ..models import CharacterMemoryItem, ChatSession, Message


SPECIAL_SECTION_RULES = """
特殊分区:
- 「关系」: 此分区永远只允许一条记忆，描述用户与角色当前关系的阶段与氛围
  （例: 已从陌生变得亲近，开始互相开玩笑）。关系发生变化时必须用 update_memory
  更新那一条并说明原因，禁止新建第二条「关系」。
- 「里程碑」: 只追加以绝对日期开头的共同经历（例: 2026-08-23 第一次一起看了流星雨）。
  这是只增不减的回忆册：不得因为时间久远而删除；仅当两条确实描述同一事件时才允许 merge。
""".strip() + "\n\n"


CORE_PRINCIPLES = """\
核心原则:
0. 对于记忆来讲，主观印象第一，客观事实第二。科技、事实等固定的客观事实必须简洁简练；用户的喜好等主观印象可以相对正常地描写。每条描述最长不超过 200 字符（含标点）。
1. 并不是对话里提及的每一个细节都值得记录。仅关注用户的喜好、用户与 AI 正在做的事、困难与解决方法等部分。其余细节应当直接丢弃。
2. 只基于对话内容记录事实，不编造不推测。信息少就少写。
3. 每条记忆只承载一个事实，每次必须指定正确的 section。
4. 用第三人称自然语言描述。
5. 禁止使用"今天""明天""昨天""下周"等相对时间词汇，必须使用绝对日期写入记忆。已提供当前日期。
6. 少即是多。任何条目不能过长。被系统驳回的过长条目请主动拆分。
7. 平台故障不是事实：网络检索失败、接口报错、功能未配置等只是临时的技术状态，与用户和剧情无关，绝对不要为它们创建或更新任何记忆条目。
""".strip()


COLD_START_SYSTEM = """\
你是一位"记忆叙事师"。根据对话记录，用第三人称简洁中文记忆关于用户的事实。
你必须使用提供的工具来管理记忆：
- 先调用 read_memories 查看当前记忆（冷启动时为空）
- 使用 create_memory 逐条添加新事实，每次必须指定 section 参数
- 无需调用 update_memory 或 delete_memory（冷启动时没有旧记忆）

由于当前记忆为空，你必须创建新分区（1-4 字中文名词，例: 身份, 品味, 瞬间, 工作）。
""" + SPECIAL_SECTION_RULES + CORE_PRINCIPLES


UPDATE_SYSTEM = """\
你是一位"记忆叙事师"。以下是当前记忆（每条带唯一 short_id 和 section）和一轮新对话。请对比新旧信息，更新记忆。
你必须使用提供的工具来管理记忆：
- 先调用 read_memories 查看所有当前记忆（注意每条记忆的 section）
- 新信息用 create_memory 逐条添加，每次必须指定 section 参数
- 已有信息需要修正或补充时用 update_memory（通过 short_id 指定），可选用 section 参数重命名
- 与新信息矛盾或已过时的条目用 delete_memory 删除
- 相似条目用 merge_memories 合并（id1 + id2 → id1 保留，合并两边的 history）

记忆分区：优先使用已有分区；若记忆不适合任何已有分区或用户明确要求新建，可创建新分区（1-4 字中文名词）。
""" + SPECIAL_SECTION_RULES + CORE_PRINCIPLES


def _format_current_items(items: Iterable[CharacterMemoryItem]) -> str:
    """Render the current items snapshot for the prompt."""
    items = list(items)
    if not items:
        return "（暂无记忆条目）"
    by_section: dict[str, list[CharacterMemoryItem]] = {}
    for item in items:
        by_section.setdefault(item.section, []).append(item)
    lines: list[str] = []
    for section, section_items in by_section.items():
        lines.append(f"## {section}")
        for item in section_items:
            lines.append(f" [{item.short_id}] {item.description}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_messages_for_prompt(chat_session: ChatSession, new_message: Message) -> str:
    """Render the messages trimmed for tool-call input."""
    from ..models import Message as MessageModel

    history = list(
        MessageModel.objects
        .filter(chat_session=chat_session)
        .order_by("timestamp")
    )
    if new_message and new_message.id:
        history = [m for m in history if m.id != new_message.id] + ([new_message] if new_message.content else [])
    # Look at most-recent 6 turns
    history = history[-6:]
    lines: list[str] = []
    for msg in history:
        role = msg.role or "unknown"
        content = (msg.content or "").strip()
        if not content:
            continue
        lines.append(f"[{role}]: {_truncate(content, 600)}")
    return "\n".join(lines).strip()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _format_research_for_prompt(research_payload: dict | None) -> str:
    """把本轮联网检索结果压缩成记忆提取可读的段落（memory v2 §搜索×记忆）。"""
    if not research_payload:
        return ""
    items = research_payload.get("items") or []
    query = (research_payload.get("query") or "").strip()
    error = (research_payload.get("error") or "").strip()
    if error or not items:
        # 检索失败属于平台临时状态。错误细节一旦进入提取 prompt，就会被
        # 误存成"角色的功能坏了"这类伪事实（2026-08-24 玛丽实测案例），
        # 所以这里选择整段省略，交给核心原则里的平台故障禁令兜底。
        return ""
    lines = ["### WEB RESEARCH THIS TURN"]
    if query:
        lines.append(f"检索词: {query}")
    for index, item in enumerate(items[:3], start=1):
        title = (item.get("title") or "Untitled").strip()
        snippet = (item.get("snippet") or "").strip()
        lines.append(f"{index}. {title} — {snippet[:160]}")
    lines.append("若检索内容揭示了用户的持久事实（喜好、计划、身份等），可按核心原则记录；"
                 "纯时效性新闻或与用户无关的内容应丢弃。")
    return "\n".join(lines)


def build_memory_extraction_prompt(
    *,
    character_name: str,
    items: Iterable[CharacterMemoryItem],
    chat_session: ChatSession | None,
    new_message: Message | None,
    timezone_name: str = "UTC",
    research_payload: dict | None = None,
) -> dict[str, str]:
    """Build the (system, user) tuple for the extraction call."""
    items_list = list(items)
    has_items = bool(items_list)
    system_prompt = UPDATE_SYSTEM if has_items else COLD_START_SYSTEM

    user_sections: list[str] = ["### CURRENT MEMORY (read-only snapshot)"]
    user_sections.append(_format_current_items(items_list))
    research_section = _format_research_for_prompt(research_payload)
    if research_section:
        user_sections.append("")
        user_sections.append(research_section)
    if chat_session:
        user_sections.append("")
        user_sections.append("### NEW TURN")
        user_sections.append(_format_messages_for_prompt(chat_session, new_message))
    try:
        now = datetime.now(ZoneInfo(timezone_name))
        date_prefix = f"\n\n--- 会话日期: {now.strftime('%Y-%m-%d')} ({now.strftime('%A')}) ---"
    except Exception:
        date_prefix = ""
    user_sections.append(date_prefix)

    return {
        "system": system_prompt + f"\n\nThis memory belongs to the AI character: {character_name}.",
        "user": "\n".join(user_sections).strip(),
    }


def get_memory_crud_tool_specs() -> list[dict]:
    """Five SonettoHere-aligned tool specs that the Celery worker exposes.

    Identical parameter shape so future SonettoHere tool definitions can be
    ported over verbatim.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "create_memory",
                "description": "Add a new long-term memory entry under a section name.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "section": {"type": "string", "description": "1-4字 (zh) or short English section name. Prefer existing sections from read_memories."},
                        "description": {"type": "string", "description": "Single-fact description, ≤200 visible characters."},
                    },
                    "required": ["section", "description"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_memories",
                "description": "List current memory entries grouped by section. Call this before any mutation if current items exist.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "section": {"type": "string", "description": "Optional section filter (1-4字 zh / short English)."},
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_memory",
                "description": "Update one existing entry's description (and optionally section).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "short_id from read_memories output."},
                        "description": {"type": "string", "description": "Updated description, ≤200 visible characters."},
                        "section": {"type": "string", "description": "Optional new section name. Omit to keep current."},
                        "reason": {"type": "string", "description": "Short note explaining why this entry changed."},
                    },
                    "required": ["id", "description"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_memory",
                "description": "Delete an existing entry by short_id (and record the reason).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "short_id from read_memories output."},
                        "reason": {"type": "string", "description": "Why this entry should be removed."},
                    },
                    "required": ["id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "merge_memories",
                "description": "Merge two related entries into one (preserves both histories).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id1": {"type": "string", "description": "short_id of the entry to KEEP."},
                        "id2": {"type": "string", "description": "short_id of the entry to MERGE IN and DELETE."},
                        "content": {"type": "string", "description": "Merged description, ≤200 visible characters."},
                        "section": {"type": "string", "description": "Section name for the merged entry."},
                        "reason": {"type": "string", "description": "Why these entries are similar enough to merge."},
                    },
                    "required": ["id1", "id2", "content", "section"],
                },
            },
        },
    ]
