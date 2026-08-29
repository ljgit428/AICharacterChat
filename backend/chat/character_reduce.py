"""character_reduce — reduce 流水线（Django 模块版）。

输入: staged uploads（`_resolve_staged_uploads` 的产出，每项含
      {name, kind, mime_type, content, file_url}，content 为全文）。
流程:
  1. 按戏份分层（纯规则，0 LLM）: 重头/中/客串
  2. 分批精读（0 LLM 组装 prompt）: 重头完整读（超长截断）；客串只取目标角色
     出现片段；批次 LLM 调用走线程池并发
  3. 每批 LLM 产出结构化笔记（带原文引用）: 性格证据/语言风格/行为演出/情绪触发点/关系网；
     单批失败重试一次后降级为空笔记，不拖垮整条管线
  4. 汇总合并（LLM）: 处理前后期变化 → 角色属性总结 + 分类台词样本库 + 行为样本；
     批次笔记超量时先按组部分合并，再最终合并

`run_reduce_pipeline()` 返回可直接映射为 PrisMateDraft 的 dict。
llm_call 通过参数注入（真实环境绑 _generate_text）。
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, List, Optional

from django.conf import settings

# ---------------------------------------------------------------------------
# 配置（可用 Django settings 覆盖）
# ---------------------------------------------------------------------------
TIER_MAIN = 30      # 重头: 目标角色台词 >= 30 句
TIER_MID = 5        # 中: 5~29 句；客串: < 5 句
CAME0_WINDOW = 3    # 客串片段: 台词前后各 N 行（保上下文、控 token）
MAIN_WINDOW = 6     # 重头/中档片段: 台词前后各 N 行


def _int_setting(name: str, default: int) -> int:
    try:
        return max(1, int(getattr(settings, name, default)))
    except (TypeError, ValueError):
        return default


BATCH_SIZE = _int_setting('CHARACTER_REDUCE_BATCH_SIZE', 8)
MAX_CONCURRENT_BATCHES = _int_setting('CHARACTER_REDUCE_MAX_CONCURRENCY', 8)
MAX_BATCH_FILE_CHARS = 6000      # 重头/中档单文件正文上限（窗口提取后再兜底截断）
MAX_NO_TARGET_FILE_CHARS = 3000  # 未指定目标名时（全员客串层）单文件正文上限
MERGE_GROUP_SIZE = 10            # 单次合并调用最多吃进的批次笔记数，超出走两级合并
MAX_CITATIONS_PER_BATCH = 6      # 合并输入里每批保留的引用条数
MAX_QUOTE_CHARS = 200            # 合并输入里单条引用的长度上限

# 单请求直达路径（方案 C 主链路）：纯规则预筛出角色相关片段后，拼装成一个
# prompt 发 1 次 LLM 请求直接出卡。预算按"慢端点也能在读超时内 prefill 完"
# 保守取值（中文约 1.5~2 字符/token）；超出预算的部分按优先级丢弃——先丢
# 他人叙述提及，最后才丢角色台词。
SINGLE_SHOT_MAX_CHARS = _int_setting('CHARACTER_SINGLE_SHOT_MAX_CHARS', 45_000)
SINGLE_SHOT_ENABLED = bool(getattr(settings, 'CHARACTER_DRAFT_SINGLE_SHOT', True))

# ---------------------------------------------------------------------------
# 1. 分层（纯规则，0 LLM）
# ---------------------------------------------------------------------------

def _speaker_line_count(content: str, target: str) -> int:
    """统计目标角色台词条数：以 `目标名:` 开头的行。"""
    if not target:
        return 0
    return sum(1 for ln in content.splitlines() if ln.strip().startswith(target))


def tier_for(line_count: int) -> str:
    if line_count >= TIER_MAIN:
        return "main"
    if line_count >= TIER_MID:
        return "mid"
    return "cameo"


def _tier_uploads(uploads: List[dict], target: str):
    """返回 {tier: [upload]}，每 upload 附 line_count。"""
    tiers = {"main": [], "mid": [], "cameo": []}
    for upload in uploads:
        n = _speaker_line_count(upload.get("content") or "", target)
        tiers[tier_for(n)].append({**upload, "line_count": n})
    for tier in tiers:
        tiers[tier].sort(key=lambda r: -r["line_count"])
    return tiers


# ---------------------------------------------------------------------------
# 1b. 单请求直达的纯规则预筛（0 LLM，毫秒级）
# ---------------------------------------------------------------------------

def extract_character_core_excerpts(
    uploads: List[dict],
    target: str,
    max_total_chars: Optional[int] = None,
) -> str:
    """从全部文件里纯代码捞出与目标角色相关的精华片段，拼成单一语料。

    上下文超限防护（两轮优先级填充）：
    - 第一轮：台词行（`目标名:` 开头，±1 行上下文）——角色灵魂，预算再紧
      也优先保留；
    - 第二轮：叙述/他人提及窗口（行内含目标名，±2 行）——弱证据，预算
      有余才纳入；
    每轮都跨文件轮转采样，避免截断偏向排在前面的大文件。返回
    ≤ max_total_chars 的拼装文本；目标角色完全没出现时返回空串（调用方
    落到按需读取路径）。全程 0 LLM、毫秒级。
    """
    if not target:
        return ""
    budget = max_total_chars or SINGLE_SHOT_MAX_CHARS
    target_re = re.compile(re.escape(target))

    # 每个文件分两个优先级桶：台词（高）与提及（低）。
    dialogue_lines: List[tuple] = []  # (name, [lines])
    mention_lines: List[tuple] = []
    for upload in uploads:
        lines = (upload.get("content") or "").splitlines()
        dialogue_keep: set = set()
        mention_keep: set = set()
        for idx, raw_line in enumerate(lines):
            stripped = raw_line.strip()
            if not stripped:
                continue
            if stripped.startswith(target) and (
                len(stripped) == len(target) or stripped[len(target)] in ":："
            ):
                for j in range(max(0, idx - 1), min(len(lines), idx + 2)):
                    if lines[j].strip():
                        dialogue_keep.add(j)
            elif target_re.search(stripped):
                for j in range(max(0, idx - 2), min(len(lines), idx + 3)):
                    if lines[j].strip() and j not in dialogue_keep:
                        mention_keep.add(j)
        name = upload.get("name") or upload.get("file_url") or "file"
        if dialogue_keep:
            deduped = list(dict.fromkeys(lines[i].strip() for i in sorted(dialogue_keep)))
            dialogue_lines.append((name, deduped))
        if mention_keep:
            deduped = list(dict.fromkeys(lines[i].strip() for i in sorted(mention_keep)))
            mention_lines.append((name, deduped))

    if not dialogue_lines and not mention_lines:
        return ""

    # 轮转采样装配：bucket 内每轮从每个文件取一块，预算用尽即停。
    header_emitted: set = set()
    sections: List[str] = []
    used = 0

    def _emit(bucket: List[tuple], chunk_per_round: int) -> None:
        nonlocal used
        cursors = {name: 0 for name, _ in bucket}
        header_cost = len(bucket) * 24
        while used < budget:
            progressed = False
            for name, kept in bucket:
                start = cursors[name]
                if start >= len(kept):
                    continue
                block = kept[start:start + chunk_per_round]
                cursors[name] = start + len(block)
                parts = []
                if name not in header_emitted:
                    parts.append(f"===== 文件: {name} =====")
                    header_emitted.add(name)
                parts.extend(block)
                section = "\n".join(parts)
                if used + len(section) + header_cost > budget:
                    cursors[name] = len(kept)
                    continue
                sections.append(section)
                used += len(section)
                progressed = True
            if not progressed:
                break

    _emit(dialogue_lines, chunk_per_round=30)
    _emit(mention_lines, chunk_per_round=20)
    return "\n".join(sections).strip()


# ---------------------------------------------------------------------------
# 2. 精读内容组装（0 LLM）
# ---------------------------------------------------------------------------

def _cameo_segments(content: str, target: str, window: int = CAME0_WINDOW) -> str:
    """客串文件：只取目标角色出现的片段，前后保留 window 行上下文。"""
    if not target:
        return content
    lines = content.splitlines()
    keep = set()
    for idx, ln in enumerate(lines):
        if ln.strip().startswith(target):
            for j in range(max(0, idx - window), min(len(lines), idx + window + 1)):
                keep.add(j)
    return "\n".join(lines[i] for i in sorted(keep)) if keep else ""


def _clamp_chars(text: str, max_chars: int) -> str:
    """超长正文保留头尾、省略中段，保证单批 prompt 体积有上界。"""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half].rstrip() + "\n…[中段省略]…\n" + text[-half:].lstrip()


def _batch_file_body(upload: dict, target: str, tier_label: str) -> str:
    """单文件进精读 prompt 的正文：按层提取片段并限量。

    - 客串（指定目标名）：只取台词窗口片段。
    - 重头/中档：取更宽的台词窗口，仍超长再头尾截断。
    - 未指定目标名：分层计数全部为 0、所有文件都落客串层，此时窗口提取
      无从下手，退化为逐文件限量截断——否则 200+ 文件 × 全文会让每批
      prompt 和合并输入一起爆炸（2026-08-28 实测 223 文件长时间打转）。
    """
    content = upload.get("content") or ""
    if tier_label == "cameo":
        if not target:
            return _clamp_chars(content, MAX_NO_TARGET_FILE_CHARS)
        # 输入改为全文后，目标高频出现的客串文件其片段总和会远超单文件
        # 上限，必须与重头/中档一样兜底截断，保证单批 prompt 体积有上界。
        return _clamp_chars(_cameo_segments(content, target, CAME0_WINDOW), MAX_BATCH_FILE_CHARS)
    if target:
        return _clamp_chars(_cameo_segments(content, target, MAIN_WINDOW), MAX_BATCH_FILE_CHARS)
    return _clamp_chars(content, MAX_BATCH_FILE_CHARS)


def _build_batch_prompt(uploads: List[dict], target: str, tier_label: str) -> str:
    parts = [f"[批次: {tier_label} 文件，共 {len(uploads)} 个]\n"]
    for upload in uploads:
        body = _batch_file_body(upload, target, tier_label)
        name = upload.get("name") or upload.get("file_url") or "uploaded-file"
        parts.append(
            f"\n===== 文件: {name}（目标角色台词 {upload['line_count']} 句）=====\n{body}"
        )
    return "\n".join(parts)


BATCH_NOTE_SYSTEM = (
    "你是角色分析师。阅读提供的文件批次，提取目标角色的结构化证据。\n"
    "每条证据必须带原文引用（file + 原句）。输出 JSON，键为：\n"
    "batch_summary(字符串), citations(数组, 每项 {file, quote, note}), "
    "personality_evidence(数组), language_style(数组), behavior_notes(数组), "
    "emotion_triggers(数组), relationships(数组)。"
)

_EMPTY_NOTE = {
    "batch_summary": "",
    "citations": [],
    "personality_evidence": [],
    "language_style": [],
    "behavior_notes": [],
    "emotion_triggers": [],
    "relationships": [],
}


def _produce_batch_notes(uploads, target, tier_label, llm_call) -> dict:
    """单批精读：LLM 产出结构化笔记。失败重试一次，再失败降级为空笔记。

    223 个文件要跑几十批，任何一批的 JSON 解析失败都不该让整条管线
    （几十分钟的调用）前功尽弃，所以这里只降级、不抛出。
    """
    prompt = _build_batch_prompt(uploads, target, tier_label)
    last_error: Optional[Exception] = None
    for attempt in range(2):
        try:
            raw = llm_call(BATCH_NOTE_SYSTEM, prompt)
            return json.loads(raw)
        except Exception as exc:  # noqa: BLE001 - 网络/解析失败都要降级
            last_error = exc
            if attempt == 0:
                prompt += "\n\n（上一次输出无法解析，请严格只输出一个 JSON 对象，不要输出任何额外文本。）"
    return {**_EMPTY_NOTE, "_error": f"{type(last_error).__name__}: {last_error}"}


# ---------------------------------------------------------------------------
# 3. 合并（LLM）
# ---------------------------------------------------------------------------

MERGE_SYSTEM = (
    "你是角色档案总编辑。把各批次的结构化笔记合并成最终角色档案，处理前后期变化"
    "（分阶段呈现性格/语气演变）。输出 JSON，键为：\n"
    "profile_summary(对象: name/description/personality/appearance/affiliation/tags), "
    "dialogue_library(对象: 按 日常/提问/情绪/命令拒绝/玩笑 分类的台词样本数组, "
    "每项 {category, quote, file, note}), "
    "behavior_samples(数组, 每项 {scenario, behavior, file}), "
    "evolution(数组, 每项 {phase, summary})。"
)

_MERGE_ARRAY_KEYS = (
    "personality_evidence",
    "language_style",
    "behavior_notes",
    "emotion_triggers",
    "relationships",
)
_MERGE_ARRAY_MAX_ITEMS = 8
_MERGE_ITEM_MAX_CHARS = 160


def _trim_note_for_merge(note: dict) -> dict:
    """把批次笔记裁剪到合并输入可接受的体积，控制合并 prompt 的 token 上限。"""
    citations = note.get("citations") or []
    kept_citations = []
    for citation in citations[:MAX_CITATIONS_PER_BATCH]:
        if isinstance(citation, dict):
            kept_citations.append({
                "file": _as_text(citation.get("file"))[:120],
                "quote": _as_text(citation.get("quote"))[:MAX_QUOTE_CHARS],
                "note": _as_text(citation.get("note"))[:_MERGE_ITEM_MAX_CHARS],
            })
    trimmed = {
        "batch_summary": _as_text(note.get("batch_summary"))[:400],
        "_tier": note.get("_tier"),
        "_files": note.get("_files"),
        "citations": kept_citations,
    }
    if len(citations) > MAX_CITATIONS_PER_BATCH:
        trimmed["citations_truncated"] = True
    for key in _MERGE_ARRAY_KEYS:
        value = note.get(key)
        if not isinstance(value, list):
            continue
        items = []
        for item in value[:_MERGE_ARRAY_MAX_ITEMS]:
            text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
            items.append(text if len(text) <= _MERGE_ITEM_MAX_CHARS else text[:_MERGE_ITEM_MAX_CHARS] + "…")
        trimmed[key] = items
    return trimmed


def _merge_call(payload: str, llm_call) -> dict:
    """执行一次合并调用，失败带提醒重试两次后抛出。"""
    last_error: Optional[Exception] = None
    for attempt in range(3):
        prompt = payload
        if attempt > 0:
            prompt += "\n\n（上一次输出无法解析，请严格只输出一个 JSON 对象，不要输出任何额外文本。）"
        try:
            raw = llm_call(MERGE_SYSTEM, prompt)
            return json.loads(raw)
        except Exception as exc:  # noqa: BLE001 - 保留最后一次异常统一抛出
            last_error = exc
    raise last_error


def _merge_notes(batch_notes: list, llm_call, merge_progress: Optional[Callable[[str, int, int], None]] = None) -> dict:
    """合并批次笔记。

    223 个文件会产出几十批笔记，一次性塞进单个合并调用会撑爆上下文；
    超过 MERGE_GROUP_SIZE 时先按组部分合并，再对部分结果做最终合并。
    merge_progress 在每次合并调用前回调（stage="merge"），可抛异常取消。
    """
    notes = [_trim_note_for_merge(note) for note in batch_notes]
    if len(notes) <= MERGE_GROUP_SIZE:
        if merge_progress is not None:
            merge_progress("merge", 0, 1)
        return _merge_call(json.dumps({"batches": notes}, ensure_ascii=False), llm_call)

    groups = [notes[index:index + MERGE_GROUP_SIZE] for index in range(0, len(notes), MERGE_GROUP_SIZE)]
    total_calls = len(groups) + 1
    partials = []
    for group_index, group in enumerate(groups):
        if merge_progress is not None:
            merge_progress("merge", group_index, total_calls)
        payload = json.dumps({"batches": group}, ensure_ascii=False)
        try:
            partials.append(_merge_call(payload, llm_call))
        except Exception:  # noqa: BLE001 - 单组合并失败丢这一组，不让整条管线报废
            continue
    if not partials:
        raise RuntimeError("All partial merge calls failed for the reduce pipeline.")
    if merge_progress is not None:
        merge_progress("merge", len(groups), total_calls)
    final_payload = json.dumps({"batches": partials}, ensure_ascii=False)
    return _merge_call(final_payload, llm_call)


# ---------------------------------------------------------------------------
# 4. 主入口
# ---------------------------------------------------------------------------

def _batch_signature(target: str, tier: str, batch_uploads: List[dict]) -> str:
    """批次的稳定指纹：目标角色 + 层 + 文件内容哈希序列。

    内容寻址：同一语料重传（新的 staging 路径）指纹不变，批次笔记缓存
    仍然命中；换了目标角色则分层与笔记都会变，指纹随之失效。
    """
    locations = "|".join(
        str(upload.get("content_hash") or upload.get("file_url") or upload.get("name") or "")
        for upload in batch_uploads
    )
    return f"{target}::{tier}::{locations}"


def run_reduce_pipeline(
    uploads: List[dict],
    target: str,
    llm_call: Callable[[str, str], str],
    batch_size: int = BATCH_SIZE,
    max_workers: int = MAX_CONCURRENT_BATCHES,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
    on_batch_note: Optional[Callable[[str, str, List[str], dict], None]] = None,
    completed_notes: Optional[dict] = None,
    fetch_cached_note: Optional[Callable[[str], Optional[dict]]] = None,
) -> dict:
    """跑完整 reduce 流水线，返回最终档案 dict（可直接映射 PrisMateDraft）。

    批次精读调用相互独立，用线程池并发执行——200+ 文件的批次 LLM 调用
    串行时总耗时是单次调用 × 批数，这也是前端长时间转圈的主因。合并依赖
    全部批次结果，仍保持串行（必要时两级合并）。

    任务化与缓存（均可选）：
    - progress_callback(stage, done, total)：每个批次完成、每次合并调用前
      回调，供任务行更新真实进度；回调内抛异常即取消整条管线。
    - on_batch_note(signature, tier, file_names, note)：每批新产出笔记即
      落库（checkpoint / 内容寻址缓存），供断点续跑与二次创建复用。
    - completed_notes：signature → note，命中批次直接复用，不再调 LLM。
    - fetch_cached_note(signature)：completed_notes 之外的懒加载查询
      （按内容哈希的持久缓存表），两处都未命中才真正调用模型。
    """
    def _notify(stage: str, done: int, total: int) -> None:
        if progress_callback is not None:
            progress_callback(stage, done, total)

    completed_notes = dict(completed_notes or {})
    tiers = _tier_uploads(uploads, target)

    jobs: List[tuple] = []
    for tier in ("main", "mid", "cameo"):
        recs = tiers[tier]
        for i in range(0, len(recs), batch_size):
            jobs.append((tier, recs[i:i + batch_size]))

    total_batches = len(jobs)
    pending_jobs: List[tuple] = []
    notes_by_index: List[Optional[dict]] = [None] * total_batches
    resumed_count = 0
    for index, (tier, batch) in enumerate(jobs):
        signature = _batch_signature(target, tier, batch)
        cached = completed_notes.get(signature)
        if cached is None and fetch_cached_note is not None:
            try:
                cached = fetch_cached_note(signature)
            except Exception:  # noqa: BLE001 - 缓存查询失败按未命中处理
                cached = None
        if cached is not None:
            notes_by_index[index] = {**cached, "_tier": tier, "_resumed": True}
            resumed_count += 1
        else:
            pending_jobs.append((index, tier, batch, signature))
    _notify("analyze", resumed_count, total_batches)

    if pending_jobs:
        workers = max(1, min(max_workers, len(pending_jobs)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {
                pool.submit(
                    _produce_batch_notes, batch, target, tier, llm_call,
                ): (index, tier, batch, signature)
                for index, tier, batch, signature in pending_jobs
            }
            done_count = resumed_count
            for future in as_completed(future_map):
                index, tier, batch, signature = future_map[future]
                note = future.result()
                notes_by_index[index] = note
                done_count += 1
                if on_batch_note is not None:
                    on_batch_note(
                        signature,
                        tier,
                        [u.get("name") or u.get("file_url") or "" for u in batch],
                        note,
                    )
                # 回调在主线程顺序触发；用户取消时在这里抛出、终止管线。
                _notify("analyze", done_count, total_batches)

    batch_notes: List[dict] = []
    for (tier, batch), note in zip(jobs, notes_by_index):
        note["_tier"] = tier
        note["_files"] = [
            u.get("name") or u.get("file_url") for u in batch
        ]
        batch_notes.append(note)

    merged = _merge_notes(batch_notes, llm_call, merge_progress=_notify)
    return {
        "target": target,
        "tier_counts": {t: len(r) for t, r in tiers.items()},
        "batch_count": len(batch_notes),
        "failed_batches": sum(1 for n in batch_notes if n.get("_error")),
        "result": merged,
    }


# ---------------------------------------------------------------------------
# 5. 对齐 PrisMateDraft
# ---------------------------------------------------------------------------

DIALOGUE_CATEGORIES = ["日常", "提问", "情绪", "命令拒绝", "玩笑"]


def _build_example_dialogue(dialogue_library: Optional[dict]) -> str:
    """把 dialogue_library（5 分类台词样本）转成 example_dialogue 文本。

    PrisMateDraft.example_dialogue 约定每段为
    "User: <一句提问或陈述>\\nCharacter: <一句完整回答>"。
    原型阶段：把样本台词作为 Character 侧内容，用「Character: <quote>」段落
    呈现（用户侧留空提示）；后续接真模型时可让 reduce 直接生成完整对白。
    """
    if not dialogue_library:
        return ""
    samples: List[str] = []
    for category in DIALOGUE_CATEGORIES:
        items = dialogue_library.get(category) or []
        if not isinstance(items, list):
            continue
        for item in items[:2]:
            if not isinstance(item, dict):
                continue
            quote = _as_text(item.get("quote"))
            if not quote:
                continue
            file_ref = _as_text(item.get("file"))
            source = f"（{file_ref}）" if file_ref else ""
            samples.append(f"User: <触发场景>{source}\nCharacter: {quote}")
    return "\n\n".join(samples)


def _as_text(value, fallback: str = "") -> str:
    """把 LLM 返回的字段安全转成文本。

    推理/中转模型偶尔会把单个字段返回成 list（如 "name": ["玛丽"]）或
    其他非字符串类型；直接 .strip() 会炸掉整条 reduce 管线
    （2026-08-24 实测 'list' object has no attribute 'strip'）。
    """
    if value is None:
        return fallback
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        parts = [str(v).strip() for v in value if v is not None and str(v).strip()]
        return "\n".join(parts) if parts else fallback
    if isinstance(value, dict):
        return ""
    text = str(value).strip()
    return text or fallback


def reduce_result_to_draft(pipeline_result: dict) -> dict:
    """把 reduce 流水线产出映射为 PrisMateDraft 兼容字段。"""
    result = pipeline_result.get("result") or {}
    summary = result.get("profile_summary") or {}

    example_dialogue = _build_example_dialogue(result.get("dialogue_library"))

    return {
        "name": _as_text(summary.get("name"), "Unknown"),
        "description": _as_text(summary.get("description")),
        "personality": _as_text(summary.get("personality")),
        "appearance": _as_text(summary.get("appearance")),
        "affiliation": _as_text(summary.get("affiliation")),
        "tags": [t for t in (summary.get("tags") or []) if isinstance(t, str) and t.strip()],
        "visual_summary": "",
        "example_dialogue": example_dialogue,
    }


def _normalize_target_name(text_context: Optional[str]) -> str:
    """从 text_context 里解析目标角色名。

    前端约定 text_context 含 "目标角色名: xxx" 行；取不到则返回空。
    名字取到行尾为止——带空格的名字（如英文 "Mika Suenaga"）不能在
    第一个空格处截断，否则台词计数永远匹配不到（2026-08-24 实测 bug）。
    """
    if not text_context:
        return ""
    m = re.search(r"目标角色名\s*[:：]\s*(.+)", text_context)
    if m:
        return m.group(1).strip()
    m = re.search(r"target\s*character\s*name\s*[:：]\s*(.+)", text_context, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""
