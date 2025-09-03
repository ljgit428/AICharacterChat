from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth import get_user_model
from django.db.models import Q
from .models import Character, ChatSession, Message
from .serializers import (
    CharacterSerializer,
    ChatSessionSerializer,
    ChatSessionCreateSerializer,
    MessageSerializer,
    MessageCreateSerializer
)
from .tasks import generate_ai_response
from rest_framework.parsers import MultiPartParser, FormParser
import google.generativeai as genai
from django.conf import settings


class CharacterViewSet(viewsets.ModelViewSet):
    queryset = Character.objects.all()
    serializer_class = CharacterSerializer
    permission_classes = []  # Allow access without authentication for development
    parser_classes = [MultiPartParser, FormParser]

    def _upload_file_to_gemini(self, file_obj):
        """A more robust helper to upload a file to Gemini."""
        try:
            print(f"Uploading file '{file_obj.name}' to Gemini...")
            genai.configure(api_key=settings.GEMINI_API_KEY)

            # 使用 with 语句确保临时文件总是被清理
            import tempfile
            import os

            # 创建一个临时文件来写入内存中的数据
            suffix = os.path.splitext(file_obj.name)[1]
            with tempfile.NamedTemporaryFile(mode='wb', delete=True, suffix=suffix, spool_max_size=1024*1024) as temp_f:
                # 将上传的文件内容写入临时文件
                for chunk in file_obj.chunks():
                    temp_f.write(chunk)
                
                # 确保所有内容都已写入磁盘
                temp_f.flush()
                
                # 现在使用这个临时文件的路径进行上传
                response = genai.upload_file(
                    path=temp_f.name,
                    display_name=file_obj.name
                )

            print(f"File uploaded successfully. Gemini file name: {response.name}")
            return response.name
                
        except Exception as e:
            print(f"Error uploading file to Gemini: {e}")
            return None

    def perform_create(self, serializer):
        User = get_user_model()
        user, _ = User.objects.get_or_create(username='default_user')
        
        gemini_ref = None
        background_file = self.request.data.get('background_document')
        print(f"DEBUG: Found background_file in request: {background_file}")
        print(f"DEBUG: File type: {type(background_file)}")
        
        if background_file:
            print(f"DEBUG: Attempting to upload file: {background_file.name}")
            gemini_ref = self._upload_file_to_gemini(background_file)
            print(f"DEBUG: Upload result: {gemini_ref}")
            
        serializer.save(created_by=user, gemini_file_ref=gemini_ref)
        print(f"DEBUG: Character saved with gemini_file_ref: {gemini_ref}")

    def perform_update(self, serializer):
        gemini_ref = serializer.instance.gemini_file_ref  # Keep old reference
        background_file = self.request.data.get('background_document')
        
        if background_file:
            # If new file is uploaded, delete old file (optional but recommended)
            if serializer.instance.gemini_file_ref:
                try:
                    genai.delete_file(name=serializer.instance.gemini_file_ref)
                    print(f"Deleted old Gemini file: {serializer.instance.gemini_file_ref}")
                except Exception as e:
                    print(f"Could not delete old Gemini file: {e}")

            gemini_ref = self._upload_file_to_gemini(background_file)
            
        serializer.save(gemini_file_ref=gemini_ref)
    
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
    parser_classes = [FormParser, MultiPartParser]
    
    @action(detail=False, methods=['post'])
    def send_message(self, request):
        """
        Send a message and get AI response
        """
        message_content = request.data.get('message')
        character_id = request.data.get('character_id')
        chat_session_id = request.data.get('chat_session_id')
        
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
            
            # Save user message
            user_message = Message.objects.create(
                chat_session=chat_session,
                role='user',
                content=message_content,
                character=character
            )
            
            # --- START OF MODIFICATION ---
            # 恢复异步调用Celery任务
            # 使用 .delay() 将任务发送到 Celery worker
            generate_ai_response.delay(user_message.id, character.id)

            # 立即返回响应，告诉前端正在处理中
            return Response({
                'user_message': MessageSerializer(user_message).data,
                'chat_session_id': chat_session.id,
                'status': 'processing' # 告知前端AI正在思考
            }, status=status.HTTP_202_ACCEPTED) # 使用 202 Accepted 状态码
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
