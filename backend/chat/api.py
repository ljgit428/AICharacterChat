from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.files.storage import default_storage
import os

@csrf_exempt
def upload_image(request):
    if request.method == 'POST' and request.FILES.get('file'):
        image = request.FILES['file']
        
        file_name = default_storage.save(f"avatars/{image.name}", image)
        
        relative_url = default_storage.url(file_name)
        
        full_url = request.build_absolute_uri(relative_url)
        
        return JsonResponse({'url': full_url})
        
    return JsonResponse({'error': 'No file uploaded'}, status=400)