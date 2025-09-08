import google.generativeai as genai
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

@api_view(['POST'])
@permission_classes([])
def upload_file_view(request):
    """
    Handles file uploads from the frontend, sends them to the Gemini Files API,
    and returns the Gemini file URI.
    """
    # 1. Check for API Key
    api_key = getattr(settings, 'GEMINI_API_KEY', '')
    if not api_key:
        return Response(
            {"error": "GEMINI_API_KEY is not configured on the server."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    genai.configure(api_key=api_key)

    # 2. Get the uploaded file from the request
    file_obj = request.FILES.get('file')
    if not file_obj:
        return Response(
            {"error": "No file was uploaded."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # 3. Upload the file to the Gemini API
    try:
        print(f"Uploading file '{file_obj.name}' to Gemini Files API...")
        # We give it a display name and the actual file bytes
        gemini_file = genai.upload_file(
            path=file_obj,
            display_name=file_obj.name
        )
        print(f"File uploaded successfully. URI: {gemini_file.uri}")

        # 4. Return the URI and name to the frontend
        return Response({
            "name": gemini_file.name,
            "uri": gemini_file.uri,
            "display_name": gemini_file.display_name,
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        import traceback
        print(f"Error uploading file to Gemini: {str(e)}")
        print(traceback.format_exc())
        return Response(
            {"error": f"Failed to upload file to Gemini API: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )