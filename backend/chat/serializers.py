import os

from rest_framework import serializers
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .attachments import get_message_attachments, get_primary_message_attachment
from .models import Character, CharacterKnowledgeAsset, ChatSession, Message, ModelConfiguration, TtsEngine, TtsServiceSettings, TtsVoiceModel, UserProfile, WebSearchConfiguration

class CharacterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Character
        fields = [
            'id', 'name', 'avatar_url', 'description', 'user_address',
            'scenario', 'example_dialogue', 'affiliation', 'tags', 'personality',
            'appearance', 'response_guidelines', 'file',
            'enable_web_search',
            'tts_config',
            'disabled_states', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class MessageAttachmentSerializer(serializers.Serializer):
    file_uri = serializers.SerializerMethodField()
    file_preview_url = serializers.SerializerMethodField()
    file_name = serializers.SerializerMethodField()
    file_type = serializers.SerializerMethodField()
    file_mime_type = serializers.SerializerMethodField()

    def get_file_uri(self, obj):
        file_obj = getattr(obj, 'file', None)
        if not file_obj:
            return None
        request = self.context.get('request')
        url = file_obj.url
        return request.build_absolute_uri(url) if request else url

    def get_file_preview_url(self, obj):
        return self.get_file_uri(obj)

    def get_file_name(self, obj):
        file_obj = getattr(obj, 'file', None)
        return getattr(obj, 'attachment_name', '') or os.path.basename(getattr(file_obj, 'name', '') or '')

    def get_file_type(self, obj):
        return getattr(obj, 'attachment_kind', '') or ''

    def get_file_mime_type(self, obj):
        return getattr(obj, 'attachment_mime_type', '') or ''


class CharacterKnowledgeAssetSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    file_name = serializers.SerializerMethodField()
    file_type = serializers.SerializerMethodField()
    file_mime_type = serializers.SerializerMethodField()

    class Meta:
        model = CharacterKnowledgeAsset
        fields = [
            'id',
            'file_url',
            'file_name',
            'file_type',
            'file_mime_type',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def get_file_url(self, obj):
        file_obj = getattr(obj, 'file', None)
        if not file_obj:
            return None
        request = self.context.get('request')
        url = file_obj.url
        return request.build_absolute_uri(url) if request else url

    def get_file_name(self, obj):
        file_obj = getattr(obj, 'file', None)
        return getattr(obj, 'attachment_name', '') or os.path.basename(getattr(file_obj, 'name', '') or '')

    def get_file_type(self, obj):
        return getattr(obj, 'attachment_kind', '') or ''

    def get_file_mime_type(self, obj):
        return getattr(obj, 'attachment_mime_type', '') or ''


class MessageSerializer(serializers.ModelSerializer):
    file_uri = serializers.SerializerMethodField()
    file_preview_url = serializers.SerializerMethodField()
    file_name = serializers.SerializerMethodField()
    file_type = serializers.SerializerMethodField()
    file_mime_type = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            'id', 'role', 'content', 'timestamp', 'character', 'research_payload',
            'thinking', 'tool_calls', 'token_usage',
            'file_uri', 'file_preview_url', 'file_name', 'file_type', 'file_mime_type', 'attachments',
        ]
        read_only_fields = ['timestamp']

    def get_file_uri(self, obj):
        attachment = get_primary_message_attachment(obj)
        if not attachment or not getattr(attachment, 'file', None):
            return None
        return MessageAttachmentSerializer(attachment, context=self.context).data['file_uri']

    def get_file_preview_url(self, obj):
        attachment = get_primary_message_attachment(obj)
        if not attachment or not getattr(attachment, 'file', None):
            return None
        return MessageAttachmentSerializer(attachment, context=self.context).data['file_preview_url']

    def get_file_name(self, obj):
        attachment = get_primary_message_attachment(obj)
        if not attachment:
            return ''
        return MessageAttachmentSerializer(attachment, context=self.context).data['file_name']

    def get_file_type(self, obj):
        attachment = get_primary_message_attachment(obj)
        if not attachment:
            return ''
        return MessageAttachmentSerializer(attachment, context=self.context).data['file_type']

    def get_file_mime_type(self, obj):
        attachment = get_primary_message_attachment(obj)
        if not attachment:
            return ''
        return MessageAttachmentSerializer(attachment, context=self.context).data['file_mime_type']

    def get_attachments(self, obj):
        return MessageAttachmentSerializer(get_message_attachments(obj), many=True, context=self.context).data


class ModelConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModelConfiguration
        fields = [
            'id', 'name', 'provider', 'model_name', 'api_key', 'base_url',
            'context_window', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate_context_window(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError('Context window must be a positive token count.')
        return value


class WebSearchConfigurationSerializer(serializers.ModelSerializer):
    def validate_provider(self, value):
        return (value or '').strip().lower() or 'tavily'

    def validate(self, attrs):
        instance = getattr(self, 'instance', None)

        if 'api_key' in attrs:
            attrs['api_key'] = (attrs.get('api_key') or '').strip()

        provider = attrs.get('provider', getattr(instance, 'provider', 'tavily')) or 'tavily'
        api_key = attrs.get('api_key', getattr(instance, 'api_key', ''))
        max_results = attrs.get('max_results', getattr(instance, 'max_results', 5))

        if provider != 'tavily':
            raise serializers.ValidationError({'provider': 'Only Tavily is supported right now.'})

        if not api_key:
            raise serializers.ValidationError({'api_key': 'API key is required.'})

        if max_results < 1 or max_results > 10:
            raise serializers.ValidationError({'max_results': 'Max results must be between 1 and 10.'})

        return attrs

    def create(self, validated_data):
        user = self.context['user']
        config, _ = WebSearchConfiguration.objects.update_or_create(
            user=user,
            defaults=validated_data,
        )
        return config

    class Meta:
        model = WebSearchConfiguration
        fields = [
            'id', 'provider', 'api_key', 'max_results',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class TtsServiceSettingsSerializer(serializers.ModelSerializer):
    """用户级 TTS 引擎设置。空字段 = 跟随环境变量默认（chat.tts.get_tts_config）。"""

    # 用 CharField 接住大小写变体（'GENIE'），validate 阶段再归一化并校验。
    default_provider = serializers.CharField(required=False, allow_blank=True)

    def validate_default_provider(self, value):
        provider = (value or '').strip().lower()
        if provider and provider not in {choice for choice, _ in TtsEngine.choices}:
            raise serializers.ValidationError(f'Unknown TTS engine: {provider}')
        return provider

    def _normalize_url(self, value):
        return (value or '').strip().rstrip('/')

    def validate(self, attrs):
        if 'genie_url' in attrs:
            attrs['genie_url'] = self._normalize_url(attrs.get('genie_url'))
        if 'gptsovits_url' in attrs:
            attrs['gptsovits_url'] = self._normalize_url(attrs.get('gptsovits_url'))
        if 'indextts_url' in attrs:
            attrs['indextts_url'] = self._normalize_url(attrs.get('indextts_url'))
        return attrs

    def create(self, validated_data):
        user = self.context['user']
        settings_row, _ = TtsServiceSettings.objects.update_or_create(
            user=user,
            defaults=validated_data,
        )
        return settings_row

    class Meta:
        model = TtsServiceSettings
        fields = ['default_provider', 'genie_url', 'gptsovits_url', 'indextts_url', 'updated_at']
        read_only_fields = ['updated_at']


# 与 chat.tts.TTS_MODEL_VERSION_ALIASES 一致：存量数据曾把 v2pro 写作 v2pr。
TTS_MODEL_VERSION_ALIASES = {'v2pr': 'v2pro'}


class TtsVoiceModelSerializer(serializers.ModelSerializer):
    """音色库条目。model_version 只做归一化不做枚举拦截：genie-tts 升级
    支持更多版本时后端无需改这里，兼容校验在合成时进行。"""

    # 用 CharField 接住大小写变体，validate 阶段再归一化并校验。
    engine = serializers.CharField()

    def validate_name(self, value):
        name = (value or '').strip()
        if not name:
            raise serializers.ValidationError('Name is required.')
        return name

    def validate_engine(self, value):
        engine = (value or '').strip().lower()
        valid = {choice for choice, _ in TtsEngine.choices}
        if engine not in valid:
            raise serializers.ValidationError(f'Unknown TTS engine: {engine}')
        return engine

    def validate_model_version(self, value):
        version = (value or '').strip().lower()
        return TTS_MODEL_VERSION_ALIASES.get(version, version)

    class Meta:
        model = TtsVoiceModel
        fields = [
            'id', 'name', 'engine', 'model_version', 'language', 'voice_name',
            'onnx_model_dir', 'ref_audio_path', 'ref_audio_text', 'ref_audio_language',
            'conversion_status', 'conversion_error',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'conversion_status', 'conversion_error', 'created_at', 'updated_at',
        ]


class UserProfileSerializer(serializers.ModelSerializer):
    def validate_timezone(self, value):
        normalized = (value or '').strip() or 'UTC'

        try:
            ZoneInfo(normalized)
        except ZoneInfoNotFoundError as exc:
            raise serializers.ValidationError('Enter a valid IANA timezone such as America/New_York.') from exc

        return normalized

    def validate(self, attrs):
        instance = getattr(self, 'instance', None)
        share_location = attrs.get('share_location', getattr(instance, 'share_location', False))
        share_weather = attrs.get('share_weather', getattr(instance, 'share_weather', False))
        location_label = (attrs.get('location_label', getattr(instance, 'location_label', '')) or '').strip()

        if 'location_label' in attrs:
            attrs['location_label'] = location_label

        if not share_location:
            attrs['location_label'] = ''
            attrs['share_weather'] = False
            return attrs

        if not location_label:
            raise serializers.ValidationError({
                'location_label': 'Location hint is required when location sharing is enabled.',
            })

        if share_weather and not location_label:
            raise serializers.ValidationError({
                'share_weather': 'Location sharing with a local location hint is required before weather context can be enabled.',
            })

        return attrs

    class Meta:
        model = UserProfile
        fields = [
            'id', 'avatar_url', 'preferred_name', 'pronouns', 'bio', 'default_enable_web_search', 'timezone',
            'interface_language', 'share_local_time', 'share_location',
            'location_precision', 'location_label', 'share_weather',
            'preferred_relationship_style', 'preferred_reply_length',
            'preferred_proactivity', 'preferred_emotional_intensity',
            'allow_long_term_memory', 'allow_preference_inference',
            'allow_research_profile_updates', 'blocked_topics',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ChatSessionSerializer(serializers.ModelSerializer):
    messages = MessageSerializer(many=True, read_only=True)
    character = CharacterSerializer(read_only=True)

    class Meta:
        model = ChatSession
        fields = [
            'id', 'character', 'user', 'title', 'messages', 'created_at', 'updated_at',
            'last_response_latency_ms', 'is_private_mode', 'origin', 'is_title_manual',
        ]
        read_only_fields = ['created_at', 'updated_at']


class ChatSessionWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatSession
        fields = ['character', 'title', 'is_private_mode']


class MessageCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['role', 'content', 'character']
