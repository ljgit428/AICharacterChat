from rest_framework import serializers
from .models import Character, ChatSession, Message


class CharacterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Character
        fields = ['id', 'name', 'description', 'personality', 'appearance', 'response_guidelines', 'file', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['id', 'role', 'content', 'timestamp', 'character', 'file_uri']
        read_only_fields = ['timestamp']


class ChatSessionSerializer(serializers.ModelSerializer):
    messages = MessageSerializer(many=True, read_only=True)
    character = CharacterSerializer(read_only=True)
    
    class Meta:
        model = ChatSession
        fields = ['id', 'character', 'user', 'title', 'messages', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']


class ChatSessionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatSession
        fields = ['character', 'title']


class MessageCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['role', 'content', 'character', 'file_uri']