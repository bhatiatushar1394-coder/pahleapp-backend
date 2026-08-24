from django.contrib import admin
from django.urls import include, path, re_path

from maintenance.media_views import serve_media

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("maintenance.urls")),
    re_path(r"^media/(?P<path>.*)$", serve_media),
]
