# Agent Strategy: Self-Build in-Stack, DSH on the Side

> Status: decision record (2026-08). Scope: PrisMate's agent capabilities beyond
> the existing tool loop. Does **not** cover new features' UI/UX, only the
> engine + integration strategy.

## TL;DR

- **Do not** rebuild PrisMate on DSH (DeepSeek Harness). DSH is a TypeScript,
  developer-preview plugin host ("Everything is a plugin") whose README itself
  warns of compatibility-breaking changes; adopting it as the core would mean
  rewriting the entire existing Django/Python backend for an unstable runtime.
- **Do** extend the agent capability PrisMate already has (OpenAI-compatible
  tool loop) with domain-specific tools, in-stack, in Python.
- **Local file / code execution is already solved** — Genie server is the
  precedent. Generalize it from "TTS engine sidecar" to "local tool executor"
  rather than inventing a desktop app or relying on a plugin ecosystem.
- Keep a thin tool boundary so a DSH sidecar can be adopted **later, with
  evidence**, if orchestration needs outgrow the in-stack loop.

## Background / the question

A popular vision (e.g. the "ElecKoi" pitch) argues SillyTavern's accumulated
plugin/preset bloat is unfixable and that the next generation should be built
on an agent framework — specifically DSH — where the user talks, and the AI
creates/edits character cards end-to-end, plus imports other authors'
workflows.

The open questions were: if PrisMate currently has no agent capability, should
it (a) be discarded and rebuilt as a DSH plugin/app, (b) integrate DSH as a
sidecar engine, or (c) build the same capability in its own stack?

## What PrisMate already has (facts, not plans)

1. **A full multi-round tool loop.** `backend/chat/tasks.py` runs an
   OpenAI-compatible function-calling loop:
   `_generate_openai_compatible_response` (multi-round loop, tools,
   tool_choice=auto), `_execute_local_memory_tool`, retry-without-tools
   fallback (`_should_retry_without_tools`), cross-round token usage
   aggregation, and event sink for streaming tool/thinking events.
   Tool call records persist in `Message.tool_calls` (`backend/chat/models.py`).
   Tools today: `list_memory_files`, `read_memory_file`.
2. **AI character generation, tool-driven, not inlined.** Uploaded character
   files are stored as knowledge assets (`CharacterKnowledgeAsset`); the
   model browses them on demand instead of the contents being pasted into the
   prompt. Large file sets run a map-reduce pipeline
   (`backend/chat/character_reduce.py`: tier by screen time → batch close-read
   → structured notes with citations → merged `PrisMateDraft`). Entry point:
   `generate_character_draft` GraphQL mutation
   (`backend/chat/graphql/schema.py:477`).
3. **Field-level AI draft UX already exists.** The frontend form
   (`CreateCharacterSimplifiedForm`) tracks which fields AI filled vs. the user
   edited (`aiFilledFields` / `aiEditedFields`), with highlight + 30s undo
   window. This is the diff-confirmation primitive needed for "AI 改卡".
4. **A local sidecar precedent: Genie server.** `backend/scripts/genie_server.py`
   is a FastAPI process bound to `127.0.0.1:8050` (`TTS_GENIE_URL`), with ONNX
   model dirs and GPU compute on the user's machine, called by Django over
   HTTP. It is **not** a plugin of anything — it responds only to PrisMate's
   own backend.

## Decision 1: self-build the agent layer, in-stack

**Rationale.**

- The agent surface a role-play app needs is small: ~5 tools + a loop (read
  memory, write memory, search, read knowledge files, create/edit character).
  A general agent framework is not required; the hard part (the loop) is
  already written.
- Multi-provider support (OpenAI-compatible + Gemini, per-user keys) is a
  differentiator. DSH is DeepSeek-first and runs as a local Node harness; it
  does not fit PrisMate's hosted, per-user-key, multi-provider model.
- PrisMate is already the "做减法" fresh start the manifesto advocates for.
  Rebuilding on DSH would discard working, mostly-tested functionality
  (memory, TTS pipeline, reduce pipeline) and re-encounter the exact same
  integration bugs in a new language + unstable framework.

**Scope guardrails.**

- Build **only** what role-play needs: multi-step planning around existing
  tools, retries, budget control. No plugin system, no workflow-import format,
  no multi-agent orchestrator, no tool marketplace — defer those until a real
  user need exists.
- Keep the tool boundary thin (`get_memory_crud_tool_specs` /
  `_execute_local_memory_tool`). This is the seam where a DSH sidecar could
  plug in later.

**When to reconsider DSH (adoption triggers).** Only if either becomes true:

1. Needed orchestration exceeds "tool loop + a few planning steps" (complex
   multi-agent collaboration, importing third-party workflow ecosystems), or
2. Building the same thing in-stack costs more maintenance than the single
   point of failure DSH introduces.

## Decision 2: dialogue-driven card creation ("说一句话就建卡")

The concrete goal: in chat, tell the character "create a new character for
me", and behind the scenes the tool pipeline really creates it.

**What's missing is wiring, not systems:**

- Register two new tools on the existing loop:
  - `create_character(text_context, source_files?)` → returns draft JSON
    (reuse `generate_character_draft` + reduce pipeline)
  - `update_character(character_id, change_description)` → returns diff for
    confirmation
- **Confirmation gate for all mutations.** These tools write to the database;
  unlike silent memory writes, the model must propose, the user must confirm
  in the UI ("AI proposes creating 米娅 — run?"), then execution happens.
  First line of defense against hallucinated data writes.
- **Tool ownership: system layer, not the character.** The character keeps
  role-playing; an invisible session-level "director" holds the tools and
  executes on the user's behalf, so the character never starts editing her own
  settings mid-scene. The existing prompt layering
  (`_build_character_reference_message`, prompt_context) already supports
  this: add one layer for "operator that may declare tool proposals".
- **In-scenario material.** Inputs can come from the conversation itself
  (the user described a new character) or from uploaded knowledge
  assets/memory.

Minimal viable slice: `create_character` + confirmation gate + confirm UI.
If that end-to-end slice works, it also proves the tool loop, streaming,
pipeline, and frontend event chain are all alive.

## Decision 3: local files & browser automation — generalize Genie, don't build a desktop app

The appeal of a desktop (DSH/ZCode) is **running where the user's files and
browser are**, not the desktop form factor. PrisMate already has a local
process: Genie server. Generalize that pattern into a **local tool executor**
(语义上 "本地伴侣", internal name: companion):

- Runs on the user's machine (`127.0.0.1:<port>`), exposes HTTP endpoints to
  the backend: read folder, list files, run a script, drive a local browser.
- Owned by PrisMate — it answers only to the Django backend. Not a plugin for
  DSH/SillyTavern/ZCode; any of those can be used *inside* the companion only
  if the protocol stays PrisMate's.
- The in-stack agent loop treats companion endpoints as just another set of
  tools; the confirmation gate must cover every high-privilege operation
  (path authorization via user-picked folder, per-command confirm dialog) —
  same trust model as DSH/ZCode's workspace trust + command approval.

**Non-hosted reality check (why not just do it in the backend):** when PrisMate
is self-hosted on the user's machine, the backend itself has disk/shell access
and no companion is needed (a `browse_local_folder` tool is ~10 lines + a
folder-path settings page). When hosted, the user's disk and browser login
state are physically elsewhere — only a local process can reach them. Design
for both: tools exist regardless; the executor is backend-local (self-hosted)
or companion (hosted).

**Mapping the three wants:**

| Want | Hosted (non-self-hosted) | Self-hosted | Needs companion? |
|---|---|---|---|
| Character browses local folder | companion reads it | backend reads it | No — Genie generalization |
| Run local scripts / code | companion runs it (gate: confirm) | backend runs it | No — same as above |
| B station: watch video / comment | companion drive a real logged-in browser | same | Yes (new capability) |

**B station / browser automation specifics.** This is Playwright-class browser
automation, orthogonal to desktop or plugin form. The one unavoidable
constraint: B station requires the user's logged-in state, so *any* solution
needs a local browser with the user's login — either the companion embeds a
managed browser (auth flow: user logs in once), or the user exports cookies
(brittle). Hard rules: watch first (no external effect, feeds the character
video/commentary material), commenting is publish-outward and must stay behind
the confirmation gate, and platform risk control (automated commenting can get
the account rate-limited/banned) means it should not ship before the basic
chain works.

## Recommended build order

1. **Prove the chain end-to-end** (the stated current blocker): upload files →
   AI character generation → chat streaming → a single message flowing through
   the tool loop with tools shown in the UI. This validates the spine that
   everything else sits on.
2. **Dialogue-driven card creation slice**: `create_character` tool +
   confirmation gate + confirm UI. Reuses Decision 2's wiring; doubles as the
   end-to-end verification.
3. **Local tools**: `browse_local_folder` (self-hosted backend path first;
   companion when/if hosted becomes the deployment mode).
4. **Browser automation**: watch-only, then commenting behind the gate.
5. **Re-evaluate DSH** only after 1-2 are working, with measurable comparison
   (same scenarios through in-stack loop vs DSH, comparing quality/tokens/
   latency). Framework-independent knowledge building (公开研究课题、标准沉淀)
   can start anytime — it needs no framework.

## Rejected options (recorded so they're not re-litigated)

- **Rebuild as DSH plugin/app.** Rejected: throws away 45k LOC + working
  functionality to adopt a preview framework promising breaking changes;
  PrisMate is not SillyTavern with inherited debt, it is already the fresh
  start the manifesto argues for. TypeScript/Node runtime additionally
  conflicts with Python backend, Celery, pg/Redis and per-user multi-provider
  design.
- **DSH as sidecar engine now.** Rejected for now: developer preview with
  explicit breaking-change warnings; two runtimes force an HTTP bridge for
  every tool that touches Django ORM; its differential value is precisely the
  plugin ecosystem we don't yet have a need for; no working baseline exists to
  measure against. Adoption is staged behind the triggers in Decision 1.
- **Build a full desktop app.** Rejected (for now): the need is local resource
  access, not a desktop shell. A desktop launcher (Tauri/Electron around the
  existing Next.js frontend + bundled companion) remains a later, cheap option
  — the path stays open, choosing Web now doesn't close it.
