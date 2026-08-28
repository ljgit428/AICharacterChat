"""Batch upload all Tendo Alice story files to the AssetEvent staging area."""
import django
import os
import json
import sys

# Add the project root (backend/) to the Python path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'prismate.settings')
django.setup()

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from chat.assets.store import AssetStore

u = User.objects.get(username='demo_user')
BASE = 'F:/git/BA_Script_CN_Extract/result/天童爱丽丝剧情'

# Collect all files (relative paths)
all_files = []
for root, dirs, fnames in os.walk(BASE):
    for fn in sorted(fnames):
        full = os.path.join(root, fn)
        rel = os.path.relpath(full, BASE).replace(os.sep, '/')
        all_files.append(rel)

print(f'Total files found: {len(all_files)}')

# Batch upload preserving the folder hierarchy
upload_ids = []
errors = []
for rel in all_files:
    full = os.path.join(BASE, rel)
    try:
        with open(full, 'rb') as f:
            content = f.read()
        if not content:
            continue
        file_obj = SimpleUploadedFile(os.path.basename(rel), content, content_type='text/plain')
        event, _ = AssetStore.upload(u, file_obj, rel)
        upload_ids.append(str(event.id))
    except Exception as exc:  # noqa: BLE001
        errors.append((rel, str(exc)[:80]))

print(f'Uploaded: {len(upload_ids)} events, errors: {len(errors)}')
for rel, err in errors[:5]:
    print(f'  ERR {rel}: {err}')

# Persist upload ids for the next step
out = os.path.join(os.environ.get('TEMP', '/tmp'), 'alice_upload_ids.json')
with open(out, 'w', encoding='utf-8') as f:
    json.dump(upload_ids, f, ensure_ascii=False)
print('upload_ids saved to', out, 'count:', len(upload_ids))
