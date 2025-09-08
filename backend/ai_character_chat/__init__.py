# backend/ai_character_chat/__init__.py

# Import Celery app instance
from .celery import app as celery_app

__all__ = ('celery_app',)
