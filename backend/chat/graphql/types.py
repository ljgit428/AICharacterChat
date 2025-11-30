import strawberry
from typing import List, Optional

@strawberry.type
class AICharacterDraft:
    name: str
    description: str
    personality: str  
    appearance: str   
    affiliation: str  
    first_message: str
    scenario: str
    tags: List[str]
    visual_summary: str

@strawberry.input
class CharacterInput:
    name: str
    avatar_url: str
    description: str
    personality: Optional[str] = ""
    appearance: Optional[str] = ""
    first_message: str
    scenario: str
    example_dialogue: str
    affiliation: Optional[str] = ""
    tags: List[str]

from chat.models import Character, ChatSession
import strawberry_django

@strawberry_django.type(Character)
class CharacterType:
    id: strawberry.ID
    name: str
    avatar_url: Optional[str]
    description: str
    personality: Optional[str]
    appearance: Optional[str]
    first_message: str
    scenario: str
    example_dialogue: str
    affiliation: str
    tags: List[str]

@strawberry_django.type(ChatSession)
class ChatSessionType:
    id: strawberry.ID
    title: str
    world_time: Optional[str]
    user_persona: str
    enable_search: bool
    output_language: str
    current_context: Optional[str]
    character: CharacterType