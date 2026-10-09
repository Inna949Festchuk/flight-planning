from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ChatView, FleetListView, MissionCreateView, MissionViewSet, ProjectViewSet

router = DefaultRouter()
router.register(r"projects", ProjectViewSet, basename="project")
router.register(r"missions", MissionViewSet, basename="mission")

urlpatterns = [
    path("", include(router.urls)),
    path("projects/<int:pk>/missions/", MissionCreateView.as_view(), name="mission-create"),
    path("fleet/", FleetListView.as_view(), name="fleet"),
    path("chat/", ChatView.as_view(), name="chat"),
]
