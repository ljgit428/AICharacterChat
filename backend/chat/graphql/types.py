import strawberry
from strawberry.scalars import JSON
from typing import List, Optional
import os
from asgiref.sync import sync_to_async
import strawberry_django
from chat.models import AttachmentKind, Character, ChatSession, CharacterKnowledgeAsset


@strawberry.type
class PrisMateDraft:
    name: str
    description: str
    personality: str
    appearance: str
    affiliation: str
    tags: List[str]
    visual_summary: str
    example_dialogue: str = ""


@strawberry.type
class CharacterDraftJobType:
    """后台草稿任务：前端启动后轮询本类型直到终态。"""

    id: strawberry.ID
    status: str
    stage: str
    progress_done: int
    progress_total: int
    error: Optional[str]
    result: Optional[PrisMateDraft]
    created_at: Optional[str]


def _serialize_character_draft_job(job) -> CharacterDraftJobType:
    return CharacterDraftJobType(
        id=str(job.id),
        status=job.status,
        stage=job.stage or "",
        progress_done=job.progress_done,
        progress_total=job.progress_total,
        error=job.error or None,
        result=PrisMateDraft(**job.result) if job.result else None,
        created_at=job.created_at.isoformat() if job.created_at else None,
    )

@strawberry.input
class CharacterKnowledgeAssetInput:
    """One staged upload to attach to the character.

    ``upload_id`` is the ``asset/uploaded`` AssetEvent id returned by the
    upload endpoint; ``file_name`` preserves the folder-group relative path.
    ``uploaded_url`` is kept for backward compatibility with older clients.
    """

    upload_id: Optional[str] = ""
    file_name: str = ""
    uploaded_url: Optional[str] = ""


@strawberry.input
class CharacterInput:
    name: str
    # 头像在 UI 上是可选项（“可选，但强烈建议添加”）；之前是必填 String!，
    # 与产品文案矛盾（2026-08-24 GUI 导入实测发现）。
    avatar_url: Optional[str] = ""
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
    # 编辑时明确删除的已有资产 id（增量 diff；None/缺省 = 不动资产）
    detached_asset_ids: Optional[List[str]] = None
    # 角色级联网搜索三态开关：None=跟随用户全局设置
    enable_web_search: Optional[bool] = None
    # 角色级语音模型配置（引擎/模型版本/音色名/ONNX 目录/参考音频）
    tts_config: Optional[JSON] = None


@strawberry.type
class CharacterKnowledgeAssetType:
    asset_id: Optional[str]
    file_url: str
    file_name: str
    file_type: str
    file_mime_type: str


def _serialize_character_knowledge_asset(asset: CharacterKnowledgeAsset) -> CharacterKnowledgeAssetType:
    return CharacterKnowledgeAssetType(
        asset_id=str(asset.id),
        file_url=asset.file.url if asset.file else "",
        file_name=asset.attachment_name or os.path.basename(asset.file.name or ""),
        file_type=asset.attachment_kind or "",
        file_mime_type=asset.attachment_mime_type or "",
    )


def _primary_text_knowledge_asset(character: Character) -> Optional[CharacterKnowledgeAsset]:
    return character.knowledge_assets.filter(
        attachment_kind=AttachmentKind.TEXT,
    ).order_by('sort_order', 'id').first()

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
    # 角色级联网搜索三态开关（None=跟随用户全局设置）
    enable_web_search: Optional[bool]
    # 角色级语音模型配置（引擎/模型版本/音色名/ONNX 目录/参考音频）
    tts_config: Optional[JSON]

    @strawberry.field
    async def background_file_url(self) -> Optional[str]:
        asset = await sync_to_async(_primary_text_knowledge_asset)(self)
        if asset and asset.file:
            try:
                return asset.file.url
            except ValueError:
                return None

        # Legacy fallback for characters that only carry a `Character.file` row.
        if self.file:
            try:
                return self.file.url
            except ValueError:
                return None
        return None

    @strawberry.field
    async def background_file_name(self) -> Optional[str]:
        asset = await sync_to_async(_primary_text_knowledge_asset)(self)
        if asset and asset.file:
            return asset.attachment_name or os.path.basename(asset.file.name or "")

        if self.file:
            return os.path.basename(self.file.name or "")
        return None

    @strawberry.field
    async def knowledge_assets(self) -> List[CharacterKnowledgeAssetType]:
        assets = await sync_to_async(list)(self.knowledge_assets.all())
        if assets:
            return [_serialize_character_knowledge_asset(asset) for asset in assets]

        if not self.file:
            return []

        return [
            CharacterKnowledgeAssetType(
                asset_id=None,
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
