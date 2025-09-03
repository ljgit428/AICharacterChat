from celery import shared_task
import sys
from django.conf import settings
import google.generativeai as genai
from .models import Message, Character, ChatSession

@shared_task
def generate_ai_response(message_id, character_id):
    """
    Generate AI response using Gemini 2.5 Flash API with persistent chat sessions
    """
    print(f"Task started: generate_ai_response for message_id={message_id}, character_id={character_id}")
    try:
        # Get the message and character
        message = Message.objects.get(id=message_id)
        character = Character.objects.get(id=character_id)
        print(f"Found message: {message.content[:50]}...")
        print(f"Found character: {character.name}")
        
        # Get API key
        api_key = getattr(settings, 'GEMINI_API_KEY', '')
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in settings")
        
        # Initialize Gemini client
        genai.configure(api_key=api_key)
        client = genai.GenerativeModel('gemini-2.5-flash')
        
        # Create or get persistent chat session
        chat_session, created = ChatSession.objects.get_or_create(
            id=message.chat_session.id,
            defaults={
                'gemini_chat_id': None,  # Will be set after first message
                'user': message.chat_session.user,
                'character': character
            }
        )
        
        # If this is the first message in the chat, create a new Gemini chat
        if created or not chat_session.gemini_chat_id:
            # Send initial character setup message
            initial_prompt = f"You are {character.name}. {character.personality}\n\n"
            initial_prompt += f"Appearance: {character.appearance}\n\n"
            initial_prompt += f"Character description: {character.description}\n\n"
            initial_prompt += "You are roleplaying as this character. Respond naturally and stay in character."
            
            chat = client.start_chat(history=[{"role": "user", "parts": [initial_prompt]}])
            chat_session.gemini_chat_id = "gemini_chat"  # Store a simple identifier
            chat_session.save()
        else:
            # Create a new chat session for each request to maintain context
            chat = client.start_chat(
                history=[{"role": "user", "parts": [message.content]}]
            )
        
        # Send user message and get AI response
        response = chat.send_message(message.content)
        ai_response = response.text
        
        # Save the AI response
        ai_message = Message.objects.create(
            chat_session=message.chat_session,
            role='assistant',
            content=ai_response,
            character=character
        )
        
        return {
            'success': True,
            'message_id': ai_message.id,
            'content': ai_response
        }
        
    except Exception as e:
        # Log the error and return failure
        print(f"Error generating AI response: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }