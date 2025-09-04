from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
import json


@csrf_exempt
@require_http_methods(["POST"])
def test_cors_view(request):
    """Test view to verify CORS headers are working"""
    try:
        # Try to parse JSON from request body
        data = json.loads(request.body)
        message = data.get('message', 'Hello from Django!')
    except (json.JSONDecodeError, AttributeError):
        message = 'Hello from Django!'
    
    response = JsonResponse({
        'status': 'success',
        'message': message,
        'timestamp': str(__import__('datetime').datetime.now())
    })
    
    # The CORS middleware should add these headers automatically
    return response