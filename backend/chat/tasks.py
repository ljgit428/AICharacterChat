from celery import shared_task
import sys
from django.conf import settings
import google.generativeai as genai
from .models import Message, Character, ChatSession, CharacterFile


@shared_task
def generate_ai_response(message_id, character_id):
    """
    Generate AI response using Gemini API, referencing multiple uploaded files for context.
    """
    print(f"Task started for message_id={message_id}, character_id={character_id}")
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
        model = genai.GenerativeModel('gemini-1.5-pro-latest')

        # --- 新逻辑：构建包含多个文件引用的 Prompt ---
        prompt_parts = []
        
        # 1. 获取所有关联的文件引用
        character_files = CharacterFile.objects.filter(character_id=character_id)
        if character_files:
            print(f"Found {character_files.count()} background files for character.")
            for char_file in character_files:
                try:
                    # 从引用ID获取文件对象并添加到 prompt
                    file_for_prompt = genai.get_file(name=char_file.gemini_file_ref)
                    prompt_parts.append(file_for_prompt)
                except Exception as e:
                    print(f"Could not retrieve file {char_file.gemini_file_ref} from Gemini: {e}")

        # 2. 构建基础的角色设定文本 (放到 prompt_parts 的开头)
        prompt_text = (
            f"You are roleplaying as '{character.name}'.\n"
            f"Personality: {character.personality}\n"
            f"Appearance: {character.appearance}\n"
            f"Background: {character.description}\n"
            "You must respond and act entirely as this character. "
            "Use the information in the provided documents to enrich your responses, "
            "treating them as your own knowledge or memory. Do not mention the documents themselves."
        )
        prompt_parts.insert(0, prompt_text)

        # 3. 构建完整的对话历史
        formatted_history = [
            {"role": "user", "parts": prompt_parts},
            {"role": "model", "parts": ["Understood. I am ready."]}
        ]
        
        # 从数据库获取此会话的所有历史消息 (除了刚刚收到的最新一条)
        history_messages = Message.objects.filter(chat_session=chat_session).order_by('timestamp')

        for msg in history_messages:
            # 数据库中的 role ('assistant') 需要映射为 'model'
            role = 'model' if msg.role == 'assistant' else 'user'
            formatted_history.append({
                "role": role,
                "parts": [msg.content]
            })

        # 4. 调用 Gemini API 生成回复
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