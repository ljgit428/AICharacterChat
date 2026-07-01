# backend/chat/middleware.py
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils.deprecation import MiddlewareMixin


class DevAutoLoginMiddleware(MiddlewareMixin):
    """
    [DEV ONLY] Automatically logs in a default user for every request.
    This simulates an authenticated session without needing a frontend login UI.
    """
    def process_request(self, request):
        if not getattr(settings, 'DEV_AUTO_LOGIN_ENABLED', False):
            return

        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=getattr(settings, 'DEV_AUTO_LOGIN_USERNAME', 'demo_user'),
            defaults={
                'email': getattr(settings, 'DEV_AUTO_LOGIN_EMAIL', 'demo@example.com'),
                'is_staff': True,
                'is_superuser': True
            }
        )

        request.user = user
