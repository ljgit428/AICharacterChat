from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Character(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()
    personality = models.TextField()
    appearance = models.TextField()
    response_guidelines = models.TextField(blank=True, null=True)
    image_uri = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_characters')
    
    def __str__(self):
        return self.name


class ChatSession(models.Model):
    character = models.ForeignKey(Character, on_delete=models.CASCADE, related_name='chat_sessions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_sessions')
    title = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_generating_response = models.BooleanField(default=False)
    gemini_chat_id = models.CharField(max_length=255, blank=True, null=True)
    
    def __str__(self):
        return f"{self.title or f'Chat with {self.character.name}'} - {self.user.username}"


class Message(models.Model):
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
    ]
    
    chat_session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    character = models.ForeignKey(Character, on_delete=models.CASCADE, related_name='messages', null=True, blank=True)
    file_uri = models.CharField(max_length=255, blank=True, null=True)
    
    class Meta:
        ordering = ['timestamp']
    
    def __str__(self):
        return f"{self.role}: {self.content[:50]}..."
