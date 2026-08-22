from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("pumps", views.PumpViewSet, basename="pump")
router.register("vendors", views.VendorViewSet, basename="vendor")
router.register("complaints", views.ComplaintViewSet, basename="complaint")

urlpatterns = [
    path("auth/login/", views.login_view),
    path("auth/me/", views.me_view),
    path("meta/", views.meta_view),
    path("dashboard/", views.dashboard_view),
    path("reports/", views.reports_export),
    path("", include(router.urls)),
]
