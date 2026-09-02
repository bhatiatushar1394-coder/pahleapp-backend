from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from django.core.files.base import ContentFile
from reportlab.lib.colors import HexColor, black
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer


NAVY = HexColor("#003087")
ORANGE = HexColor("#f36c21")
SLATE = HexColor("#334155")


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


def _date_text(value):
    if not value:
        return ""
    return value.strftime("%d %B %Y")


def _signature_image(cert):
    if not cert.signature:
        return None
    try:
        from PIL import Image as PILImage

        with cert.signature.open("rb") as fh:
            im = PILImage.open(fh).convert("RGBA")
        pixels = []
        for r, g, b, a in im.getdata():
            if r > 245 and g > 245 and b > 245:
                pixels.append((r, g, b, 0))
            else:
                pixels.append((r, g, b, a))
        im.putdata(pixels)
        out = BytesIO()
        im.save(out, format="PNG")
        out.seek(0)
        iw, ih = im.size
        if not iw or not ih:
            return None
        height = 16 * mm
        width = min(55 * mm, height * (iw / ih))
        img = Image(out, width=width, height=height)
        img.hAlign = "LEFT"
        return img
    except Exception:
        return None


def build_certificate_pdf(cert):
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=28 * mm,
        rightMargin=28 * mm,
        topMargin=14 * mm,
        bottomMargin=20 * mm,
        title=f"Job Completion Certificate — {cert.complaint.complaint_id}",
        author="PAHLE-APP",
    )

    title_style = ParagraphStyle(
        "CertTitle",
        fontName="Times-Bold",
        fontSize=18,
        leading=22,
        textColor=NAVY,
        alignment=TA_CENTER,
        spaceAfter=0,
    )
    body = ParagraphStyle(
        "CertBody",
        fontName="Helvetica",
        fontSize=11,
        leading=16,
        textColor=black,
        alignment=TA_LEFT,
        spaceAfter=0,
    )
    body_gap = ParagraphStyle("CertBodyGap", parent=body, spaceBefore=10, spaceAfter=0)
    vendor_name = ParagraphStyle(
        "CertVendor",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        spaceBefore=2,
    )
    subject = ParagraphStyle(
        "CertSubject",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=16,
        spaceBefore=12,
        spaceAfter=2,
    )
    ack = ParagraphStyle(
        "CertAck",
        parent=body,
        fontSize=11.5,
        leading=17,
        spaceBefore=12,
    )
    caption = ParagraphStyle(
        "CertCaption",
        parent=body,
        fontSize=9,
        leading=12,
        textColor=SLATE,
        spaceBefore=2,
    )
    name_style = ParagraphStyle(
        "CertName",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=11,
        spaceBefore=8,
    )
    small = ParagraphStyle("CertSmall", parent=body, fontSize=10, leading=14, spaceBefore=4)

    story = []
    banner = _banner_path()
    if banner:
        mark = Image(str(banner))
        mark.drawHeight = 22 * mm
        mark.drawWidth = mark.drawHeight * (1024 / 342)
        mark.hAlign = "CENTER"
        story.append(mark)

    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(width="100%", thickness=2.2, color=ORANGE, spaceBefore=0, spaceAfter=0))
    story.append(Spacer(1, 20 * mm))
    story.append(Paragraph("Job Completion Certificate", title_style))
    story.append(Spacer(1, 12 * mm))

    cid = getattr(getattr(cert, "complaint", None), "complaint_id", "") or ""
    if cid:
        story.append(Paragraph(escape(f"Complaint ID: {cid}"), body))
        story.append(Paragraph(escape(f"Date: {_date_text(cert.certificate_date)}"), body_gap))
    else:
        story.append(Paragraph(escape(f"Date: {_date_text(cert.certificate_date)}"), body))

    story.append(Paragraph("To,", body_gap))
    story.append(Paragraph(escape(f"M/s {cert.vendor_name}"), vendor_name))
    if cert.vendor_address:
        for line in str(cert.vendor_address).splitlines():
            if line.strip():
                story.append(Paragraph(escape(line.strip()), body))

    story.append(
        Paragraph(
            f"Subject: Job Completion Certificate for {escape(cert.nature_of_job)} at {escape(cert.customer_name)}",
            subject,
        )
    )
    satisfactory = "and Work is Satisfactory" if cert.work_satisfactory else "and Work is noted"
    story.append(
        Paragraph(
            f"It is hereby acknowledged that Work has been completed by M/s {escape(cert.vendor_name)} {satisfactory}.",
            ack,
        )
    )

    sign_bits = [Spacer(1, 16 * mm)]
    sig = _signature_image(cert)
    if sig:
        sign_bits.append(sig)
    sign_bits.append(HRFlowable(width=55 * mm, thickness=0.6, color=HexColor("#94a3b8"), spaceBefore=2, spaceAfter=0, hAlign="LEFT"))
    sign_bits.append(Paragraph("Sign of Customer", caption))
    sign_bits.append(Paragraph(escape(cert.customer_name or ""), name_style))
    sign_bits.append(Paragraph(escape(f"Date of Job Completion: {_date_text(cert.job_completion_date)}"), small))
    story.append(KeepTogether(sign_bits))

    doc.build(story)
    return ContentFile(buf.getvalue(), name=f"{cert.complaint.complaint_id}-job-completion.pdf")
