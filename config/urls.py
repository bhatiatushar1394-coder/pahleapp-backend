from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("maintenance.urls")),
    # django.conf.urls.static() is a no-op when DEBUG=False, which is why
    # uploaded photos 404 on Render. Serve media explicitly for this demo.
    re_path(
        r"^media/(?P<path>.*)$",
        serve,
        {"document_root": settings.MEDIA_ROOT},
    ),
]
