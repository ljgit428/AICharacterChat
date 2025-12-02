from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

def get_default_disabled_states():
    return {
        "name": False,
        "description": False,
        "personality": False,
        "appearance": False,
        "responseGuidelines": False,
        "file": False,
    }

class Character(models.Model):
    id = models.AutoField(primary_key=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="characters")
    created_at = models.DateTimeField(auto_now_add=True)
    
    name = models.CharField(max_length=100)
    avatar_url = models.URLField(max_length=500, blank=True, null=True)
    description = models.TextField(help_text="The core personality and visual description.")
    first_message = models.TextField(blank=True, help_text="First message sent when chat starts.")
    scenario = models.TextField(blank=True, default="", help_text="Default context/environment.")
    example_dialogue = models.TextField(blank=True, default="", help_text="<START> User: ... Char: ...")
    affiliation = models.TextField(blank=True, default="", help_text="Character's organization or faction.")
    tags = models.JSONField(default=list, blank=True)
    
    personality = models.TextField(blank=True, null=True)
    appearance = models.TextField(blank=True, null=True)
    response_guidelines = models.TextField(blank=True, null=True)
    file = models.FileField(upload_to='character_files/', blank=True, null=True)
    gemini_file_uri = models.CharField(max_length=255, blank=True, null=True)
    disabled_states = models.JSONField(default=get_default_disabled_states)
    updated_at = models.DateTimeField(auto_now=True)
    
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
    
    world_time = models.CharField(max_length=100, blank=True, default="Current time")
    user_persona = models.TextField(blank=True, default="", help_text="User's role or identity in this chat")
    enable_web_search = models.BooleanField(default=False)
    output_language = models.CharField(max_length=50, blank=True, default="English")
    additional_context = models.TextField(blank=True, default="", help_text="Extra instructions for this session")
    
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
