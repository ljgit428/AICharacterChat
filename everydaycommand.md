# Everyday Commands

> Everyday command reference for the AI Character Chat stack.
> Stack: Django 5.2 + Celery (backend) · PostgreSQL · Redis · Next.js (frontend).
> Virtual env on this machine is **`backend\venv_stable`** (not `venv`).

---

## 0. First-time setup (only once)

```bash
# Backend
cd backend
cp .env.template .env            # fill in DATABASE_*, SECRET_KEY, REDIS_URL
python -m venv venv_stable       # only if it does not already exist
source venv_stable/Scripts/activate    # Windows / Git Bash
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser       # optional
deactivate

# Frontend
cd ../frontend
cp .env.local.template .env.local  # NEXT_PUBLIC_API_URL=...
npm install
```

> Prerequisites: Node.js 18+, Python 3.10+, PostgreSQL running locally, Redis
> available (project provides `docker-compose.yml` → `docker-compose up -d redis`).

### PowerShell-only: if `Activate.ps1` is blocked

Windows PowerShell often rejects the venv activation script under the default
execution policy. Fix once per user:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then activate with:

```powershell
.\venv_stable\Scripts\Activate.ps1
```

> cmd / Git Bash users: ignore this section, just use `venv_stable\Scripts\activate`.

---

## 1. Start the stack (every day)

Open **three terminals** (or use a tmux/tmuxinator setup).

```bash
# Terminal 1 — Redis (if not using a system-wide service)
docker-compose up -d redis

# Terminal 2 — Django API + Celery worker (in one shell)
cd backend
source venv_stable/Scripts/activate        # PowerShell: .\venv_stable\Scripts\Activate.ps1
python manage.py runserver                 # API → http://127.0.0.1:8000
celery -A ai_character_chat worker --loglevel=info

cd backend
python -m celery -A ai_character_chat worker --loglevel=info

# Terminal 3 — Next.js dev server
cd frontend
npm run dev                                # UI → http://localhost:3000
```

---

## 2. Common maintenance

```bash
# Backend (venv_stable must be active)
cd backend
source venv_stable/Scripts/activate        # PowerShell: .\venv_stable\Scripts\Activate.ps1
python manage.py makemigrations chat       # after model edits
python manage.py migrate                   # apply pending migrations
python manage.py showmigrations chat       # see applied status
python manage.py createsuperuser           # new admin
python manage.py shell                     # ad-hoc ORM queries

# Frontend
cd frontend
npm run lint                               # ESLint (eslint-config-next)
npx tsc --noEmit                           # typecheck
```

---

## 3. Stop everything

```bash
# Stop Celery + runserver: Ctrl+C in Terminal 2
# Stop npm dev:          Ctrl+C in Terminal 3
# Stop Redis:
docker-compose stop redis
# (or `docker-compose down` to also remove the container)
```

---

## 4. Troubleshooting cheatsheet

| Symptom | Fix |
|---|---|
| `celery : 无法将"celery"项识别为 cmdlet…` (PowerShell) | Activate venv: `.\venv_stable\Scripts\Activate.ps1`. Or use `python -m celery -A ai_character_chat worker --loglevel=info` to bypass the PATH/exit-script entirely. |
| `Activate.ps1 is not digitally signed` | `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` once. |
| `psycopg2.OperationalError ... could not connect to server` | Start PostgreSQL; double-check `DATABASE_HOST`/`PORT` in `backend/.env`. |
| `字段 chat_chatsession.<xxx> 不存在` / `column ... does not exist` | Run `python manage.py migrate`. |
| Celery tasks hang / no log | Confirm Redis is up (`docker ps`) and `REDIS_URL` matches `backend/.env`. |
| Next.js shows 4xx/5xx to API | Verify `NEXT_PUBLIC_API_URL` in `frontend/.env.local` and that `runserver` is up. |
| Port 8000 already in use | `python manage.py runserver 8001` (update `NEXT_PUBLIC_API_URL` accordingly). |
| Port 3000 already in use | `npm run dev -- -p 3001` (update backend `CORS_ALLOWED_ORIGINS` accordingly). |
