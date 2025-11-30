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
import logging

logger = logging.getLogger(__name__)

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
            return
        
        genai.configure(api_key=api_key)
        try:
            genai.delete_file(name=gemini_uri)
        except Exception as e:
            logger.error(f"Failed to delete file from Gemini: {e}")

    def _upload_to_gemini_and_save_uri(self, instance, request):
        """
        Helper function to upload file from request to Gemini and save the URI.
        """
        if 'file' not in request.FILES:
            return

        file_obj = request.FILES['file']
        
        api_key = getattr(settings, 'GEMINI_API_KEY', '')
        if not api_key:
            return
        genai.configure(api_key=api_key)

        temp_file_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file_obj.name}") as temp_file:
                for chunk in file_obj.chunks():
                    temp_file.write(chunk)
                temp_file_path = temp_file.name
            
            gemini_file = genai.upload_file(path=temp_file_path, display_name=file_obj.name)
            
            instance.gemini_file_uri = gemini_file.name
            instance.save(update_fields=['gemini_file_uri'])
        
        except Exception as e:
            logger.error(f"Failed to upload file to Gemini: {e}")
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
        Handle instance updates in a single atomic operation, including file handling.
        """
        instance = serializer.instance

        if 'file' in self.request.FILES:
            self._delete_gemini_file(instance.gemini_file_uri)
            if instance.file:
                instance.file.delete(save=False)

        elif self.request.data.get('clear_file') in ['true', 'True', True]:
            self._delete_gemini_file(instance.gemini_file_uri)
            if instance.file:
                instance.file.delete(save=False)

            serializer.validated_data['file'] = None
            serializer.validated_data['gemini_file_uri'] = None

        serializer.save()

        if 'file' in self.request.FILES:
            instance.refresh_from_db()
            self._upload_to_gemini_and_save_uri(instance, self.request)

    def update(self, request, *args, **kwargs):
        """
        Robust atomic update method ensuring all changes are persisted to the database.
        """
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        instance.refresh_from_db()
        return Response(self.get_serializer(instance).data)

    @action(detail=False, methods=['get'])
    def my_characters(self, request):
        characters = Character.objects.filter(created_by=request.user)
        serializer = self.get_serializer(characters, many=True)
        return Response(serializer.data)

class ChatSessionViewSet(viewsets.ModelViewSet):
    queryset = ChatSession.objects.all()
    permission_classes = []
    
    def get_serializer_class(self):
        if self.action == 'create':
            return ChatSessionCreateSerializer
        return ChatSessionSerializer
    
    def get_queryset(self):
        queryset = ChatSession.objects.all()
        character_id = self.request.query_params.get('character_id')
        if character_id:
            queryset = queryset.filter(character_id=character_id)
        
        return queryset.order_by('-updated_at')

    def perform_create(self, serializer):
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username='default_user',
            defaults={'email': 'default@example.com'}
        )
        serializer.save(user=user)

class MessageViewSet(viewsets.ModelViewSet):
    queryset = Message.objects.all()
    permission_classes = []
    
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
    permission_classes = []
    
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
            
            User = get_user_model()
            user, created = User.objects.get_or_create(
                username='default_user',
                defaults={'email': 'default@example.com'}
            )
            
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
                    title=f"Chat with {character.name}",
                    world_time=request.data.get('world_time', "Current time"),
                    user_persona=request.data.get('user_persona', "Sensei"),
                    enable_web_search=request.data.get('enable_web_search', False),
                    output_language=request.data.get('output_language', "English"),
                    additional_context=request.data.get('additional_context', "")
                )
            

            user_message = Message.objects.create(
                chat_session=chat_session,
                role='user',
                content=message_content,
                character=character,
                file_uri=file_uri
            )
            
            chat_session.save()
            
            result = generate_ai_response(user_message.id, character.id)
            
            if not result.get('success'):
                return Response(
                    {'error': result.get('error', 'Failed to generate AI response')},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            ai_message = Message.objects.get(id=result['message_id'])

            return Response({
                'user_message': MessageSerializer(user_message).data,
                'ai_message': MessageSerializer(ai_message).data,
                'chat_session_id': chat_session.id
            })
            
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
