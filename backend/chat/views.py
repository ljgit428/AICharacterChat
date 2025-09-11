from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.conf import settings
import tempfile
import os
import google.generativeai as genai
from .models import Character, ChatSession, Message
from .serializers import (
    CharacterSerializer,
    ChatSessionSerializer,
    ChatSessionCreateSerializer,
    MessageSerializer,
    MessageCreateSerializer
)
from .tasks import generate_ai_response


class CharacterViewSet(viewsets.ModelViewSet):
    queryset = Character.objects.all()
    serializer_class = CharacterSerializer
    permission_classes = []
    
    def _delete_gemini_file(self, gemini_uri):
        """Helper to delete a file from Gemini API."""
        if not gemini_uri:
            return
            
        api_key = getattr(settings, 'GEMINI_API_KEY', '')
        if not api_key:
            print("CRITICAL: GEMINI_API_KEY is not configured. Cannot delete Gemini file.")
            return
        
        genai.configure(api_key=api_key)
        try:
            print(f"Deleting old Gemini file: {gemini_uri}")
            genai.delete_file(name=gemini_uri)
        except Exception as e:
            # It's okay if it fails (e.g., file already deleted), just log it.
            print(f"Could not delete Gemini file {gemini_uri}: {e}")

    def _upload_to_gemini_and_save_uri(self, instance, request):
        """
        Helper function to upload file from request to Gemini and save the URI.
        """
        if 'file' not in request.FILES:
            return

        # --- ▼▼▼ 核心修正 #1 ▼▼▼ ---
        # 根据新要求，即使有旧文件，我们也不再从Gemini云端删除它。
        # 我们只在数据库中用新的URI覆盖旧的URI。
        # self._delete_gemini_file(instance.gemini_file_uri) # 注释掉此行
        # --- ▲▲▲ 修正结束 ▲▲▲ ---
        
        file_obj = request.FILES['file']
        
        api_key = getattr(settings, 'GEMINI_API_KEY', '')
        if not api_key:
            print("CRITICAL: GEMINI_API_KEY is not configured.")
            return
        genai.configure(api_key=api_key)

        temp_file_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file_obj.name}") as temp_file:
                for chunk in file_obj.chunks():
                    temp_file.write(chunk)
                temp_file_path = temp_file.name
            
            print(f"Uploading character file '{file_obj.name}' to Gemini...")
            gemini_file = genai.upload_file(path=temp_file_path, display_name=file_obj.name)
            
            instance.gemini_file_uri = gemini_file.name
            instance.save(update_fields=['gemini_file_uri'])
            print(f"Successfully uploaded. Stored Gemini URI: {gemini_file.name}")
        
        except Exception as e:
            print(f"Failed to upload character file to Gemini: {e}")
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)

    def perform_create(self, serializer):
        User = get_user_model()
        user, _ = User.objects.get_or_create(username='default_user')
        instance = serializer.save(created_by=user)
        self._upload_to_gemini_and_save_uri(instance, self.request)

    def perform_update(self, serializer):
        """
        在一次原子操作中处理实例的更新，包括文件操作。
        """
        instance = serializer.instance

        # 场景1：请求中上传了一个新文件
        if 'file' in self.request.FILES:
            # 这个辅助函数会处理上传和保存，替换旧文件
            self._upload_to_gemini_and_save_uri(instance, self.request)
        
        # 场景2：请求中明确要求清除文件
        elif self.request.data.get('clear_file') in ['true', 'True', True]:
            print("Clear file request received. Modifying instance in memory before save.")
            
            # 从外部服务和本地存储中删除物理文件
            self._delete_gemini_file(instance.gemini_file_uri)
            if instance.file:
                instance.file.delete(save=False)

            # 在内存中将实例的字段设置为空，等待统一保存
            instance.file = None
            instance.gemini_file_uri = None

        # 最终，执行保存。
        # 这会将请求中的文本字段更改，以及我们对文件字段的任何修改，一次性地保存到数据库。
        serializer.save()

    # --- ▼▼▼ 请用下面的代码块【替换】您现有的 update 方法 ▼▼▼ ---
    def update(self, request, *args, **kwargs):
        """
        重写 update 方法，强制使用部分更新(partial=True)，并确保
        在执行自定义文件逻辑后，返回的是最新的、与数据库一致的数据。
        """
        # 强制部分更新，防止仅更新文本字段时，现有文件被意外清除
        partial = True
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        
        # 调用我们全新的、更健壮的 perform_update 方法
        self.perform_update(serializer)

        # 从数据库重新加载实例，确保返回给前端的是绝对最新的状态
        instance.refresh_from_db()
        
        # 返回更新后的数据
        return Response(self.get_serializer(instance).data)
    # --- ▲▲▲ 替换结束 ▲▲▲ ---

    @action(detail=False, methods=['get'])
    def my_characters(self, request):
        characters = Character.objects.filter(created_by=request.user)
        serializer = self.get_serializer(characters, many=True)
        return Response(serializer.data)


class ChatSessionViewSet(viewsets.ModelViewSet):
    queryset = ChatSession.objects.all()
    permission_classes = []  # Allow access without authentication for development
    
    def get_serializer_class(self):
        if self.action == 'create':
            return ChatSessionCreateSerializer
        return ChatSessionSerializer
    
    def get_queryset(self):
        # Get or create default user for development
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username='default_user',
            defaults={'email': 'default@example.com'}
        )
        
        queryset = ChatSession.objects.filter(user=user)
        character_id = self.request.query_params.get('character_id')
        if character_id:
            queryset = queryset.filter(character_id=character_id)
        return queryset
    
    def perform_create(self, serializer):
        # Get or create default user for development
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username='default_user',
            defaults={'email': 'default@example.com'}
        )
        serializer.save(user=user)


class MessageViewSet(viewsets.ModelViewSet):
    queryset = Message.objects.all()
    permission_classes = []  # Allow access without authentication for development
    
    def get_serializer_class(self):
        if self.action == 'create':
            return MessageCreateSerializer
        return MessageSerializer
    
    def get_queryset(self):
        queryset = Message.objects.all()
        chat_session_id = self.request.query_params.get('chat_session_id')
        if chat_session_id:
            queryset = queryset.filter(chat_session_id=chat_session_id)
        return queryset
    
    def perform_create(self, serializer):
        chat_session_id = self.request.data.get('chat_session_id')
        if not chat_session_id:
            return Response(
                {'error': 'chat_session_id is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Get or create default user for development
            User = get_user_model()
            user, created = User.objects.get_or_create(
                username='default_user',
                defaults={'email': 'default@example.com'}
            )
            
            chat_session = ChatSession.objects.get(
                id=chat_session_id,
                user=user
            )
            serializer.save(chat_session=chat_session)
        except ChatSession.DoesNotExist:
            return Response(
                {'error': 'Chat session not found or access denied'}, 
                status=status.HTTP_404_NOT_FOUND
            )


class ChatViewSet(viewsets.ViewSet):
    permission_classes = []  # Allow access without authentication for development
    
    @action(detail=False, methods=['post'])
    def send_message(self, request):
        """
        Send a message and get AI response
        """
        message_content = request.data.get('message')
        character_id = request.data.get('character_id')
        chat_session_id = request.data.get('chat_session_id')
        file_uri = request.data.get('file_uri', None)
        
        if not message_content or not character_id:
            return Response(
                {'error': 'message and character_id are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            character = Character.objects.get(id=character_id)
            
            # Get or create default user for development
            User = get_user_model()
            user, created = User.objects.get_or_create(
                username='default_user',
                defaults={'email': 'default@example.com'}
            )
            
            # Create or get chat session
            if chat_session_id:
                chat_session = ChatSession.objects.get(
                    id=chat_session_id,
                    user=user,
                    character=character
                )
            else:
                chat_session = ChatSession.objects.create(
                    user=user,
                    character=character,
                    title=f"Chat with {character.name}"
                )
            
            # Save user message with optional file_uri
            user_message = Message.objects.create(
                chat_session=chat_session,
                role='user',
                content=message_content,
                character=character,
                file_uri=file_uri
            )
            
            # --- START OF MODIFICATION ---
            # 直接调用函数，而不是使用 .delay()
            # 这将使请求同步等待AI响应
            result = generate_ai_response(user_message.id, character.id)
            
            if not result.get('success'):
                # 如果AI响应生成失败，返回错误
                return Response(
                    {'error': result.get('error', 'Failed to generate AI response')},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # 从数据库获取新创建的AI消息
            ai_message = Message.objects.get(id=result['message_id'])
            
            # 返回包含用户消息和AI消息的响应
            return Response({
                'user_message': MessageSerializer(user_message).data,
                'ai_message': MessageSerializer(ai_message).data,
                'chat_session_id': chat_session.id
            })
            # --- END OF MODIFICATION ---
            
        except Character.DoesNotExist:
            return Response(
                {'error': 'Character not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except ChatSession.DoesNotExist:
            return Response(
                {'error': 'Chat session not found or access denied'},
                status=status.HTTP_404_NOT_FOUND
            )
