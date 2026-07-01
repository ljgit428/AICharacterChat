# AI Character Chat Application

A role-playing chat application built with Next.js, TypeScript, Redux for the frontend and Django with Celery for the backend. The application uses per-user model configurations for AI responses and PostgreSQL for data storage.

## Features

- Two-column layout with chat window and character settings
- Real-time chat with AI character
- Character customization (name, description, personality, appearance)
- Chat history stored in PostgreSQL database
- Responsive design for mobile and desktop
- **Long-Term Memory (v1.0.2+):** A Celery pipeline emits durable per-character memory items (`CharacterMemoryItem` + `MemoryAuditLog`) and renders them as a `wiki/memory.md` virtual file. The `/memory` page lets users browse, edit, merge, and wipe entries; per-session Private Mode keeps a chat out of the durable record.

## Tech Stack

### Frontend
- Next.js 14 with TypeScript
- Redux Toolkit for state management
- Tailwind CSS for styling
- Hybrid (REST for Chat Stream + GraphQL for Data Management)

### Backend
- Django 5.2 with Django REST Framework
- PostgreSQL database
- Celery for background tasks
- Redis as message broker

## Ecosystem & Related Repositories

This project is the **core platform** of a larger GenAI ecosystem. To ensure modularity and quality, specific components were decoupled:

*   ** Inference Engine (Colab):** [GPT-SOVITS-infer-Colab](https://github.com/ljgit428/GPT-SOVITS-infer-Colab)
    *   *Role:* Acts as an ephemeral GPU worker for offloading heavy GPT-SOVITS text-to-speech inference tasks.
*   ** QA & Validation Pipeline:** [speechbrain_Voiceprint_Recognition](https://github.com/ljgit428/speechbrain_Voiceprint_Recognition)
    *   *Role:* Automated voiceprint verification tool achieving 78% similarity scores.
    *   *Live Demo:* [https://huggingface.co/spaces/l73jiang/speechbrain_Voiceprint_Recognition]



## Environment Security

This project uses environment templates to protect sensitive information:

- `backend/.env.template` - Template for backend environment variables
- `frontend/.env.local.template` - Template for frontend environment variables

**Important Security Note:**
- Never commit actual environment files (`.env`, `.env.local`) to version control
- Only commit the template files (`.env.template`, `.env.local.template`)
- Copy templates to actual environment files and fill in your values:
  ```bash
  # Backend
  cp backend/.env.template backend/.env
  
  # Frontend
  cp frontend/.env.local.template frontend/.env.local
  ```

The project includes `.gitignore` files to prevent accidental commits of sensitive environment files.

## Setup Instructions

### Prerequisites
- Node.js 18+
- Python 3.10+
- PostgreSQL
- Redis
- A model API key that you will save in the app after login

### Docker Setup (Optional)

This project includes Docker support for easy deployment of Redis and other services. To use Docker:

1. **Start Redis using Docker**
   ```bash
   docker-compose up -d redis
   ```
   
   This command will:
   - Pull the latest Redis Docker image
   - Start the Redis container named 'redis-server'
   - Map port 6379 from the container to your local machine
   - Configure the container to automatically restart unless stopped
   - Make Redis available at redis://localhost:6379/0

2. **Verify Redis is running**
   ```bash
   docker ps
   ```

3. **Restart Redis if needed**
   ```bash
   docker-compose restart redis
   ```

4. **Stop Redis**
   ```bash
   docker-compose stop redis
   ```

**Note:** The `docker-compose.yml` file is already configured with Redis settings. You can customize the Redis configuration by modifying the `docker-compose.yml` file.

### Redis Configuration

### Backend Setup

1. **Navigate to the backend directory**
   ```bash
   cd backend
   ```

2. **Create and activate a virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up PostgreSQL database**
   - Create a PostgreSQL database named `ai_character_chat`
    (Make sure your PostgreSQL server is running)

5. **Set up environment variables**
    Copy the template file and create your `.env` file:
    ```bash
    cp backend/.env.template backend/.env
    ```
    
    Edit the `backend/.env` file with your actual values:
    ```
    SECRET_KEY=your-django-secret-key-here
    DEBUG=True
    DATABASE_NAME=ai_character_chat
    DATABASE_USER=postgres
    DATABASE_PASSWORD=
    DATABASE_HOST=localhost
    DATABASE_PORT=5432
    REDIS_URL=redis://localhost:6379/0
    ```
    
    **Important:** Never commit your actual `.env` file to version control. Only the template file `.env.template` should be committed.

6. **Run database migrations**
    ```bash
    python manage.py migrate
    ```

7. **Create and apply chat app migrations**
    ```bash
    python manage.py makemigrations chat
    python manage.py migrate chat
    ```

8. **Verify all migrations are complete**
    ```bash
    python manage.py showmigrations
    ```

9. **Create a superuser (optional)**
    ```bash
    python manage.py createsuperuser
    ```

10. **Start the Django development server**
    ```bash
    python manage.py runserver
    ```

**Note:** The backend server will be available at http://127.0.0.1:8000/ once started. All migrations should be applied without errors for the application to function properly.

9. **Start Celery worker (in a separate terminal)**
   ```bash
   celery -A ai_character_chat worker --loglevel=info
   ```

### Frontend Setup

1. **Navigate to the frontend directory**
   ```bash
   cd frontend
   ```

2. **Install dependencies**
   ```bash
   npm install
   ```

3. **Set up environment variables**
    Copy the template file and create your `.env.local` file:
    ```bash
    cp frontend/.env.local.template frontend/.env.local
    ```
    
    Edit the `frontend/.env.local` file with your actual values:
    ```
    NEXT_PUBLIC_API_URL=http://localhost:8000/api
    ```
    
    **Important:** Never commit your actual `.env.local` file to version control. Only the template file `.env.local.template` should be committed.

4. **Start the development server**
   ```bash
   npm run dev
   ```

5. **Configure your own model API in the app**
   - Sign in to the application
   - Open `Project Settings`
   - Create a model configuration with your own API key
   - Gemini and OpenAI-compatible providers are both supported, but only user-saved keys are used

## Usage

1. Open your browser and navigate to `http://localhost:3000`
2. Click on "Character Settings" to customize your AI character
3. Start chatting with your character in the chat window
4. Your conversations are automatically saved to the database


## API Endpoints

### Characters
- `GET /api/characters` - List all characters
- `POST /api/characters` - Create a new character
- `GET /api/characters/{id}` - Get character details
- `PUT /api/characters/{id}` - Update character
- `GET /api/characters/{id}/memory` - Long-term memory snapshot (sections + wiki/memory.md)
- `POST /api/characters/{id}/memory` - Create a memory entry
- `PATCH /api/characters/{id}/memory/{short_id}` - Update a memory entry
- `DELETE /api/characters/{id}/memory/{short_id}` - Delete a memory entry
- `POST /api/characters/{id}/memory/merge` - Merge two entries within the same section
- `DELETE /api/characters/{id}/memory` - Wipe all memory entries (audited)

### Chat Sessions
- `GET /api/sessions` - List chat sessions
- `POST /api/sessions` - Create a new chat session
- `GET /api/sessions/{id}` - Get session details
- `PATCH /api/sessions/{id}` - Update session. Body shape (any subset): `{ "title"?: string, "is_private_mode"?: boolean }`. `is_private_mode: true` keeps the chat out of long-term memory for the remainder of the session.

### Messages
- `GET /api/messages?chat_session_id={id}` - Get messages for a session
- `POST /api/chat/send_message` - Send a message and get AI response

## Project Structure

```
AICharacterChat/
├── backend/                 # Django backend
│   ├── ai_character_chat/   # Django project settings
│   ├── chat/               # Chat app
│   │   ├── models.py       # Database models
│   │   ├── views.py        # API views
│   │   ├── serializers.py  # DRF serializers
│   │   └── tasks.py        # Celery tasks
│   └── requirements.txt    # Python dependencies
├── frontend/               # Next.js frontend
│   ├── src/
│   │   ├── app/           # Next.js app directory
│   │   ├── components/    # React components
│   │   ├── store/         # Redux store
│   │   ├── types/         # TypeScript types
│   │   └── utils/         # Utility functions
│   └── package.json       # Node.js dependencies
└── README.md
```

## License

This project is licensed under the MIT License.
