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
        Also deletes the old Gemini file if one exists.
        """
        if 'file' not in request.FILES:
            return

        # If there was an old file, delete it from Gemini first to avoid orphans
        self._delete_gemini_file(instance.gemini_file_uri)
        
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
            # The file itself will be saved by the serializer, here we just update the URI
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
        instance = serializer.save()

        # Case 1: A new file is being uploaded. The helper will handle it.
        if 'file' in self.request.FILES:
            self._upload_to_gemini_and_save_uri(instance, self.request)
        
        # Case 2: NO new file is uploaded, check if we should CLEAR the existing one.
        # FormData sends boolean 'true' as a string.
        elif self.request.data.get('clear_file') in ['true', 'True', True]:
            print("Clear file request received. Deleting existing file.")
            
            # Delete remote file
            self._delete_gemini_file(instance.gemini_file_uri)
            
            # Delete local file from storage
            if instance.file:
                instance.file.delete(save=False)

            # Clear fields in the database
            instance.gemini_file_uri = None
            instance.save()

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
