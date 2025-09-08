# backend/chat/file_views.py

import google.generativeai as genai
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
import tempfile  # 用于创建临时文件
import os        # 用于删除临时文件

@api_view(['POST'])
@permission_classes([])
def upload_file_view(request):
    """
    Handles file uploads by saving them to a temporary file, uploading to Gemini,
    and then cleaning up the temporary file.
    """
    # 1. API Key Check (remains the same)
    api_key = getattr(settings, 'GEMINI_API_KEY', '')
    if not api_key:
        return Response(
            {"error": "GEMINI_API_KEY is not configured on the server."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    genai.configure(api_key=api_key)

    # 2. Get File Object (remains the same)
    file_obj = request.FILES.get('file')
    if not file_obj:
        return Response(
            {"error": "No file was uploaded."},
            status=status.HTTP_400_BAD_REQUEST
        )

    temp_file_path = None
    try:
        # --- vvv 核心修正逻辑 vvv ---

        # 3. 创建一个安全的临时文件来保存上传的内容
        #    使用 delete=False 是因为我们需要在 with 块之外保持文件存在，以便传递路径
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file_obj.name}") as temp_file:
            # 4. 将上传的文件内容写入这个临时文件
            for chunk in file_obj.chunks():
                temp_file.write(chunk)
            # 5. 获取这个临时文件的完整路径
            temp_file_path = temp_file.name

        print(f"Uploading file '{file_obj.name}' from temporary path '{temp_file_path}'...")

        # 6. 使用临时文件的路径调用 Gemini API
        gemini_file = genai.upload_file(
            path=temp_file_path,  # <--- 现在传递的是一个字符串路径，完全符合要求
            display_name=file_obj.name,
        )
        
        # --- ^^^ 核心修正逻辑结束 ^^^ ---
        
        print(f"File uploaded successfully. URI: {gemini_file.uri}")

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
    finally:
        # 7. 清理工作：无论成功还是失败，都要确保删除临时文件
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            print(f"Cleaned up temporary file: {temp_file_path}")