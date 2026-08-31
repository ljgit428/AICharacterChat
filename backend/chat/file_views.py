import os

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .assets.store import AssetStore

MAX_RELATIVE_PATH_SEGMENTS = 12


def sanitize_relative_path(raw_path):
    """Normalize a client-supplied folder path (e.g. webkitRelativePath) into a
    safe display sub-path. Keeps the folder hierarchy so that file groups stay
    browsable in the memory filesystem; collapses traversal and empty parts."""
    normalized = (raw_path or '').replace('\\', '/').strip()
    segments = []
    for segment in normalized.split('/'):
        segment = segment.strip()
        if not segment or segment in {'.', '..'}:
            continue
        segments.append(segment)
        if len(segments) >= MAX_RELATIVE_PATH_SEGMENTS:
            break
    return '/'.join(segments)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_file_view(request):
    """Stage a character-reference file as an ``asset/uploaded`` event.

    The file is stored under a per-user pending directory with a TTL; the
    response carries ``upload_id`` which the character create/edit mutations
    use to attach it. Staging files are reclaimed lazily and via
    ``clean_stale_uploads``.
    """
    file_obj = request.FILES.get('file')
    if not file_obj:
        return Response(
            {"error": "No file was uploaded."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Folder uploads send the original webkitRelativePath so that file groups
    # keep their directory tree; plain single-file uploads just use the name.
    relative_path = sanitize_relative_path(
        request.POST.get('relative_path') or file_obj.name
    ) or os.path.basename(file_obj.name)

    try:
        event, metadata = AssetStore.upload(request.user, file_obj, relative_path)
        return Response({
            "upload_id": event.id,
            "name": metadata['name'],
            "relative_path": metadata['relative_path'],
            "display_name": file_obj.name,
        }, status=status.HTTP_201_CREATED)
    except ValueError as exc:
        return Response(
            {"error": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as exc:  # noqa: BLE001
        return Response(
            {"error": f"Failed to upload file: {str(exc)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
