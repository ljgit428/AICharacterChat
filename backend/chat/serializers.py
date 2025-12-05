from rest_framework import serializers
from .models import Character, ChatSession, Message

class CharacterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Character
        fields = [
            'id', 'name', 'avatar_url', 'description', 'first_message',
            'scenario', 'example_dialogue', 'affiliation', 'tags', 'personality',
            'appearance', 'response_guidelines', 'file',
            'disabled_states', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['id', 'role', 'content', 'timestamp', 'character']
        read_only_fields = ['timestamp']

class ChatSessionSerializer(serializers.ModelSerializer):
    messages = MessageSerializer(many=True, read_only=True)
    character = CharacterSerializer(read_only=True)
    
    class Meta:
        model = ChatSession
        fields = [
            'id', 'character', 'user', 'title', 'messages', 'created_at', 'updated_at',
            'world_time', 'user_persona', 'enable_web_search', 'output_language', 'additional_context'
        ]
        read_only_fields = ['created_at', 'updated_at']

class ChatSessionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatSession
        fields = ['character', 'title', 'world_time', 'user_persona', 'enable_web_search', 'output_language', 'additional_context']

class MessageCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['role', 'content', 'character']