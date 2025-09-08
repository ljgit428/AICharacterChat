from celery import shared_task
import sys
from django.conf import settings
import google.generativeai as genai
from google.generativeai.types import file_types
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

        # --- vvv 核心逻辑重构 vvv ---

        # 1. 构建初始系统提示 (包含角色图片)
        initial_prompt_text = (
            f"You are roleplaying as '{character.name}'.\n"
            f"Personality: {character.personality}.\n"
            f"Appearance: {character.appearance}.\n"
            f"Background: {character.description}.\n"
            f"Guidelines: {character.responseGuidelines}\n" # Assuming you have this field
            "Respond and act entirely as this character."
        )
        
        initial_prompt_parts = []
        if character.image_uri:
            print(f"Adding character image URI: {character.image_uri}")
            # MIME type is often inferred, but specifying helps.
            # For generic files, we might need a better way to determine this.
            image_part = {"file_data": {"mime_type": "image/jpeg", "file_uri": character.image_uri}}
            initial_prompt_parts.append(image_part)
        initial_prompt_parts.append({"text": initial_prompt_text})

        formatted_history = [
            {"role": "user", "parts": initial_prompt_parts},
            {"role": "model", "parts": [{"text": "Understood. I am ready."}]}
        ]

        # 2. 构建包含文件和文本的完整对话历史
        history_messages = Message.objects.filter(chat_session=chat_session).order_by('timestamp')

        for msg in history_messages:
            role = 'model' if msg.role == 'assistant' else 'user'
            
            # 为每条消息创建一个 parts 列表
            message_parts = []

            # 如果消息有关联的文件URI，将其作为第一个 part 添加
            if msg.file_uri:
                print(f"Adding file URI for message {msg.id}: {msg.file_uri}")
                # For non-images, we need a generic MIME type or a lookup.
                # For now, we let Gemini infer it by not providing one.
                file_part = {"file_data": {"mime_type": None, "file_uri": msg.file_uri}}
                message_parts.append(file_part)

            # 将消息的文本内容作为下一个 part 添加
            # Gemini要求，如果有多媒体内容，文本不能是空的
            if msg.content or not message_parts:
                 message_parts.append({"text": msg.content or ""}) # Use empty string if content is null but file exists

            formatted_history.append({
                "role": role,
                "parts": message_parts
            })

        # --- ^^^ 核心逻辑重构结束 ^^^ ---

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