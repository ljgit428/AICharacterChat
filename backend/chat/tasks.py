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
    parts = [initial_prompt_text]
    if character.gemini_file_uri:
        try:
            print(f"Found Gemini file URI for character '{character.name}': {character.gemini_file_uri}")
            character_file_for_api = genai.get_file(name=character.gemini_file_uri)
            parts.append(character_file_for_api)
            print(f"Successfully retrieved character file '{character.gemini_file_uri}' for Gemini API.")
        except Exception as e:
            print(f"Error retrieving character file '{character.gemini_file_uri}' from Gemini: {str(e)}")
    return parts

@shared_task
def generate_ai_response(message_id, character_id):
    """
    Generate AI response using Gemini API, including the character file AND all previous chat files.
    """
    print(f"Task started: generate_ai_response for message_id={message_id}, character_id={character_id}")
    try:
        # 1. Get core objects
        user_message = Message.objects.get(id=message_id)
        character = Character.objects.get(id=character_id)
        chat_session = user_message.chat_session
        
        print(f"Found user_message: {user_message.content[:50]}...")
        print(f"Found character: {character.name}")

        # 2. Configure Gemini API
        api_key = getattr(settings, 'GEMINI_API_KEY', '')
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in settings")
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-pro') # 使用支持长上下文的2.5 Pro模型

        # 3. --- REBUILT LOGIC: Construct a complete conversation history ---
        formatted_history = []
        history_messages = Message.objects.filter(chat_session=chat_session).order_by('timestamp')

        # Get the very first message, which is the system prompt
        system_prompt_message = history_messages.first()
        if not system_prompt_message:
            raise ValueError("Cannot generate response for an empty chat session.")

        # Part 1: Build the initial System Prompt with the character file
        system_prompt_text = system_prompt_message.content
        system_parts = build_gemini_parts(character, system_prompt_text) # build_gemini_parts gets the character file
        formatted_history.append({"role": "user", "parts": system_parts})
        # Prime the model to acknowledge its role
        formatted_history.append({"role": "model", "parts": ["Understood. I will now act as the character."]})

        # Part 2: Loop through the actual chat messages (skipping the system prompt)
        actual_chat_messages = history_messages[1:]
        for msg in actual_chat_messages:
            role = 'model' if msg.role == 'assistant' else 'user'
            
            # Each message part starts with its text content
            parts = [msg.content]
            
            # Add the chat file URI if it exists for THIS specific message
            if msg.file_uri:
                try:
                    print(f"Retrieving chat file '{msg.file_uri}' for message ID {msg.id}")
                    chat_file = genai.get_file(name=msg.file_uri)
                    parts.append(chat_file)
                    print(f"Successfully added chat file to history.")
                except Exception as e:
                    print(f"Could not retrieve chat file '{msg.file_uri}': {e}")

            formatted_history.append({"role": role, "parts": parts})
        
        # 4. Call Gemini API with the complete, correctly constructed history
        print("Sending complete history to Gemini...")
        response = model.generate_content(formatted_history)
        ai_response_text = response.text
        
        # 5. Save AI's response to the database
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