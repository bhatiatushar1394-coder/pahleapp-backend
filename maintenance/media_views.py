from django.conf import settings
from django.http import HttpResponse
from django.views.static import serve as static_serve

from .models import StoredFile


def serve_media(request, path):
    rec = StoredFile.objects.filter(path=path).first()
    if rec:
        response = HttpResponse(bytes(rec.data), content_type=rec.content_type or "application/octet-stream")
        response["Cache-Control"] = "public, max-age=86400"
        response["Content-Disposition"] = "inline"
        return response
    return static_serve(request, path, document_root=settings.MEDIA_ROOT)
