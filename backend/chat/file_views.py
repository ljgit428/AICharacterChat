import os

from django.core.files.storage import default_storage
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

MAX_RELATIVE_PATH_SEGMENTS = 12


def sanitize_relative_path(raw_path):
    """Normalize a client-supplied folder path (e.g. webkitRelativePath) into a
    safe storage sub-path. Keeps the folder hierarchy so that file groups stay
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
@permission_classes([])
def upload_file_view(request):
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
        saved_path = default_storage.save(f"uploads/{relative_path}", file_obj)
        relative_url = default_storage.url(saved_path)
        absolute_url = request.build_absolute_uri(relative_url)

        return Response({
            "name": os.path.basename(saved_path),
            "uri": absolute_url,
            "display_name": file_obj.name,
            "relative_path": relative_path,
        }, status=status.HTTP_201_CREATED)
    except Exception as e:
        return Response(
            {"error": f"Failed to upload file: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
