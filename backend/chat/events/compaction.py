"""Compaction engine: shadow old events with an LLM summary (pure logic).

The Celery task in ``chat.tasks`` wires these helpers to the model client;
nothing here touches the network, the task queue, or the ORM beyond reading
already-loaded ``ChatEvent`` objects. Compaction appends a
``compaction/summary`` event that shadows a seq range; it never mutates or
deletes existing events.
"""
from __future__ import annotations

from ..models import ChatEvent, ChatEventType
from .store import estimate_event_tokens


def resolve_context_window(runtime_config: dict, *, default: int = 32000) -> int:
    """Context window from the runtime config, with a sane fallback."""
    value = runtime_config.get('context_window')
    if isinstance(value, int) and value > 0:
        return value
    return default


def _active_events(events: list[ChatEvent]) -> list[dict]:
    """Message events not shadowed by an earlier compaction summary.

    Each item is ``{'seq', 'role', 'tokens'}`` in seq order.
    """
    shadow_ranges: list[tuple[int, int]] = []
    for event in events:
        if event.event_type == ChatEventType.COMPACTION_SUMMARY:
            data = event.data or {}
            start = data.get('shadowed_start_seq')
            end = data.get('shadowed_end_seq')
            if start is not None and end is not None:
                shadow_ranges.append((int(start), int(end)))

    active: list[dict] = []
    range_index = 0
    for event in events:
        while (
            range_index < len(shadow_ranges)
            and shadow_ranges[range_index][1] < event.seq
        ):
            range_index += 1
        if event.event_type not in (
            ChatEventType.USER_MESSAGE,
            ChatEventType.ASSISTANT_MESSAGE,
        ):
            continue
        in_shadow = (
            range_index < len(shadow_ranges)
            and shadow_ranges[range_index][0] <= event.seq <= shadow_ranges[range_index][1]
        )
        if in_shadow:
            continue
        active.append({
            'seq': event.seq,
            'role': 'user' if event.event_type == ChatEventType.USER_MESSAGE else 'assistant',
            'tokens': estimate_event_tokens(event),
        })
    return active


def select_shadow_range(
    events: list[ChatEvent],
    *,
    context_window: int,
    threshold_ratio: float = 0.7,
    retain_ratio: float = 0.3,
    min_history_tokens: int = 8000,
    min_retain_tokens: int = 4000,
) -> tuple[int, int] | None:
    """Pick the inclusive seq range to shadow, or ``None`` when compaction is
    not useful.

    Only *active* events (those after the latest compaction's shadow range)
    are eligible. The newest ``retain_tokens`` of active history stays
    verbatim; everything older is shadowed. The summary pseudo-message is a
    user-role message, so the retained tail is trimmed to start with an
    assistant message — otherwise the first retained user message is absorbed
    into the shadow range to keep roles alternating.
    """
    active = _active_events(events)
    total_tokens = sum(item['tokens'] for item in active)
    if total_tokens < min_history_tokens:
        return None
    threshold = int(context_window * threshold_ratio)
    if total_tokens <= threshold:
        return None

    retain_tokens = max(min_retain_tokens, int(context_window * retain_ratio))

    # Walk newest -> oldest, accumulating the retained tail.
    retained_seqs: list[int] = []
    budget = retain_tokens
    for item in reversed(active):
        retained_seqs.append(item['seq'])
        budget -= item['tokens']
        if budget <= 0:
            break
    if not retained_seqs:
        return None

    shadowed_seqs = [item['seq'] for item in active if item['seq'] not in retained_seqs]
    if not shadowed_seqs:
        return None

    start = shadowed_seqs[0]
    end = shadowed_seqs[-1]

    # Alternation: the oldest retained message is the one right after the
    # shadowed range; if it is a user message it would sit directly after the
    # user-role summary, so absorb it into the shadow range instead.
    oldest_retained_seq = min(retained_seqs)
    retained_by_seq = {item['seq']: item for item in active}
    if retained_by_seq[oldest_retained_seq]['role'] == 'user':
        end = oldest_retained_seq
        retained_seqs.remove(oldest_retained_seq)
        if not retained_seqs:
            return None

    return start, end


def render_shadowed_conversation(
    events: list[ChatEvent],
    start_seq: int,
    end_seq: int,
    *,
    per_message_chars: int = 600,
) -> str:
    """Render the shadowed message events as ``[用户]/[角色]: content`` lines
    for the summarization call."""
    lines: list[str] = []
    for event in events:
        if not (start_seq <= event.seq <= end_seq):
            continue
        if event.event_type == ChatEventType.USER_MESSAGE:
            role = '用户'
            content = (event.data or {}).get('content') or ''
        elif event.event_type == ChatEventType.ASSISTANT_MESSAGE:
            role = '角色'
            content = (event.data or {}).get('content') or ''
        else:
            continue
        content = content.strip()
        if not content:
            continue
        if len(content) > per_message_chars:
            content = content[: per_message_chars - 3].rstrip() + '...'
        lines.append(f"[{role}]: {content}")
    return "\n".join(lines)


SUMMARY_SYSTEM = """\
你是一位对话摘要师。请把下面这段角色扮演对话压缩成一段简洁的中文摘要。
必须保留：用户的持久信息（姓名、喜好、身份、工作、生活习惯）、
人物关系进展、剧情关键节点、尚未解决的问题、用户明确表达过的偏好。
应该丢弃：寒暄、重复的琐碎细节、平台技术状态、网络检索过程。
要求：第三人称自然语言，不超过 400 字，不使用"今天/昨天/下周"等相对时间词。"""


def build_summary_prompt(conversation_text: str) -> tuple[str, str]:
    """Return the ``(system, user)`` pair for the summarization call."""
    user = (
        "### CONVERSATION TO SUMMARIZE\n"
        f"{conversation_text}\n\n"
        "请输出压缩后的摘要。"
    )
    return SUMMARY_SYSTEM, user


def shadowed_token_total(events: list[ChatEvent], start_seq: int, end_seq: int) -> int:
    """Estimated token count of the shadowed message events."""
    total = 0
    for event in events:
        if start_seq <= event.seq <= end_seq and event.event_type in (
            ChatEventType.USER_MESSAGE,
            ChatEventType.ASSISTANT_MESSAGE,
        ):
            total += estimate_event_tokens(event)
    return total
