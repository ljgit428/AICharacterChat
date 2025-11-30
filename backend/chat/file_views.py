import google.generativeai as genai
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
import tempfile
import os

@api_view(['POST'])
@permission_classes([])
def upload_file_view(request):
    """
    Handles file uploads by saving them to a temporary file, uploading to Gemini,
    and then cleaning up the temporary file.
    """
    
    api_key = getattr(settings, 'GEMINI_API_KEY', '')
    if not api_key:
        return Response(
            {"error": "GEMINI_API_KEY is not configured on the server."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    genai.configure(api_key=api_key)

    file_obj = request.FILES.get('file')
    if not file_obj:
        return Response(
            {"error": "No file was uploaded."},
            status=status.HTTP_400_BAD_REQUEST
        )

    temp_file_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file_obj.name}") as temp_file:
            
            for chunk in file_obj.chunks():
                temp_file.write(chunk)
            
            temp_file_path = temp_file.name

        gemini_file = genai.upload_file(
            path=temp_file_path,
            display_name=file_obj.name,
        )
        
        return Response({
            "name": gemini_file.name,
            "uri": gemini_file.uri,
            "display_name": gemini_file.display_name,
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        import traceback
        return Response(
            {"error": f"Failed to upload file to Gemini API: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    finally:
        
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)