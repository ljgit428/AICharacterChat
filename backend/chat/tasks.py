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
        # 1. 获取核心对象
        user_message = Message.objects.get(id=message_id)
        character = Character.objects.get(id=character_id)
        chat_session = user_message.chat_session
        
        print(f"Found user_message: {user_message.content[:50]}...")
        print(f"Found character: {character.name}")

        # 2. 配置 Gemini API
        api_key = getattr(settings, 'GEMINI_API_KEY', '')
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in settings")
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash') # 使用 1.5-flash 或 2.5-pro

        # 3. 构建完整的对话历史
        # 首先，构建角色设定的初始提示
        initial_prompt = (
            f"You are now roleplaying as the character '{character.name}'. "
            f"Your personality is: {character.personality}. "
            f"Your appearance is: {character.appearance}. "
            f"Here is your background story: {character.description}. "
            "From this moment on, you must respond and act entirely as this character. Do not break character. "
            "Engage with the user naturally based on your defined traits."
        )

        # Gemini API 期望的格式是 [{"role": "user/model", "parts": [text]}]
        # 我们用一个 "system" instruction 来设定角色
        formatted_history = [
            # Gemini 没有 system role, 我们用 user/model 对来模拟
            {"role": "user", "parts": [initial_prompt]},
            {"role": "model", "parts": ["Understood. I am ready to embody the character and begin our conversation."]}
        ]

        # 从数据库获取此会话的所有历史消息 (除了刚刚收到的最新一条)
        # 注意：这里我们获取的是所有消息，包括最新的用户消息，因为下面会直接用 generate_content
        history_messages = Message.objects.filter(chat_session=chat_session).order_by('timestamp')

        for msg in history_messages:
            # 数据库中的 role ('assistant') 需要映射为 'model'
            role = 'model' if msg.role == 'assistant' else 'user'
            formatted_history.append({
                "role": role,
                "parts": [msg.content]
            })

        # 4. 调用 Gemini API 生成回复
        # 使用 generate_content 并传入完整的历史记录
        response = model.generate_content(formatted_history)
        ai_response_text = response.text
        
        # 5. 保存 AI 的回复到数据库
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
        # 记录详细错误，方便调试
        import traceback
        print(f"Error generating AI response: {str(e)}")
        print(traceback.format_exc())
        return {
            'success': False,
            'error': str(e)
        }