import strawberry
from typing import List, Optional
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.conf import settings
import google.generativeai as genai
import json
import logging
import os
import re
from urllib.parse import urlparse, unquote

from .types import CharacterType, ChatSessionType, CharacterInput, AICharacterDraft
from chat.models import Character, ChatSession
from chat.constants import DEFAULT_CHAT_SESSION_SETTINGS

logger = logging.getLogger(__name__)

@strawberry.input
class ChatSessionInput:
    character_id: strawberry.ID
    title: Optional[str] = ""
    world_time: Optional[str] = DEFAULT_CHAT_SESSION_SETTINGS["world_time"]
    user_persona: Optional[str] = DEFAULT_CHAT_SESSION_SETTINGS["user_persona"]
    enable_search: Optional[bool] = DEFAULT_CHAT_SESSION_SETTINGS["enable_web_search"]
    output_language: Optional[str] = DEFAULT_CHAT_SESSION_SETTINGS["output_language"]
    current_context: Optional[str] = DEFAULT_CHAT_SESSION_SETTINGS["additional_context"]

@strawberry.type
class Mutation:
    @strawberry.mutation
    async def generate_character_draft(self, file_url: Optional[str] = None, text_context: Optional[str] = None) -> AICharacterDraft:
        """
        Calls Gemini API to analyze text and return a structured Character Draft.
        Handles local file reading for .txt/.md/.json files to support "Auto-Create" from text files.
        """
        api_key = getattr(settings, 'GEMINI_API_KEY', '')
        if not api_key:
            return AICharacterDraft(
                name="Generation Failed",
                description="Server Error: GEMINI_API_KEY not found.",
                personality="", appearance="", affiliation="",
                first_message="", scenario="", tags=[], visual_summary=""
            )

        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.5-flash')

            file_content_str = ""
            
            if file_url:
                lower_url = file_url.lower()
                if lower_url.endswith('.txt') or lower_url.endswith('.md') or lower_url.endswith('.json'):
                    try:
                        parsed_url = urlparse(file_url)
                        # Remove '/media/' from the start of the path if present to join with MEDIA_ROOT
                        relative_path = unquote(parsed_url.path).lstrip('/')
                        if relative_path.startswith('media/'):
                            relative_path = relative_path[6:]
                        
                        file_path = os.path.join(settings.MEDIA_ROOT, relative_path)
                        
                        if os.path.exists(file_path):
                            with open(file_path, 'r', encoding='utf-8') as f:
                                file_content_str = f.read()
                            logger.info(f"Successfully read text file content from: {file_path}")
                        else:
                            logger.warning(f"File not found at path: {file_path}")
                    except Exception as e:
                        logger.error(f"Failed to read local text file: {e}")

            # Construct the Prompt
            prompt = """
            You are an expert Character Designer. 
            Analyze the provided context to extract specific character details.
            
            Return ONLY a raw JSON object (no markdown formatting) with the following keys:
            - name (string): Character name
            - description (string): A comprehensive background and summary (at least 3 sentences)
            - personality (string): Key personality traits
            - appearance (string): Physical description
            - affiliation (string): Organization or faction
            - first_message (string): An engaging opening line for a chat (Roleplay style)
            - scenario (string): The setting where the chat takes place
            - tags (list of strings): 3-6 keywords
            - visual_summary (string): Brief visual notes

            Context to analyze:
            """
            
            content_parts = [prompt]
            
            if text_context:
                content_parts.append(f"\n[User Input Context]:\n{text_context}")
            
            if file_content_str:
                content_parts.append(f"\n[Uploaded File Content]:\n{file_content_str}")
            
            # Generate
            response = await sync_to_async(model.generate_content)(content_parts)
            raw_text = response.text.strip()
            
            json_match = re.search(r"```(?:json)?\s*(.*?)```", raw_text, re.DOTALL)
            if json_match:
                raw_text = json_match.group(1).strip()
            
            data = json.loads(raw_text)

            return AICharacterDraft(
                name=data.get("name", "Unknown"),
                description=data.get("description", ""),
                personality=data.get("personality", ""),
                appearance=data.get("appearance", ""),
                affiliation=data.get("affiliation", ""),
                first_message=data.get("first_message", ""),
                scenario=data.get("scenario", ""),
                tags=data.get("tags", []),
                visual_summary=data.get("visual_summary", "")
            )

        except Exception as e:
            logger.error(f"AI Generation Error: {e}")
            return AICharacterDraft(
                name="Generation Failed",
                description=f"Error generating draft: {str(e)}",
                personality="", appearance="", affiliation="",
                first_message="", scenario="", tags=[], visual_summary=""
            )

    @strawberry.mutation
    async def create_character(self, info, input: CharacterInput) -> CharacterType:
        @sync_to_async
        def create_char_sync():
            user = info.context.request.user
            
            return Character.objects.create(
                name=input.name,
                avatar_url=input.avatar_url,
                description=input.description,
                personality=input.personality,
                appearance=input.appearance,
                first_message=input.first_message,
                scenario=input.scenario,
                example_dialogue=input.example_dialogue,
                affiliation=input.affiliation,
                tags=input.tags,
                created_by=user
            )
        return await create_char_sync()

    @strawberry.mutation
    async def delete_character(self, id: strawberry.ID) -> bool:
        @sync_to_async
        def delete_sync():
            try:
                character = Character.objects.get(pk=id)
                
                if character.chat_sessions.exists():
                    return False
                
                character.delete()
                return True
            except Character.DoesNotExist:
                return False
        return await delete_sync()

    @strawberry.mutation
    async def update_character(self, id: strawberry.ID, input: CharacterInput) -> CharacterType:
        @sync_to_async
        def update_char_sync():
            try:
                character = Character.objects.get(pk=id)
                character.name = input.name
                character.avatar_url = input.avatar_url
                character.description = input.description
                character.personality = input.personality
                character.appearance = input.appearance
                character.first_message = input.first_message
                character.scenario = input.scenario
                character.example_dialogue = input.example_dialogue
                character.affiliation = input.affiliation
                character.tags = input.tags
                character.save()
                return character
            except Character.DoesNotExist:
                raise Exception("Character not found")
        return await update_char_sync()

    @strawberry.mutation
    async def create_chat_session(self, info, input: ChatSessionInput) -> ChatSessionType:
        @sync_to_async
        def create_session_sync():
            try:
                character = Character.objects.get(pk=input.character_id)
                
                user = info.context.request.user

                return ChatSession.objects.create(
                    character=character,
                    user=user,
                    title=input.title or f"Chat with {character.name}",
                    world_time=input.world_time,
                    user_persona=input.user_persona,
                    enable_web_search=input.enable_search,
                    output_language=input.output_language,
                    additional_context=input.current_context
                )
            except Character.DoesNotExist:
                raise Exception("Character not found")
        return await create_session_sync()

    @strawberry.mutation
    async def update_chat_session(self, id: strawberry.ID, input: ChatSessionInput) -> ChatSessionType:
        @sync_to_async
        def update_session_sync():
            try:
                session = ChatSession.objects.get(pk=id)
                session.title = input.title or session.title
                session.world_time = input.world_time
                session.user_persona = input.user_persona
                session.enable_web_search = input.enable_search
                session.output_language = input.output_language
                session.additional_context = input.current_context
                session.save()
                return session
            except ChatSession.DoesNotExist:
                raise Exception("Chat session not found")
        return await update_session_sync()

@strawberry.type
class Query:
    @strawberry.django.field
    def characters(self) -> List[CharacterType]:
        return Character.objects.all()
    
    @strawberry.django.field
    def character(self, id: strawberry.ID) -> CharacterType:
        try:
            return Character.objects.get(pk=id)
        except Character.DoesNotExist:
            raise Exception("Character not found")
        
    @strawberry.django.field
    def chat_sessions(self) -> List[ChatSessionType]:
        return ChatSession.objects.all().order_by('-updated_at')
    
    @strawberry.django.field
    def chat_session(self, id: strawberry.ID) -> ChatSessionType:
        try:
            return ChatSession.objects.get(pk=id)
        except ChatSession.DoesNotExist:
            raise Exception("Chat session not found")

schema = strawberry.Schema(query=Query, mutation=Mutation)