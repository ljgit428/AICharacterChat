# backend/chat/tasks.py

from celery import shared_task
import sys
from django.conf import settings
import google.generativeai as genai
from .models import Message, Character, ChatSession

@shared_task
def generate_ai_response(message_id, character_id):
    """
    Generate AI response using Gemini API, including character's profile file
    and any files attached to specific messages.
    """
    print(f"Task started: generate_ai_response for message_id={message_id}, character_id={character_id}")
    try:
        # 1. Get core objects
        user_message = Message.objects.get(id=message_id)
        character = Character.objects.get(id=character_id)
        chat_session = user_message.chat_session
        
        print(f"Found user_message: {user_message.content[:50]}...")
        print(f"Found character: {character.name}")
        if character.file_uri:
            print(f"Character has an associated file URI: {character.file_uri}")

        # 2. Configure Gemini API
        api_key = getattr(settings, 'GEMINI_API_KEY', '')
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in settings")
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-pro')

        # 3. Build the complete conversation history for the AI
        
        # --- vvv CORE FIX START vvv ---
        
        # Part A: Build the initial system prompt with character definitions AND the character's file
        initial_prompt_text = (
            f"You are now roleplaying as the character '{character.name}'.\n"
            f"Your personality is: {character.personality}\n"
            f"Your appearance is: {character.appearance}\n"
            f"Here is your background story: {character.description}\n"
            f"Your response guidelines are: {character.response_guidelines}\n"
            "From this moment on, you must respond and act entirely as this character. "
            "Do not break character. Engage with the user naturally based on your defined traits and the provided file context."
        )

        # The `parts` for the first user message can contain multiple items (text, files)
        initial_prompt_parts = [initial_prompt_text]

        # If the character has an associated file, add it to the initial prompt
        if character.file_uri:
            try:
                # Use genai.get_file to retrieve the file handle from the stored URI
                character_file = genai.get_file(name=character.file_uri)
                initial_prompt_parts.append(character_file)
                print(f"Successfully retrieved character file '{character.file_uri}' for AI context.")
            except Exception as e:
                print(f"Warning: Could not retrieve character file from URI '{character.file_uri}'. Error: {str(e)}")


        # The Gemini API expects history in the format: [{"role": "user/model", "parts": [text, file, ...]}, ...]
        # We simulate a "system" prompt with a user/model exchange at the beginning.
        formatted_history = [
            {"role": "user", "parts": initial_prompt_parts},
            {"role": "model", "parts": ["Understood. I am ready to embody the character and begin our conversation based on the provided profile and file."]}
        ]

        # Part B: Append all subsequent chat messages from the database
        # We skip the very first message if it was the auto-generated prompt from the old system.
        # This makes the new logic robust. A simple order_by is sufficient.
        history_messages = Message.objects.filter(chat_session=chat_session).order_by('timestamp')

        for msg in history_messages:
            role = 'model' if msg.role == 'assistant' else 'user'
            message_parts = []
            
            # Add the text content of the message, if any
            if msg.content:
                message_parts.append(msg.content)
            
            # If a file was attached to THIS SPECIFIC message, add it too
            if msg.file_uri:
                try:
                    message_file = genai.get_file(name=msg.file_uri)
                    message_parts.append(message_file)
                    print(f"Adding message-specific file '{msg.file_uri}' to history.")
                except Exception as e:
                    print(f"Warning: Could not retrieve message file '{msg.file_uri}'. Error: {str(e)}")

            # Only add to history if there's something to add
            if message_parts:
                formatted_history.append({
                    "role": role,
                    "parts": message_parts
                })

        # --- ^^^ CORE FIX END ^^^ ---

        # 4. Call Gemini API with the rich, file-inclusive history
        print("Generating AI response with the following history structure:")
        for item in formatted_history:
            print(f"- Role: {item['role']}, Parts: {[type(p) for p in item['parts']]}")

        response = model.generate_content(formatted_history)
        ai_response_text = response.text
        
        # 5. Save AI's response to the database
        ai_message = Message.objects.create(
            chat_session=chat_session,
            role='assistant',
            content=ai_response_text,
            character=character
        )
        
        print(f"Successfully generated and saved AI response with ID: {ai_message.id}")

        return {
            'success': True,
            'message_id': ai_message.id,
            'content': ai_response_text
        }
        
    except Exception as e:
        import traceback
        print(f"Error generating AI response: {str(e)}")
        print(traceback.format_exc())
        return {
            'success': False,
            'error': str(e)
        }