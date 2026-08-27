from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth.hashers import make_password
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont

from maintenance.constants import SLA_HOURS
from maintenance.notifications import (
    notify_escalation,
    notify_new_complaint,
    notify_registration,
    notify_site_issue,
    notify_transition,
)
from maintenance.models import (
    Complaint,
    ComplaintFeedback,
    ComplaintMedia,
    ConsumerPump,
    DivisionalOffice,
    PumpFacility,
    RegistrationRequest,
    SalesArea,
    StatusHistory,
    User,
    Vendor,
    Notification,
    VendorSiteIssue,
)

PASSWORD = "Pahle@123"


def proof_file(label, bg):
    img = Image.new("RGB", (800, 500), bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle((16, 16, 784, 484), outline=(255, 255, 255), width=6)
    font = ImageFont.load_default()
    draw.text((48, 220), label, fill=(255, 255, 255), font=font)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    buf.seek(0)
    slug = label.lower().replace(" ", "_")
    return ContentFile(buf.getvalue(), name=f"{slug}.jpg")


def attach_proof(complaint, uploaded_by, kind, label, color):
    rec = ComplaintMedia(complaint=complaint, kind=kind, uploaded_by=uploaded_by)
    rec.file.save(f"{complaint.complaint_id}_{kind.lower()}.jpg", proof_file(label, color), save=True)


def user(username, first, last, role, **kwargs):
    obj, created = User.objects.get_or_create(
        username=username,
        defaults={
            "first_name": first,
            "last_name": last,
            "email": f"{username.replace('.', '_')}@pahle.iocl.local",
            "role": role,
            **kwargs,
        },
    )
    obj.set_password(PASSWORD)
    for k, v in kwargs.items():
        setattr(obj, k, v)
    obj.role = role
    obj.first_name = first
    obj.last_name = last
    obj.save()
    return obj


class Command(BaseCommand):
    help = "Load demo PAHLE-APP data matching the client mockups"

    def handle(self, *args, **options):
        Complaint.objects.all().delete()
        Notification.objects.all().delete()
        RegistrationRequest.objects.all().delete()
        Vendor.objects.all().delete()
        PumpFacility.objects.all().delete()
        ConsumerPump.objects.all().delete()
        SalesArea.objects.all().delete()
        DivisionalOffice.objects.all().delete()
        User.objects.exclude(is_superuser=True).delete()

        do_lko = DivisionalOffice.objects.create(code="DO-LKO", name="DO Lucknow")

        sa1 = SalesArea.objects.create(
            code="LKO-I", name="Lucknow I IBSA", zone="Lucknow", divisional_office=do_lko
        )
        sa2 = SalesArea.objects.create(
            code="LKO-III", name="Lucknow III IBSA", zone="Lucknow", divisional_office=do_lko
        )

        himanshu = user(
            "himanshu.saxena",
            "Himanshu",
            "Saxena",
            User.Role.ADMIN,
            sales_area=sa1,
            divisional_office=do_lko,
            is_staff=True,
        )
        priya = user(
            "priya.verma",
            "Priya",
            "Verma",
            User.Role.SALES_OFFICER,
            sales_area=sa2,
            divisional_office=do_lko,
        )
        anil = user(
            "anil.gupta",
            "Anil",
            "Gupta",
            User.Role.SALES_OFFICER,
            sales_area=sa1,
            divisional_office=do_lko,
        )
        raman = priya
        amit = user(
            "amit.sharma",
            "Amit",
            "Sharma",
            User.Role.ENGINEERING_OFFICER,
            sales_area=sa1,
            divisional_office=do_lko,
        )
        kulkarni = user(
            "s.kulkarni",
            "S.",
            "Kulkarni",
            User.Role.ENGINEERING_OFFICER,
            sales_area=sa2,
            divisional_office=do_lko,
        )
        user("do.lucknow", "Divisional", "Lucknow", User.Role.DO_OFFICER, divisional_office=do_lko)

        customers = [
            ("CP-LKO-01", "Supply Depot Lucknow", "Lucknow Cantonement Lucknow 226005", "Lucknow", sa1, himanshu, amit),
            ("CP-LKO-02", "TATA Motors Ltd", "Deva Road, Chinhat Industrial Area Chinhat, Lucknow, Uttar Pradesh 226019", "Lucknow", sa2, priya, kulkarni),
            ("CP-LKO-03", "Aerolloy Technologies Limited", "F-1, Defence Industrial Corridor, Haruni Lucknow 226401", "Lucknow", sa2, priya, kulkarni),
            ("CP-LKO-04", "EKANA SPORTZ CITY PVT. LTD.", "Saheed Path, Vill: Ardunamau, Gomti Nagar Extension, Sarojininagar, Lucknow 226010", "Lucknow", sa2, priya, kulkarni),
            ("CP-LKO-05", "UPSRTC Qaiserbagh Lucknow", "Qaiserbagh Lucknow 261001", "Lucknow", sa1, himanshu, amit),
        ]
        pumps = []
        for code, name, address, city, area, so, eo in customers:
            pumps.append(
                ConsumerPump.objects.create(
                    pump_code=code,
                    name=name,
                    address=address,
                    city=city,
                    sales_area=area,
                    sales_officer=so,
                    engineering_officer=eo,
                )
            )
        p1, p2, p3, p4, p5 = pumps

        for pump, labels in [
            (p1, ["2 Dispensing Units", "Canopy Light", "CVT Backup", "Kerb Wall"]),
            (p2, ["3 Dispensing Units", "Underground Tank 20KL", "GenSet 25kVA"]),
            (p3, ["1 Dispensing Unit", "Solar Canopy", "SOP Signage"]),
            (p4, ["2 Dispensing Units", "Dual Underground Tanks"]),
            (p5, ["Fleet Filling Point", "Canopy Light", "Office Block"]),
        ]:
            for label in labels:
                PumpFacility.objects.create(pump=pump, label=label)

        metro_user = user("supplydepot.cp", "Maj Sudhir", "Yadav", User.Role.CP_USER, consumer_pump=p1, sales_area=sa1)
        national_user = user("tata.cp", "Nitansh", "Kamboj", User.Role.CP_USER, consumer_pump=p2, sales_area=sa2)
        tech_user = user("aerolloy.cp", "Manish", "Pandey", User.Role.CP_USER, consumer_pump=p3, sales_area=sa2)
        south_user = user("ekana.cp", "Pradeep", "Tiwari", User.Role.CP_USER, consumer_pump=p4, sales_area=sa2)
        user("upsrtc.cp", "Mohd", "Arif", User.Role.CP_USER, consumer_pump=p5, sales_area=sa1)

        lucknow_vendors = [
            ("deepak.vendor", "Deepak", "Kumar", "DEEPAK ELECTRIC AND WELDING WORKS", Vendor.Specialization.ELECTRICAL, "9000011001", 4.8),
            ("electroflow.vendor", "Mushahid", "Khan", "ELECTRO FLOW", Vendor.Specialization.TANK, "9000011002", 4.7),
            ("luv.vendor", "Chitrakala", "Mallah", "LUV CONSTRUCTION", Vendor.Specialization.CIVIL, "9000011003", 4.6),
            ("atharv.vendor", "Pankaj", "Tripathi", "ATHARV ENTERPRISES", Vendor.Specialization.OTHER, "9000011004", 4.5),
            ("kanpurelec.vendor", "Mohit", "Bajpai", "KANPUR ELECTRICAL ENTERPRISES", Vendor.Specialization.ELECTRICAL, "9000011005", 4.6),
            ("perfect.vendor", "Paldhar", "Mallah", "PERFECT CONSTRUCTION", Vendor.Specialization.CIVIL, "9000011006", 4.4),
            ("rahat.vendor", "Amir", "Khan", "RAHAT ELECTRIC WORKS", Vendor.Specialization.ELECTRICAL, "9000011007", 4.5),
            ("spark.vendor", "Shabeena", "Parveen", "SPARK TECHNOCRATS", Vendor.Specialization.ELECTRICAL, "9000011008", 4.7),
            ("structural.vendor", "Kamal", "Jaiswal", "STRUCTURAL ENGINEERS", Vendor.Specialization.CIVIL, "9000011009", 4.5),
            ("verma.vendor", "Banvari", "Lal", "VERMA ELECTRONICS", Vendor.Specialization.OTHER, "9000011010", 4.3),
        ]
        created_vendors = []
        for username, first, last, firm, spec, phone, rating in lucknow_vendors:
            login = user(username, first, last, User.Role.VENDOR)
            slug = username.split(".")[0]
            created_vendors.append(
                Vendor.objects.create(
                    name=firm,
                    specialization=spec,
                    phone=f"+91 {phone}",
                    email=f"{slug}@pahle.iocl.local",
                    user=login,
                    rating=rating,
                )
            )
        apex_user = User.objects.get(username="deepak.vendor")
        hydro_user = User.objects.get(username="electroflow.vendor")
        build_user = User.objects.get(username="luv.vendor")
        apex = created_vendors[0]
        hydro = created_vendors[1]
        build = created_vendors[2]

        now = timezone.now()

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

        c1 = Complaint.objects.create(
            complaint_id="CMP-2026-001",
            pump=p1,
            submitted_by=metro_user,
            sales_officer=himanshu,
            assigned_vendor=apex,
            category=Complaint.Category.ELECTRICAL,
            specific_problem="Servo/CVT/Battery Issue (Voltage fluctuation / backup)",
            description="Dispensing Unit #2 tripping repeatedly due to unstable CVT output voltage.",
            priority=Complaint.Priority.HIGH,
            status=Complaint.Status.WORK_COMPLETION,
            officer_remarks="Inspect CVT transformer coils immediately as fuel sales affected.",
            vendor_remarks="Replaced faulty 5KVA voltage regulator module and calibrated voltage to 230V.",
            sla_hours=SLA_HOURS["ELECTRICAL"],
            created_at=now - timedelta(hours=18),
        )
        add_history(
            c1,
            [
                (Complaint.Status.SUBMITTED, "Complaint lodged", now - timedelta(hours=18)),
                (Complaint.Status.ASSIGNED_TO_OFFICER, "Auto-mapped to LKO-I", now - timedelta(hours=18)),
                (Complaint.Status.ASSIGNED_TO_VENDOR, "Assigned DEEPAK ELECTRIC AND WELDING WORKS", now - timedelta(hours=16)),
                (Complaint.Status.VENDOR_ACKNOWLEDGED, "Vendor acknowledged", now - timedelta(hours=15)),
                (Complaint.Status.WORK_IN_PROGRESS, "Work started", now - timedelta(hours=10)),
                (Complaint.Status.WORK_COMPLETION, "Work completed", now - timedelta(hours=2)),
            ],
            himanshu,
        )
        attach_proof(c1, metro_user, ComplaintMedia.Kind.USER_PHOTO, "User photo — DU #2 trip", (0, 48, 135))
        attach_proof(c1, apex_user, ComplaintMedia.Kind.BEFORE_PROOF, "Before — faulty CVT regulator", (212, 85, 18))
        attach_proof(c1, apex_user, ComplaintMedia.Kind.AFTER_PROOF, "After — replaced 5KVA module", (3, 48, 135))
        notify_transition(c1, apex_user, Complaint.Status.WORK_IN_PROGRESS, Complaint.Status.WORK_COMPLETION)

        c2 = Complaint.objects.create(
            complaint_id="CMP-2026-002",
            pump=p2,
            submitted_by=national_user,
            sales_officer=priya,
            assigned_vendor=hydro,
            category=Complaint.Category.TANK,
            specific_problem="Tank Leakage (Seepage / contamination risk)",
            description="Minor fuel odor reported near Tank 1 manhole chamber.",
            priority=Complaint.Priority.HIGH,
            status=Complaint.Status.WORK_IN_PROGRESS,
            officer_remarks="Conduct tightness testing & gasket check.",
            vendor_remarks="Manhole gasket seal opened for pressure check; replacing nitrile seals.",
            sla_hours=SLA_HOURS["TANK"],
            created_at=now - timedelta(hours=36),
        )
        add_history(
            c2,
            [
                (Complaint.Status.SUBMITTED, "Complaint lodged", now - timedelta(hours=36)),
                (Complaint.Status.ASSIGNED_TO_OFFICER, "Auto-mapped to LKO-III", now - timedelta(hours=36)),
                (Complaint.Status.ASSIGNED_TO_VENDOR, "Assigned ELECTRO FLOW", now - timedelta(hours=30)),
                (Complaint.Status.VENDOR_ACKNOWLEDGED, "Vendor acknowledged", now - timedelta(hours=28)),
                (Complaint.Status.WORK_IN_PROGRESS, "Work started", now - timedelta(hours=20)),
            ],
            priya,
        )
        c2.escalated_at = now - timedelta(hours=4)
        c2.escalation_note = (
            "Vendor has been on site but fuel odor is still strong. Please treat this as urgent."
        )
        c2.escalation_count = 1
        c2.save(update_fields=["escalated_at", "escalation_note", "escalation_count"])
        StatusHistory.objects.create(
            complaint=c2,
            from_status=Complaint.Status.WORK_IN_PROGRESS,
            to_status=Complaint.Status.WORK_IN_PROGRESS,
            actor=national_user,
            note="User escalated (#1): Vendor has been on site but fuel odor is still strong.",
            created_at=now - timedelta(hours=4),
        )
        notify_escalation(c2, national_user, c2.escalation_note)
        issue = VendorSiteIssue.objects.create(
            complaint=c2,
            reported_by=hydro_user,
            kind=VendorSiteIssue.Kind.PARTS,
            description="Required nitrile manhole seals are not in local stock. Need approval to source from Lucknow warehouse.",
        )
        issue.created_at = now - timedelta(hours=6)
        issue.save(update_fields=["created_at"])
        StatusHistory.objects.create(
            complaint=c2,
            from_status=Complaint.Status.WORK_IN_PROGRESS,
            to_status=Complaint.Status.WORK_IN_PROGRESS,
            actor=hydro_user,
            note="Vendor site issue (Parts / material not available): Required nitrile manhole seals are not in local stock.",
            created_at=now - timedelta(hours=6),
        )
        notify_site_issue(issue)

        c3 = Complaint.objects.create(
            complaint_id="CMP-2026-003",
            pump=p3,
            submitted_by=tech_user,
            sales_officer=priya,
            assigned_vendor=build,
            category=Complaint.Category.CIVIL,
            specific_problem="Kerb wall repair/Painting",
            description="Kerb wall chipped near island 1; painting and civil repair required.",
            priority=Complaint.Priority.MEDIUM,
            status=Complaint.Status.ESTIMATION_PENDING,
            officer_remarks="Schedule civil crew this week.",
            estimation_remarks="Kerb wall civil repair, primer, and two coats of paint including labour and material.",
            estimation_amount=Decimal("18500.00"),
            sla_hours=SLA_HOURS["CIVIL"],
            created_at=now - timedelta(hours=10),
        )
        add_history(
            c3,
            [
                (Complaint.Status.SUBMITTED, "Complaint lodged", now - timedelta(hours=10)),
                (Complaint.Status.ASSIGNED_TO_OFFICER, "Auto-mapped to LKO-III", now - timedelta(hours=10)),
                (Complaint.Status.ASSIGNED_TO_VENDOR, "Assigned LUV CONSTRUCTION", now - timedelta(hours=6)),
                (Complaint.Status.VENDOR_ACKNOWLEDGED, "Vendor acknowledged", now - timedelta(hours=5)),
                (Complaint.Status.ESTIMATION_PENDING, "Estimation submitted: ₹18500.00", now - timedelta(hours=4)),
            ],
            priya,
        )
        notify_transition(c3, build_user, Complaint.Status.VENDOR_ACKNOWLEDGED, Complaint.Status.ESTIMATION_PENDING)

        c4 = Complaint.objects.create(
            complaint_id="CMP-2026-004",
            pump=p4,
            submitted_by=south_user,
            sales_officer=raman,
            category=Complaint.Category.OTHER,
            specific_problem="Any other issues (Pneumatic line, air compressor, CCTV, general)",
            description="Air compressor trip and CCTV blank on island 2.",
            priority=Complaint.Priority.MEDIUM,
            status=Complaint.Status.SUBMITTED,
            sla_hours=SLA_HOURS["OTHER"],
            created_at=now - timedelta(hours=8),
        )
        add_history(
            c4,
            [(Complaint.Status.SUBMITTED, "Complaint lodged", now - timedelta(hours=8))],
            south_user,
        )

        pending_assign = [
            {
                "id": "CMP-2026-020",
                "pump": p1,
                "user": metro_user,
                "officer": himanshu,
                "cat": Complaint.Category.ELECTRICAL,
                "problem": "DU Issue (Dispensing Unit failure / meter error)",
                "desc": "Dispensing Unit #1 showing meter mismatch of 0.4L per fill. Sales halted on this nozzle.",
                "priority": Complaint.Priority.HIGH,
                "hours": 6,
            },
            {
                "id": "CMP-2026-021",
                "pump": p2,
                "user": national_user,
                "officer": priya,
                "cat": Complaint.Category.ELECTRICAL,
                "problem": "Generator Issue (Starter failure / fuel leakage)",
                "desc": "25kVA genset failed to crank during evening power cut. Starter solenoid suspected.",
                "priority": Complaint.Priority.HIGH,
                "hours": 14,
            },
            {
                "id": "CMP-2026-022",
                "pump": p3,
                "user": tech_user,
                "officer": priya,
                "cat": Complaint.Category.ELECTRICAL,
                "problem": "Canopy/Pole Light Issue (Illumination / wiring)",
                "desc": "Three canopy lights on island 2 flickering after rain. Possible loose wiring.",
                "priority": Complaint.Priority.MEDIUM,
                "hours": 9,
            },
            {
                "id": "CMP-2026-023",
                "pump": p4,
                "user": south_user,
                "officer": raman,
                "cat": Complaint.Category.TANK,
                "problem": "Tank Leakage (Seepage / contamination risk)",
                "desc": "Water-white sheen reported in Tank 2 observation well. Needs tightness test.",
                "priority": Complaint.Priority.HIGH,
                "hours": 22,
            },
            {
                "id": "CMP-2026-024",
                "pump": p1,
                "user": metro_user,
                "officer": himanshu,
                "cat": Complaint.Category.CIVIL,
                "problem": "Shed repair/painting",
                "desc": "Office shed roof sheets lifted in last storm; rain leaking onto documents.",
                "priority": Complaint.Priority.MEDIUM,
                "hours": 30,
            },
            {
                "id": "CMP-2026-025",
                "pump": p2,
                "user": national_user,
                "officer": priya,
                "cat": Complaint.Category.CIVIL,
                "problem": "SOP/Signage board repair/replacement",
                "desc": "Safety SOP board near Tank farm rusted and unreadable. Replacement required.",
                "priority": Complaint.Priority.LOW,
                "hours": 4,
            },
            {
                "id": "CMP-2026-026",
                "pump": p3,
                "user": tech_user,
                "officer": priya,
                "cat": Complaint.Category.ELECTRICAL,
                "problem": "Servo/CVT/Battery Issue (Voltage fluctuation / backup)",
                "desc": "CVT output dropping below 200V during peak hours; DU #1 trips twice daily.",
                "priority": Complaint.Priority.HIGH,
                "hours": 11,
            },
            {
                "id": "CMP-2026-027",
                "pump": p1,
                "user": metro_user,
                "officer": himanshu,
                "cat": Complaint.Category.OTHER,
                "problem": "Any other issues (Pneumatic line, air compressor, CCTV, general)",
                "desc": "CCTV NVR not recording since last night. Island cameras show no signal.",
                "priority": Complaint.Priority.MEDIUM,
                "hours": 3,
            },
        ]
        for item in pending_assign:
            ticket = Complaint.objects.create(
                complaint_id=item["id"],
                pump=item["pump"],
                submitted_by=item["user"],
                sales_officer=item["officer"],
                category=item["cat"],
                specific_problem=item["problem"],
                description=item["desc"],
                priority=item["priority"],
                status=Complaint.Status.ASSIGNED_TO_OFFICER,
                sla_hours=SLA_HOURS[item["cat"]],
                created_at=now - timedelta(hours=item["hours"]),
            )
            add_history(
                ticket,
                [
                    (Complaint.Status.SUBMITTED, "Complaint lodged", now - timedelta(hours=item["hours"])),
                    (
                        Complaint.Status.ASSIGNED_TO_OFFICER,
                        f"Auto-mapped to {item['pump'].sales_area.code}",
                        now - timedelta(hours=item["hours"]),
                    ),
                ],
                item["user"],
            )
            notify_new_complaint(ticket)

        c0 = Complaint.objects.create(
            complaint_id="CMP-2026-000",
            pump=p1,
            submitted_by=metro_user,
            sales_officer=himanshu,
            assigned_vendor=apex,
            category=Complaint.Category.ELECTRICAL,
            specific_problem="Canopy/Pole Light Issue (Illumination / wiring)",
            description="Canopy lights out on island 1 after storm.",
            priority=Complaint.Priority.LOW,
            status=Complaint.Status.CLOSED,
            officer_remarks="Replace fittings and check wiring.",
            vendor_remarks="Replaced 4 LED canopy fittings; circuit restored.",
            sla_hours=SLA_HOURS["ELECTRICAL"],
            created_at=now - timedelta(days=12),
            closed_at=now - timedelta(days=11, hours=12),
        )
        add_history(
            c0,
            [
                (Complaint.Status.SUBMITTED, "Complaint lodged", now - timedelta(days=12)),
                (Complaint.Status.ASSIGNED_TO_OFFICER, "Auto-mapped", now - timedelta(days=12)),
                (Complaint.Status.ASSIGNED_TO_VENDOR, "Assigned DEEPAK ELECTRIC AND WELDING WORKS", now - timedelta(days=12)),
                (Complaint.Status.VENDOR_ACKNOWLEDGED, "Ack", now - timedelta(days=12)),
                (Complaint.Status.WORK_IN_PROGRESS, "Work", now - timedelta(days=12)),
                (Complaint.Status.WORK_COMPLETION, "Done", now - timedelta(days=11, hours=14)),
                (Complaint.Status.USER_CONFIRMATION, "User confirmed", now - timedelta(days=11, hours=12)),
                (Complaint.Status.CLOSED, "Closed", now - timedelta(days=11, hours=12)),
            ],
            himanshu,
        )
        ComplaintFeedback.objects.create(
            complaint=c0,
            resolved=True,
            rating=5,
            remarks="Great service, completed well within time.",
            submitted_by=metro_user,
        )
        attach_proof(c0, metro_user, ComplaintMedia.Kind.USER_PHOTO, "User photo — canopy dark", (0, 48, 135))
        attach_proof(c0, apex_user, ComplaintMedia.Kind.BEFORE_PROOF, "Before — failed fittings", (243, 108, 33))
        attach_proof(c0, apex_user, ComplaintMedia.Kind.AFTER_PROOF, "After — LED fittings restored", (0, 48, 135))

        # Extra closed jobs so vendor cards show completed counts close to the mockup
        extra = [
            (apex, p1, metro_user, himanshu, Complaint.Category.ELECTRICAL, "DU Issue (Dispensing Unit failure / meter error)", 11),
            (apex, p1, metro_user, himanshu, Complaint.Category.ELECTRICAL, "Generator Issue (Starter failure / fuel leakage)", 10),
            (hydro, p2, national_user, priya, Complaint.Category.TANK, "Tank Leakage (Seepage / contamination risk)", 14),
            (build, p3, tech_user, priya, Complaint.Category.CIVIL, "Shed repair/painting", 7),
            (build, p3, tech_user, priya, Complaint.Category.CIVIL, "SOP/Signage board repair/replacement", 6),
        ]
        for idx, (vendor, pump, submitter, officer, cat, problem, days) in enumerate(extra, start=10):
            closed = Complaint.objects.create(
                complaint_id=f"CMP-2026-{idx:03d}",
                pump=pump,
                submitted_by=submitter,
                sales_officer=officer,
                assigned_vendor=vendor,
                category=cat,
                specific_problem=problem,
                description="Historical resolved ticket (seed).",
                priority=Complaint.Priority.MEDIUM,
                status=Complaint.Status.CLOSED,
                vendor_remarks="Resolved.",
                sla_hours=SLA_HOURS[cat],
                created_at=now - timedelta(days=days),
                closed_at=now - timedelta(days=days - 1),
            )
            ComplaintFeedback.objects.create(
                complaint=closed, resolved=True, rating=5, remarks="OK", submitted_by=submitter
            )

        spark = RegistrationRequest.objects.create(
            kind=RegistrationRequest.Kind.VENDOR,
            username="crown.vendor",
            password_hash=make_password(PASSWORD),
            first_name="Pending",
            last_name="Vendor",
            email="crown_vendor@pahle.iocl.local",
            phone="+91 9000011099",
            organization_name="CROWN CONSTRUCTION AND SUPPLIERS",
            specialization=Vendor.Specialization.CIVIL,
        )
        cantt = RegistrationRequest.objects.create(
            kind=RegistrationRequest.Kind.CP_USER,
            username="pending.cp",
            password_hash=make_password(PASSWORD),
            first_name="Pending",
            last_name="User",
            email="pending_cp@pahle.iocl.local",
            phone="+91 9000011098",
            consumer_pump=p1,
        )
        notify_registration(spark)
        notify_registration(cantt)

        from maintenance.ibsa import apply_ibsa_officers

        apply_ibsa_officers()

        self.stdout.write(self.style.SUCCESS("Seeded PAHLE-APP demo data. Password for all users: Pahle@123"))
