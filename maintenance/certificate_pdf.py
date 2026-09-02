from io import BytesIO
from pathlib import Path

from django.core.files.base import ContentFile
from reportlab.lib.colors import HexColor, black
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


NAVY = HexColor("#003087")
ORANGE = HexColor("#f36c21")


def _banner_path():
    here = Path(__file__).resolve().parent
    candidates = [
        here / "assets" / "pahle-brand-banner.png",
        here.parents[1] / "frontend" / "public" / "pahle-brand-banner.png",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _draw_wrapped(page, text, x, y, max_width, font, size, leading):
    page.setFont(font, size)
    line = ""
    for word in str(text).split():
        trial = f"{line} {word}".strip()
        if stringWidth(trial, font, size) <= max_width:
            line = trial
            continue
        if line:
            page.drawString(x, y, line)
            y -= leading
        line = word
    if line:
        page.drawString(x, y, line)
        y -= leading
    return y


def build_certificate_pdf(cert):
    buf = BytesIO()
    page = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    left = 28 * mm
    right = width - 28 * mm
    y = height - 16 * mm

    banner = _banner_path()
    if banner:
        try:
            img = ImageReader(str(banner))
            iw, ih = img.getSize()
            max_w = right - left
            max_h = 24 * mm
            scale = min(max_w / iw, max_h / ih)
            bw, bh = iw * scale, ih * scale
            page.drawImage(img, (width - bw) / 2, y - bh, width=bw, height=bh, mask="auto", preserveAspectRatio=True)
            y -= bh + 5 * mm
        except Exception:
            pass

    page.setStrokeColor(ORANGE)
    page.setLineWidth(3)
    page.line(left, y + 4 * mm, right, y + 4 * mm)
    page.setFillColor(NAVY)
    page.setFont("Times-Bold", 18)
    page.drawCentredString(width / 2, y, "Job Completion Certificate")
    y -= 14 * mm

    page.setFillColor(black)
    page.setFont("Times-Roman", 11)
    date_str = cert.certificate_date.strftime("%d %B %Y") if cert.certificate_date else ""
    page.drawString(left, y, f"Date: {date_str}")
    y -= 12 * mm

    page.drawString(left, y, "To,")
    y -= 6 * mm
    page.setFont("Times-Bold", 12)
    page.drawString(left, y, f"M/s {cert.vendor_name}")
    y -= 6 * mm
    page.setFont("Times-Roman", 11)
    if cert.vendor_address:
        for line in str(cert.vendor_address).splitlines() or [cert.vendor_address]:
            page.drawString(left, y, line[:95])
            y -= 5.5 * mm
    y -= 6 * mm

    max_width = right - left
    y = _draw_wrapped(
        page,
        f"Subject: Job Completion Certificate for {cert.nature_of_job} at {cert.customer_name}",
        left,
        y,
        max_width,
        "Times-Bold",
        11,
        5.5 * mm,
    )
    y -= 6 * mm

    y = _draw_wrapped(
        page,
        f"It is hereby acknowledged that Work has been completed by M/s {cert.vendor_name}",
        left,
        y,
        max_width,
        "Times-Roman",
        12,
        6 * mm,
    )
    y -= 7 * mm
    satisfactory = "and Work is Satisfactory" if cert.work_satisfactory else "and Work is noted"
    page.drawString(left, y, satisfactory)
    y -= 22 * mm

    if cert.signature:
        try:
            with cert.signature.open("rb") as fh:
                img = ImageReader(BytesIO(fh.read()))
            page.drawImage(img, left, y - 8 * mm, width=50 * mm, height=18 * mm, mask="auto", preserveAspectRatio=True)
        except Exception:
            pass
    page.setStrokeColor(HexColor("#94a3b8"))
    page.setLineWidth(0.6)
    page.line(left, y - 10 * mm, left + 55 * mm, y - 10 * mm)
    page.setFillColor(black)
    page.setFont("Times-Roman", 10)
    page.drawString(left, y - 16 * mm, "Sign of Customer")
    page.setFont("Times-Bold", 11)
    page.drawString(left, y - 23 * mm, cert.customer_name)
    page.setFont("Times-Roman", 10)
    done = cert.job_completion_date.strftime("%d %B %Y") if cert.job_completion_date else ""
    page.drawString(left, y - 29 * mm, f"Date of Job Completion: {done}")

    page.setStrokeColor(NAVY)
    page.setLineWidth(2)
    page.line(left, 18 * mm, right, 18 * mm)
    page.setFont("Times-Roman", 8)
    page.setFillColor(NAVY)
    page.drawCentredString(width / 2, 12 * mm, "PAHLE-APP  ·  IndianOil Army Consumer Pump Maintenance")

    page.showPage()
    page.save()
    return ContentFile(buf.getvalue(), name=f"{cert.complaint.complaint_id}-job-completion.pdf")
