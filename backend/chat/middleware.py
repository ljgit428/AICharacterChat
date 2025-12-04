# backend/chat/middleware.py
from django.contrib.auth import get_user_model
from django.utils.deprecation import MiddlewareMixin

class DevAutoLoginMiddleware(MiddlewareMixin):
    """
    [DEV ONLY] Automatically logs in a default user for every request.
    This simulates an authenticated session without needing a frontend login UI.
    """
    def process_request(self, request):
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username='demo_user',
            defaults={'email': 'demo@example.com', 'is_staff': True, 'is_superuser': True}
        )

        request.user = user