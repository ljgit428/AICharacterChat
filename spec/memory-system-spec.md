# Memory System Spec — Long-Term Memory via Celery

> Status: **Spec only — no code changes yet.** This document is the
> authoritative reference for the upcoming implementation. Any
> non-trivial deviation must revise this doc first.

> **Naming convention.** Backend identifiers in this spec follow
> [`Miso2233/SonettoHere`](https://github.com/Miso2233/SonettoHere) so
> future maintainers can jump between the two codebases without
> translating the domain terms. Specifically:
>
> | SonettoHere | This spec | Notes |
> |---|---|---|
> | `memory/narrative.py` | `backend/chat/memory/` (new package) | "narrative" = the rendered text of all entries; the file that the AI consumes at session start. |
> | `LongTermMemoryInterface` | `celery_task sync_long_term_memory` + Django-side `MemoryManager` helper module | Mirror of send_history → `.delay()` and `_consumer` → the worker body. |
> | `MemoryManager` | `backend/chat/memory/manager.py:MemoryManager` | Wraps DB read/write/CRUD for entries. |
> | `MemoryItem` | `CharacterMemoryItem` | A single entry row. (Prefixed `Character` to avoid Django app-name collisions with the user model's `bio`/`preferred_name` and to make the relation to `Character` explicit.) |
> | `memory.yaml` | virtual file `wiki/memory.md` in the existing MemoryExplorer | Identical role: long-term memory file rendered to the AI in the system prompt. |
> | `create_memory`, `read_memories`, `update_memory`, `delete_memory`, `merge_memories` | The Celery worker's tool specs | Adopted verbatim. |
> | `theme` | `section` in our schema | Renamed to `section` because `theme` collides with the `theme/index.ts` UI tokens. Concept is the same. |
> | `narrative` (text blob) | "long-term memory" / "记忆叙事" in copy | Used loosely for the formatted prose that the prompt consumes. |
>
> The intentional departures (`CharacterMemoryItem`, `theme → section`)
> are called out in §4 and §6.

## 1. Background and Inspiration

### 1.1 Reference implementation: SonettoHere

[`Miso2233/SonettoHere`](https://github.com/Miso2233/SonettoHere)
implements a **per-turn, async-queued long-term memory** model with
four moving parts:

1. **`memory/narrative.py → LongTermMemoryInterface`** holds an
   `asyncio.Queue`. After every AI turn the chat pipeline calls
   `ltm.send_history(turn_messages, session_id, turn_id)` to enqueue.
2. A single background coroutine (`_consumer`) drains the queue and,
   for each turn, spins up a **separate ReAct agent**
   (`create_react_agent(model=llm, tools=crud_tools)`) with five CRUD
   tools: `create_memory`, `read_memories`, `update_memory`,
   `delete_memory`, `merge_memories`.
3. State is persisted in a single YAML file,
   `config/personas/memory.yaml`, as
   `{id: {description, theme, history: [...]}}`. Each entry carries an
   inline JSON history of past descriptions.
4. CRUD events are pushed over WebSocket to the frontend in real time
   via `MemoryToolCallback`.

The system prompt is built from this file once per session; the
section is injected as `## 我对用户的记忆` (the memory narrator's
narrative of the AI's memory of them).

### 1.2 User's own design vision (`memory_design.txt`)

The repo contains an aspirational hierarchical design (Constitution,
Persona, Relationship, User Model, Episodic, Knowledge Base,
Reflection, Working Memory, Research) with patch-based updates, lock
flags, candidate updates, and a separate research-evidence layer.
That document is a design dream, not a working system.

### 1.3 What was tried and abandoned

The repo evidence shows:

- Migration `0008` added `ChatSession.memory_summary`, `pinned_memory`,
  `knowledge_base`. Migration `0009` added
  `character_growth_summary`, `knowledge_updates_summary`,
  `user_preferences_summary`. Migration `0010` introduced
  `SoulDocument` / `SoulPatch` (proposed/applied/rejected) — a
  patch-lifecycle model.
- Migration `0018` removed `Character.first_message` and
  `knowledge_base`. Migration `0020` deleted `SoulDocument` and
  `SoulPatch`. Migration `0022` stripped every session-level memory
  summary field. The codebase clearly walked away from per-session
  summaries and from the proposed/applied patch lifecycle.

This spec respects that history: one durable **per-character**
memory anchor (no session-level summary fields), no patch lifecycle,
but with **per-entry inline history** so reversibility still exists.

### 1.4 What already exists in AICharacterChat

- `Celery 5.5.3` on Redis is configured and `autodiscover_tasks`, but
  the chat flow calls `tasks.generate_ai_response(...)` and
  `tasks.update_session_title(...)` **synchronously in-process**
  (`backend/chat/views.py:ChatViewSet.send_message`, `stream_message`).
  So the broker is live; we just need to `.delay(...)` for our new
  task.
- `backend/chat/soul.py` exposes a **read-only Memory Explorer VFS**
  with three layers: `schema/`, `wiki/`, `raw/`. The `wiki/` layer is
  reserved for "curated long-term knowledge and growing summaries"
  but currently **renders nothing** — there is no writer. This spec
  turns it into the user-facing surface of the new memory system by
  synthesising `wiki/memory.md` from the new DB rows.
- `backend/chat/models.py:UserProfile` already carries
  `allow_long_term_memory`, `allow_preference_inference`,
  `allow_research_profile_updates`, `blocked_topics` — perfect gating
  primitives.
- `Message.research_payload` already exists, so when the agent's
  system prompt sees what was searched in a turn, the memory task has
  that data available too.
- The frontend's `frontend/src/components/SoulPanel.tsx` (the
  "soul/memory" sidebar) exists but we have agreed it's a poor name —
  this spec **deletes it from the chat screen entirely** and moves
  the wiki view to a dedicated full-page route. The legacy component
  file is renamed `KnowledgeAssetsPanel.tsx` and demoted to a thin
  file-list under the new `/memory` page.
- The entire data flow is GraphQL + REST + Strawberry + DRF, all of
  which plays well with Celery tasks that take Python object IDs.
- The README is acknowledged as **outdated and too long** and needs
  a refresh alongside this work.

## 2. Goals & Non-Goals

### 2.1 Goals

1. Long-term memory is **per-character** (the AI's evolving impression
   of *this user *when talking to *this character*). Two characters
   you talk to can have different impressions, mirroring SonettoHere
   (each character has its own `personas/memory.yaml`).
2. Memory is **written automatically after every AI turn** by a Celery
   worker (the trigger is the AI reply — same cadence as a chat reply).
3. Updates go through **structured CRUD tools** the worker exposes
   against a Django-managed DB table, mirroring SonettoHere's ReAct
   pattern but pulled out of the request loop. Tool names match
   SonettoHere byte-for-byte.
4. Each entry keeps an **inline JSON history** of past descriptions
   (SonettoHere style — chose in Round 3).
5. The Memory Explorer exposes memory as a single virtual file
   `wiki/memory.md` per character (Round 3, SonettoHere parity with
   `memory.yaml`).
6. CRUD events stream back to the chat UI in real time via the
   existing `/api/chat/stream_message` SSE pipe (Round 3, modelled on
   SonettoHeres `MemoryToolCallback`).
7. UI **keeps the existing sidebar `SoulPanel`** as-is (the
   file lives at `frontend/src/components/SoulPanel.tsx`). On top of
   it we **add** a dedicated full-page **Memory Browser** page at
   `/memory` and a small inline `MemoryPanel.tsx` widget that surfaces
   the freshly-written `wiki/memory.md` near the chat composer. The
   sidebar is not renamed, not removed, and not changed in this PR.
8. **README gets a refresh** alongside this work: outdated sections
   pruned, replaced with accurate architecture; a new "Long-Term
   Memory" section documents the new subsystem and lists the
   *deferred / harder* memory layers from this spec so future
   contributors know they were considered.

### 2.2 Non-Goals (a.k.a. what is *not* in this PR)

Only the **User Model** (i.e. SonettoHeres `memory.yaml`, our
`wiki/memory.md`) layer is automated by this work. The other layers
from `memory_design.txt` are **deliberately out of scope** and
**their deleted remnants are expunged from code**:

| Layer | Status |
|-------|--------|
| **User Model / `memory.yaml` (per-character)** | ✅ Built |
| **Constitution** | ❌ Not automated. Lives in `Character.avatar_url`/`description`/`personality`/etc. User-only writes. |
| **Persona** | ❌ Same as above. User-defined only. Maps to SonettoHeres `SOUL.md` if you extend later. |
| **Relationship** | ❌ Documented in README as a future expansion. Not code. |
| **Episodic memory / session summary** | ❌ Removed. Per-turn transcripts already live in `ChatSession.messages` so we don't need a duplicate summary field. |
| **Knowledge Base** | ❌ Already handled by `CharacterKnowledgeAsset` (round 3 answered *keep wiki folder name but store the user model in it as a single markdown blob*; KB files remain under `raw/character_setup/uploads` and are not affected). |
| **Reflection** | ❌ Documented in README. No code. |
| **Working Memory** | ❌ Already handled by the existing `_build_stream_memory_prefetch` and `RETRIEVED MEMORY` section; no new model required. |
| **Research evidence** | ❌ Documented in README. Search results still land on `Message.research_payload`. The ReAct agent can optionally treat them as scratch input but doesn't *write* them into long-term storage. |

The README gets a "Roadmap (memory)" subsection listing each ❌
layer with a one-paragraph rationale, so future contributors don't
restart the patch-lifecycle work the 0008-0022 migration arc already
burned down.

## 3. Architecture Overview

```
┌──────────────┐    POST /api/chat/send_message┐
│  Chat UI     ├──────────────────────────────►┤ views.send_message
└──────────────┘                                │ (Celery-aware)
                                                ▼
                                  ┌─────────────────────────┐
                                  │ tasks.generate_ai    │
                                  │ _response(...) (sync) │
                                  └────┬────────┬─────────┘
                            saves         │        │
                            AI reply      ▼        ▼
                                  ┌────────────┐  ┌──────────────────────────┐
                                  │ Message    │  │ tasks.sync_long_term_    │
                                  │ + research │  │ memory.delay(            │
                                  │ payload    │  │   message_id,            │
                                  └────────────┘  │   chat_session_id,       │
                                                   │   character_id)          │
                                                   └─────┬────────────────────┘
                                                         │  enqueue
                                                         ▼
                     ┌───────────────────────────────────────────────────┐
                     │ Celery worker: sync_long_term_memory(             │
                     │   message_id, chat_session_id, character_id)       │
                     │   1. Profile gate                                  │
                     │      (allow_long_term_memory? private_mode?)      │
                     │   2. Build prompt (current items + new turn)      │
                     │   3. Call LLM with 5 CRUD tool specs              │
                     │   4. Tool impls → atomic DB writes                 │
                     │   5. Publish SSE events per CRUD                  │
                     │   6. Inline history ties each update               │
                     └────────────┬───────────────┬───────────────────────┘
                                  ▼               ▼
                     ┌────────────────────────┐  ┌─────────────────────┐
                     │ CharacterMemoryItem    │  │ SSE channel         │
                     │ (DB table; manager.py  │  │ /memory_update      │
                     │ wraps read/write/CRUD) │  │  events into        │
                     │   + items compose      │  │  stream_message     │
                     │     wiki/memory.md     │  └────────┬────────────┘
                     └─────────┬──────────────┘           │
                               ▼                          ▼
                     ┌────────────────────────┐  ┌─────────────────────┐
                     │ /memory page renders   │  │ Chat window shows  │
                     │ sections + entries     │  │ small "记忆已更新" │
                     │ (replaces SoulPanel    │  │ toast/badge        │
                     │ sidebar)               │  └─────────────────────┘
                     └────────────────────────┘
```

**Key points:**

- Memory write happens **off the user's request path** (Celery worker,
  not the chat view). Chat latency is unchanged.
- **One Celery task per AI turn**, with a configurable rate limit and
  per-character lock to avoid racing writes. SonettoHere serializes
  YAML with `portalocker`; we use
  `Character.objects.select_for_update().get(id=character_id)` and
  wrap the per-task transactions in `transaction.atomic()`.
- The CRUD tools are *declared* as OpenAI-compatible function specs;
  the **worker's local tool implementations** write straight to
  PostgreSQL via `MemoryManager` (the SonettoHere-named wrapper).
  Gemini path falls back to plain-text + `_extract_json_object`
  (already implemented in `tasks.py`).
- A per-character "current state" snapshot is composed on-the-fly from
  the `CharacterMemoryItem` rows and served through
  `soul.list_memory_explorer_path` / `soul.read_memory_explorer_file`
  as the virtual file `wiki/memory.md`. **The DB stays the only
  source of truth**; the file is a view, not a write target.
- The same snapshot is injected into the system prompt as a
  `[LONG-TERM MEMORY]` section at session start and bumped into the
  character setup for warm reloads between turns. This is our
  equivalent of SonettoHeres `get_system_prompt_parts()` writing
  `## 我对用户的记忆` + `get_narrative()`.

## 4. Data Model

### 4.1 New: `CharacterMemoryItem`

(Django model name kept prefixed to avoid collisions with other
`Memory*` symbols.)

```
CharacterMemoryItem
├── id            BigAutoField(pk)
├── character     FK(Character, on_delete=CASCADE, related_name='memory_items')
├── short_id      CharField(8 chars, unique with character)  # 4-byte hex
├── section       CharField(64, db_index=True)              # free-form 1-4字 (zh) or 1-4 words (en). (SonettoHeres `theme`.)
├── description   TextField                                 # current ≤ 200 char limit (75 中文字符 ceiling, denormalized into 200 Latin chars)
├── description_history JSONField(default=list)              # [{old_desc, new_desc, reason, old_section, new_section?, old_time, new_time}]
├── created_at    DateTimeField(auto_now_add=True)
├── updated_at    DateTimeField(auto_now=True)

Meta:
  unique_together = [(character, short_id)]
  index = [(character, section), (character, updated_at)]
```

Notes:

- `section` is **free-form** (Round 3 answered *和SonettoHere一样*,
  which means the model picks and reuses short section names like
  身份, 工作, 品味). Maps onto SonettoHeres `MemoryItem.theme`.
- `description_history` keeps the inline **SonettoHere-style**
  history (the YAML records `history: []` on every `MemoryItem`). UI
  can show "current / v3 → v2 → v1" drawer per entry.
- A second migration creates a unique constraint
  `(character, short_id)` so per-entry updates can't clash.

### 4.2 New: `MemoryAuditLog` (lightweight, sidekick)

```
MemoryAuditLog
├── id            BigAutoField(pk)
├── character     FK(Character, on_delete=CASCADE, related_name='memory_audit_log')
├── chat_session  FK(ChatSession, blank=True, null=True, on_delete=SET_NULL)
├── message       FK(Message, blank=True, null=True, on_delete=SET_NULL)
├── action        CharField(choices=create|update|delete|merge)
├── entry_short_id  CharField(8, blank=True)
├── before_description  TextField(blank=True)
├── after_description   TextField(blank=True)
├── reason        TextField(blank=True)
├── source        CharField(choices=celery_worker|user_edit)
├── created_at    DateTimeField(auto_now_add=True)
```

Notes:

- Append-only. Different from `description_history` (which lives *inside*
  each entry) because it is the cross-entry activity log read by the
  "Activity" tab on the `/memory` page.
- Captures the last-write-wins audit for the *Memory Browser* UI's
  timeline view.
- Compatible with deletion: entries gone but the audit log keeps the
  rationale.

### 4.3 New column on `ChatSession` (private mode only)

```
ChatSession
└── is_private_mode  BooleanField(default=False)   # SonettoHere parity
```

Per-session override on top of the long-term memory floor
(`UserProfile.allow_long_term_memory`). The chat-session flag is the
override; the floor is global.

### 4.4 Tables / fields removed

Anything that still references the old schema must be **deleted**:

- `_draft` columns on models that were never applied are gone
  (`ChatSession.memory_summary`, `pinned_memory`,
  `character_growth_summary`, `knowledge_updates_summary`,
  `user_preferences_summary`, `additional_context`,
  `enable_web_search`, `model_config`, `output_language`,
  `user_persona`, `world_time`).
- The orphaned helper dict `tasks.MEMORY_DEFAULTS` (formerly named
  `SOUL_DOCUMENT_DEFAULTS` in
  `backend/chat/tasks.py` lines 67-79) — the new system uses the
  `MemoryManager` helpers instead.
- `CharacterKnowledgeAsset`'s references in `wiki/` — `wiki/` becomes
  "long-term memory only". Existing `CharacterKnowledgeAsset` rows
  render under `raw/character_setup/uploads` (already in `builder` in
  `soul.py`), which is unchanged.
- Stragglers found in `backend/chat/constants.py` lines 12-16
  (`world_time`, `user_persona`, `enable_web_search`,
  `additional_context`) and any references from `views.py`,
  `tasks.py`, `tests.py`. Code-search already turned up:
  - `tasks.py:67` — `MEMORY_DEFAULTS['memory_summary']` placeholder
    strings used by the unused `_resolve_character_memory_section`.
  - `constants.py:DEFAULT_CHAT_SESSION_SETTINGS` keys.
  - `frontend/src/i18n/zh-CN.ts:365` and
    `frontend/src/i18n/en-US.ts:376` — `failedToSaveSoulDocument`
    labels never wired to a real endpoint.
  - `backend/chat/tasks.py:_resolve_character_memory_section` and
    `_resolve_user_model_section` (depend on dead fields).
  All get removed this PR.

A grep pass is documented in §11. The actual deletion happens in the
implementation PR, not in this spec.

## 5. Celery Task Pipeline

### 5.1 Single new task: `sync_long_term_memory`

(Equivalent to SonettoHeres `LongTermMemoryInterface.send_history()` +
the `_consumer` body rolled into one Celery task per turn. The asyncio
queue collapses because Celery broker = Redis.)

```python
@shared_task(
    bind=True,
    autoretry_for=(HTTPError, Timeout),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
    rate_limit="30/m",      # one per 2s baseline; tune later
)
def sync_long_term_memory(self, message_id, chat_session_id, character_id):
    # 1. Load + lock the character; mirror SonettoHer's portalocker via select_for_update
    character = Character.objects.select_for_update().get(pk=character_id)
    chat_session = ChatSession.objects.get(pk=chat_session_id)
    message = Message.objects.select_related("chat_session").get(pk=message_id)

    # 2. Privacy gating
    profile = UserProfile.get_or_create_for_user(character.created_by)
    if not profile.allow_long_term_memory:
        return {"status": "skipped", "reason": "user_disabled_long_term_memory"}
    if chat_session.is_private_mode:
        return {"status": "skipped", "reason": "private_mode"}

    # 3. Load current items + build prompt (mirrors SonettoHer's _consumer body)
    items = list(
        CharacterMemoryItem.objects
        .filter(character=character)
        .order_by("section", "short_id")
    )
    prompt = _build_memory_extraction_prompt(character, items, message)

    # 4. Run LLM with tool specs (OpenAI-compatible) or JSON parse (Gemini)
    runtime_config = _get_runtime_model_config(chat_session)
    if runtime_config["provider"] == "openai_compatible":
        # Up to 8 tool-call round-trips, mirroring SonettoHer's ReAct loop
        actions = _run_memory_crud_agent(
            runtime_config=runtime_config,
            prompt=prompt,
            character=character,
            max_tool_round_trips=8,
        )
    else:
        actions = _run_memory_crud_agent_gemini(
            runtime_config=runtime_config,
            prompt=prompt,
            character=character,
        )

    # 5. Apply actions transactionally via MemoryManager.write_item(...)
    with transaction.atomic():
        for action in actions:
            _apply_memory_action(character, message, action)

    # 6. Publish SSE events per CRUD (memory_create/update/delete/merge)
    for action in actions:
        _publish_memory_event(chat_session_id, action)

    return {"status": "ok", "actions": len(actions)}
```

### 5.2 Memory CRUD tool specs (OpenAI-compatible path)

Mirroring SonettoHeres 5 tools verbatim:

| Tool | SonettoHere | Here |
|------|--------------|------|
| `create_memory` | ✓ | ✓ |
| `read_memories` | ✓ | ✓ |
| `update_memory` | ✓ | ✓ |
| `delete_memory` | ✓ | ✓ |
| `merge_memories` | ✓ | ✓ |

Plus their parameter/docstring shapes:

| Tool | Parameters | Behavior |
|------|-----------|----------|
| `create_memory` | `content: ≤200 chars`, `section: ≤64 chars` | Insert new `CharacterMemoryItem` with new short_id. Emit `memory_create` SSE. |
| `read_memories` | `section?: str` | Return items — same character, optional section filter. **No DB write.** Returns ID + section + description. |
| `update_memory` | `id: short_id`, `content: ≤200 chars`, `reason: short text` (§ 5.4 + `section`) | If `section` also supplied, rename; else keep. Push old→new onto `description_history`. Emit `memory_update` SSE. |
| `delete_memory` | `id: short_id`, `reason: short text` | Hard delete (recorded in `MemoryAuditLog`). Emit `memory_delete` SSE. |
| `merge_memories` | `id1, id2, content, section, reason` | Merge `id2 → id1`: copy `id2.description_history` into `id1`, then delete `id2`. Length sanity: `len(content) ≤ 200`. Emit `memory_merge` SSE. |

Each tool returns a small, human-readable confirmation string
("已创建 [a3f9] (工作): 用户是一名后端工程师"). The Celery task
collects the structured tool calls (OpenAI path) or parses them out of
the final assistant text (Gemini path) before applying.

### 5.3 Prompt template (system / user split)

Same shape as SonettoHeres `COLD_START_SYSTEM` / `UPDATE_SYSTEM` pair,
with the strict rules adapted for length and locale:

**System:**
1. You are a "memory narrator" (`记忆叙事师`) for the AI character
   `<character.name>`.
2. Decide which items to **create / update / delete / merge** based
   on the new turn's messages and the *current memory state* below.
3. Hard rules:
   - Subjective impressions > objective facts.
   - Long bullet enumerations are forbidden; one fact per item.
   - Each `content` MUST be ≤ 200 visible characters (Chinese counts
     as one character; SonettoHeres 75-char cap maps to ~200 Latin
     chars).
   - Use **third person** (e.g. "用户喜欢...").
   - Use **absolute dates** (`2026-04-23`); never "yesterday / today".
   - Prefer an existing `section`; only mint a new section name when
     the existing ones genuinely don't fit.
   - When the user explicitly corrects something, **delete** the old
     wrong item and **create** a new one.
4. Always call `read_memories` first if any items exist before
   mutating them.
5. Limit churn: do not create an item for every sentence; only
   durable facts the AI should remember weeks from now.

**User:** a small bundle of:

- Pointer: "### CURRENT MEMORY (read-only snapshot)" — list of
  `{short_id, section, description}` rows for the character, sorted by
  section then by short_id.
- Pointer: "### NEW TURN" — the assistant reply that just landed,
  the previous user message, and (optionally) the `research_payload`
  on the assistant message if non-empty.
- Pointer: today's `YYYY-MM-DD` + weekday in UI locale.

### 5.4 Trigger point — where the task gets enqueued

`backend/chat/views.py:ChatViewSet._prepare_chat_turn` returns a
`chat_session`. After `_finalize_ai_response` saves the `Message` and
sets `research_payload`, the view enqueues:

```python
sync_long_term_memory.delay(
    message_id=ai_message.id,
    chat_session_id=chat_session.id,
    character_id=character.id,
)
```

Both the non-streaming `/api/chat/send_message` and the streaming
`/api/chat/stream_message` paths emit the agent's "final done" event
*before* the memory task is enqueued, so the user never waits on
memory.

Race conditions: per-character `select_for_update()` on the worker
side serializes writes. Multiple turns in flight for the same
character will queue in the broker, then process one at a time. This
matches SonettoHer's `portalocker` semantics.

### 5.5 Celery wrapper class — `LongTermMemoryInterface` parity

We expose a thin Python class (not a Celery task, but a
"low-level orchestrator") so future code paths (e.g. a button to
"force a memory sync now") can call into the same glue:

```python
# backend/chat/memory/interface.py
class LongTermMemoryInterface:
    """Thin Python facade mirroring SonettoHer's LongTermMemoryInterface.

    Real scheduling happens via Celery; this class is just the
    Python-side dispatch + structured return shape.
    """

    @staticmethod
    def enqueue(chat_session, message):
        return sync_long_term_memory.delay(
            message_id=message.id,
            chat_session_id=chat_session.id,
            character_id=chat_session.character_id,
        )

    @staticmethod
    def get_narrative(character):
        """SonettoHere-equivalent: render CharacterMemoryItems as
        one paragraph-block for inclusion in the system prompt."""
        return render_memory_narrative(character)

    @staticmethod
    def snapshot(character):
        """Return { sections: [{section, items: [...]}] } similar to
        SonettoHere.get_memories_grouped()."""
        ...
```

`get_narrative` is the Python twin of SonettoHeres
`get_narrative()` that reads `memory.yaml` and formats it for the
prompt (§6.3).

### 5.6 Failure modes / observability

- LLM timeout → Celery retry with backoff (2 attempts).
- Bad JSON / no tool calls → log INFO and exit, no row writes.
- Tool call attempt to write a too-long description → return
  rejection string; the caller (model) is expected to retry with a
  trimmed entry. We do not punish with rate limiting.
- Heartbeat: each task logs `skipped / ok / error` with the action
  count and a hash of the input. Useful for parsing in the README's
  new "Troubleshooting memory" section.

## 6. Memory Explorer Integration (`wiki/memory.md`)

### 6.1 New virtual file shape

The Memory Explorer already accommodates a `wiki/` layer. Add one
helper in `backend/chat/memory/manager.py`:

- `MemoryManager.render_wiki_file(character) -> str` — formats the
  `CharacterMemoryItem` rows into a single markdown block with
  section-grouped headers.
- `list_memory_explorer_path(...)` (in `soul.py`) is updated to
  surface `wiki/memory.md` for the character. (We don't rename
  `wiki/` itself — Round 3 answered *keep wiki folder name*.)

Example rendered content (matches SonettoHere `memory.yaml` semantics
but in markdown for human/renderer consumption):

```
# Long-Term Memory (User Model)

Last updated: 2026-04-23T10:15:00Z

## 身份
- 用户是一名后端工程师，常用 Python + Django。
- 用户常住在北京市海淀区。

## 品味
- 用户喜欢听落日飞车 (Sunset Rollercoaster)。

---
16 entries. 8 sections. Auto-written after every AI turn. Edit in the
/memory page.
```

The file's `kind` is `markdown`, `layer` is `wiki`, `preview_kind`
is `text`, `manageable` is `false` (read-only in any old surfaces
that still load the file — user edits go through the new `/memory`
page). The existing `TextAttachment`/image attachment system does
not change.

The read API surface stays byte-compatible with the existing
`/api/characters/{id}/soul_files` and `/api/characters/{id}/soul_file`
URLs — no frontend regressions.

### 6.2 Read endpoint stays the same

`backend/chat/views.py:CharacterViewSet.soul_file` continues to serve
the file without a code-change. The CTS `MemoryExplorerFile`
returned carries a slightly bigger `read_hint` ("Auto-written by the
memory Celery task after every AI turn. Edit in the /memory page.").

### 6.3 Same path used in the prompt

The memory narrative snapshot is composed via
`LongTermMemoryInterface.get_narrative(character)` (mirror of
SonettoHeres `get_narrative()` from `memory/narrative.py`). The
existing `_build_stream_memory_prefetch` in `backend/chat/tasks.py`
gains a small branch:

```python
narrative = LongTermMemoryInterface.get_narrative(character)
if narrative.strip():
    sections.append(_normalize_prompt_memory_section(
        "Long-Term Memory",
        _truncate_text(narrative, STREAM_MEMORY_SECTION_LIMIT),
    ))
```

The `[LONG-TERM MEMORY]` block is appended just above the existing
`[RETRIEVED MEMORY]` block, mirroring SonettoHier's system-prompt
ordering (AGENTS → SOUL → USER → 我对用户的记忆).

The `memory.yaml` content can also be inspected via the existing
`GET /api/characters/{id}/soul_file?path=wiki/memory.md` endpoint —
the Web UI's file-pane can show its freshly edited state after each
Celery write.

## 7. Live Push Events (SSE)

### 7.1 Bus

We add `MEMORY_UPDATE_PUBSUB = "chat:memory_updates:<chat_session_id>"` on
the existing Redis connection (already used by Celery). The chat stream
generator subscribes to it just before yielding the `done` event, and
unsubscribes at the end of the response.

### 7.2 Wire format

Each `_publish_memory_event(chat_session_id, action)` runs (mirrors
SonettoHere `MemoryToolCallback`):

```python
r = get_redis()
r.publish(channel, json.dumps({
    "type": "memory_update",  # future: memory_create / memory_update / memory_delete / memory_merge
    "session_id": chat_session_id,
    "payload": {
        "short_id": "...",
        "section": "...",
        "action": "create|update|delete|merge",
        "description": "...",   # current value (or last-known for delete)
        "timestamp": "...",
    },
}, ensure_ascii=False))
```

The frontend, while a streaming `/chat/stream_message` is in flight,
forwards these events to the chat taxi as additional `type: "memory_*"`
NDJSON lines next to its `delta`/`session`/`done`. Format compatible
with the existing parse loop in
`frontend/src/utils/api.ts:streamMessage`.

### 7.3 Frontend handling — small toast

A toast-style chip appears in the chat input area near the send
button:

> 🧠 已记住：你喜欢听落日飞车 (Sunset Rollercoaster)。

Auto-dismiss after 5s; clicking it opens the Memory Browser in a new
tab. Implemented in `frontend/src/components/ImmersiveChatWindow.tsx`
via a new `memory` slice on the existing Redux store
(`memoryEvents: MemoryEvent[]`). No changes to Redux Toolkit setup.

## 8. Privacy / Private Mode

### 8.1 Three gates, in order

1. `UserProfile.allow_long_term_memory == False` ⇒ Celery task
   immediately returns `skipped: user_disabled_long_term_memory`.
2. `ChatSession.is_private_mode == True` ⇒ Celery task returns
   `skipped: private_mode`.
3. `UserProfile.blocked_topics` contains a substring of the new turn's
   text ⇒ Celery task returns `skipped: blocked_topic`. (Optional, low
   priority; can defer.)

### 8.2 UI for `is_private_mode`

Add a toggle button next to the chat header in
`ImmersiveChatWindow.tsx`. Toggling issues a `PATCH /api/sessions/{id}`
to update the field. Private-on sessions visually mark the header
"🔒 Private — not saved to long-term memory". No new permission model;
just a per-session setter.

### 8.3 Migration / data hygiene

Existing ChatSession rows default `is_private_mode=False`. No backfill
needed for items since the table is brand-new.

## 9. UI Surface — Rename + Redesign

### 9.1 Additive — sidebar unchanged

We **do not touch the sidebar in this PR**. The existing
`frontend/src/components/SoulPanel.tsx` keeps its current mount
point, props, copy keys, and behavior. Its tree-renderer already
hits the `/api/characters/{id}/soul_files` and
`/api/characters/{id}/soul_file` endpoints, so once the backend
starts emitting `wiki/memory.md`, the sidebar will simply start
displaying real content (Django change only, zero frontend changes
beyond a small "last updated" line if we want one).

New additions ride **on top of** the sidebar:

- **`frontend/src/components/MemoryPanel.tsx`** is **new** and small:
  a one-column read-only mini-view of `wiki/memory.md` rendered inline.
  Mounted as a stacked card near the bottom of the chat composer (or
  beneath the chat scroll area on mobile). It carries an "Open Memory
  Browser" link that goes to the `/memory` page. This is the
  smallest, lowest-risk UI surface that proves the new pipeline is
  producing content end-to-end.
- **`frontend/src/app/memory/page.tsx`** is **new**: the dedicated
  Memory Browser full-page route. Replaces nothing; it is purely
  additive. It owns the section/edit/revert/audit affordances that
  are too rich for a sidebar card.
- The component names follow SonettoHere naming (the artifact is
  `memory`, the wrapper is `MemoryPanel`, the page is `/memory`).
  Existing `Soul*` namespace copy keys survive untouched because
  the sidebar that uses them is unchanged.

### 9.2 New full-page route

Add `frontend/src/app/memory/page.tsx` (and a sidebar/nav entry in
`frontend/src/components/Providers.tsx`).

**Layout:**

```
┌──────────────────────────────────────────────────┐
│  Header:  Long-Term Memory  [per character select]│
│  Subhead: last refreshed · item count             │
├────────────────┬─────────────────────────────────┤
│  Section rail  │  Selected section               │
│  (left ~30%)   │  (right ~70%)                   │
│                │                                 │
│  * 身份 (4)    │  Each item =                    │
│  * 工作 (6)    │    • short_id                    │
│  * 品味 (3)    │    • section                     │
│  * 地点 (2)    │    • description                 │
│  * 瞬间 (1)    │    • inline history drawer       │
│                │      (toggle to reveal)          │
│                │    • edit pencil / revert / del  │
└────────────────┴─────────────────────────────────┘
```

- **Per-character dropdown** drives the underlying `GET /memory?character_id=`.
- **Search box** filters by substring of `description` (client-side
  filter on the list response). No full-text search needed in v1.
- **Auditing tab** at the top right: "Activity log" lists the last 50
  `MemoryAuditLog` rows for the character.
- **Edit affordance**: clicking the pencil on an item opens an inline
  editor. Save → `PATCH /api/characters/{id}/memory/items/{short_id}`
  with the new `description` (and optional `section` rename).
- **Revert affordance**: for items with `description_history.length >
  1`, a "Restore this version" button on each history row triggers
  `PATCH .../revert?history_index=N`.

### 9.3 Wire endpoints

Add these REST endpoints (mirror the rest of the project — `viewsets`,
not GraphQL — since they are CRUDish):

- `GET  /api/characters/{id}/memory` — list items (JSON, paginated).
  SonettoHere prototype reference: `GET /api/memories`.
- `GET  /api/characters/{id}/memory/items/{short_id}` — single item.
- `PATCH /api/characters/{id}/memory/items/{short_id}` — manual edit;
  writes `MemoryAuditLog` row with `source=user_edit`.
- `POST /api/characters/{id}/memory/items/{short_id}/revert` — rewind
  to a `description_history` index; writes audit.
- `DELETE /api/characters/{id}/memory/items/{short_id}` — manual
  delete; writes audit.
- `GET  /api/characters/{id}/memory/audit` — paginated `MemoryAuditLog`
  rows.
- `GET  /api/characters/{id}/memory/narrative` — mirrors SonettoHeres
  `GET /api/memory/narrative`; returns the rendered markdown blob that
  the prompt receives.
  This is the same content as `wiki/memory.md` but exposed as a
  first-class REST endpoint (handy for `/memory` page widgets).
- `DELETE /api/characters/{id}/memory` — wipe *only* the long-term
  memory for a character (one-shot; writes one summary audit row).
  Useful when the user wants to start fresh without deleting the
  character.

Authz: every endpoint is gated by `IsAuthenticated` + owned-by
(`character.created_by == request.user`). Nothing new in the auth
stack.

### 9.4 Cleanup of i18n dead strings

`frontend/src/i18n/zh-CN.ts:365` (`failedToSaveSoulDocument`) and
`en-US.ts:376` are removed if and only if no other component
references them in this PR (grep already confirms they aren't
wired). Same review for any `soul.*` namespaces that turn out to be
orphan.

## 10. README Refresh Plan

The README is currently **outdated and too long** (existing README
still says "Synchronous Execution (Direct Invocation)" and refers to a
Gemini-only setup, which no longer matches reality).

This PR ships:

1. **New "Long-Term Memory" subsection** under Tech Stack → Backend:
   - One-paragraph narrative of the pipeline.
   - One small ASCII diagram (mirror of §3 above).
   - Link to the **new `memory-system-spec.md`** for anyone needing
     depth.
   - SonettoHere parity callout: we mirror SonettoHere's ReAct CRUD
     pattern + LongTermMemoryInterface pattern but use Celery + Django
     instead of asyncio + YAML.
   - Cost-control note: 30 tasks/minute, max-retries=2, retries silent.
2. **"Roadmap (memory)" subsection** listing the ❌ layers from §2.2
   and why they were deferred, so future contributors don't repeat
   the `SoulDocument`/`SoulPatch` lifecycle loop.
3. **Trimmed "Features"** list: drop the obsolete "Real-time chat
   with AI character" / "Character customization" boilerplate that
   hasn't aged well; replace with a tight 3–4 bullet list that names
   the new things the app actually does (per-turn memory, web search,
   multimodal attachments, multilingual UI).
4. **Genuine "Concurrency & Async Strategy" rewrite**: the current
   text says synchronous on purpose to dodge Gemini 429s. We're now
   declaring Celery properly used; explain that the chat path stays
   sync (latency + throttling) but the **memory write path** is
   async (Celery).
5. **Refresh "Project Structure"**: drop the now-incorrect
   `├── chat/├── models.py├── views.py├── tasks.py` minimum; add the
   new dirs (`backend/chat/memory/`, `frontend/src/app/memory`)
   and the `memory-system-spec.md` at repo root.

The README's `QUICK_START.md`, `ARCHITECTURE.md`, and
`memory_design.txt` are **untouched** in this PR.

## 11. Cleanup Pass — Dead Code to Remove

Code-search and grep already pinned the offenders. All of these get
removed in the implementation PR unless explicitly mentioned above:

- **Backend Python:**
  - Rename `SOUL_DOCUMENT_DEFAULTS` → `MEMORY_DEFAULTS` (kept-importable
    alias for one minor version), then **delete it**. The new system
    uses `MemoryManager` helpers.
  - Delete the helpers that depended on it:
    `_resolve_character_memory_section`,
    `_resolve_user_model_section`,
    `_build_character_user_model_fallback`,
    `_build_profile_user_model_fallback`,
    `_is_seeded_character_user_model`,
    `_build_account_runtime_sections` (only the legacy keys inside it).
  - `backend/chat/constants.py` keys: `world_time`, `user_persona`,
    `enable_web_search`, `additional_context`.
  - `backend/chat/views.py` writes that depended on these (none left
    in `serializers.py`, but confirm).
  - `backend/chat/tests.py` references (`self.assertTrue(payload['default_enable_web_search'])`,
    `defaults={'default_enable_web_search': True}`).
  - Removed in migration 0020 already: anything that imports
    `SoulDocument`/`SoulPatch`. Confirm no stragglers.- `frontend/src/i18n/zh-CN.ts:365` `failedToSaveSoulDocument`.
  - `frontend/src/i18n/en-US.ts:376` `failedToSaveSoulDocument`.

(We intentionally **do not rename or remove `SoulPanel.tsx`** here;
the existing sidebar stays so users keep their current workflow. The
next cleanup PR can revisit once the `/memory` page has shipped and
been validated.)

A grep ref-check (one per location) is part of the implementation
PR's acceptance test, not this spec.

## 12. Open Questions for Future PRs (Documented, Not Built)

These were floated during the rounds and deliberately deferred:

1. **Embedding-based retrieval.** SonettoHere hand-loads `memory.yaml`
   into the system prompt at session start. We do the same. Switching
   to RAG-style chunk retrieval (a vector index across all items) is
   a separate PR; we keep the design noting that the `[LONG-TERM
   MEMORY]` block will become a list of **merged with retrieval**
   items, not "all items dumped into the prompt".
2. **Rate limiting per character.** Right now, `rate_limit="30/m"`
   guards us against runaway retries. A per-character token bucket
   would be smarter. Future.
3. **Conflict resolution when an item collides with `UserProfile`.**
   SonettoHere uses the YAML file as ground truth. We compare the
   per-character item's `description` against the user-entered
   `UserProfile.preferred_name` / `UserProfile.bio` at write time; a
   hard conflict writes an audit row but doesn't override the
   UserProfile. Future PR.
4. **Merging items across characters.** The UserProfile field is
   cross-character (one preferred_name); the Long-Term Memory items
   are per-character. SonettoHere effectively does both too
   (USER.md cross-character; memory.yaml per-deployment). If a user
   wants a single "long-term memory" across all their characters,
   that's a future "global wiki/" layer. Future.

## 13. Test Plan

- **Unit tests** for `MemoryManager` Django logic
  (`CharacterMemoryItem.objects.create/update/...`, history push,
  short_id round-trips), SonettoHere-parity via the same
  `manager.py` helpers.
- **Pydantic-free** Celery task tests via `task.apply((args), link=None)`
  bypassing the broker.
- **Prompt snapshot tests**: golden file with the exact prompt string
  for a fixture character + two items.
- **Tool-specs tests**: ensure each OpenAI-tool-spec produced passes
  `MemoryManager.execute_tool(character, tool_name, args)` round-trip.
- **End-to-end**: pick a character, send a turn producing a memory
  write, eyeball: `wiki/memory.md` reflects it; system prompt
  gets a `[LONG-TERM MEMORY]` block; ChatSession shows a memory
  update; Memory Browser page shows the item.
- **Privacy gate**: enabled via `UserProfile.allow_long_term_memory
  = False`, send a turn, assert no `CharacterMemoryItem` rows are
  created.
- **Cleanup**: run grep for `memory_summary`, `pinned_memory`,
  `SoulDocument`, `SoulPatch`, `SoulPanel`, `soul_panel`,
  `failedToSaveSoulDocument` and assert zero hits in the repo after
  the PR.

Frontend smoke relies on the backend integration test suite in
`backend/chat/tests_memory.py` (the Celery `sync_long_term_memory`
happy-path test exercises the same full pipeline that a browser
smoke test would assert on). Browser-driven Playwright smoke was
originally planned under `frontend/e2e` but was removed before
v1.0.2 (see commit on the `v1.0.2` branch); the React UI is
covered by manual testing until a future PR reintroduces a UI
test harness.

## 14. Acceptance Criteria

1. After one full user→assistant exchange, the `wiki/memory.md`
   file is reachable via
   `GET /api/characters/{id}/soul_file?path=wiki/memory.md`
   and contains ≥ 1 sections with ≥ 1 item that quoted from the
   user message.
2. `CharacterMemoryItem` rows have populated `short_id`, `section`,
   `description`, and `description_history` (`[{desc, reason, ...}]`).
3. `tasks.sync_long_term_memory` is enqueued from
   `ChatViewSet._finalize_ai_response_call_site` and **does not
   block** the chat response (p95 streaming latency unchanged).
4. `private_mode=True` ⇒ no new `CharacterMemoryItem` rows; audit
   log contains `skipped: private_mode`.
5. `UserProfile.allow_long_term_memory=False` ⇒ same.
6. Frontend: chat window shows the toast chip after a memory write;
   `/memory` page renders existing items grouped by section and
   supports inline edit + revert.
7. Grep for `SoulDocument|SoulPatch|memory_summary|pinned_memory|character_growth_summary|knowledge_updates_summary|user_preferences_summary|additional_context|user_persona|world_time|SoulPanel|failedToSaveSoulDocument` returns **0 backend** hits and **0 frontend** hits except in test fixtures.
8. README has a new "Long-Term Memory" subsection and a
   "Roadmap (memory)" subsection listing the ❌ layers.
9. The renamed identifiers match SonettoHeres naming
   (`sync_long_term_memory`, `MemoryManager`, `LongTermMemoryInterface`,
   `CharacterMemoryItem`, `wiki/memory.md`, `create_memory` /
   `read_memories` / `update_memory` / `delete_memory` /
   `merge_memories`).

## 15. Appendix — File-by-File Touch Map

| File | Change |
|------|--------|
| `backend/chat/migrations/0025_long_term_memory.py` (new) | New migrations: `CharacterMemoryItem`, `MemoryAuditLog`, `ChatSession.is_private_mode` |
| `backend/chat/models.py` | Add `CharacterMemoryItem`, `MemoryAuditLog`; add `ChatSession.is_private_mode` |
| `backend/chat/memory/manager.py` (new) | `MemoryManager` wrapper (DB CRUD + history + rendering) — SonettoHere namesake |
| `backend/chat/memory/interface.py` (new) | `LongTermMemoryInterface` Python facade |
| `backend/chat/memory/prompts.py` (new) | `build_memory_extraction_prompt` (SonettoHeres `_consumer` body in Python) |
| `backend/chat/tasks.py` | Add `sync_long_term_memory`; remove `_resolve_character_memory_section` and friends; upload `LongTermMemoryInterface.get_narrative(...)` into `_build_stream_memory_prefetch` |
| `backend/chat/views.py` | Add the 8 memory endpoints (`/memory`, `/memory/items/<short_id>`, `/memory/items/<short_id>/revert`, `/memory/audit`, `/memory/narrative`); remove dead imports; emit `sync_long_term_memory.delay(...)` after `_finalize_ai_response` |
| `backend/chat/soul.py` | Add `wiki/memory.md` rendering via `MemoryManager.render_wiki_file(...)`; expose `wiki/memory.md` from `list_memory_explorer_path` |
| `backend/chat/serializers.py` | New serializers for memory endpoints |
| `backend/chat/constants.py` | Drop obsolete `DEFAULT_CHAT_SESSION_SETTINGS` keys |
| `backend/chat/tests.py` | Tests for new endpoints, the Celery task (inline apply), and grep-style cleanup assertions |
| `backend/requirements.txt` | No new deps (Celery + DRF + Redis already there). No `portalocker` — we use `select_for_update`. |
| `frontend/src/types/index.ts` | Add `MemoryItem`, `MemoryAuditRow`, `MemoryEvent`, `MemoryNarrative` types (rename `MemoryExplorerFile.content` reading; do not conflict with the existing `MemoryExplorerFile.content` API contract) |
| `frontend/src/utils/api.ts` | Add API methods for the 8 endpoints + memory SSE listener |
| `frontend/src/store/chatSlice.ts` (or new `memorySlice.ts`) | Add `memoryEvents` slice |
| `frontend/src/components/SoulPanel.tsx` | **No change.** Existing sidebar keeps working; once backend emits `wiki/memory.md` it will display content automatically. |
| `frontend/src/components/MemoryPanel.tsx` (new) | Small inline read-only view of `wiki/memory.md` near chat composer |
| `frontend/src/app/memory/page.tsx` (new) | The dedicated Memory Browser page |
| `frontend/src/components/Providers.tsx` | Add nav entry for `/memory`; route mount |
| `frontend/src/components/ImmersiveChatWindow.tsx` | Subscribe to memory SSE; render toast chip; private-mode toggle |
| `frontend/src/i18n/{zh-CN,en-US}.ts` | Drop `failedToSaveSoulDocument`; add memory-page copy; add `privateMode.*` strings |
| `README.md` | Refresh per §10 |
| `memory-system-spec.md` | This document |

---

**Checklist before moving from spec → code:**
- [ ] The user confirms scope is correct.
- [ ] A code-reviewer-minimax-m3 reviews this PR.
- [ ] At least one round of integration testing on a real backend +
  frontend stack.
- [ ] README + `/memory` page screenshot attached to the PR.
