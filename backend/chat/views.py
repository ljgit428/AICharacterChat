from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
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
        serializer.save(created_by=self.request.user)
    
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
        queryset = ChatSession.objects.filter(user=self.request.user)
        character_id = self.request.query_params.get('character_id')
        if character_id:
            queryset = queryset.filter(character_id=character_id)
        return queryset
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


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
            chat_session = ChatSession.objects.get(
                id=chat_session_id, 
                user=self.request.user
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
        
        if not message_content or not character_id:
            return Response(
                {'error': 'message and character_id are required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            character = Character.objects.get(id=character_id)
            
            # Create or get chat session
            if chat_session_id:
                chat_session = ChatSession.objects.get(
                    id=chat_session_id,
                    user=request.user,
                    character=character
                )
            else:
                # For development, create or get a test user if anonymous
                if request.user.is_anonymous:
                    from django.contrib.auth.models import User
                    test_user, created = User.objects.get_or_create(
                        username='testuser',
                        defaults={'email': 'test@example.com'}
                    )
                    user = test_user
                else:
                    user = request.user
                
                chat_session, created = ChatSession.objects.get_or_create(
                    user=user,
                    character=character,
                    defaults={'title': f"Chat with {character.name}"}
                )
            
            # Save user message
            user_message = Message.objects.create(
                chat_session=chat_session,
                role='user',
                content=message_content,
                character=character
            )
            
            try:
                # Queue AI response generation task
                task = generate_ai_response.delay(user_message.id, character.id)
                
                # Return immediate response with task ID
                return Response({
                    'user_message': MessageSerializer(user_message).data,
                    'task_id': task.id,
                    'status': 'processing',
                    'message': 'AI response is being generated...'
                })
            except Exception as e:
                # If Celery is not available, return a simple response
                # In production, you'd want to handle this more gracefully
                print(f"Celery error: {str(e)}")
                return Response({
                    'user_message': MessageSerializer(user_message).data,
                    'task_id': None,
                    'status': 'error',
                    'message': f'AI response queued but processing failed: {str(e)}',
                    'error': 'Celery worker connection failed. Please check Redis connection and Celery worker status.'
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
