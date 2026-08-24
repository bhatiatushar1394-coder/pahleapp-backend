from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("pumps", views.PumpViewSet, basename="pump")
router.register("vendors", views.VendorViewSet, basename="vendor")
router.register("complaints", views.ComplaintViewSet, basename="complaint")

router.register("registrations", views.RegistrationViewSet, basename="registration")
router.register("notifications", views.NotificationViewSet, basename="notification")

urlpatterns = [
    path("auth/login/", views.login_view),
    path("auth/me/", views.me_view),
    path("auth/register/", views.register_view),
    path("auth/register-options/", views.register_options_view),
    path("health/", views.health_view),
    path("ai/models/", views.assistant_models_view),
    path("ai/chat/", views.assistant_chat_view),
    path("meta/", views.meta_view),
    path("dashboard/", views.dashboard_view),
    path("users/", views.users_directory_view),
    path("reports/", views.reports_export),
    path("", include(router.urls)),
]
