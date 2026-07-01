# Quick Start Guide

## Frontend Development Server

To start the frontend development server:

```bash
cd frontend
npm run dev
```

This command will:
- Navigate to the frontend directory
- Start the Next.js development server
- Make the application available at:
  - Local: http://localhost:3000
  - Network: http://10.0.0.9:3000
- Load environment variables from `.env.local`

The server will automatically reload when you make changes to the source code.

## Backend Development Server

To start the backend development server:

```bash
cd backend
python manage.py runserver
```

This command will:
- Navigate to the backend directory
- Start the Django development server
- Make the API available at:
  - Local: http://localhost:8000
- Load environment variables from `.env`
- Use Django REST Framework for API endpoints
- Configure Gemini AI API for chat functionality

The server will automatically reload when you make changes to the Python source code.

## Redis Server

To start the Redis server using Docker:

```bash
docker-compose up -d redis
```

This command will:
- Pull the latest Redis Docker image (if not already available)
- Start the Redis container named 'redis-server'
- Map port 6379 from the container to your local machine
- Configure the container to automatically restart unless stopped
- Make Redis available at redis://localhost:6379/0

You can verify Redis is running by checking the container status:
```bash
docker ps
```

## Environment Variables

### Backend (.env)
The backend uses several environment variables:

```env
SECRET_KEY=django-insecure-ip$yu!sa#f5*iw6^-zxwp&eq$&t$vt+#o%cv*sm9^qlgvg@ru&
DEBUG=True
GEMINI_API_KEY=
DATABASE_URL=postgresql://postgres:0324@localhost:5432/ai_character_chat
REDIS_URL=redis://localhost:6379/0
```

**Important:** The `GEMINI_API_KEY` is required for AI chat functionality and must be set to a valid Gemini API key.

## Celery Worker

To start the Celery worker for background AI response generation:

```bash
cd backend
python -m celery -A ai_character_chat worker --loglevel=info
```

To avoid Error 429
```bash
cd backend
python -m celery -A ai_character_chat worker --loglevel=info -c 1
```

This command will:
- Navigate to the backend directory
- Start the Celery worker process
- Connect to the configured message broker (Redis for production, memory for development)
- Listen for background tasks to generate AI responses
- Display logs at info level for monitoring task execution

**Note:** The Celery worker should be started in a separate terminal window alongside the Django development server. The worker will automatically process AI response generation tasks when users send messages in the chat interface.

## Long-Term Memory

After v1.0.2 the Celery worker also runs the `sync_long_term_memory` task after every response. It reads the assistant's tool calls (merge / insert / update / delete / noop) and persists them to `CharacterMemoryItem`, leaving an auditable trail in `MemoryAuditLog`.

- **Enable per user:** open *User Settings → Memory & Privacy → Allow long-term persistent memory updates based on conversation*.
- **Disable per session:** toggle *Private Mode* inside the chat header or the right-side Memory panel. Private turns still stream, they just aren't written to long-term memory.
- **Browse / edit / wipe:** open the `/memory` page in the sidebar to inspect sections, edit individual entries, merge two in the same section, or wipe the whole record.
- **Audit trail:** every CRUD call writes a `MemoryAuditLog` row (`action`, `before_description` / `after_description`, `reason`, `source`), queryable from the Django admin.
