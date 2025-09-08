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


class CharacterViewSet(viewsets.ModelViewSet):
    queryset = Character.objects.all()
    serializer_class = CharacterSerializer
    permission_classes = []  # Allow access without authentication for development
    
    def perform_create(self, serializer):
        # Get or create default user for development
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username='default_user',
            defaults={'email': 'default@example.com'}
        )
        serializer.save(created_by=user)
    
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
