import os

from django.core.files.storage import default_storage
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response


@api_view(['POST'])
@permission_classes([])
def upload_file_view(request):
    file_obj = request.FILES.get('file')
    if not file_obj:
        return Response(
            {"error": "No file was uploaded."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        saved_path = default_storage.save(f"uploads/{file_obj.name}", file_obj)
        relative_url = default_storage.url(saved_path)
        absolute_url = request.build_absolute_uri(relative_url)

        return Response({
            "name": os.path.basename(saved_path),
            "uri": absolute_url,
            "display_name": file_obj.name,
        }, status=status.HTTP_201_CREATED)
    except Exception as e:
        return Response(
            {"error": f"Failed to upload file: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
