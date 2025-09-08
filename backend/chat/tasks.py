# backend/chat/tasks.py

from celery import shared_task
from django.conf import settings
import google.generativeai as genai
from .models import Message, Character, ChatSession
import traceback

# Helper to construct the multimodal parts for the Gemini API
def build_gemini_parts(character, initial_prompt_text):
    """
    Constructs the list of parts for the Gemini API, including the character file if it exists.
    """
    parts = [initial_prompt_text]  # Always start with the text prompt

    # Check if the character has an associated file
    if character.file:
        try:
            print(f"Found file for character '{character.name}': {character.file.path}")
            # The Gemini library can take a path directly.
            # It will handle the MIME type detection.
            character_file_for_api = genai.upload_file(path=character.file.path)
            parts.append(character_file_for_api)
            print(f"Successfully prepared file '{character.file.name}' for Gemini API.")
        except Exception as e:
            print(f"Error processing character file '{character.file.path}': {str(e)}")
            # If the file processing fails, we continue with text only.
            # You could add more robust error handling here.
    
    return parts

@shared_task
def generate_ai_response(message_id, character_id):
    """
    Generate AI response using Gemini API, including the character file if available.
    """
    print(f"Task started: generate_ai_response for message_id={message_id}, character_id={character_id}")
    try:
        # 1. Get core objects (unchanged)
        user_message = Message.objects.get(id=message_id)
        character = Character.objects.get(id=character_id)
        chat_session = user_message.chat_session
        
        print(f"Found user_message: {user_message.content[:50]}...")
        print(f"Found character: {character.name}")

        # 2. Configure Gemini API (unchanged)
        api_key = getattr(settings, 'GEMINI_API_KEY', '')
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in settings")
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-pro')

        # 3. Construct conversation history
        formatted_history = []
        history_messages = Message.objects.filter(chat_session=chat_session).order_by('timestamp')

        for i, msg in enumerate(history_messages):
            role = 'model' if msg.role == 'assistant' else 'user'
            
            # --- vvv THIS IS THE CORE LOGIC CHANGE vvv ---
            if i == 0:
                # This is the very first message, which contains the system prompt.
                # We need to check for a character file and include it here.
                initial_prompt_text = msg.content
                parts = build_gemini_parts(character, initial_prompt_text)
                formatted_history.append({"role": role, "parts": parts})
                # We also add the "Understood" response to prime the model
                formatted_history.append({"role": "model", "parts": ["Understood. I will now act as the character."]})
            else:
                # For all subsequent messages, handle both text and chat message files.
                parts = [msg.content]
                if msg.file_uri:
                    try:
                        # For chat files, we use the URI directly from the Gemini File API
                        chat_file = genai.get_file(name=msg.file_uri)
                        parts.append(chat_file)
                        print(f"Added chat file '{msg.file_uri}' to history.")
                    except Exception as e:
                        print(f"Could not retrieve chat file '{msg.file_uri}': {e}")

                formatted_history.append({"role": role, "parts": parts})
            # --- ^^^ END OF CORE LOGIC CHANGE ^^^ ---

        # 4. Call Gemini API with the potentially multimodal history
        response = model.generate_content(formatted_history)
        ai_response_text = response.text
        
        # 5. Save AI's response to the database (unchanged)
        ai_message = Message.objects.create(
            chat_session=chat_session,
            role='assistant',
            content=ai_response_text,
            character=character
        )
        
        print(f"Successfully generated and saved AI response for message_id={ai_message.id}")
        return {
            'success': True,
            'message_id': ai_message.id,
            'content': ai_response_text
        }
        
    except Exception as e:
        print(f"Error generating AI response: {str(e)}")
        print(traceback.format_exc())
        return {
            'success': False,
            'error': str(e)
        }