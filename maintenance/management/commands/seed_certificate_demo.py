from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont

from maintenance.constants import SLA_HOURS
from maintenance.models import (
    Complaint,
    ComplaintMedia,
    ConsumerPump,
    JobCompletionCertificate,
    StatusHistory,
    User,
    Vendor,
)

DEMO_IDS = [
    "CMP-2026-030",
    "CMP-2026-031",
    "CMP-2026-032",
    "CMP-2026-033",
    "CMP-2026-034",
    "CMP-2026-035",
]


def proof_file(label, bg):
    img = Image.new("RGB", (800, 500), bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle((16, 16, 784, 484), outline=(255, 255, 255), width=6)
    draw.text((48, 220), label, fill=(255, 255, 255), font=ImageFont.load_default())
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    buf.seek(0)
    return ContentFile(buf.getvalue(), name=f"{label.lower().replace(' ', '_')}.jpg")


def attach_proof(complaint, uploaded_by, kind, label, color):
    rec = ComplaintMedia(complaint=complaint, kind=kind, uploaded_by=uploaded_by)
    rec.file.save(f"{complaint.complaint_id}_{kind.lower()}.jpg", proof_file(label, color), save=True)


def add_history(complaint, steps, actor):
    prev = ""
    for step, note, when in steps:
        StatusHistory.objects.create(
            complaint=complaint,
            from_status=prev,
            to_status=step,
            actor=actor,
            note=note,
            created_at=when,
        )
        prev = step


def completed_flow(now, hours):
    return [
        (Complaint.Status.SUBMITTED, "Complaint lodged", now - timedelta(hours=hours)),
        (Complaint.Status.ASSIGNED_TO_OFFICER, "Auto-mapped to officer", now - timedelta(hours=hours)),
        (Complaint.Status.ASSIGNED_TO_VENDOR, "Assigned vendor", now - timedelta(hours=hours - 4)),
        (Complaint.Status.VENDOR_ACKNOWLEDGED, "Vendor acknowledged", now - timedelta(hours=hours - 6)),
        (Complaint.Status.ESTIMATION_PENDING, "Estimation submitted", now - timedelta(hours=hours - 8)),
        (Complaint.Status.ESTIMATION_APPROVED, "Estimation approved", now - timedelta(hours=hours - 10)),
        (Complaint.Status.WORK_IN_PROGRESS, "Work started", now - timedelta(hours=hours - 14)),
        (Complaint.Status.WORK_COMPLETION, "Work completed — awaiting certificate / confirmation", now - timedelta(hours=2)),
    ]


class Command(BaseCommand):
    help = "Add demo tickets waiting for vendor to fill the Job Completion Certificate, and tickets waiting for customer signature."

    def handle(self, *args, **options):
        pump = ConsumerPump.objects.order_by("id").first()
        vendor = Vendor.objects.order_by("id").first()
        if not pump or not vendor:
            self.stderr.write("Need at least one pump and one vendor first.")
            return

        customers = list(User.objects.filter(role=User.Role.CP_USER).order_by("id"))
        if not customers:
            self.stderr.write("Need a customer user.")
            return
        vendor_user = vendor.user
        officer = pump.sales_officer
        now = timezone.now()

        specs = [
            {
                "id": "CMP-2026-030",
                "fill": False,
                "hours": 22,
                "cat": Complaint.Category.ELECTRICAL,
                "problem": "Canopy/Pole Light Issue (Illumination / wiring)",
                "desc": "Island 1 canopy lights failed after rain. Vendor replaced fittings and restored the circuit.",
                "remarks": "Replaced 3 LED canopy fittings and tightened junction box wiring. Lights tested OK.",
                "amount": "9200.00",
                "address": "Shop No. 12, Alambagh Industrial Area, Lucknow",
            },
            {
                "id": "CMP-2026-031",
                "fill": False,
                "hours": 30,
                "cat": Complaint.Category.DU,
                "problem": "DU related",
                "desc": "DU #2 meter mismatch of 0.3L. Vendor calibrated the pulser and resealed the meter.",
                "remarks": "Calibrated pulser, resealed meter, and verified 3 test fills. Variance within tolerance.",
                "amount": "14500.00",
                "address": "Shop No. 12, Alambagh Industrial Area, Lucknow",
                "du": ("Gilbarco", "SK700-2", "GB-88421"),
            },
            {
                "id": "CMP-2026-032",
                "fill": False,
                "hours": 40,
                "cat": Complaint.Category.CIVIL,
                "problem": "Kerb wall repair/Painting",
                "desc": "Kerb wall at island 2 chipped. Civil repair and two coats of paint completed.",
                "remarks": "Patched kerb, primer plus two coats. Site cleaned and handed over.",
                "amount": "18500.00",
                "address": "Shop No. 12, Alambagh Industrial Area, Lucknow",
            },
            {
                "id": "CMP-2026-033",
                "fill": True,
                "hours": 26,
                "cat": Complaint.Category.ELECTRICAL,
                "problem": "Servo/CVT/Battery Issue (Voltage fluctuation / backup)",
                "desc": "CVT output dropping below 200V; DU #1 tripping. Regulator replaced and voltage set to 230V.",
                "remarks": "Replaced 5KVA regulator module, calibrated to 230V, 30-minute load test passed.",
                "amount": "24800.00",
                "address": "12/4, Transport Nagar, Lucknow 226012",
            },
            {
                "id": "CMP-2026-034",
                "fill": True,
                "hours": 34,
                "cat": Complaint.Category.TANK,
                "problem": "Tank Leakage (Seepage / contamination risk)",
                "desc": "Fuel odor at Tank 1 manhole. Nitrile seals replaced and tightness test passed.",
                "remarks": "Replaced manhole nitrile seals, tightness test held 30 minutes. No seepage.",
                "amount": "31200.00",
                "address": "12/4, Transport Nagar, Lucknow 226012",
            },
            {
                "id": "CMP-2026-035",
                "fill": True,
                "hours": 18,
                "cat": Complaint.Category.OTHER,
                "problem": "Any other issues (Pneumatic line, air compressor, CCTV, general)",
                "desc": "Island 2 CCTV blank. NVR ports cleaned, cameras re-terminated, recording restored.",
                "remarks": "Re-terminated two cameras, replaced one BNC, NVR recording confirmed for 2 hours.",
                "amount": "6400.00",
                "address": "12/4, Transport Nagar, Lucknow 226012",
            },
        ]

        created = 0
        skipped = 0
        for i, spec in enumerate(specs):
            if Complaint.objects.filter(complaint_id=spec["id"]).exists():
                skipped += 1
                continue
            customer = customers[i % len(customers)]
            du = spec.get("du") or ("", "", "")
            ticket = Complaint.objects.create(
                complaint_id=spec["id"],
                pump=pump,
                submitted_by=customer,
                sales_officer=officer,
                assigned_vendor=vendor,
                category=spec["cat"],
                specific_problem=spec["problem"],
                description=spec["desc"],
                du_make=du[0],
                du_model=du[1],
                du_serial=du[2],
                priority=Complaint.Priority.MEDIUM if spec["cat"] == Complaint.Category.CIVIL else Complaint.Priority.HIGH,
                status=Complaint.Status.WORK_COMPLETION,
                officer_remarks="Attend and close with Job Completion Certificate.",
                vendor_remarks=spec["remarks"],
                estimation_remarks=spec["remarks"],
                estimation_amount=Decimal(spec["amount"]),
                estimation_reviewed_by=officer,
                estimation_reviewed_at=now - timedelta(hours=spec["hours"] - 10),
                po_number=f"PO/LKO/2026/{spec['id'][-3:]}",
                sla_hours=SLA_HOURS.get(spec["cat"], 48),
                created_at=now - timedelta(hours=spec["hours"]),
            )
            add_history(ticket, completed_flow(now, spec["hours"]), officer)
            attach_proof(ticket, customer, ComplaintMedia.Kind.USER_PHOTO, "User photo — site issue", (0, 48, 135))
            attach_proof(ticket, vendor_user, ComplaintMedia.Kind.BEFORE_PROOF, "Before proof", (212, 85, 18))
            attach_proof(ticket, vendor_user, ComplaintMedia.Kind.AFTER_PROOF, "After proof — work done", (3, 48, 135))
            if spec["fill"]:
                JobCompletionCertificate.objects.create(
                    complaint=ticket,
                    stage=JobCompletionCertificate.Stage.VENDOR_DRAFT,
                    certificate_date=timezone.localdate(),
                    vendor_name=vendor.name,
                    vendor_address=spec["address"],
                    nature_of_job=spec["problem"],
                    customer_name=pump.name,
                    job_completion_date=timezone.localdate(),
                    work_satisfactory=True,
                    prepared_by=vendor_user,
                    prepared_at=now - timedelta(hours=1),
                )
                StatusHistory.objects.create(
                    complaint=ticket,
                    from_status=Complaint.Status.WORK_COMPLETION,
                    to_status=Complaint.Status.WORK_COMPLETION,
                    actor=vendor_user,
                    note="Vendor filled Job Completion Certificate",
                    created_at=now - timedelta(hours=1),
                )
            created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Certificate demo tickets: created {created}, skipped {skipped}. "
                "030–032 wait for vendor to fill the form; 033–035 wait for customer signature."
            )
        )
