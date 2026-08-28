# System Architecture & Data Flow

## 1. Core Chat Loop (Sending Message)
## 2. AI Character Gen
## 3. Character Persistence
## 4. Sessions History Sidebar Display
## 5. Session Management
## 6. History List
## 7. Message Restoration & Chat Initialization
## 8. Delete Conversation (REST)
## 9. Delete Character (GraphQL + Validation)

## 1. Core Chat Loop (Sending Message) (REST API)
**Goal:** Real-time messaging with latency control.
**Flow:**
1. [UI] `ChatInterface.tsx` (User Input) (`handleSendMessage` function)
   ↓
2. [Client] `api.ts` (`sendMessage` function)
   ↓ POST /api/chat/send_message/
3. [View] `views.py` (`ChatViewSet`) -> Save User Message to DB
   ├── **Step A: Session Handling**
   │   Check `chat_session_id`. If null -> `ChatSession.objects.create()`
   │   (Initialize with User Persona, World Time, etc.)
   │
   └── **Step B: User Persistence**
       `Message.objects.create(role='user', content=...)`
       **[DB Write 1]** Save User Message to PostgreSQL.
   ↓ (Synchronous Call)
4. [Engine] `tasks.py` (`generate_ai_response`)
   ↓
5. [LLM] **Google Gemini API** (Context Window Injection)
   ↓
6. [DB] `models.py` (Save Assistant Response)
   ↓
7. [Client State] `ChatInterface.tsx` (Handle Response)
   ├── **Update Redux:** `dispatch(addMessage(ai_message))`
   │
   └── **Bind Session:** `setChatSessionId(response.chat_session_id)`
       (Crucial: Transitions state from "New Chat" -> "Existing Session")
   ↓
8. [Cross-Component Sync]
   `onSessionUpdate()` callback
   ↓ Triggers `page.tsx`
   ↓ Refreshes Sidebar History List (Shows new title/timestamp)

---

## 2. AI Character Generation (GraphQL / ETL)
**Goal:** Extract structured persona from unstructured files (novels/PDFs/dialogue scripts).
**Flow:**
1. [UI] `CreateCharacterSimplifiedForm.tsx` (File Drop) -> uploads land via `/api/upload`
   ↓ GraphQL Mutation (`GENERATE_DRAFT`, fileUrls + textContext)
2. [Schema] `graphql/schema.py` (`generateCharacterDraft`)
   ↓ `_resolve_staged_uploads()` — resolve uploaded URLs to in-memory records
   (text content extracted; images carry URL/metadata only)
   ↓
   **Branch A — small batches (< 12 text files): Memory Tools ReAct loop**
   - Files are NOT inlined into the prompt. The model calls `list_memory_files` /
     `read_memory_file` (backed by `StagedUploadMemoryFilesystem`) and reads only
     what it needs. Providers: OpenAI-compatible / Anthropic (Gemini falls back
     to local text reads).
   ↓
   **Branch B — large batches (>= 12 text files): reduce pipeline**
   `chat/character_reduce.py` `run_reduce_pipeline()`:
   1. Tier files by target-character line count (rules, 0 LLM): main/mid/cameo
   2. Batch close-read: main in full, cameo as ±3-line segments
   3. Per-batch LLM -> structured notes (personality evidence / language style /
      behavior / emotion triggers / relationships) with source-file citations
   4. Merge LLM -> profile_summary + dialogue_library + behavior_samples + evolution
   5. `reduce_result_to_draft()` maps the result onto the `PrisMateDraft` schema
   ↓
3. [Parser] JSON Response -> GraphQL Object (`PrisMateDraft`)
   ↓
4. [UI] Auto-fill React Form Fields

---

## 4. Character Persistence (CRUD)
**Goal:** Create and update character definitions.
**Flow:**
1. [UI] `CreateCharacterForm.tsx` (User clicks Save)
   ↓ GraphQL Mutation (`CREATE_CHARACTER` or `UPDATE_CHARACTER`)
2. [Client] `apolloClient.ts`
   ↓ POST /api/graphql/
3. [Schema] `graphql/schema.py` (Mutation Resolvers)
   ↓
4. [ORM] `models.py` (`Character` model)
   ↓
5. [DB] PostgreSQL (Persistent Storage)

---

## 3. Sessions History Sidebar Display
**Goal:** Show All Sessions in History Sidebar.
**Flow:**
1. [Client] `api.ts` (`getChatSessions`)
   ↓ GET /api/sessions/
2. [View] `views.py` -> `serializers.py` (Serialize DB Objects)
   ↓ JSON Response (Snake_Case)
3. [Client] `api.ts` (`normalizeSession`) -> **Data Normalization**
   ↓ CamelCase Data
4. [UI] Sidebar Render

---

## 5. Session Context Management
**Goal:** Persist dynamic settings (World Time, User Persona) for the session.
**Flow:**
1. [UI] `SessionSettings.tsx` (User updates settings)
   ↓
2. [Client] `api.ts` (`updateChatSession`)
   ↓ PATCH /api/sessions/{id}/
3. [View] `views.py` (`ChatSessionViewSet`)
   ↓
4. [Serializer] `serializers.py` (Validation)
   ↓
5. [DB] Update `ChatSession` row in PostgreSQL

---

## 6. History List Interface (Main View)
**Goal:** Display paginated, detailed list of all conversations.
**Flow:**
1. [UI] `page.tsx` (Switch view to 'history_all')
   ↓
2. [Data] Reuses `recentChats` state (Fetched via `api.getChatSessions`)
   ↓
3. [Render] Map through history items
   ↓
4. [Interaction] **Delete Session**
   ↓ `api.deleteChatSession` (DELETE /api/sessions/{id}/)
   ↓ Update State (Remove item from list)

---

## 7.1 Message Restoration (Chat Detail)
**Goal:** Reload previous messages when entering an old session.
**Flow:**
1. [User] Selects a Chat ID
   ↓
2. [UI] `ChatInterface.tsx` (useEffect trigger)
   ↓ Parallel Requests
3. [Client] `api.ts`
   ├── `getMessages(id)` (GET /api/messages/?chat_session_id=X)
   └── `getChatSession(id)` (GET /api/sessions/{id}/)
   ↓
4. [Backend] `views.py` (`MessageViewSet`) filters by Session ID
   ↓
5. [State] **Redux Store** (`setMessages`, `setChatSession`)
   ↓
6. [UI] `ChatWindow.tsx` (Re-renders message bubbles)

---

## 7.2 Chat Initialization
**Goal:** Load character details and restore chat history when entering a room.
**Location:** `frontend/src/components/ChatInterface.tsx`

**Flow A: Character Context (for NEW chat)**
1. [Trigger] `useEffect` (on `characterId` change)
   ↓
2. [Function] **`loadCharacter()`** (Internal Async)
   ↓
3. [Client] `api.ts` (`getCharacter`) -> GET /api/characters/{id}/
   ↓
4. [State] `dispatch(setCharacter)` -> Update Redux

**Flow B: History Restoration (for OLD chat)**
1. [Trigger] `useEffect` (on `initialSessionId` change)
   ↓
2. [Function] **`loadChatHistory()`** (Internal Async)
   ↓
3. [Client] Parallel Fetch via `api.ts`:
   ├── `getMessages(id)` -> GET /api/messages/
   └── `getChatSession(id)` -> GET /api/sessions/{id}/
   ↓
4. [State] `dispatch(setMessages)` & `dispatch(setChatSession)`

---

## 8. Delete Conversation (REST)
**Goal:** Remove specific chat history and cleanup database.
**Flow:**
1. [UI] `page.tsx` (User clicks Trash icon in Sidebar)
   ↓
2. [Client] `api.ts` (`deleteChatSession`)
   ↓ DELETE /api/sessions/{id}/
3. [View] `views.py` (`ChatSessionViewSet`)
   ↓ (Inherited `destroy` method)
4. [DB] PostgreSQL
   **[Cascade Delete]** Removes Session AND all associated Messages automatically.
   ↓
5. [UI] State Update (Filter out item from `recentChats` list)

---

## 9. Delete Character (GraphQL + Validation)
**Goal:** Safely remove a character while preserving data integrity.
**Flow:**
1. [UI] `CharacterGallery.tsx` (User clicks Delete)
   ↓ GraphQL Mutation (`DELETE_CHARACTER`)
2. [Schema] `graphql/schema.py` (`delete_character` resolver)
   ↓
   **[Validation Check]**
   `if character.chat_sessions.exists(): return False`
   *(Prevents deleting characters that have active history)*
   **Referential Integrity**
   ↓
3. [DB] PostgreSQL (Delete Row)
   ↓
4. [UI] Refetch List / Remove Card


## 10. Event-Sourced Chat History & Compaction (v0.1.4)

**Goal:** Solve context-window overflow by making conversation history an
append-only event log, deriving the model-facing prompt from it, and
compacting old events with an LLM summary.

### Core Principle
The `Message` table is no longer the source of truth. The source of truth is
the `ChatEvent` table — an append-only log of every conversation event.
`Message` rows are a **materialized projection** of that log (write-through on
every append, rebuildable from scratch with
`python manage.py rebuild_message_projection`).

### Event Vocabulary
| Event Type | Payload | Produces Message Row? |
|---|---|---|
| `session/created` | `{origin, title}` | No |
| `user/message` | `{content, attachments: […]}` | Yes |
| `assistant/message` | `{content, thinking, tool_calls, token_usage, research_payload}` | Yes |
| `compaction/summary` | `{summary, shadowed_start_seq, shadowed_end_seq, shadowed_count, tokens_freed}` | No |

`ChatSession` metadata (title, origin, `is_private_mode`, `is_title_manual`,
`last_response_latency_ms`) stays in the `ChatSession` table — it is *session
header state*, not a conversation event (deepseek-harness SessionHeader
principle).

### Write Path
1. `views.py:_prepare_chat_turn` → `EventStore.append('user/message', payload)`
   → projection creates the `Message` + `MessageAttachment` rows.
2. `tasks.py:_finalize_ai_response` → `EventStore.append('assistant/message', payload)`
   → projection creates the `Message` row.

### Read Path (Model Prompt)
`tasks.py:_build_provider_messages` → `EventStore.derive_messages(session, compacted=True)`:
- Returns `MessageView` dataclasses, duck-typed for the existing prompt builders.
- Events shadowed by `compaction/summary` events are skipped; the summary
  pseudo-message (`<compacted-summary>…</compacted-summary>`, user role)
  replaces them in place.
- Adjacent same-role messages are merged to prevent alternation conflicts.
- A fallback keeps sessions that still have `Message` rows without an event log
  (pre-backfill data) working via the projection.

### UI Read Path (Unchanged)
`GET /messages` → `MessageSerializer` from the `Message` projection (full
history — compaction never hides data from the UI).

### Compaction
**Trigger:** after every assistant reply, `_maybe_dispatch_compaction()`
estimates total history tokens; if they cross `threshold_ratio × context_window`
(default 70%), the Celery task `compact_session_history` runs.

**Task logic** (`events.compaction.select_shadow_range`):
1. Identify *active events* (those not yet shadowed by an earlier compaction).
2. If active tokens ≥ `min_history_tokens` (8k) and above the threshold:
   - Retain the newest `retain_tokens` worth of history (default 30% of
     context_window, clamped by `min_retain_tokens`).
   - Everything older becomes the *shadow range*.
   - The retained tail is trimmed to start with an assistant message so the
     user-role summary never creates a user+user adjacency conflict.
3. Generate a summary via LLM (reuses `_generate_text`; prompt in
   `events.compaction.SUMMARY_SYSTEM`).
4. Append `compaction/summary` event.

**Full history is preserved** in the event log and the Message projection —
only the derived model prompt is compacted.

### Key Modules
| Module | Role |
|---|---|
| `chat/events/types.py` | Event payload builders |
| `chat/events/store.py` | `EventStore` (append / load / derive_messages) + `MessageView` + token estimation |
| `chat/events/projection.py` | Write-through projection: Event → Message / MessageAttachment |
| `chat/events/compaction.py` | Range selection + summary-prompt builder (pure logic) |
| `chat/management/commands/rebuild_message_projection.py` | Rebuild Message rows from events (`--session <id> / --all / --check`) |






















