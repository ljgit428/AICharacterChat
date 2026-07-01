import strawberry
from typing import List, Optional
import os
from asgiref.sync import sync_to_async

@strawberry.type
class AICharacterDraft:
    name: str
    description: str
    personality: str
    appearance: str
    affiliation: str
    tags: List[str]
    visual_summary: str
    example_dialogue: str = ""

@strawberry.input
class CharacterKnowledgeAssetInput:
    uploaded_url: str
    file_name: str


@strawberry.input
class CharacterInput:
    name: str
    avatar_url: str
    description: str
    user_address: Optional[str] = ""
    personality: Optional[str] = ""
    appearance: Optional[str] = ""
    response_guidelines: Optional[str] = ""
    scenario: str
    example_dialogue: str
    affiliation: Optional[str] = ""
    system_prompt_preview: Optional[str] = ""
    tags: List[str]
    background_file_url: Optional[str] = ""
    background_file_name: Optional[str] = ""
    background_files: Optional[List[CharacterKnowledgeAssetInput]] = None

from chat.models import Character, ChatSession, CharacterKnowledgeAsset
import strawberry_django


@strawberry.type
class CharacterKnowledgeAssetType:
    file_url: str
    file_name: str
    file_type: str
    file_mime_type: str


def _serialize_character_knowledge_asset(asset: CharacterKnowledgeAsset) -> CharacterKnowledgeAssetType:
    return CharacterKnowledgeAssetType(
        file_url=asset.file.url if asset.file else "",
        file_name=asset.attachment_name or os.path.basename(asset.file.name or ""),
        file_type=asset.attachment_kind or "",
        file_mime_type=asset.attachment_mime_type or "",
    )

@strawberry_django.type(Character)
class CharacterType:
    id: strawberry.ID
    name: str
    avatar_url: Optional[str]
    description: str
    user_address: str
    personality: Optional[str]
    appearance: Optional[str]
    response_guidelines: Optional[str]
    scenario: str
    example_dialogue: str
    affiliation: str
    system_prompt_preview: str
    tags: List[str]

    @strawberry.field
    def background_file_url(self) -> Optional[str]:
        if not self.file:
            return None
        try:
            return self.file.url
        except ValueError:
            return None

    @strawberry.field
    def background_file_name(self) -> Optional[str]:
        if not self.file:
            return None
        return os.path.basename(self.file.name or "")

    @strawberry.field
    async def knowledge_assets(self) -> List[CharacterKnowledgeAssetType]:
        assets = await sync_to_async(list)(self.knowledge_assets.all())
        if assets:
            return [_serialize_character_knowledge_asset(asset) for asset in assets]

        if not self.file:
            return []

        return [
            CharacterKnowledgeAssetType(
                file_url=self.file.url,
                file_name=os.path.basename(self.file.name or ""),
                file_type='text',
                file_mime_type='text/plain',
            )
        ]

@strawberry_django.type(ChatSession)
class ChatSessionType:
    id: strawberry.ID
    title: str
    last_response_latency_ms: Optional[int]
    character: CharacterType
