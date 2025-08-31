from celery import shared_task
import requests
import json
from django.conf import settings
from .models import Message, Character, ChatSession

@shared_task
def generate_ai_response(message_id, character_id):
    """
    Generate AI response using Gemini 2.5 Pro API
    """
    print(f"Task started: generate_ai_response for message_id={message_id}, character_id={character_id}")
    try:
        # Get the message and character
        message = Message.objects.get(id=message_id)
        character = Character.objects.get(id=character_id)
        print(f"Found message: {message.content[:50]}...")
        print(f"Found character: {character.name}")
        
        # Prepare the prompt
        prompt = f"You are {character.name}. {character.personality}\n\n"
        prompt += f"Appearance: {character.appearance}\n\n"
        prompt += f"Character description: {character.description}\n\n"
        
        # Add conversation history
        conversation_history = Message.objects.filter(
            chat_session=message.chat_session
        ).order_by('timestamp')[:10]  # Get last 10 messages
        
        for msg in conversation_history:
            prompt += f"{msg.role}: {msg.content}\n"
        
        prompt += f"assistant: "
        
        # Call Gemini API
        api_key = getattr(settings, 'GEMINI_API_KEY', '')
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in settings")
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={api_key}"
        
        headers = {
            'Content-Type': 'application/json',
        }
        
        data = {
            "contents": [{
                "parts": [{
                    "text": prompt
                }]
            }],
            "generationConfig": {
                "temperature": 1,
                "topK": 40,
                "topP": 0.95,
                "maxOutputTokens": 1024,
            }
        }
        
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        
        # Parse the response
        response_data = response.json()
        ai_response = response_data['candidates'][0]['content']['parts'][0]['text']
        
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