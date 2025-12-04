from rest_framework.authentication import SessionAuthentication

class CsrfExemptSessionAuthentication(SessionAuthentication):
    """
    Custom authentication class that uses Django's session mechanism (request.user)
    but completely bypasses the CSRF check. 
    
    Useful for development when using DevAutoLoginMiddleware.
    """
    def enforce_csrf(self, request):
        return