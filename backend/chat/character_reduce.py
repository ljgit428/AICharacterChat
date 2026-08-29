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
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, List, Optional

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
TIER_MAIN = 30      # 重头: 目标角色台词 >= 30 句
TIER_MID = 5        # 中: 5~29 句；客串: < 5 句
CAME0_WINDOW = 3    # 客串片段: 台词前后各 N 行（保上下文、控 token）
MAIN_WINDOW = 6     # 重头/中档片段: 台词前后各 N 行
BATCH_SIZE = 6      # 每批精读的文件数
MAX_CONCURRENT_BATCHES = 4   # 并发精读批次数：200+ 文件的批次 LLM 调用不再串行
MAX_BATCH_FILE_CHARS = 6000      # 重头/中档单文件正文上限（窗口提取后再兜底截断）
MAX_NO_TARGET_FILE_CHARS = 3000  # 未指定目标名时（全员客串层）单文件正文上限
MERGE_GROUP_SIZE = 10            # 单次合并调用最多吃进的批次笔记数，超出走两级合并
MAX_CITATIONS_PER_BATCH = 6      # 合并输入里每批保留的引用条数
MAX_QUOTE_CHARS = 200            # 合并输入里单条引用的长度上限

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
        return _cameo_segments(content, target, CAME0_WINDOW)
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


def _merge_notes(batch_notes: list, llm_call) -> dict:
    """合并批次笔记。

    223 个文件会产出几十批笔记，一次性塞进单个合并调用会撑爆上下文；
    超过 MERGE_GROUP_SIZE 时先按组部分合并，再对部分结果做最终合并。
    """
    notes = [_trim_note_for_merge(note) for note in batch_notes]
    if len(notes) <= MERGE_GROUP_SIZE:
        return _merge_call(json.dumps({"batches": notes}, ensure_ascii=False), llm_call)

    partials = []
    for index in range(0, len(notes), MERGE_GROUP_SIZE):
        group = notes[index:index + MERGE_GROUP_SIZE]
        payload = json.dumps({"batches": group}, ensure_ascii=False)
        try:
            partials.append(_merge_call(payload, llm_call))
        except Exception:  # noqa: BLE001 - 单组合并失败丢这一组，不让整条管线报废
            continue
    if not partials:
        raise RuntimeError("All partial merge calls failed for the reduce pipeline.")
    final_payload = json.dumps({"batches": partials}, ensure_ascii=False)
    return _merge_call(final_payload, llm_call)


# ---------------------------------------------------------------------------
# 4. 主入口
# ---------------------------------------------------------------------------

def run_reduce_pipeline(
    uploads: List[dict],
    target: str,
    llm_call: Callable[[str, str], str],
    batch_size: int = BATCH_SIZE,
    max_workers: int = MAX_CONCURRENT_BATCHES,
) -> dict:
    """跑完整 reduce 流水线，返回最终档案 dict（可直接映射 PrisMateDraft）。

    批次精读调用相互独立，用线程池并发执行——200+ 文件按 6 个一批要发
    几十次 LLM 调用，串行时总耗时是单次调用 × 批数，这也是前端长时间
    转圈的主因。合并依赖全部批次结果，仍保持串行（必要时两级合并）。
    """
    tiers = _tier_uploads(uploads, target)

    jobs: List[tuple] = []
    for tier in ("main", "mid", "cameo"):
        recs = tiers[tier]
        for i in range(0, len(recs), batch_size):
            jobs.append((tier, recs[i:i + batch_size]))

    if jobs:
        workers = max(1, min(max_workers, len(jobs)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            # pool.map 保序返回，批次笔记顺序与作业顺序一致
            notes_list = list(pool.map(
                lambda job: _produce_batch_notes(job[1], target, job[0], llm_call),
                jobs,
            ))
    else:
        notes_list = []

    batch_notes: List[dict] = []
    for (tier, batch), notes in zip(jobs, notes_list):
        notes["_tier"] = tier
        notes["_files"] = [
            u.get("name") or u.get("file_url") for u in batch
        ]
        batch_notes.append(notes)

    merged = _merge_notes(batch_notes, llm_call)
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
