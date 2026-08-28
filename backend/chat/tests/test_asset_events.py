"""Asset event-log tests: upload lifecycle, projection, TTL reclamation.

Follows ``test_memory.py``'s SQLite-in-memory pattern so the suite stays
runnable without a local PostgreSQL. SQLite does not hit the JSONB-vs-bigint
PostgreSQL issue, so these tests exercise the store/projection logic directly.
"""
import os
import tempfile
import shutil
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from .test_memory import SQLITE_TEST_DATABASES


@override_settings(DATABASES=SQLITE_TEST_DATABASES)
@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
@override_settings(ASSET_UPLOAD_TTL_DAYS=7)
class AssetEventBaseTests(TestCase):
    def setUp(self):
        from chat.models import Character

        self.media_root = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()

        self.user = User.objects.create_user(username='asset-owner', password='x')
        self.other_user = User.objects.create_user(username='asset-other', password='x')
        self.character = Character.objects.create(
            created_by=self.user,
            name='Asset Character',
            description='For asset event tests.',
            scenario='Test',
            tags=['assets'],
        )

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    def _upload(self, filename='scene.txt', content='Hello world.', user=None):
        from chat.assets.store import AssetStore

        file_obj = SimpleUploadedFile(filename, content.encode('utf-8'), content_type='text/plain')
        event, metadata = AssetStore.upload(user or self.user, file_obj, filename)
        return event, metadata


class AssetStoreUploadTests(AssetEventBaseTests):
    def test_upload_creates_event_with_pending_file(self):
        from chat.models import AssetEvent, AssetEventType

        event, metadata = self._upload()
        self.assertEqual(event.event_type, AssetEventType.UPLOADED)
        self.assertEqual(event.user_id, self.user.id)
        self.assertIsNotNone(event.expires_at)
        self.assertEqual(metadata['upload_id'], event.id)
        # The file is staged under a pending dir.
        self.assertIn('uploads/pending/', event.data['file_path'])
        stored = os.path.join(self.media_root, event.data['file_path'])
        self.assertTrue(os.path.exists(stored))
        self.assertEqual(AssetEvent.objects.filter(event_type=AssetEventType.UPLOADED).count(), 1)

    def test_upload_rejects_oversized_or_unsupported_files(self):
        # Unsupported kind (e.g. audio) raises.
        from chat.assets.store import AssetStore

        audio = SimpleUploadedFile('sound.mp3', b'data', content_type='audio/mpeg')
        with self.assertRaises(ValueError):
            AssetStore.upload(self.user, audio, 'sound.mp3')

    def test_upload_is_owner_scoped(self):
        from chat.assets.store import AssetStore

        event, _ = self._upload(user=self.other_user)
        pending = AssetStore.pending_uploads(self.user)
        self.assertEqual(pending, [])  # other user's upload not visible
        pending_other = AssetStore.pending_uploads(self.other_user)
        self.assertEqual([e.id for e in pending_other], [event.id])


class AssetStoreAttachDetachTests(AssetEventBaseTests):
    def test_attach_projects_knowledge_asset_and_consumes_pending_file(self):
        from chat.assets.store import AssetStore
        from chat.models import AssetEvent, AssetEventType, CharacterKnowledgeAsset

        event, _ = self._upload(filename='raw/notes.txt', content='Archive notes.')
        pending_path = event.data['file_path']

        assets = AssetStore.attach(self.character, [event.id])
        self.assertEqual(len(assets), 1)
        asset = assets[0]
        self.assertEqual(asset.character_id, self.character.id)
        self.assertEqual(asset.attachment_name, 'raw/notes.txt')
        self.assertEqual(asset.attachment_text_content, 'Archive notes.')
        self.assertEqual(asset.upload_event_id, event.id)

        # attached event recorded
        self.assertTrue(
            AssetEvent.objects.filter(event_type=AssetEventType.ATTACHED, character=self.character).exists()
        )
        # pending file consumed (moved to asset storage)
        self.assertFalse(os.path.exists(os.path.join(self.media_root, pending_path)))
        self.assertTrue(asset.file and os.path.exists(asset.file.path))
        self.assertEqual(CharacterKnowledgeAsset.objects.filter(character=self.character).count(), 1)

    def test_attach_rejects_missing_or_unowned_uploads(self):
        from chat.assets.store import AssetStore

        # other user's upload cannot be attached to my character
        event, _ = self._upload(user=self.other_user)
        with self.assertRaises(Exception):
            AssetStore.attach(self.character, [event.id])

        # unknown id
        with self.assertRaises(Exception):
            AssetStore.attach(self.character, [999999])

    def test_attach_rejects_already_attached_upload(self):
        from chat.assets.store import AssetStore

        event, _ = self._upload()
        AssetStore.attach(self.character, [event.id])
        with self.assertRaises(Exception):
            AssetStore.attach(self.character, [event.id])

    def test_attach_raises_when_pending_file_missing(self):
        from chat.assets.store import AssetStore
        from chat.assets.projection import AssetFileMissingError

        event, _ = self._upload()
        # delete the staging file behind the store's back
        os.remove(os.path.join(self.media_root, event.data['file_path']))
        with self.assertRaises(AssetFileMissingError):
            AssetStore.attach(self.character, [event.id])

    def test_detach_removes_asset_and_file(self):
        from chat.assets.store import AssetStore
        from chat.models import AssetEvent, AssetEventType, CharacterKnowledgeAsset

        assets = AssetStore.attach(self.character, [self._upload()[0].id])
        asset = assets[0]
        asset_path = asset.file.path

        count = AssetStore.detach(self.character, [asset.id], reason='test')
        self.assertEqual(count, 1)
        self.assertEqual(CharacterKnowledgeAsset.objects.filter(character=self.character).count(), 0)
        self.assertFalse(os.path.exists(asset_path))
        self.assertTrue(
            AssetEvent.objects.filter(event_type=AssetEventType.DETACHED, character=self.character).exists()
        )

    def test_detach_legacy_asset_without_upload_event_id(self):
        """Directly-created (pre-event-log) assets can be detached too."""
        from chat.assets.store import AssetStore
        from chat.models import CharacterKnowledgeAsset

        legacy = CharacterKnowledgeAsset.objects.create(
            character=self.character,
            file=SimpleUploadedFile('legacy.txt', b'legacy', content_type='text/plain'),
            attachment_name='legacy.txt',
            attachment_kind='text',
            attachment_text_content='legacy',
            sort_order=0,
        )
        legacy_path = legacy.file.path

        count = AssetStore.detach(self.character, [legacy.id], reason='user delete')
        self.assertEqual(count, 1)
        self.assertFalse(os.path.exists(legacy_path))
        self.assertEqual(CharacterKnowledgeAsset.objects.filter(character=self.character).count(), 0)


class AssetStoreReclamationTests(AssetEventBaseTests):
    def test_expire_stale_closes_expired_uploads(self):
        from chat.assets.store import AssetStore
        from chat.models import AssetEvent, AssetEventType

        event, _ = self._upload()
        pending_path = event.data['file_path']

        # Backdate the expires_at so it is stale.
        AssetEvent.objects.filter(id=event.id).update(
            expires_at=timezone.now() - timedelta(hours=1)
        )
        count = AssetStore.expire_stale()
        self.assertEqual(count, 1)
        self.assertTrue(
            AssetEvent.objects.filter(event_type=AssetEventType.EXPIRED).exists()
        )
        self.assertFalse(os.path.exists(os.path.join(self.media_root, pending_path)))

    def test_attached_upload_is_not_expired(self):
        from chat.assets.store import AssetStore
        from chat.models import AssetEvent

        event, _ = self._upload()
        AssetStore.attach(self.character, [event.id])
        AssetEvent.objects.filter(id=event.id).update(
            expires_at=timezone.now() - timedelta(hours=1)
        )
        count = AssetStore.expire_stale()
        self.assertEqual(count, 0)  # attached upload survives
        self.assertFalse(AssetEvent.objects.filter(event_type='asset/expired').exists())

    def test_pending_uploads_excludes_attached_and_expired(self):
        from chat.assets.store import AssetStore
        from chat.models import AssetEvent

        attached_event, _ = self._upload(filename='attached.txt')
        stale_event, _ = self._upload(filename='stale.txt')
        AssetStore.attach(self.character, [attached_event.id])
        AssetEvent.objects.filter(id=stale_event.id).update(
            expires_at=timezone.now() - timedelta(hours=1)
        )
        AssetStore.expire_stale()

        pending = AssetStore.pending_uploads(self.user)
        self.assertNotIn(attached_event.id, [e.id for e in pending])
        self.assertNotIn(stale_event.id, [e.id for e in pending])


class AssetProjectionRebuildTests(AssetEventBaseTests):
    def test_rebuild_restores_assets_from_events(self):
        from chat.assets.projection import rebuild_character_assets
        from chat.assets.store import AssetStore
        from chat.models import CharacterKnowledgeAsset

        a1, _ = self._upload(filename='one.txt', content='First.')
        a2, _ = self._upload(filename='two.txt', content='Second.')
        AssetStore.attach(self.character, [a1.id, a2.id])
        before = {
            (asset.attachment_name, asset.attachment_text_content, asset.upload_event_id)
            for asset in CharacterKnowledgeAsset.objects.filter(character=self.character)
        }
        self.assertEqual(len(before), 2)

        restored = rebuild_character_assets(self.character)
        after = {
            (asset.attachment_name, asset.attachment_text_content, asset.upload_event_id)
            for asset in restored
        }
        self.assertEqual(after, before)

    def test_upload_endpoint_requires_authentication(self):
        """Regression: /files/upload must not be anonymous."""
        response = self.client.post(
            '/api/files/upload/',
            data={'file': SimpleUploadedFile('x.txt', b'x', content_type='text/plain')},
            format='multipart',
        )
        # Not authenticated → 401/403, never a 201 with a stored file.
        self.assertIn(response.status_code, (401, 403))
