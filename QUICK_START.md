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

## Environment Variables

### Backend (.env)
The backend uses several environment variables:

```env
SECRET_KEY=django-insecure-ip$yu!sa#f5*iw6^-zxwp&eq$&t$vt+#o%cv*sm9^qlgvg@ru&
DEBUG=True
GEMINI_API_KEY=AIzaSyBDyzyaALuXGVjkt1vvTm9K5nEjipckZW0
DATABASE_URL=postgresql://postgres:0324@localhost:5432/ai_character_chat
REDIS_URL=redis://localhost:6379/0
```

**Important:** The `GEMINI_API_KEY` is required for AI chat functionality and must be set to a valid Gemini API key.