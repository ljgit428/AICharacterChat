from rest_framework import serializers
from .models import Character, ChatSession, Message, CharacterFile


# New CharacterFile Serializer
class CharacterFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CharacterFile
        fields = ['id', 'original_filename', 'gemini_file_ref', 'uploaded_at']


class CharacterSerializer(serializers.ModelSerializer):
    # Make API able to return full URLs for files
    profile_image = serializers.ImageField(max_length=None, use_url=True, required=False)
    # Use new serializer to show related files
    background_files = CharacterFileSerializer(many=True, read_only=True)
    
    class Meta:
        model = Character
        fields = [
            'id', 'name', 'description', 'personality', 'appearance', 'requirement',
            'created_at', 'updated_at', 'profile_image', 'background_files'
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
        fields = ['id', 'character', 'user', 'title', 'messages', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']


class ChatSessionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatSession
        fields = ['character', 'title']


class MessageCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['role', 'content', 'character']