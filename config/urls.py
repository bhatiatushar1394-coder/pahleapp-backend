from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("maintenance.urls")),
]

# Serve uploaded complaint photos on free hosts (SQLite/local disk demo).
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
