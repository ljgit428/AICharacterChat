from celery import shared_task
import sys
from django.conf import settings
import google.generativeai as genai
# --- CORRECT IMPORT ---
from google.generativeai.types import Part
from .models import Message, Character, ChatSession

@shared_task
def generate_ai_response(message_id, character_id):
    """
    Generate AI response using Gemini API with full multimodal support
    for both character images and per-message files.
    """
    print(f"Task started for message_id={message_id}, character_id={character_id}")
    try:
        user_message = Message.objects.get(id=message_id)
        character = Character.objects.get(id=character_id)
        chat_session = user_message.chat_session

        api_key = getattr(settings, 'GEMINI_API_KEY', '')
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found")
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')

        # 1. Build initial system prompt (with character file if it exists)
        initial_prompt_text = (
            f"You are roleplaying as '{character.name}'.\n"
            f"Personality: {character.personality}.\n"
            f"Appearance: {character.appearance}.\n"
            f"Background: {character.description}.\n"
            f"Guidelines: {character.response_guidelines}\n"
            "Respond and act entirely as this character."
        )
        
        initial_prompt_parts = []
        if character.image_uri:
            print(f"Adding character file URI: {character.image_uri}")
            # The SDK handles determining the MIME type from the URI for common types
            file_part = Part.from_uri(uri=character.image_uri, mime_type=None)
            initial_prompt_parts.append(file_part)
        
        initial_prompt_parts.append(Part.from_text(initial_prompt_text))

        formatted_history = [
            {"role": "user", "parts": initial_prompt_parts},
            {"role": "model", "parts": [Part.from_text("Understood. I am ready.")]}
        ]

        # 2. Build the rest of the chat history, including per-message files
        history_messages = Message.objects.filter(chat_session=chat_session).order_by('timestamp')

        for msg in history_messages:
            role = 'model' if msg.role == 'assistant' else 'user'
            message_parts = []

            if msg.file_uri:
                print(f"Adding file URI for message {msg.id}: {msg.file_uri}")
                file_part = Part.from_uri(uri=msg.file_uri, mime_type=None)
                message_parts.append(file_part)

            if msg.content or not message_parts:
                message_parts.append(Part.from_text(msg.content or ""))

            # Avoid adding empty user messages unless they contain a file
            if message_parts:
                formatted_history.append({"role": role, "parts": message_parts})

        response = model.generate_content(formatted_history)
        ai_response_text = response.text
        
        ai_message = Message.objects.create(
            chat_session=chat_session,
            role='assistant',
            content=ai_response_text,
            character=character
        )
        
        print(f"Successfully generated response for message_id={ai_message.id}")
        return {'success': True, 'message_id': ai_message.id, 'content': ai_response_text}
        
    except Exception as e:
        import traceback
        print(f"Error in generate_ai_response: {str(e)}")
        print(traceback.format_exc())
        return {'success': False, 'error': str(e)}