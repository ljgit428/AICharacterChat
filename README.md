# PrisMate

Role-playing chat app with custom AI personas, per-user API keys, persistent
long-term memory, and a soul/persona system that lets characters grow over time.

## Stack

- **Frontend:** Next.js 15 · React 19 · TypeScript · Tailwind 4 · Redux Toolkit · Apollo Client (GraphQL)
- **Backend:** Django 5.2 · DRF · Strawberry GraphQL · Celery · PostgreSQL · Redis
- **AI:** OpenAI-compatible + Gemini providers (key configured per user in-app)

## Quick Start

Prereqs: Node 18+, Python 3.10+, PostgreSQL, Redis.

```bash
# Redis
docker-compose up -d redis

# Backend
cd backend
python -m venv venv_stable
source venv_stable/Scripts/activate   # PowerShell: .\venv_stable\Scripts\Activate.ps1
cp .env.template .env                # set DATABASE_*, REDIS_URL, SECRET_KEY
pip install -r requirements.txt
python manage.py migrate

# Run API + worker (separate terminals)
# 注意：聊天流式（SSE/NDJSON）依赖 ASGI 实时转发（views.stream_message），
# 用 runserver（WSGI，Django 处理层会把流整体缓冲后一次性发出 → 思考/正文
# 看起来"一股脑全部输出"，v0.1.5 实测），必须用 uvicorn 启动：
python -m uvicorn prismate.asgi:application --host 0.0.0.0 --port 8000
python -m celery -A prismate worker --loglevel=info -c 1

# Frontend
cd ../frontend
cp .env.local.template .env.local    # NEXT_PUBLIC_API_URL=http://localhost:8000/api
npm install
npm run dev                          # http://localhost:3000
```

Sign in → open **Project Settings** → add a model configuration with your API key.

## Features

- Custom character creation (manual form or AI-assisted generation from files)
- **Character reference files** stored in exactly one place (`CharacterKnowledgeAsset`);
  the legacy `Character.file` mirror is no longer written
- **Memory Tools for draft generation** — uploaded files are never inlined into the
  prompt; the model browses/reads them on demand via `list_memory_files` /
  `read_memory_file` (OpenAI-compatible / Anthropic)
- **Reduce pipeline for large uploads** — when 12+ text files are attached,
  `generateCharacterDraft` runs a tiered map-reduce pipeline
  (`chat/character_reduce.py`): tier by screen time → batch close-read (main files
  in full, cameo files as segments) → structured notes with citations → merge into
  a `PrisMateDraft`-aligned profile
- Streamed chat with persistent per-session history
- **Long-term memory** per character, with browse/edit/merge/wipe UI at `/memory`
- **Private Mode** per session to skip long-term memory writes
- i18n (zh-CN / en-US)

## Key Endpoints

- `POST /api/chat/send_message` — send a user message (streamed response in payload)
- `GET/POST /api/characters` · `GET /api/characters/{id}` · `GET /api/sessions`
- `GET /api/characters/{id}/memory` · `POST/PATCH/DELETE /api/characters/{id}/memory[/{id}]`
- `POST /api/characters/{id}/memory/merge` · `DELETE /api/characters/{id}/memory`
- `POST /api/graphql/` — character CRUD (Strawberry GraphQL)

See `backend/chat/urls.py` for the full route map.

## Project Layout

```
backend/
  chat/                # the single business app: models, views, graphql, tasks,
                       #   soul, asr/tts, character_reduce, memory/, tests/
  prismate/            # Django project assembly (settings, celery, root urls)
  scripts/             # standalone tooling (prototypes, genie_server launcher)
frontend/src/
  app/                 # Next.js routes (/, /chat, /create-character,
                       #   /edit-character/[id], /memory, /settings)
  components/          # ChatInterface, ChatWindow, MemoryPanel, SoulPanel…
  constants/           # compile-time constants + provider presets
  store/               # Redux Toolkit slices
  i18n/                # zh-CN / en-US
  utils/api.ts         # REST client
  lib/apolloClient.ts  # GraphQL client
docs/
  architecture.md      # internal data-flow reference
  design/              # system & feature specs (memory system, natural chat…)
  guides/              # daily-commands cheat-sheet
  benchmarks/          # latency reports
  versions/            # release notes
```

See [`docs/project-structure.md`](./docs/project-structure.md) for the full
directory responsibility spec — what belongs where.

## Daily Commands

See [`docs/guides/daily-commands.md`](./docs/guides/daily-commands.md) for the full cheat-sheet (setup, run,
migrate, troubleshooting).
