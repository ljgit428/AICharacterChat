import json
import os
from pathlib import Path
from uuid import uuid4

import requests
from django.conf import settings
from django.core.files.storage import default_storage
from django.http import HttpResponse, StreamingHttpResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .attachments import extract_text_attachment_content, guess_attachment_kind, validate_attachment_size
from . import asr as chat_asr
from . import tts as chat_tts
from .cleanup import cleanup_character_files
from .memory.interface import LongTermMemoryInterface as CharacterLongTermMemory
from .memory.manager import MemoryItemNotFoundError, MemoryManager
from .events.store import EventStore
from .events.types import user_message_payload, assistant_message_payload
from .models import (
    AttachmentKind,
    Character,
    CharacterKnowledgeAsset,
    ChatEventType,
    ChatSession,
    MemoryAuditSource,
    Message,
    MessageAttachment,
    ModelConfiguration,
    ModelRole,
    ModelRoleAssignment,
    TtsEngine,
    TtsServiceSettings,
    TtsVoiceModel,
    UserProfile,
    WebSearchConfiguration,
)
from .model_catalog import probe_provider_models
from .search import search_web
from .serializers import (
    CharacterSerializer,
    CharacterKnowledgeAssetSerializer,
    ChatSessionSerializer,
    ChatSessionWriteSerializer,
    MessageSerializer,
    MessageCreateSerializer,
    ModelConfigurationSerializer,
    TtsServiceSettingsSerializer,
    TtsVoiceModelSerializer,
    UserProfileSerializer,
    WebSearchConfigurationSerializer,
)
from .tasks import generate_ai_response, stream_ai_response
from .file_views import sanitize_relative_path
from .soul import list_memory_explorer_path, read_memory_explorer_file, sanitize_memory_relative_path
import logging

logger = logging.getLogger(__name__)


def _message_serializer(message, request):
    return MessageSerializer(message, context={'request': request})


def _persist_attachment_files(attachment_payloads):
    """Save uploaded files to the chat-attachments storage.

    Each payload dict has a ``file`` key (the uploaded file object) that is
    replaced by the resulting storage name (``file_name``) so the event
    payload can reference it. The projection recreates ``MessageAttachment``
    rows from those names without re-saving the bytes.
    """
    persisted = []
    for payload in attachment_payloads:
        file_obj = payload.pop('file', None)
        saved_name = ''
        if file_obj:
            saved_name = default_storage.save(
                os.path.join('chat_attachments', os.path.basename(file_obj.name or 'uploaded_file')),
                file_obj,
            )
        persisted.append({
            **payload,
            'file_name': saved_name,
        })
    return persisted


def _get_required_model_config(user, model_config_id=None):
    if model_config_id not in [None, "", "null"]:
        model_config = ModelConfiguration.objects.get(id=model_config_id, user=user)
    else:
        model_config = ModelRoleAssignment.get_role_config(user, ModelRole.TEXT) or (
            ModelConfiguration.objects.filter(user=user).order_by('id').first()
        )

    if not model_config:
        raise ValueError('Please configure your own model API in Project Settings before starting a chat.')

    # Gemini/Anthropic 必须显式 api_key；openai_compatible 允许本地反代网关自鉴权，所以这里放过。
    if not model_config.api_key and model_config.provider in {'gemini', 'anthropic'}:
        raise ValueError('The selected model configuration is missing an API key.')

    return model_config
class CharacterViewSet(viewsets.ModelViewSet):
    queryset = Character.objects.all()
    serializer_class = CharacterSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Character.objects.filter(created_by=self.request.user)

    def perform_create(self, serializer):
        user = self.request.user
        serializer.save(created_by=user)

    def perform_update(self, serializer):
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        character = self.get_object()
        # 先清磁盘文件（头像、知识资产、消息附件等），再级联删除关系行。
        cleanup_character_files(character)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['get'])
    def soul_files(self, request, pk=None):
        character = self.get_object()
        return Response(list_memory_explorer_path(
            character,
            path_prefix=request.query_params.get('path_prefix', ''),
            recursive=request.query_params.get('recursive', '').lower() == 'true',
            max_entries=request.query_params.get('max_entries', 200),
        ))

    @action(detail=True, methods=['get'])
    def soul_file(self, request, pk=None):
        character = self.get_object()
        path = request.query_params.get('path', '')
        if not path:
            raise ValidationError({'path': 'path is required'})
        return Response(read_memory_explorer_file(
            character,
            path=path,
            max_chars=request.query_params.get('max_chars', 6000),
            offset=request.query_params.get('offset', 0),
        ))

    @action(detail=True, methods=['get', 'post'], url_path='knowledge_assets')
    def knowledge_assets(self, request, pk=None):
        character = self.get_object()
        if request.method == 'POST':
            return self._upload_knowledge_assets(request, character)

        serializer = CharacterKnowledgeAssetSerializer(
            character.knowledge_assets.order_by('sort_order', 'id'),
            many=True,
            context={'request': request},
        )
        return Response({'assets': serializer.data})

    def _upload_knowledge_assets(self, request, character):
        files = list(request.FILES.getlist('files'))
        if not files:
            single_file = request.FILES.get('file')
            if single_file:
                files = [single_file]

        if not files:
            raise ValidationError({'files': 'At least one file is required.'})

        # Optional parallel array of folder-group relative paths (e.g. from a
        # browser upload that preserves webkitRelativePath). Files land inside
        # the memory filesystem tree at raw/character_setup/uploads/<rel>.
        relative_paths = self._extract_relative_paths(request)
        if len(relative_paths) not in (0, len(files)):
            raise ValidationError({'relative_paths': 'relative_paths must match the number of uploaded files.'})

        next_sort_order = (
            character.knowledge_assets.order_by('-sort_order').values_list('sort_order', flat=True).first() or 0
        )
        created_assets = []
        for index, uploaded_file in enumerate(files, start=1):
            attachment_kind, attachment_mime_type = guess_attachment_kind(uploaded_file)
            if attachment_kind not in {AttachmentKind.TEXT, AttachmentKind.IMAGE}:
                raise ValidationError({'files': 'Only text files and images are supported for character reference uploads.'})

            validate_attachment_size(uploaded_file, attachment_kind)
            attachment_text_content = ''
            if attachment_kind == AttachmentKind.TEXT:
                attachment_text_content = extract_text_attachment_content(uploaded_file)

            relative_path = sanitize_memory_relative_path(relative_paths[index - 1]) if relative_paths else ''
            attachment_name = relative_path or (uploaded_file.name or '')

            created_assets.append(
                CharacterKnowledgeAsset.objects.create(
                    character=character,
                    file=uploaded_file,
                    attachment_name=attachment_name,
                    attachment_mime_type=attachment_mime_type,
                    attachment_kind=attachment_kind,
                    attachment_text_content=attachment_text_content,
                    sort_order=next_sort_order + index,
                )
            )

        serializer = CharacterKnowledgeAssetSerializer(created_assets, many=True, context={'request': request})
        return Response({'assets': serializer.data}, status=status.HTTP_201_CREATED)

    @staticmethod
    def _extract_relative_paths(request):
        values = list(request.data.getlist('relative_paths')) if hasattr(request.data, 'getlist') else []

        # Multipart clients send either repeated relative_paths fields or one
        # JSON-encoded array; accept both shapes.
        if len(values) == 1 and isinstance(values[0], str) and values[0].lstrip().startswith('['):
            try:
                parsed = json.loads(values[0])
            except ValueError:
                raise ValidationError({'relative_paths': 'relative_paths must be a JSON array when sent as one field.'})
            if not isinstance(parsed, list):
                raise ValidationError({'relative_paths': 'relative_paths must be an array.'})
            return [str(item) for item in parsed]

        return [str(value) for value in values]

    @action(detail=True, methods=['delete'], url_path=r'knowledge_assets/(?P<asset_id>[^/.]+)')
    def delete_knowledge_asset(self, request, pk=None, asset_id=None):
        character = self.get_object()
        try:
            asset = character.knowledge_assets.get(pk=asset_id)
        except CharacterKnowledgeAsset.DoesNotExist as exc:
            raise ValidationError({'asset_id': 'Knowledge asset not found for this character.'}) from exc

        asset.file.delete(save=False)
        asset.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get', 'post', 'delete'], url_path='memory')
    def memory_collection(self, request, pk=None):
        view = CharacterMemoryViewSet()
        view.permission_classes = self.permission_classes
        view.request = request
        if request.method == 'GET':
            return view.list(request=request, pk=pk)
        if request.method == 'POST':
            return view.create(request=request, pk=pk)
        return view.wipe_all(request=request, pk=pk)

    # NOTE: ``memory/merge`` is declared BEFORE ``memory/{short_id}`` so the
    # literal route is tried first by DRF's router. The ``memory_item``
    # regex below ALSO uses a negative lookahead to reject reserved
    # sub-action names ("merge", "audit", "narrative", "wipe"). The
    # lookahead uses ``/?$`` (not bare ``$``) so reserved names match
    # even when the trailing slash is present (``memory/merge/`` would
    # otherwise slip past the bare ``$`` anchor and be captured as a
    # ``short_id``). The lookahead is the structural enforcement; the
    # declaration ordering is belt-and-suspenders that future readers
    # can safely ignore.
    @action(detail=True, methods=['post'], url_path='memory/merge')
    def memory_merge(self, request, pk=None):
        view = CharacterMemoryViewSet()
        view.permission_classes = self.permission_classes
        view.request = request
        return view.merge(request=request, pk=pk)

    @action(detail=True, methods=['get'], url_path='memory/narrative')
    def memory_narrative(self, request, pk=None):
        view = CharacterMemoryViewSet()
        view.permission_classes = self.permission_classes
        view.request = request
        return view.narrative(request=request, pk=pk)

    @action(
        detail=True,
        methods=['patch', 'delete'],
        url_path=r'memory/(?P<short_id>(?!merge/?$|audit/?$|narrative/?$|wipe/?$)[^/.]+)',
    )
    def memory_item(self, request, pk=None, short_id=None):
        view = CharacterMemoryViewSet()
        view.permission_classes = self.permission_classes
        view.request = request
        if request.method == 'PATCH':
            return view.update(request=request, pk=pk, short_id=short_id)
        return view.destroy(request=request, pk=pk, short_id=short_id)


class ModelConfigurationViewSet(viewsets.ModelViewSet):
    queryset = ModelConfiguration.objects.none()
    serializer_class = ModelConfigurationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ModelConfiguration.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        model_config = serializer.save(user=self.request.user)
        # 首个配置自动接管 text 槽位：避免「有配置但无 text 分配」的状态
        # （该状态下聊天会静默回退到 id 最小的配置，可能选错模型）。
        if not ModelRoleAssignment.objects.filter(user=self.request.user, role=ModelRole.TEXT).exists():
            ModelRoleAssignment.objects.get_or_create(
                user=self.request.user,
                role=ModelRole.TEXT,
                defaults={'model_config': model_config},
            )

    def perform_update(self, serializer):
        serializer.save(user=self.request.user)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if ModelRoleAssignment.objects.filter(model_config=instance, role=ModelRole.TEXT).exists():
            return Response(
                {'error': 'This model is assigned to the text role. Switch the text model before deleting it.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # 媒体槽位（图片/音频/视频）引用随 CASCADE 自动清空。
        return super().destroy(request, *args, **kwargs)


class ModelRoleAssignmentView(APIView):
    """四角色槽位（text/image/audio/video）的读取与更新。

    PUT 语义：payload 中出现的角色会被设置（显式 null 表示清空），
    未出现的角色保持现状；text 角色必须始终指向一个有效配置。
    """

    permission_classes = [IsAuthenticated]

    def _serialize_assignments(self, user):
        data = {role: None for role, _label in ModelRole.choices}
        assignments = (
            ModelRoleAssignment.objects.filter(user=user)
            .select_related('model_config')
        )
        for assignment in assignments:
            data[assignment.role] = ModelConfigurationSerializer(
                assignment.model_config,
                context={'request': self.request},
            ).data
        return data

    def get(self, request):
        return Response(self._serialize_assignments(request.user))

    def put(self, request):
        payload = request.data if isinstance(request.data, dict) else {}

        requested = {}
        for role, _label in ModelRole.choices:
            if role not in payload:
                continue
            value = payload.get(role)
            requested[role] = None if value in [None, '', 'null'] else str(value)

        if not requested:
            return Response({'error': 'No role assignments provided'}, status=status.HTTP_400_BAD_REQUEST)

        if ModelRole.TEXT in requested and requested[ModelRole.TEXT] is None:
            return Response(
                {'error': 'A text model is required and cannot be empty'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # payload 未提及 text 时，必须已存在 text 分配；否则会留下
        # 「有配置但无 text」的静默错误状态（聊天回退到任意第一个配置）。
        if ModelRole.TEXT not in requested and not ModelRoleAssignment.objects.filter(
            user=request.user, role=ModelRole.TEXT
        ).exists():
            return Response(
                {'error': 'A text model is required. Assign a text model before configuring other roles.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        config_ids = {value for value in requested.values() if value}
        configs = {
            str(config.id): config
            for config in ModelConfiguration.objects.filter(user=request.user, id__in=config_ids)
        }
        for role, value in requested.items():
            if value and value not in configs:
                return Response(
                    {'error': f'Model configuration not found or access denied for role "{role}"'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        from django.db import transaction

        with transaction.atomic():
            for role, value in requested.items():
                ModelRoleAssignment.objects.filter(user=request.user, role=role).delete()
                if value:
                    ModelRoleAssignment.objects.create(
                        user=request.user,
                        role=role,
                        model_config=configs[value],
                    )

        return Response(self._serialize_assignments(request.user))


class ModelCatalogViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    # POST 而非 GET：api_key 放 body，避免泄漏进 access log / 浏览器历史
    @action(detail=False, methods=['post'])
    def probe(self, request):
        payload = request.data if isinstance(request.data, dict) else {}
        provider = str(payload.get('provider') or '').strip()
        base_url = str(payload.get('base_url') or '').strip()
        api_key = str(payload.get('api_key') or '').strip()

        try:
            models = probe_provider_models(provider, base_url=base_url, api_key=api_key)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001
            logger.warning('Model probe failed for provider=%s base_url=%s: %s', provider, base_url, exc)
            return Response(
                {'error': 'Failed to fetch the model list. Check the provider, base URL, and API key, or enter the model name manually.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({'models': models})


class UserProfileViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get', 'patch'])
    def me(self, request):
        profile = UserProfile.get_or_create_for_user(request.user)

        if request.method == 'GET':
            return Response(UserProfileSerializer(profile).data)

        serializer = UserProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class WebSearchConfigurationViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'])
    def readiness(self, request):
        """前端提示用：联网搜索是否开启、Tavily key 是否已配置。

        enabled 解析与聊天门控一致：角色三态覆盖优先，否则回退用户全局默认。
        """
        enabled = None
        character_id = request.query_params.get('character')
        if character_id:
            try:
                character = Character.objects.get(pk=character_id, created_by=request.user)
                if character.enable_web_search is not None:
                    enabled = bool(character.enable_web_search)
            except Character.DoesNotExist:
                pass
        if enabled is None:
            profile = getattr(request.user, 'profile', None)
            enabled = bool(getattr(profile, 'default_enable_web_search', False))

        config = WebSearchConfiguration.get_for_user(request.user)
        configured = bool(config and (config.api_key or '').strip())
        return Response({'enabled': enabled, 'configured': configured})

    @action(detail=False, methods=['get', 'patch'])
    def me(self, request):
        config = WebSearchConfiguration.get_for_user(request.user)

        if request.method == 'GET':
            config = config or WebSearchConfiguration(
                user=request.user,
                provider='tavily',
                api_key='',
                max_results=5,
            )
            return Response(WebSearchConfigurationSerializer(config).data)

        serializer = WebSearchConfigurationSerializer(
            config,
            data=request.data,
            partial=True,
            context={'user': request.user},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def test(self, request):
        query = (request.data.get('query') or '').strip()
        if not query:
            raise ValidationError({'query': 'query is required'})

        config = WebSearchConfiguration.get_for_user(request.user)
        payload = search_web(query, user=request.user, config=config)
        return Response(payload)


def _save_upload_to(directory: Path, uploaded) -> Path:
    """把上传文件落盘到 MEDIA_ROOT 子目录，返回服务器绝对路径（genie/api_v2
    按本机路径读取参考音频）。"""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / Path(uploaded.name or 'upload.bin').name
    with open(target, 'wb') as handle:
        for chunk in uploaded.chunks():
            handle.write(chunk)
    return target


class TtsServiceSettingsViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get', 'patch'])
    def me(self, request):
        settings_row = TtsServiceSettings.get_for_user(request.user)

        if request.method == 'GET':
            settings_row = settings_row or TtsServiceSettings(user=request.user)
            return Response(TtsServiceSettingsSerializer(settings_row).data)

        serializer = TtsServiceSettingsSerializer(
            settings_row,
            data=request.data,
            partial=True,
            context={'user': request.user},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def test(self, request):
        """连通性测试：{engine} → {ok, hint}。使用合并用户设置后的地址。"""
        engine = (request.data.get('engine') or '').strip().lower()
        if engine not in chat_tts.PROVIDER_CLASSES:
            raise ValidationError({'engine': f'Unknown TTS engine: {engine}'})
        config = chat_tts.get_tts_config(chat_tts.service_overrides_for_user(request.user))
        ok, hint = chat_tts.provider_ready(config, engine)
        if ok:
            try:
                instance = chat_tts.build_provider(engine, config)
                ok, hint = instance.readiness_probe()
            except chat_tts.TtsUnavailableError as exc:
                ok, hint = False, str(exc)
        return Response({'ok': bool(ok), 'hint': hint})


class TtsVoiceModelViewSet(viewsets.ModelViewSet):
    """音色库 CRUD + 上传转换。角色通过 tts_config.voice_model_id 引用这里的记录。"""

    queryset = TtsVoiceModel.objects.none()
    serializer_class = TtsVoiceModelSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return TtsVoiceModel.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=False, methods=['post'])
    def upload_convert(self, request):
        """multipart 上传 GPT-SoVITS torch 权重并交给 Genie 服务转 ONNX。

        字段：ckpt（T2S .ckpt）、pth（VITS .pth）必填；name/language/
        model_version/ref_audio(+text/lang) 可选。转换在 Genie 侧异步执行，
        本端点只投递任务并立即返回（conversion_status=pending/converting），
        前端经 /conversion_status/ 轮询直到 ready/failed。
        """
        ckpt = request.FILES.get('ckpt')
        pth = request.FILES.get('pth')
        missing = [field for field, file in (('ckpt', ckpt), ('pth', pth)) if not file]
        if missing:
            raise ValidationError({field: 'This file is required.' for field in missing})

        name = (request.data.get('name') or '').strip() or Path(pth.name or '').stem.strip() or 'voice'
        model_version = (request.data.get('model_version') or '').strip().lower()
        language = (request.data.get('language') or '').strip().lower()

        source_dir = Path(settings.MEDIA_ROOT) / 'tts' / 'model_sources' / uuid4().hex
        ckpt_path = _save_upload_to(source_dir, ckpt)
        pth_path = _save_upload_to(source_dir, pth)

        ref_audio_path = ''
        ref_audio = request.FILES.get('ref_audio')
        if ref_audio:
            ref_audio_path = str(_save_upload_to(Path(settings.MEDIA_ROOT) / 'tts' / 'ref_audio', ref_audio))

        dir_name = slugify(name) or uuid4().hex[:8]
        output_dir = str(Path(settings.MEDIA_ROOT) / 'tts' / 'onnx_models' / f'{dir_name}_onnx')

        voice = TtsVoiceModel.objects.create(
            user=request.user,
            name=name,
            engine=TtsEngine.GENIE,
            model_version=model_version,
            language=language,
            onnx_model_dir=output_dir,
            ref_audio_path=ref_audio_path,
            ref_audio_text=(request.data.get('ref_audio_text') or '').strip(),
            ref_audio_language=(request.data.get('ref_audio_language') or '').strip(),
            source_ckpt_path=str(ckpt_path),
            source_pth_path=str(pth_path),
            conversion_status=TtsVoiceModel.ConversionStatus.PENDING,
        )

        genie_url = chat_tts.get_tts_config(chat_tts.service_overrides_for_user(request.user))['genie_url']
        try:
            response = requests.post(f'{genie_url}/convert_to_onnx', json={
                'torch_ckpt_path': str(ckpt_path),
                'torch_pth_path': str(pth_path),
                'output_dir': output_dir,
            }, timeout=(5, 30))
            response.raise_for_status()
            job_id = str((response.json() or {}).get('job_id') or '')
            if job_id:
                voice.conversion_job_id = job_id
                voice.conversion_status = TtsVoiceModel.ConversionStatus.CONVERTING
                voice.save(update_fields=['conversion_job_id', 'conversion_status'])
            else:
                voice.conversion_status = TtsVoiceModel.ConversionStatus.FAILED
                voice.conversion_error = 'Genie-TTS 转换服务未返回 job_id。'
                voice.save(update_fields=['conversion_status', 'conversion_error'])
        except requests.RequestException as exc:
            voice.conversion_status = TtsVoiceModel.ConversionStatus.FAILED
            voice.conversion_error = f'无法连接 Genie-TTS 转换服务（{genie_url}）：{exc.__class__.__name__}'
            voice.save(update_fields=['conversion_status', 'conversion_error'])

        return Response(TtsVoiceModelSerializer(voice).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def conversion_status(self, request, pk=None):
        """轮询转换进度：向 Genie 查询并把终态回写到音色记录。"""
        voice = self.get_object()
        if voice.conversion_job_id and voice.conversion_status == TtsVoiceModel.ConversionStatus.CONVERTING:
            genie_url = chat_tts.get_tts_config(chat_tts.service_overrides_for_user(request.user))['genie_url']
            try:
                upstream = requests.get(f'{genie_url}/convert_status/{voice.conversion_job_id}', timeout=10)
                upstream.raise_for_status()
                payload = upstream.json() or {}
            except requests.RequestException as exc:
                return Response(
                    {'detail': f'转换状态查询失败：{exc.__class__.__name__}'},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            state = (payload.get('status') or '').lower()
            if state == 'done':
                voice.conversion_status = TtsVoiceModel.ConversionStatus.READY
                voice.conversion_error = ''
                voice.save(update_fields=['conversion_status', 'conversion_error', 'updated_at'])
            elif state == 'error':
                voice.conversion_status = TtsVoiceModel.ConversionStatus.FAILED
                voice.conversion_error = payload.get('error') or 'ONNX 转换失败。'
                voice.save(update_fields=['conversion_status', 'conversion_error', 'updated_at'])
        return Response(TtsVoiceModelSerializer(voice).data)

    @action(detail=False, methods=['post'])
    def upload_ref_audio(self, request):
        """上传参考音频（音色或情感组用），返回服务器绝对路径供 genie 读取。

        供设置页「选择音频文件」按钮使用：把本机音频传到 MEDIA_ROOT/tts/ref_audio，
        返回绝对路径回填到表单的 ref_audio_path，避免用户手敲服务器路径。
        """
        audio = request.FILES.get('file')
        if not audio:
            raise ValidationError({'file': 'This file is required.'})
        path = _save_upload_to(Path(settings.MEDIA_ROOT) / 'tts' / 'ref_audio', audio)
        return Response({'path': str(path), 'name': audio.name})

    @action(detail=False, methods=['post'])
    def upload_onnx_dir(self, request):
        """上传一个 ONNX 模型文件夹（webkitdirectory 多文件），返回服务器目录路径。

        文件字段为 files[]（重复 files），保留相对路径目录结构，
        落盘到 MEDIA_ROOT/tts/onnx_models/<name>_onnx/ 并返回目录绝对路径。
        """
        files = request.FILES.getlist('files')
        if not files:
            raise ValidationError({'files': 'At least one file is required.'})
        relative_paths = request.POST.getlist('relative_paths[]')
        name = (request.data.get('name') or '').strip() or slugify(
            Path(relative_paths[0] if relative_paths else '').parts[0]
        ) or f'voice_{uuid4().hex[:6]}'

        output_dir = Path(settings.MEDIA_ROOT) / 'tts' / 'onnx_models' / f'{slugify(name) or uuid4().hex[:8]}_onnx'
        output_dir.mkdir(parents=True, exist_ok=True)

        for index, file_obj in enumerate(files):
            rel = relative_paths[index] if index < len(relative_paths) else file_obj.name
            rel = sanitize_relative_path(rel) or os.path.basename(file_obj.name)
            target = output_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, 'wb') as handle:
                for chunk in file_obj.chunks():
                    handle.write(chunk)

        return Response({'path': str(output_dir), 'name': str(output_dir.name)})


class ChatSessionViewSet(viewsets.ModelViewSet):
    queryset = ChatSession.objects.none()
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return ChatSessionWriteSerializer
        return ChatSessionSerializer

    def get_queryset(self):
        queryset = ChatSession.objects.filter(user=self.request.user).select_related('character').prefetch_related('messages__attachments')
        character_id = self.request.query_params.get('character_id')
        if character_id:
            queryset = queryset.filter(character_id=character_id)

        origin = self.request.query_params.get('origin')
        if origin in dict(ChatSession.ORIGIN_CHOICES):
            queryset = queryset.filter(origin=origin)

        return queryset.order_by('-updated_at')

    def perform_create(self, serializer):
        user = self.request.user
        try:
            _get_required_model_config(user=user)
        except ValueError as exc:
            raise ValidationError({'title': str(exc)}) from exc
        serializer.save(user=user)

    def partial_update(self, request, *args, **kwargs):
        """Allow toggling ``is_private_mode`` from the chat composer without
        sending every other field. A manually patched ``title`` marks the
        session so the auto title generator will not overwrite it."""
        instance = self.get_object()
        if 'is_private_mode' in request.data:
            is_private_mode = self._parse_bool(request.data.get('is_private_mode'))
            instance.is_private_mode = is_private_mode
            instance.save(update_fields=['is_private_mode', 'updated_at'])
            return Response(ChatSessionSerializer(instance).data)

        if 'title' in request.data and (request.data.get('title') or '').strip():
            # Set the manual flag before the generic update so the auto
            # generator can never race a just-renamed session.
            instance.is_title_manual = True
            instance.save(update_fields=['is_title_manual'])

        super().partial_update(request, *args, **kwargs)
        instance.refresh_from_db()
        return Response(ChatSessionSerializer(instance, context={'request': request}).data)

    @staticmethod
    def _parse_bool(value):
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).lower() in {'1', 'true', 'yes', 'on'}


class CharacterMemoryViewSet(viewsets.ViewSet):
    """REST surface for ``wiki/memory.md`` (per-character long-term memory).

    Five CRUD verbs mirroring SonettoHeres tools byte-for-byte:

    - ``GET /api/characters/{id}/memory/`` — snapshot grouped by section.
    - ``POST /api/characters/{id}/memory/`` — ``create_memory`` action.
    - ``PATCH /api/characters/{id}/memory/{short_id}/`` — ``update_memory``.
    - ``DELETE /api/characters/{id}/memory/{short_id}/`` — ``delete_memory``.
    - ``POST /api/characters/{id}/memory/merge/`` — ``merge_memories``.

    Every write logs to ``MemoryAuditLog`` with source ``user_edit``,
    matching the audit trail that ``sync_long_term_memory`` already writes.
    """

    permission_classes = [IsAuthenticated]

    def _memory(self, request, pk):
        # Use get_object_or_404 so cross-user access surfaces as 404
        # instead of leaking a 500 from an uncaught DoesNotExist.
        character = get_object_or_404(
            Character,
            pk=pk,
            created_by=request.user,
        )
        return character, MemoryManager(character)

    def list(self, request, pk=None):
        character, manager = self._memory(request, pk)
        snapshot = CharacterLongTermMemory.snapshot(character)
        return Response({
            'sections': snapshot['sections'],
            'wiki_markdown': manager.render_wiki_markdown(),
            'count': sum(len(section['items']) for section in snapshot['sections']),
        })

    def narrative(self, request, pk=None):
        """AI-view preview: the exact text injected into the system prompt
        (memory v2 §5.3), plus whether budget trimming kicked in."""
        from .memory.constants import STREAM_MEMORY_SECTION_LIMIT

        character, manager = self._memory(request, pk)
        narrative, truncated = manager.get_prompt_memory(
            budget_chars=STREAM_MEMORY_SECTION_LIMIT,
        )
        items = manager.list_items()
        last_updated = max((item.updated_at for item in items), default=None)
        return Response({
            'narrative': narrative,
            'truncated': truncated,
            'count': len(items),
            'last_updated': last_updated.isoformat() if last_updated else None,
        })

    def create(self, request, pk=None):
        character, manager = self._memory(request, pk)
        description = request.data.get('description', '')
        section = request.data.get('section', '')
        reason = request.data.get('reason', '')
        try:
            item = manager.create_item(
                section=section,
                description=description,
                source=MemoryAuditSource.USER_EDIT,
                reason=reason or 'User edit via /memory page.',
            )
        except ValueError as exc:
            raise ValidationError({'description': str(exc)}) from exc
        return Response(_serialise_memory_item(item), status=status.HTTP_201_CREATED)

    def update(self, request, pk=None, short_id=None):
        character, manager = self._memory(request, pk)
        description = request.data.get('description', '')
        section = request.data.get('section')
        reason = request.data.get('reason', '')
        try:
            item = manager.update_item(
                short_id=short_id,
                description=description,
                section=section,
                reason=reason or 'User edit via /memory page.',
                source=MemoryAuditSource.USER_EDIT,
            )
        except ValueError as exc:
            raise ValidationError({'description': str(exc)}) from exc
        except MemoryItemNotFoundError as exc:
            raise ValidationError({'short_id': str(exc)}) from exc
        return Response(_serialise_memory_item(item))

    def destroy(self, request, pk=None, short_id=None):
        character, manager = self._memory(request, pk)
        reason = request.data.get('reason', '') or 'User delete via /memory page.'
        try:
            deleted_desc = manager.delete_item(
                short_id=short_id,
                reason=reason,
                source=MemoryAuditSource.USER_EDIT,
            )
        except MemoryItemNotFoundError as exc:
            raise ValidationError({'short_id': str(exc)}) from exc
        return Response({'deleted': short_id, 'description': deleted_desc}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def merge(self, request, pk=None):
        character, manager = self._memory(request, pk)
        try:
            item = manager.merge_items(
                id1=request.data.get('id1', ''),
                id2=request.data.get('id2', ''),
                content=request.data.get('content', ''),
                section=request.data.get('section', ''),
                reason=request.data.get('reason', '') or 'User merge via /memory page.',
                source=MemoryAuditSource.USER_EDIT,
            )
        except ValueError as exc:
            raise ValidationError({'content': str(exc)}) from exc
        except MemoryItemNotFoundError as exc:
            raise ValidationError({'short_id': str(exc)}) from exc
        return Response(_serialise_memory_item(item))

    @action(detail=False, methods=['delete'])
    def wipe_all(self, request, pk=None):
        character, _ = self._memory(request, pk)
        deleted = CharacterLongTermMemory.wipe(character)
        return Response({'deleted': deleted})


def _serialise_memory_item(item):
    return {
        'short_id': item.short_id,
        'section': item.section,
        'description': item.description,
        'description_history': list(item.description_history or []),
        'created_at': item.created_at.isoformat() if item.created_at else None,
        'updated_at': item.updated_at.isoformat() if item.updated_at else None,
    }

class MessageViewSet(viewsets.ModelViewSet):
    queryset = Message.objects.none()
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return MessageCreateSerializer
        return MessageSerializer

    def get_queryset(self):
        queryset = Message.objects.filter(chat_session__user=self.request.user).prefetch_related('attachments').order_by('timestamp')
        chat_session_id = self.request.query_params.get('chat_session_id')
        if chat_session_id:
            queryset = queryset.filter(chat_session_id=chat_session_id)
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        chat_session_id = request.data.get('chat_session_id')
        if not chat_session_id:
            raise ValidationError('chat_session_id is required')
        try:
            chat_session = ChatSession.objects.get(
                id=chat_session_id,
                user=request.user,
            )
        except ChatSession.DoesNotExist:
            raise ValidationError('Chat session not found or access denied')

        validated = serializer.validated_data
        role = validated.get('role') or 'user'
        content = validated.get('content') or ''
        character = validated.get('character')

        # Every message is a conversation event; the Message row is the
        # write-through projection.
        if not chat_session.events.exists():
            EventStore.append(
                chat_session,
                ChatEventType.SESSION_CREATED,
                {'origin': chat_session.origin, 'title': chat_session.title},
            )
        if role == 'assistant':
            _event, message = EventStore.append(
                chat_session,
                ChatEventType.ASSISTANT_MESSAGE,
                assistant_message_payload(content=content),
                character=character,
            )
        else:
            _event, message = EventStore.append(
                chat_session,
                ChatEventType.USER_MESSAGE,
                user_message_payload(content=content),
                character=character,
            )
        return Response(
            MessageSerializer(message, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

class ChatViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['post'])
    def send_message(self, request):
        try:
            chat_session, character, user_message, generate_greeting = self._prepare_chat_turn(request)
            result = generate_ai_response(
                user_message.id if user_message else None,
                character.id,
                generate_greeting=generate_greeting,
                chat_session_id=chat_session.id,
            )

            if not result.get('success'):
                return Response(
                    {'error': result.get('error', 'Failed to generate AI response')},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            ai_message = Message.objects.get(id=result['message_id'])
            payload = {
                'ai_message': _message_serializer(ai_message, request).data,
                'chat_session_id': chat_session.id,
            }
            if user_message:
                payload['user_message'] = _message_serializer(user_message, request).data
            return Response(payload)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Character.DoesNotExist:
            return Response({'error': 'Character not found'}, status=status.HTTP_404_NOT_FOUND)
        except ChatSession.DoesNotExist:
            return Response({'error': 'Chat session not found or access denied'}, status=status.HTTP_404_NOT_FOUND)
        except ModelConfiguration.DoesNotExist:
            return Response({'error': 'Model configuration not found or access denied'}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=['post'])
    def stream_message(self, request):
        try:
            chat_session, character, user_message, generate_greeting = self._prepare_chat_turn(request)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Character.DoesNotExist:
            return Response({'error': 'Character not found'}, status=status.HTTP_404_NOT_FOUND)
        except ChatSession.DoesNotExist:
            return Response({'error': 'Chat session not found or access denied'}, status=status.HTTP_404_NOT_FOUND)
        except ModelConfiguration.DoesNotExist:
            return Response({'error': 'Model configuration not found or access denied'}, status=status.HTTP_404_NOT_FOUND)

        def event_stream():
            yield self._serialize_stream_event({
                'type': 'session',
                'chat_session_id': chat_session.id,
                'user_message': _message_serializer(user_message, request).data if user_message else None,
                'is_greeting': generate_greeting,
            })

            try:
                for event in stream_ai_response(
                    chat_session=chat_session,
                    character=character,
                    user_message=user_message,
                    generate_greeting=generate_greeting,
                ):
                    yield self._serialize_stream_event(event)
            except Exception as exc:
                logger.exception("Streaming response failed for session %s", chat_session.id)
                yield self._serialize_stream_event({
                    'type': 'error',
                    'error': str(exc),
                })

        return StreamingHttpResponse(event_stream(), content_type='application/x-ndjson')

    @action(detail=False, methods=['post'])
    def asr(self, request):
        """实时模式语音转文字：multipart audio → 文本。

        延迟是一等指标：响应带 processing_ms / model_load_ms，前端角标
        与 docs/latency 记录都消费这两个字段。
        """
        upload = request.FILES.get('audio')
        if upload is None:
            return Response({'error': 'audio file is required'}, status=status.HTTP_400_BAD_REQUEST)
        if upload.size > chat_asr.MAX_ASR_AUDIO_BYTES:
            return Response(
                {'error': f'audio too large (max {chat_asr.MAX_ASR_AUDIO_BYTES // (1024 * 1024)}MB)'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        mime_type = (upload.content_type or '').split(';')[0].strip().lower()
        if mime_type not in chat_asr.SUPPORTED_AUDIO_MIME_TYPES:
            return Response(
                {'error': f'unsupported audio type "{mime_type or "unknown"}"; expected webm/ogg/wav'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not chat_asr.asr_available():
            return Response(
                {'error': chat_asr.readiness()['hint'], 'readiness': chat_asr.readiness()},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        try:
            result = chat_asr.transcribe_bytes(
                upload.read(),
                mime_type,
                language=(request.data.get('language') or '').strip() or None,
            )
        except chat_asr.AsrUnavailableError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            logger.exception("ASR transcription failed")
            return Response({'error': f'ASR failed: {exc}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(result)

    @action(detail=False, methods=['get'])
    def asr_readiness(self, request):
        """前端实时模式开关的提示数据源（未安装/未启用时给出可读 hint）。"""
        return Response(chat_asr.readiness())

    @action(detail=False, methods=['post'])
    def tts(self, request):
        """实时模式语音合成：{text, provider?, character_id?, emotion?} → 音频流。

        provider 由 TTS_PROVIDER 配置（genie/gptsovits/indextts），请求可覆盖。
        emotion 对应角色情感组的情感名，命中时使用该情感专属的参考音频。
        未配置返回 501；已配置但服务不可达返回 503 + readiness 提示。
        """
        text = (request.data.get('text') or '').strip()
        if not text:
            return Response({'error': 'text is required'}, status=status.HTTP_400_BAD_REQUEST)
        if len(text) > 1000:
            return Response(
                {'error': 'text too long (max 1000 chars per request); split by sentence first.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        provider = (request.data.get('provider') or '').strip().lower() or None
        emotion = (request.data.get('emotion') or '').strip() or None
        # 音色的模型目录/参考音频来自设置页登记的音色库（角色 tts_config 通过
        # voice_model_id 引用；旧数据的直填字段仍兼容）。无效/不属于当前用户
        # 的 character_id 视作未提供配置，genie 通道会直接报"请先配置语音模型"。
        character_tts_config = None
        character_id = str(request.data.get('character_id') or '').strip()
        if character_id:
            try:
                character = Character.objects.get(pk=character_id, created_by=request.user)
                character_tts_config = character.tts_config or {}
            except (Character.DoesNotExist, ValueError):
                pass
        service_overrides = chat_tts.service_overrides_for_user(request.user)
        try:
            result = chat_tts.synthesize_speech(
                text, provider=provider, character_tts_config=character_tts_config,
                user=request.user, service_overrides=service_overrides, emotion=emotion,
            )
        except chat_tts.TtsUnavailableError as exc:
            readiness = chat_tts.readiness()
            status_code = (
                status.HTTP_501_NOT_IMPLEMENTED
                if readiness['provider'] == 'none'
                else status.HTTP_503_SERVICE_UNAVAILABLE
            )
            return Response({'error': str(exc), 'readiness': readiness}, status=status_code)
        except Exception as exc:
            logger.exception("TTS synthesis failed")
            return Response({'error': f'TTS failed: {exc}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        audio_response = HttpResponse(result['audio'], content_type=result['content_type'])
        audio_response['X-TTS-Provider'] = result['provider']
        audio_response['X-TTS-Processing-Ms'] = str(result['processing_ms'])
        if result.get('first_byte_ms') is not None:
            audio_response['X-TTS-First-Byte-Ms'] = str(result['first_byte_ms'])
        return audio_response

    @action(detail=False, methods=['get'])
    def tts_readiness(self, request):
        """前端"语音回复"开关的提示数据源（未配置/不可达时给出可读 hint）。"""
        return Response(chat_tts.readiness(chat_tts.service_overrides_for_user(request.user)))

    def _prepare_chat_turn(self, request):
        user = request.user
        message_content = (request.data.get('message') or '').strip()
        character_id = request.data.get('character_id')
        chat_session_id = request.data.get('chat_session_id')
        start_conversation = self._parse_bool(request.data.get('start_conversation', False))
        origin = request.data.get('origin')
        if origin not in dict(ChatSession.ORIGIN_CHOICES):
            origin = 'topic'
        attachments = list(request.FILES.getlist('attachments'))
        if not attachments:
            legacy_attachment = request.FILES.get('attachment')
            if legacy_attachment:
                attachments = [legacy_attachment]

        if not character_id:
            raise ValueError('character_id is required')

        if not start_conversation and not message_content and not attachments:
            raise ValueError('message or attachment is required')

        attachment_payloads = []
        for index, attachment in enumerate(attachments):
            attachment_kind, attachment_mime_type = guess_attachment_kind(attachment)
            validate_attachment_size(attachment, attachment_kind)
            attachment_text_content = ''
            if attachment_kind == AttachmentKind.TEXT:
                attachment_text_content = extract_text_attachment_content(attachment)
            attachment_payloads.append({
                'file': attachment,
                'attachment_name': attachment.name or '',
                'attachment_kind': attachment_kind,
                'attachment_mime_type': attachment_mime_type,
                'attachment_text_content': attachment_text_content,
                'sort_order': index,
            })

        character = Character.objects.get(id=character_id, created_by=user)
        _get_required_model_config(user)

        if chat_session_id:
            chat_session = ChatSession.objects.get(
                id=chat_session_id,
                user=user,
                character=character,
            )
        else:
            chat_session = ChatSession.objects.create(
                user=user,
                character=character,
                title=f"Chat with {character.name}",
                origin=origin,
            )

        has_existing_messages = chat_session.messages.exists()
        if start_conversation and has_existing_messages:
            raise ValueError('This conversation has already started')

        # A greeting is generated ONLY for an explicit start request carrying no
        # user content. Any non-empty message/attachment is a real first turn and
        # must be saved and answered (memory v2 §3.3: the first typed message used
        # to be silently swallowed here, so it never reached chat history or the
        # long-term memory extractor).
        generate_greeting = (
            start_conversation
            and not message_content
            and not attachment_payloads
            and not has_existing_messages
        )

        # Event-sourced history: every session gets a ``session/created`` marker
        # (exactly once — also covers sessions created via GraphQL), and every
        # user turn becomes a ``user/message`` event. The Message row is the
        # write-through projection of that event.
        if not chat_session.events.exists():
            EventStore.append(
                chat_session,
                ChatEventType.SESSION_CREATED,
                {'origin': chat_session.origin, 'title': chat_session.title},
            )

        user_message = None
        if not generate_greeting:
            # Persist uploaded files first so the event payload can carry the
            # storage names; the projection recreates MessageAttachment rows
            # from them without touching the bytes again.
            attachment_payloads = _persist_attachment_files(attachment_payloads)
            _, user_message = EventStore.append(
                chat_session,
                ChatEventType.USER_MESSAGE,
                user_message_payload(content=message_content, attachments=attachment_payloads),
                character=character,
            )
            chat_session.save(update_fields=['updated_at'])

        return chat_session, character, user_message, generate_greeting

    def _parse_bool(self, value):
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).lower() in {'1', 'true', 'yes', 'on'}

    def _serialize_stream_event(self, payload):
        return json.dumps(payload, ensure_ascii=False) + '\n'
