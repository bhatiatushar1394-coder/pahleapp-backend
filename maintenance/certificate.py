from datetime import date

from django.core.files.base import ContentFile
from django.utils import timezone

from .certificate_pdf import build_certificate_pdf
from .models import Complaint, ComplaintMedia, JobCompletionCertificate, User

CERT_READY_STATUSES = {
    Complaint.Status.WORK_COMPLETION,
    Complaint.Status.USER_CONFIRMATION,
    Complaint.Status.CLOSED,
}


def today_local():
    return timezone.localdate()


def certificate_defaults(complaint):
    vendor = complaint.assigned_vendor
    nature = (complaint.specific_problem or "").strip() or complaint.get_category_display()
    return {
        "certificate_date": today_local(),
        "vendor_name": (vendor.name if vendor else "") or "",
        "vendor_address": "",
        "nature_of_job": nature[:255],
        "customer_name": complaint.pump.name if complaint.pump_id else "",
        "job_completion_date": today_local(),
        "work_satisfactory": True,
    }


def parse_date(value, fallback):
    if not value:
        return fallback
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return fallback


def parse_bool(value, fallback):
    if value is None or value == "":
        return fallback
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def apply_letter_fields(cert, data):
    cert.certificate_date = parse_date(data.get("certificate_date"), cert.certificate_date or today_local())
    if data.get("vendor_name") is not None:
        cert.vendor_name = str(data.get("vendor_name") or "").strip()[:200] or cert.vendor_name
    if data.get("vendor_address") is not None:
        cert.vendor_address = str(data.get("vendor_address") or "").strip()
    if data.get("nature_of_job") is not None:
        cert.nature_of_job = str(data.get("nature_of_job") or "").strip()[:255] or cert.nature_of_job
    if data.get("customer_name") is not None:
        cert.customer_name = str(data.get("customer_name") or "").strip()[:200] or cert.customer_name
    cert.job_completion_date = parse_date(data.get("job_completion_date"), cert.job_completion_date or today_local())
    if data.get("work_satisfactory") is not None:
        cert.work_satisfactory = parse_bool(data.get("work_satisfactory"), cert.work_satisfactory)


def get_certificate(complaint):
    return getattr(complaint, "job_certificate", None)


def get_or_create_draft(complaint, user=None):
    cert = get_certificate(complaint)
    if cert:
        return cert
    defaults = certificate_defaults(complaint)
    return JobCompletionCertificate.objects.create(
        complaint=complaint,
        stage=JobCompletionCertificate.Stage.VENDOR_DRAFT,
        prepared_by=user,
        prepared_at=timezone.now() if user else None,
        **defaults,
    )


def vendor_owns(user, complaint):
    if user.role != User.Role.VENDOR:
        return False
    profile = getattr(user, "vendor_profile", None)
    return bool(profile and complaint.assigned_vendor_id == profile.id)


def customer_owns(user, complaint):
    return user.role == User.Role.CP_USER and (
        complaint.submitted_by_id == user.id or complaint.pump_id == user.consumer_pump_id
    )


def save_generated_pdf(cert):
    pdf = build_certificate_pdf(cert)
    cert.generated_pdf.save(pdf.name, pdf, save=True)


def attach_certificate_media(complaint, file_field, user):
    if not file_field:
        return
    file_field.open("rb")
    try:
        content = ContentFile(file_field.read(), name=file_field.name.split("/")[-1])
    finally:
        try:
            file_field.seek(0)
        except Exception:
            pass
    ComplaintMedia.objects.create(
        complaint=complaint,
        kind=ComplaintMedia.Kind.CERTIFICATE,
        file=content,
        uploaded_by=user,
    )
