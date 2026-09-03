import mimetypes
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote

from django.conf import settings
from django.http import FileResponse
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


def _headers(response, filename):
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    response["Cross-Origin-Resource-Policy"] = "cross-origin"
    response["Cache-Control"] = "public, max-age=86400"
    return response


def serve_media(request, path):
    path = unquote(path or "").lstrip("/")
    rec = StoredFile.objects.filter(path=path).first()
    filename = Path(path).name or "file"
    if rec:
        response = FileResponse(
            BytesIO(bytes(rec.data)),
            content_type=_content_type(path, rec.content_type),
        )
        return _headers(response, filename)
    response = static_serve(request, path, document_root=settings.MEDIA_ROOT)
    response["Content-Type"] = _content_type(path, response.get("Content-Type", ""))
    return _headers(response, filename)
