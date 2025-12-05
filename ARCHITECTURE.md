# System Architecture & Data Flow

## 1. Core Chat Loop (Sending Message)
## 2. AI Character Gen
## 3. Character Persistence
## 4. Sessions History Sidebar Display
## 5. Session Management
## 6. History List
## 7. Message Restoration

## 1. Core Chat Loop (Sending Message) (REST API)
**Goal:** Real-time messaging with latency control.
**Flow:**
1. [UI] `ChatInterface.tsx` (User Input)
   ↓
2. [Client] `api.ts` (`sendMessage` function)
   ↓ POST /api/chat/send_message/
3. [View] `views.py` (`ChatViewSet`) -> Save User Message to DB
   ↓ (Synchronous Call)
4. [Engine] `tasks.py` (`generate_ai_response`)
   ↓
5. [LLM] **Google Gemini API** (Context Window Injection)
   ↓
6. [DB] `models.py` (Save Assistant Response)
   ↓
7. [UI] Frontend Redux Store Update

---

## 2. AI Character Generation (GraphQL / ETL)
**Goal:** Extract structured persona from unstructured files (novels/PDFs).
**Flow:**
1. [UI] `CreateCharacterForm.tsx` (File Drop)
   ↓ GraphQL Mutation (`GENERATE_DRAFT`)
2. [Schema] `graphql/schema.py`
   ↓
3. [ETL] **Gemini 2.5 Flash** (Prompt: "Extract JSON")
   ↓
4. [Parser] JSON Response -> GraphQL Object
   ↓
5. [UI] Auto-fill React Form Fields

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
























