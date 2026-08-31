"""Clean up stale character-reference asset staging files.

This command handles two cleaning tasks:

1. **Event-based reclamation**: expire unattached ``asset/uploaded`` events
   whose TTL has elapsed (same as the lazy reclamation in ``AssetStore.upload``
   but runs explicitly for all users).
2. **Legacy orphan cleanup**: when run with ``--purge-legacy-uploads``, delete
   the old ``media/uploads/`` directory contents (pre-v0.1.4 bare staging files
   that were never attached and have no owner or TTL). This is a one-time
   migration step.

Run ``python manage.py clean_stale_uploads --dry-run`` to preview.
"""
from __future__ import annotations

import os
import shutil

from django.conf import settings
from django.core.management.base import BaseCommand

from chat.assets.store import AssetStore


class Command(BaseCommand):
    help = 'Reclaim stale character-reference asset staging files.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be cleaned without actually deleting.',
        )
        parser.add_argument(
            '--purge-legacy-uploads',
            action='store_true',
            help='Delete the old media/uploads/ directory (pre-v0.1.4 bare staging files).',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        purge_legacy = options['purge_legacy_uploads']

        # --- event-based reclamation ---
        if dry_run:
            self.stdout.write('Dry run: would run expire_stale()')
        else:
            count = AssetStore.expire_stale()
            self.stdout.write(self.style.SUCCESS(f'Expired {count} stale uploads'))

        # --- legacy uploads/ directory purge ---
        legacy_dir = os.path.join(settings.MEDIA_ROOT, 'uploads')
        if purge_legacy and os.path.isdir(legacy_dir):
            if dry_run:
                self.stdout.write(f'Dry run: would delete {legacy_dir} and its contents')
            else:
                shutil.rmtree(legacy_dir)
                self.stdout.write(self.style.SUCCESS(f'Deleted {legacy_dir}'))
        elif purge_legacy:
            self.stdout.write(f'Legacy uploads directory not found: {legacy_dir}')