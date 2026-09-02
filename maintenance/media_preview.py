from io import BytesIO
from pathlib import Path

from django.core.files.base import ContentFile


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def is_image_name(name):
    return Path(name or "").suffix.lower() in IMAGE_SUFFIXES


def is_pdf_name(name):
    return Path(name or "").suffix.lower() == ".pdf"


def ensure_media_preview(media):
    """Build a first-page PNG for PDFs so quotation/certificate slots show a thumbnail."""
    if not media or not media.file or media.preview:
        return media
    name = media.file.name or ""
    if is_image_name(name) or not is_pdf_name(name):
        return media
    try:
        import pypdfium2 as pdfium

        media.file.open("rb")
        data = media.file.read()
        try:
            media.file.seek(0)
        except Exception:
            pass
        pdf = pdfium.PdfDocument(data)
        page = pdf[0]
        image = page.render(scale=1.4).to_pil()
        pdf.close()
        image.thumbnail((640, 400))
        buf = BytesIO()
        image.convert("RGB").save(buf, format="PNG")
        buf.seek(0)
        media.preview.save(f"{Path(name).stem}-preview.png", ContentFile(buf.read()), save=True)
    except Exception:
        return media
    return media
