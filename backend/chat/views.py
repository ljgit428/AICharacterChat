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
        确保所有更改都被正确保存到数据库。
        """
        instance = serializer.instance
        print(f"--- PERFORM_UPDATE CALLED FOR CHARACTER ID: {instance.id} ---")
        print(f"Request Data: {self.request.data}")
        print(f"Request Files: {self.request.FILES}")

        # 场景1：上传了新文件
        if 'file' in self.request.FILES:
            print("Processing file upload...")
            # 在上传新文件前，先删除旧文件
            self._delete_gemini_file(instance.gemini_file_uri)
            if instance.file:
                instance.file.delete(save=False)
            # 序列化器会自动处理新文件的保存
        
        # 场景2：明确要求删除文件 (且没有上传新文件)
        elif self.request.data.get('clear_file') in ['true', 'True', True]:
            print("Processing file clearance...")
            self._delete_gemini_file(instance.gemini_file_uri)
            if instance.file:
                instance.file.delete(save=False)
            
            # 手动将序列化器验证过的数据中的file字段设为None
            serializer.validated_data['file'] = None
            serializer.validated_data['gemini_file_uri'] = None

        # 执行最终的、唯一的保存操作
        # serializer.save() 会将所有验证过的文本更改和我们处理过的文件更改
        # 一次性、原子地写入数据库。
        try:
            serializer.save()
            print("--- DATABASE SAVE SUCCESSFUL ---")
        except Exception as e:
            print(f"--- DATABASE SAVE FAILED: {e} ---")
            raise

        # 如果是上传文件，save之后我们还需要上传到Gemini并更新URI
        if 'file' in self.request.FILES:
            # 重新从数据库获取实例，确保它有关联的新文件
            instance.refresh_from_db()
            self._upload_to_gemini_and_save_uri(instance, self.request)

    def update(self, request, *args, **kwargs):
        """
        一个健壮的、原子化的更新方法，确保所有更改都被正确保存到数据库。
        """
        print(f"--- UPDATE REQUEST RECEIVED FOR CHARACTER ID: {kwargs.get('pk')} ---")
        print(f"Request Data: {request.data}")
        print(f"Request Files: {request.FILES}")

        # 1. 获取要更新的对象实例
        instance = self.get_object()

        # 2. 准备序列化器，强制使用部分更新(partial=True)
        #    这确保了只修改文本时，文件字段不会被意外置空。
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        
        # 3. 验证前端发来的数据是否有效
        serializer.is_valid(raise_exception=True)

        # 4. 调用我们重写过的 perform_update，所有魔法都在那里发生
        self.perform_update(serializer)

        # 5. 从数据库重新加载实例，确保返回给前端的是绝对最新的真实数据
        instance.refresh_from_db()
        
        # 6. 返回更新后的数据
        return Response(self.get_serializer(instance).data)

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
