from celery import shared_task
from django.conf import settings
import google.generativeai as genai
from .models import Message, Character, ChatSession
import traceback
import logging

logger = logging.getLogger(__name__)

@shared_task(retry_backoff=True)
def build_gemini_parts(initial_prompt_text):
    """
    Constructs the list of parts for the Gemini API, including the character file if it exists.
    """
    parts = [initial_prompt_text]
    return parts
    
@shared_task(retry_backoff=True)
def update_session_title(chat_session, history_text, api_key):
    """
    Helper function to generate a creative title based on chat history.
    """
    try:
        # Use the same model configuration as the main chat to ensure availability
        model_name = getattr(settings, 'GEMINI_MODEL_NAME', 'gemini-2.5-pro')
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        
        # Optimized prompt for title generation
        prompt = (
            f"Analyze the following short conversation start.\n"
            f"Generate a short, engaging title (2-6 words) that summarizes the topic.\n"
            f"Rules:\n"
            f"1. Use the same language as the conversation (e.g., if Chinese, use Chinese).\n"
            f"2. Do NOT use quotation marks.\n"
            f"3. Do NOT include words like 'Chat', 'Conversation', 'Title'.\n"
            f"4. Just the topic.\n\n"
            f"Conversation:\n{history_text}"
        )
        
        response = model.generate_content(prompt)
        new_title = response.text.strip().replace('"', '').replace("'", "")
        
        if new_title:
            chat_session.title = new_title
            chat_session.save(update_fields=['title'])
            logger.info(f"[SUCCESS] Successfully updated session {chat_session.id} title to: {new_title}")
        else:
            logger.warning(f"[WARNING] AI returned empty title for session {chat_session.id}")
            
    except Exception as e:
        logger.error(f"[ERROR] Failed to auto-generate title: {e}")

@shared_task(retry_backoff=True)
def generate_ai_response(message_id, character_id):
    """
    Generate AI response using Gemini API, including the character file and all previous chat files.
    """
    try:
        user_message = Message.objects.get(id=message_id)
        character = Character.objects.get(id=character_id)
        chat_session = user_message.chat_session
        
        api_key = getattr(settings, 'GEMINI_API_KEY', '')
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in settings")
        
        genai.configure(api_key=api_key)
        
        tools = []
        if chat_session.enable_web_search:
            tools.append({'google_search': {
                'dynamic_retrieval_config': {
                    'mode': 'dynamic',
                    'dynamic_threshold': 0.6,
                }
            }})
            
        model_name = getattr(settings, 'GEMINI_MODEL_NAME', 'gemini-2.5-pro')
        model = genai.GenerativeModel(model_name, tools=tools if tools else None)

        formatted_history = []
        history_messages = Message.objects.filter(chat_session=chat_session).order_by('timestamp')

        system_prompt_message = history_messages.first()
        if not system_prompt_message:
            raise ValueError("Cannot generate response for an empty chat session.")

        session_settings_text = ""
        settings_parts = []
        
        if chat_session.world_time:
            settings_parts.append(f"Current World Time: {chat_session.world_time}")
        if chat_session.user_persona:
            settings_parts.append(f"User Persona/Role: {chat_session.user_persona}")
        if chat_session.output_language:
            settings_parts.append(f"Must Respond in Language: {chat_session.output_language}")
        if chat_session.additional_context:
            settings_parts.append(f"Additional Context: {chat_session.additional_context}")
            
        if settings_parts:
            session_settings_text = "\n\n[SESSION CONFIGURATION]\n" + "\n".join(settings_parts)

        system_prompt_text = system_prompt_message.content + session_settings_text
        
        system_parts = build_gemini_parts(system_prompt_text)
        formatted_history.append({"role": "user", "parts": system_parts})

        # Prepare text for title generation (User's first message)
        conversation_text_for_title = f"User: {user_message.content}\n"

        actual_chat_messages = history_messages[1:]
        for msg in actual_chat_messages:
            role = 'model' if msg.role == 'assistant' else 'user'
            
            parts = [msg.content]
            
            if msg.file_uri:
                try:
                    chat_file = genai.get_file(name=msg.file_uri)
                    parts.append(chat_file)
                except Exception as e:
                    logger.warning(f"Failed to load chat file from Gemini: {e}")

            formatted_history.append({"role": role, "parts": parts})
        
        response = model.generate_content(formatted_history)
        ai_response_text = response.text.strip()
        
        ai_message = Message.objects.create(
            chat_session=chat_session,
            role='assistant',
            content=ai_response_text,
            character=character
        )

        # Update session timestamp
        chat_session.save()
        
        # Logic: If title is default ("Chat with...") OR it's one of the very first turns (e.g. message count < 4)
        # We trigger title generation.
        message_count = history_messages.count()
        is_default_title = chat_session.title.startswith("Chat with")
        
        if is_default_title or message_count <= 4:
            conversation_text_for_title += f"Character: {ai_response_text[:100]}..."
            logger.info(f"Triggering title generation for Session {chat_session.id}...")
            update_session_title(chat_session, conversation_text_for_title, api_key)
        
        return {
            'success': True,
            'message_id': ai_message.id,
            'content': ai_response_text
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }
