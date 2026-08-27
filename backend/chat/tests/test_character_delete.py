"""Character deletion tests.

Covers the DELETE /api/characters/{id} endpoint for characters that own
chat history: the endpoint used to refuse deletion when any chat session
existed, leaving the user stuck. Character deletion now cascades the
related rows (sessions, messages, knowledge assets, memory items, audit
log) and removes the on-disk files (avatar, character file, knowledge
assets, message attachments).

Runs on in-memory SQLite like ``test_memory`` so it stays usable without
a local PostgreSQL. Media files go to the real MEDIA_ROOT under
uuid-prefixed names and are removed by the flow under test.
"""
import uuid

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from chat.models import (
    AttachmentKind,
    Character,
    CharacterKnowledgeAsset,
    CharacterMemoryItem,
    ChatSession,
    MemoryAuditAction,
    MemoryAuditLog,
    Message,
)

SQLITE_TEST_DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    },
}


@override_settings(DATABASES=SQLITE_TEST_DATABASES)
@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class CharacterDeleteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='delete-owner', password='password123')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.character = Character.objects.create(
            created_by=self.user,
            name='Delete Me',
            description='A character with chat history.',
        )

        token = uuid.uuid4().hex

        avatar_name = default_storage.save(f'avatars/delete-{token}.png', ContentFile(b'fake png'))
        self.character.avatar_url = default_storage.url(avatar_name)
        self.avatar_path = avatar_name

        self.character.file.save(f'char-{token}.txt', ContentFile(b'character file'))
        self.char_file_path = self.character.file.name

        self.asset = CharacterKnowledgeAsset.objects.create(
            character=self.character,
            attachment_name=f'ref-{token}.txt',
            attachment_kind=AttachmentKind.TEXT,
        )
        self.asset.file.save(self.asset.attachment_name, ContentFile(b'reference file'))
        self.asset_file_path = self.asset.file.name

        self.session = ChatSession.objects.create(
            character=self.character,
            user=self.user,
            title='chat history',
        )
        self.message = Message.objects.create(
            chat_session=self.session,
            role='user',
            content='hello there',
            character=self.character,
        )
        self.message.attachment.save(f'voice-{token}.mp3', ContentFile(b'fake audio'))
        self.attachment_path = self.message.attachment.name

        self.memory_item = CharacterMemoryItem.objects.create(
            character=self.character,
            short_id=uuid.uuid4().hex[:8],
            section='meta',
            description='something the model learned about the user.',
        )
        MemoryAuditLog.objects.create(
            character=self.character,
            action=MemoryAuditAction.CREATE,
            entry_short_id=self.memory_item.short_id,
            reason='test',
        )

    def test_delete_character_with_history_cascades_and_cleans_files(self):
        response = self.client.delete(f'/api/characters/{self.character.pk}/')

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Character.objects.filter(pk=self.character.pk).exists())
        self.assertFalse(ChatSession.objects.filter(pk=self.session.pk).exists())
        self.assertFalse(Message.objects.filter(pk=self.message.pk).exists())
        self.assertFalse(CharacterKnowledgeAsset.objects.filter(pk=self.asset.pk).exists())
        self.assertFalse(CharacterMemoryItem.objects.filter(pk=self.memory_item.pk).exists())
        self.assertFalse(MemoryAuditLog.objects.exists())

        for file_path in (
            self.avatar_path,
            self.char_file_path,
            self.asset_file_path,
            self.attachment_path,
        ):
            self.assertFalse(default_storage.exists(file_path), f'{file_path} should be deleted')

    def test_delete_character_without_history_still_works(self):
        plain = Character.objects.create(
            created_by=self.user,
            name='No History',
            description='A character without any chat history.',
        )

        response = self.client.delete(f'/api/characters/{plain.pk}/')

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Character.objects.filter(pk=plain.pk).exists())
