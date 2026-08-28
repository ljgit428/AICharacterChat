from django.core.validators import MaxLengthValidator
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

LONG_TERM_MEMORY_DESC_LIMIT = 200


def get_default_disabled_states():
    return {
        "name": False,
        "description": False,
        "personality": False,
        "appearance": False,
        "responseGuidelines": False,
        "file": False,
    }


class ModelProvider(models.TextChoices):
    GEMINI = "gemini", "Gemini"
    OPENAI_COMPATIBLE = "openai_compatible", "OpenAI Compatible"
    ANTHROPIC = "anthropic", "Anthropic"


class ModelRole(models.TextChoices):
    TEXT = "text", "Text chat"
    IMAGE = "image", "Image understanding"
    AUDIO = "audio", "Audio understanding"
    VIDEO = "video", "Video understanding"


class WebSearchProvider(models.TextChoices):
    TAVILY = "tavily", "Tavily"


class TtsEngine(models.TextChoices):
    GENIE = "genie", "Genie-TTS (GPT-SoVITS ONNX)"
    GPTSOVITS = "gptsovits", "GPT-SoVITS api_v2"
    INDEXTTS = "indextts", "IndexTTS"


class AttachmentKind(models.TextChoices):
    TEXT = "text", "Text"
    IMAGE = "image", "Image"
    AUDIO = "audio", "Audio"
    VIDEO = "video", "Video"


class LocationPrecision(models.TextChoices):
    REGION = "region", "Region"
    CITY = "city", "City"
    EXACT = "exact", "Exact"


class ReplyLengthPreference(models.TextChoices):
    SHORT = "short", "Short"
    MEDIUM = "medium", "Medium"
    LONG = "long", "Long"


class PreferenceLevel(models.TextChoices):
    LOW = "low", "Low"
    NORMAL = "normal", "Normal"
    HIGH = "high", "High"


class ModelConfiguration(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="model_configurations")
    name = models.CharField(max_length=100)
    provider = models.CharField(max_length=32, choices=ModelProvider.choices, default=ModelProvider.OPENAI_COMPATIBLE)
    model_name = models.CharField(max_length=255)
    api_key = models.CharField(max_length=500, blank=True)
    base_url = models.URLField(max_length=500, blank=True, default="")
    context_window = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        help_text="Model context window in tokens; powers the accurate context-usage indicator.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["user", "name"], name="unique_model_configuration_name_per_user"),
        ]

    def __str__(self):
        return f"{self.name} ({self.model_name})"


class ModelRoleAssignment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="model_role_assignments")
    role = models.CharField(max_length=16, choices=ModelRole.choices)
    model_config = models.ForeignKey(ModelConfiguration, on_delete=models.CASCADE, related_name="role_assignments")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["role"]
        constraints = [
            models.UniqueConstraint(fields=["user", "role"], name="unique_model_role_assignment_per_user"),
        ]

    def __str__(self):
        return f"{self.user_id}:{self.role} -> {self.model_config_id}"

    @classmethod
    def get_role_config(cls, user, role):
        assignment = cls.objects.select_related("model_config").filter(user=user, role=role).first()
        return assignment.model_config if assignment else None

    @classmethod
    def get_role_configs(cls, user):
        """Return {role: ModelConfiguration} for all assigned roles."""
        assignments = cls.objects.select_related("model_config").filter(user=user)
        return {assignment.role: assignment.model_config for assignment in assignments}


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    avatar_url = models.URLField(max_length=500, blank=True, default="")
    preferred_name = models.CharField(max_length=100, blank=True, default="")
    pronouns = models.CharField(max_length=50, blank=True, default="")
    bio = models.TextField(blank=True, default="")
    default_enable_web_search = models.BooleanField(default=False)
    timezone = models.CharField(max_length=64, blank=True, default="UTC")
    interface_language = models.CharField(max_length=50, blank=True, default="zh-CN")
    share_local_time = models.BooleanField(default=True)
    share_location = models.BooleanField(default=False)
    location_precision = models.CharField(
        max_length=16,
        choices=LocationPrecision.choices,
        default=LocationPrecision.CITY,
    )
    location_label = models.CharField(max_length=255, blank=True, default="")
    share_weather = models.BooleanField(default=False)
    preferred_relationship_style = models.CharField(max_length=64, blank=True, default="")
    preferred_reply_length = models.CharField(
        max_length=16,
        choices=ReplyLengthPreference.choices,
        default=ReplyLengthPreference.MEDIUM,
    )
    preferred_proactivity = models.CharField(
        max_length=16,
        choices=PreferenceLevel.choices,
        default=PreferenceLevel.NORMAL,
    )
    preferred_emotional_intensity = models.CharField(
        max_length=16,
        choices=PreferenceLevel.choices,
        default=PreferenceLevel.NORMAL,
    )
    allow_long_term_memory = models.BooleanField(default=True)
    allow_preference_inference = models.BooleanField(default=True)
    allow_research_profile_updates = models.BooleanField(default=False)
    blocked_topics = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user_id"]

    def __str__(self):
        return f"Profile for {self.user.username}"

    @classmethod
    def get_or_create_for_user(cls, user):
        profile, _ = cls.objects.get_or_create(user=user)
        return profile


class WebSearchConfiguration(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="web_search_configuration")
    provider = models.CharField(
        max_length=32,
        choices=WebSearchProvider.choices,
        default=WebSearchProvider.TAVILY,
    )
    api_key = models.CharField(max_length=500, blank=True, default="")
    max_results = models.PositiveSmallIntegerField(default=5)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user_id"]

    def __str__(self):
        return f"Web search for {self.user.username} ({self.provider})"

    @classmethod
    def get_for_user(cls, user):
        return cls.objects.filter(user=user).first()


class TtsServiceSettings(models.Model):
    """用户级 TTS 引擎服务设置（设置界面「语音设置」）。

    只存引擎服务地址与默认 provider；引擎本身仍是独立进程，Django 不背
    推理栈。字段为空 = 跟随环境变量默认（chat.tts.get_tts_config），保存
    后覆盖 env。
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="tts_service_settings")
    default_provider = models.CharField(max_length=16, choices=TtsEngine.choices, blank=True, default="")
    genie_url = models.CharField(max_length=500, blank=True, default="")
    gptsovits_url = models.CharField(max_length=500, blank=True, default="")
    indextts_url = models.CharField(max_length=500, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user_id"]

    def __str__(self):
        return f"TTS settings for {self.user.username}"

    @classmethod
    def get_for_user(cls, user):
        return cls.objects.filter(user=user).first()


class TtsVoiceModel(models.Model):
    """音色库：设置页统一登记的语音模型，角色通过 tts_config.voice_model_id 引用。

    engine=gptsovits 只需参考音频（api_v2 支持全部模型版本）；engine=genie
    需要 onnx_model_dir。model_version 存自由值、API 层不做兼容拦截——
    上传转换照单全收，genie 不支持时透传其报错；genie-tts 升级支持更多
    版本时只需更新 chat/tts.py 的 GENIE_SUPPORTED_MODEL_VERSIONS。
    """

    class ConversionStatus(models.TextChoices):
        READY = "ready", "Ready"
        PENDING = "pending", "Pending conversion"
        CONVERTING = "converting", "Converting"
        FAILED = "failed", "Conversion failed"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="tts_voice_models")
    name = models.CharField(max_length=100)
    engine = models.CharField(max_length=16, choices=TtsEngine.choices, default=TtsEngine.GENIE)
    model_version = models.CharField(max_length=16, blank=True, default="", help_text="v2 / v2pro / v2proplus / v4，空=未指定")
    language = models.CharField(max_length=8, blank=True, default="", help_text="模型语言 zh/jp/en/ko")
    voice_name = models.CharField(max_length=100, blank=True, default="", help_text="genie 侧音色键，空则取 ONNX 目录名")
    onnx_model_dir = models.CharField(max_length=500, blank=True, default="", help_text="genie 通道：convert_to_onnx 输出目录")
    ref_audio_path = models.CharField(max_length=500, blank=True, default="", help_text="参考音频服务器路径（绝对路径或 MEDIA_ROOT 相对路径）")
    ref_audio_text = models.TextField(blank=True, default="")
    ref_audio_language = models.CharField(max_length=8, blank=True, default="")
    # 情感组属于音色资产：每种情感一份参考音频，合成时按情感名切换。
    # 角色 tts_config.emotions 仍可覆盖（旧角色数据兼容），这里为空时使用。
    emotions = models.JSONField(
        default=list,
        blank=True,
        help_text="情感组列表：[{name, ref_audio_path, ref_audio_text, ref_audio_language}]",
    )
    conversion_status = models.CharField(max_length=16, choices=ConversionStatus.choices, blank=True, default="")
    conversion_job_id = models.CharField(max_length=64, blank=True, default="")
    conversion_error = models.TextField(blank=True, default="")
    source_ckpt_path = models.CharField(max_length=500, blank=True, default="", help_text="上传的 T2S .ckpt（转换源）")
    source_pth_path = models.CharField(max_length=500, blank=True, default="", help_text="上传的 VITS .pth（转换源）")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["user", "name"], name="unique_tts_voice_model_name_per_user"),
        ]

    def __str__(self):
        return f"{self.name} ({self.engine})"


class Character(models.Model):
    id = models.AutoField(primary_key=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="characters")
    created_at = models.DateTimeField(auto_now_add=True)

    name = models.CharField(max_length=100)
    avatar_url = models.URLField(max_length=500, blank=True, null=True)
    description = models.TextField(help_text="The core personality and visual description.")
    user_address = models.CharField(max_length=100, blank=True, default="", help_text="How this character prefers to address the user.")
    scenario = models.TextField(blank=True, default="", help_text="Default context/environment.")
    example_dialogue = models.TextField(blank=True, default="", help_text="<START> User: ... Char: ...")
    affiliation = models.TextField(blank=True, default="", help_text="Character's organization or faction.")
    tags = models.JSONField(default=list, blank=True)

    personality = models.TextField(blank=True, null=True)
    appearance = models.TextField(blank=True, null=True)
    response_guidelines = models.TextField(blank=True, null=True)
    system_prompt_preview = models.TextField(
        blank=True,
        default="",
        help_text="Editable character setup block injected into the system prompt.",
    )
    file = models.FileField(upload_to='character_files/', blank=True, null=True)
    disabled_states = models.JSONField(default=get_default_disabled_states)
    # 角色级联网搜索开关（三态）：None=跟随用户全局设置 default_enable_web_search；
    # True/False=强制覆盖。创建与编辑角色时可在表单中选择。
    enable_web_search = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        help_text="Per-character web search override. None follows the user's global default.",
    )
    # 角色级语音模型配置（TTS）——语音模型配置的唯一入口，全部字段都在角色
    # 编辑界面的"语音模型"区块：引擎、GPT-SoVITS 模型版本（v2/v2pro/v2proplus/v4）、
    # TTS 服务内音色名、ONNX 模型目录、参考音频及台词。空 dict = 未配置，
    # 合成时回退到全局 TTS_PROVIDER 默认音色。
    tts_config = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class CharacterKnowledgeAsset(models.Model):
    character = models.ForeignKey(Character, on_delete=models.CASCADE, related_name='knowledge_assets')
    file = models.FileField(upload_to='character_knowledge_assets/')
    attachment_name = models.CharField(max_length=255, blank=True, default="")
    attachment_mime_type = models.CharField(max_length=100, blank=True, default="")
    attachment_kind = models.CharField(max_length=16, choices=AttachmentKind.choices, blank=True, default="")
    attachment_text_content = models.TextField(blank=True, default="")
    media_analysis = models.TextField(blank=True, default="")
    gemini_file_name = models.TextField(blank=True, default="")
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f"{self.character.name}: {self.attachment_name or self.file.name}"


class ChatSession(models.Model):
    ORIGIN_CHOICES = [
        ('topic', 'Topic workspace'),
        ('chat', 'Discord-style chat page'),
    ]

    character = models.ForeignKey(Character, on_delete=models.CASCADE, related_name='chat_sessions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_sessions')
    title = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_generating_response = models.BooleanField(default=False)
    last_response_latency_ms = models.PositiveIntegerField(blank=True, null=True)
    is_private_mode = models.BooleanField(
        default=False,
        help_text='Per-session override: when true, the long-term memory pipeline skips writes for turns in this session.',
    )
    origin = models.CharField(
        max_length=10,
        choices=ORIGIN_CHOICES,
        default='topic',
        help_text='Which interface created this session; the two interfaces keep independent session pools.',
    )
    is_title_manual = models.BooleanField(
        default=False,
        help_text='When true, the auto title generator must not overwrite this title.',
    )

    def __str__(self):
        return f"{self.title or f'Chat with {self.character.name}'} - {self.user.username}"


class Message(models.Model):
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
    ]

    chat_session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    character = models.ForeignKey(Character, on_delete=models.CASCADE, related_name='messages', null=True, blank=True)
    research_payload = models.JSONField(default=dict, blank=True)
    thinking = models.TextField(
        blank=True,
        default="",
        help_text="Model native reasoning text (e.g. DeepSeek reasoning_content) captured during streaming.",
    )
    tool_calls = models.JSONField(
        default=list,
        blank=True,
        help_text="List of {tool, arguments} dicts executed while producing this reply.",
    )
    token_usage = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Normalized LLM usage for this reply: "
            "{prompt_tokens, completion_tokens, total_tokens, cached_tokens}."
        ),
    )
    attachment = models.FileField(upload_to='chat_attachments/', blank=True, null=True)
    attachment_name = models.CharField(max_length=255, blank=True, default="")
    attachment_mime_type = models.CharField(max_length=100, blank=True, default="")
    attachment_kind = models.CharField(max_length=16, choices=AttachmentKind.choices, blank=True, default="")
    attachment_text_content = models.TextField(blank=True, default="")

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"{self.role}: {self.content[:50]}..."


class MessageAttachment(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='chat_attachments/')
    attachment_name = models.CharField(max_length=255, blank=True, default="")
    attachment_mime_type = models.CharField(max_length=100, blank=True, default="")
    attachment_kind = models.CharField(max_length=16, choices=AttachmentKind.choices, blank=True, default="")
    attachment_text_content = models.TextField(blank=True, default="")
    media_analysis = models.TextField(blank=True, default="")
    gemini_file_name = models.TextField(blank=True, default="")
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f"{self.message_id}: {self.attachment_name or self.file.name}"


class MemoryAuditSource(models.TextChoices):
    CELERY_WORKER = 'celery_worker', 'Celery worker'
    USER_EDIT = 'user_edit', 'User edit'


class MemoryAuditAction(models.TextChoices):
    CREATE = 'create', 'Create'
    UPDATE = 'update', 'Update'
    DELETE = 'delete', 'Delete'
    MERGE = 'merge', 'Merge'


class CharacterMemoryItem(models.Model):
    """A single long-term-memory entry the AI has learned about the user.

    Mirrors SonettoHer's ``MemoryItem``: short_id + section + description +
    per-entry history. Free-form section names (the model picks and reuses).
    The system prompt sees this collection as ``wiki/memory.md``.
    """

    character = models.ForeignKey(
        Character,
        on_delete=models.CASCADE,
        related_name='memory_items',
    )
    short_id = models.CharField(
        max_length=8,
        help_text='4-byte hex id, stable for the lifetime of the entry.',
    )
    section = models.CharField(
        max_length=64,
        help_text='Free-form section name picked and reused by the model. Composite index on (character, section) is created below.',
    )
    description = models.TextField(
        validators=[MaxLengthValidator(LONG_TERM_MEMORY_DESC_LIMIT)],
        help_text='Current description. Hard limit 200 visible characters (Chinese counts as one).',
    )
    description_history = models.JSONField(
        default=list,
        blank=True,
        help_text='List of {old_desc, new_desc, reason, old_section, new_section, old_time, new_time} dicts.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['section', 'short_id']
        constraints = [
            models.UniqueConstraint(fields=['character', 'short_id'], name='unique_memory_short_id_per_character'),
        ]
        indexes = [
            models.Index(fields=['character', 'section']),
            models.Index(fields=['character', 'updated_at']),
        ]

    def __str__(self):
        return f"[{self.short_id}] {self.section}: {self.description[:40]}"


class ChatEventType(models.TextChoices):
    """The append-only event vocabulary for a chat session's conversation log.

    Every conversation fact that must survive reload/replay is recorded as one
    of these events. ``Message`` rows are a materialized projection of this
    log (see ``chat.events.projection``); this table is the single source of
    truth. ``ChatSession`` metadata (title / origin / private mode / latency)
    deliberately stays outside the log — it is session header state, not a
    conversation event (deepseek-harness SessionHeader principle).
    """

    SESSION_CREATED = 'session/created', 'Session created'
    USER_MESSAGE = 'user/message', 'User message'
    ASSISTANT_MESSAGE = 'assistant/message', 'Assistant message'
    COMPACTION_SUMMARY = 'compaction/summary', 'Compacted-history summary'


class ChatEvent(models.Model):
    """One append-only entry in a chat session's event log.

    ``seq`` is monotonic per ``chat_session`` (allocated inside a transaction
    by ``EventStore.append``) and ``data`` is a lossless JSON payload. Events
    are never updated or deleted — compaction appends a ``compaction/summary``
    event that *shadows* a seq range instead.
    """

    chat_session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name='events',
    )
    character = models.ForeignKey(
        Character,
        on_delete=models.CASCADE,
        related_name='events',
        null=True,
        blank=True,
    )
    seq = models.PositiveIntegerField()
    event_type = models.CharField(max_length=40, choices=ChatEventType.choices)
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['seq']
        constraints = [
            models.UniqueConstraint(
                fields=['chat_session', 'seq'],
                name='unique_chat_event_seq_per_session',
            ),
        ]
        indexes = [
            models.Index(fields=['chat_session', 'seq']),
            models.Index(fields=['character', 'seq']),
        ]

    def __str__(self):
        return f"{self.event_type} #{self.seq} [{self.chat_session_id}]"


class MemoryAuditLog(models.Model):
    """Append-only log of who created/updated/deleted/merged memory entries."""

    character = models.ForeignKey(
        Character,
        on_delete=models.CASCADE,
        related_name='memory_audit_log',
    )
    chat_session = models.ForeignKey(
        ChatSession,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='memory_audit_log',
    )
    message = models.ForeignKey(
        Message,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='memory_audit_log',
    )
    action = models.CharField(max_length=16, choices=MemoryAuditAction.choices)
    entry_short_id = models.CharField(max_length=8, blank=True, default='')
    before_description = models.TextField(blank=True, default='')
    after_description = models.TextField(blank=True, default='')
    reason = models.TextField(blank=True, default='')
    source = models.CharField(max_length=16, choices=MemoryAuditSource.choices, default=MemoryAuditSource.CELERY_WORKER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['character', '-created_at']),
        ]

    def __str__(self):
        return f"{self.action} [{self.entry_short_id}] for {self.character_id}"
