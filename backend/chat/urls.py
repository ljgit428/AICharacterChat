from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CharacterViewSet, ChatSessionViewSet, MessageViewSet, ChatViewSet

router = DefaultRouter()
router.register(r'characters', CharacterViewSet)
router.register(r'sessions', ChatSessionViewSet)
router.register(r'messages', MessageViewSet)
router.register(r'chat', ChatViewSet, basename='chat')

urlpatterns = [
    path('', include(router.urls)),
]