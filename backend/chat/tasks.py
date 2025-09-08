# backend/chat/tasks.py

from celery import shared_task
import sys
from django.conf import settings
import google.generativeai as genai
# --- 移除所有来自 google.generativeai.types 的错误导入 ---
from .models import Message, Character, ChatSession

@shared_task
def generate_ai_response(message_id, character_id):
    """
    Generate AI response using Gemini API with full multimodal support,
    using the correct dictionary format for parts.
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
        model = genai.GenerativeModel('gemini-2.5-pro')

        # --- vvv 核心逻辑修正 vvv ---

        # 直接使用数据库中的对话历史，移除重复的角色提示生成
        formatted_history = []
        
        # 获取此会话的所有历史消息（包括用户发送的完整prompt）
        history_messages = Message.objects.filter(chat_session=chat_session).order_by('timestamp')

        for msg in history_messages:
            # 数据库中的 role ('assistant') 需要映射为 'model'
            role = 'model' if msg.role == 'assistant' else 'user'
            message_parts = []

            if msg.file_uri:
                print(f"Adding file URI for message {msg.id}: {msg.file_uri}")
                # 对于未知文件类型，不提供 mime_type 让 Gemini 自行推断
                file_part = {
                    "file_data": {
                        "mime_type": None,
                        "file_uri": msg.file_uri
                    }
                }
                message_parts.append(file_part)

            if msg.content or not message_parts:
                 message_parts.append({"text": msg.content or ""})

            if message_parts:
                formatted_history.append({
                    "role": role,
                    "parts": message_parts
                })

        # 如果历史记录为空（理论上不应该，因为至少有用户的消息），可以添加一个安全检查
        if not formatted_history:
             raise ValueError("Cannot generate response from an empty chat history.")

        # --- ^^^ 核心逻辑修正结束 ^^^ ---

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