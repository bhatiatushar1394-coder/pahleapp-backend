import mimetypes
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.views.static import serve as static_serve

from .models import StoredFile

_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
    ".pdf": "application/pdf",
}


def _content_type(path, stored=""):
    ext = Path(path).suffix.lower()
    if ext in _TYPES:
        return _TYPES[ext]
    if stored and stored != "application/octet-stream":
        return stored
    guessed, _ = mimetypes.guess_type(path)
    return guessed or stored or "application/octet-stream"


def serve_media(request, path):
    rec = StoredFile.objects.filter(path=path).first()
    filename = Path(path).name or "file"
    if rec:
        response = HttpResponse(bytes(rec.data), content_type=_content_type(path, rec.content_type))
        response["Cache-Control"] = "public, max-age=86400"
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response
    response = static_serve(request, path, document_root=settings.MEDIA_ROOT)
    response["Content-Type"] = _content_type(path, response.get("Content-Type", ""))
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response
