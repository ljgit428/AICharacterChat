from django.contrib import admin
from .models import Character, ChatSession, Message, ModelConfiguration, ModelRoleAssignment


@admin.register(ModelConfiguration)
class ModelConfigurationAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'provider', 'model_name', 'updated_at')
    list_filter = ('provider',)
    search_fields = ('name', 'model_name', 'user__username')


@admin.register(ModelRoleAssignment)
class ModelRoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'model_config', 'updated_at')
    list_filter = ('role',)
    list_select_related = ('user', 'model_config')
    search_fields = ('user__username', 'model_config__name')


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'user', 'character', 'updated_at')
    list_select_related = ('user', 'character')
    search_fields = ('title', 'user__username', 'character__name')


@admin.register(Character)
class CharacterAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'created_by', 'updated_at')
    search_fields = ('name', 'created_by__username')


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'chat_session', 'role', 'timestamp')
    list_filter = ('role',)
