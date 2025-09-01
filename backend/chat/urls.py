from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CharacterViewSet, ChatSessionViewSet, MessageViewSet, ChatViewSet
from .authentication_views import login, register, logout

router = DefaultRouter()
router.register(r'characters', CharacterViewSet)
router.register(r'sessions', ChatSessionViewSet)
router.register(r'messages', MessageViewSet)
router.register(r'chat', ChatViewSet, basename='chat')

urlpatterns = [
    path('', include(router.urls)),
    path('auth/login/', login, name='login'),
    path('auth/register/', register, name='register'),
    path('auth/logout/', logout, name='logout'),
]