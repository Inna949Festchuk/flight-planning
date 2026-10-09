"""Аутентификация по внутреннему токену (для MCP-сервера)."""

from rest_framework.authentication import BaseAuthentication

from django.conf import settings
from django.contrib.auth import get_user_model


class InternalTokenAuthentication(BaseAuthentication):
    def authenticate(self, request):
        token = request.META.get("HTTP_X_INTERNAL_TOKEN")
        if not token or token != settings.INTERNAL_API_TOKEN:
            return None
        user = get_user_model().objects.filter(username="mcp_agent").first()
        if user is None:
            user = get_user_model().objects.create_user(username="mcp_agent", email="mcp@geoscan.local")
        return (user, None)

    def authenticate_header(self, request):
        return "X-Internal-Token"
