from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible


@deconstructible
class DatabaseStorage(Storage):
    """Keep uploaded photos in Postgres so they survive Render redeploys."""

    def _save(self, name, content):
        from .models import StoredFile

        name = self.get_available_name(name)
        if hasattr(content, "chunks"):
            data = b"".join(chunk for chunk in content.chunks())
        else:
            data = content.read()
        content_type = getattr(content, "content_type", None) or ""
        if not content_type or content_type == "application/octet-stream":
            import mimetypes

            content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        StoredFile.objects.update_or_create(
            path=name,
            defaults={"data": data, "content_type": content_type, "size": len(data)},
        )
        return name

    def _open(self, name, mode="rb"):
        from .models import StoredFile

        rec = StoredFile.objects.get(path=name)
        return ContentFile(bytes(rec.data), name=name)

    def exists(self, name):
        from .models import StoredFile

        return StoredFile.objects.filter(path=name).exists()

    def delete(self, name):
        from .models import StoredFile

        StoredFile.objects.filter(path=name).delete()

    def url(self, name):
        from django.conf import settings

        prefix = settings.MEDIA_URL if settings.MEDIA_URL.endswith("/") else f"{settings.MEDIA_URL}/"
        return f"{prefix}{name.lstrip('/')}"

    def size(self, name):
        from .models import StoredFile

        rec = StoredFile.objects.filter(path=name).only("size").first()
        return rec.size if rec else 0
