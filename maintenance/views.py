import csv
from decimal import Decimal, InvalidOperation
from io import StringIO

from django.contrib.auth.hashers import make_password
from django.db.models import Avg, Count, Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from .constants import PROBLEM_MASTER, SLA_HOURS, STATUS_FLOW
from .geo import parse_coordinates
from .models import (
    Complaint,
    ComplaintFeedback,
    ComplaintMedia,
    ConsumerPump,
    DivisionalOffice,
    Notification,
    RegistrationRequest,
    SalesArea,
    StatusHistory,
    User,
    Vendor,
    VendorSiteIssue,
)
from .notifications import (
    notify,
    notify_escalation,
    notify_new_complaint,
    notify_registration,
    notify_registration_decision,
    notify_site_issue,
    notify_transition,
)
from .permissions import OFFICER_ROLES, IsAdmin, IsOfficer
from .serializers import (
    ComplaintSerializer,
    ConsumerPumpSerializer,
    DivisionalOfficeSerializer,
    LoginSerializer,
    RegistrationCreateSerializer,
    RegistrationRequestSerializer,
    SalesAreaSerializer,
    UserProfileUpdateSerializer,
    UserPublicSerializer,
    VendorSerializer,
    NotificationSerializer,
)


def scoped_complaints(user):
    qs = Complaint.objects.select_related(
        "pump",
        "pump__sales_area",
        "pump__sales_area__divisional_office",
        "pump__engineering_officer",
        "sales_officer",
        "assigned_vendor",
        "submitted_by",
        "feedback",
    ).prefetch_related("media", "history", "pump__facilities", "site_issues", "site_issues__reported_by")
    if user.role == User.Role.ADMIN:
        return qs
    if user.role == User.Role.DO_OFFICER and user.divisional_office_id:
        return qs.filter(pump__sales_area__divisional_office_id=user.divisional_office_id)
    if user.role in (User.Role.SALES_OFFICER, User.Role.ENGINEERING_OFFICER):
        return qs.filter(
            Q(sales_officer=user)
            | Q(pump__sales_officer=user)
            | Q(pump__engineering_officer=user)
            | Q(pump__sales_area_id=user.sales_area_id)
        )
    if user.role == User.Role.CP_USER:
        return qs.filter(Q(submitted_by=user) | Q(pump=user.consumer_pump))
    if user.role == User.Role.VENDOR:
        profile = getattr(user, "vendor_profile", None)
        return qs.filter(assigned_vendor=profile) if profile else qs.none()
    return qs.none()


def scoped_pumps(user):
    qs = ConsumerPump.objects.select_related(
        "sales_area", "sales_area__divisional_office", "sales_officer", "engineering_officer"
    ).prefetch_related("facilities")
    if user.role == User.Role.ADMIN:
        return qs
    if user.role == User.Role.DO_OFFICER and user.divisional_office_id:
        return qs.filter(sales_area__divisional_office_id=user.divisional_office_id)
    if user.role in (User.Role.SALES_OFFICER, User.Role.ENGINEERING_OFFICER):
        return qs.filter(
            Q(sales_officer=user) | Q(engineering_officer=user) | Q(sales_area_id=user.sales_area_id)
        )
    if user.role == User.Role.CP_USER and user.consumer_pump_id:
        return qs.filter(id=user.consumer_pump_id)
    return qs.none()


def transition(complaint, to_status, actor, note="", notify=True):
    from_status = complaint.status
    history = StatusHistory.objects.create(
        complaint=complaint,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        note=note,
    )
    complaint.status = to_status
    if to_status == Complaint.Status.CLOSED:
        complaint.closed_at = timezone.now()
    complaint.save()
    if notify:
        notify_transition(complaint, actor, from_status, to_status)
    return history


@api_view(["POST"])
def assistant_chat_view(request):
    from .ai_agent import run_assistant

    messages = request.data.get("messages")
    if not isinstance(messages, list):
        return Response({"detail": "Send messages as a list."}, status=400)
    try:
        result = run_assistant(request.user, messages, request)
    except RuntimeError as exc:
        return Response({"detail": str(exc)}, status=503)
    return Response(result)


@api_view(["GET"])
@permission_classes([AllowAny])
def health_view(request):
    return Response({"status": "ok"})


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        user = User.objects.get(username=serializer.validated_data["username"])
    except User.DoesNotExist:
        return Response({"detail": "Invalid username or password."}, status=400)
    if not user.check_password(serializer.validated_data["password"]):
        return Response({"detail": "Invalid username or password."}, status=400)
    if not user.is_active:
        return Response({"detail": "This account is inactive."}, status=400)
    refresh = RefreshToken.for_user(user)
    return Response(
        {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": UserPublicSerializer(user, context={"request": request}).data,
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def register_options_view(request):
    pumps = ConsumerPump.objects.filter(is_active=True).order_by("name")
    return Response(
        {
            "pumps": [
                {"id": p.id, "pump_code": p.pump_code, "name": p.name, "city": p.city}
                for p in pumps
            ],
            "specializations": [
                {"value": value, "label": label} for value, label in Vendor.Specialization.choices
            ],
        }
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def register_view(request):
    serializer = RegistrationCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    username = data["username"].strip()
    if User.objects.filter(username__iexact=username).exists():
        return Response({"detail": "This username is already taken."}, status=400)
    if RegistrationRequest.objects.filter(
        username__iexact=username, status=RegistrationRequest.Status.PENDING
    ).exists():
        return Response({"detail": "A registration with this username is already pending approval."}, status=400)
    if data["kind"] == RegistrationRequest.Kind.VENDOR and not data.get("organization_name"):
        return Response({"detail": "Vendor company name is required."}, status=400)
    if data["kind"] == RegistrationRequest.Kind.CP_USER and not data.get("consumer_pump"):
        return Response({"detail": "Please select a Consumer Pump."}, status=400)
    pump = None
    if data.get("consumer_pump"):
        pump = ConsumerPump.objects.filter(pk=data["consumer_pump"]).first()
        if not pump:
            return Response({"detail": "Invalid Consumer Pump."}, status=400)
    spec = (data.get("specialization") or "").upper()
    if data["kind"] == RegistrationRequest.Kind.VENDOR and spec not in Vendor.Specialization.values:
        spec = Vendor.Specialization.OTHER
    latitude = longitude = None
    amc_type = ""
    if data["kind"] == RegistrationRequest.Kind.CP_USER:
        parsed = parse_coordinates(
            data.get("coordinates") or "",
            data.get("latitude"),
            data.get("longitude"),
        )
        if not parsed:
            return Response(
                {"detail": "Enter Google Maps coordinates as latitude, longitude (example: 26.8467, 80.9462)."},
                status=400,
            )
        latitude, longitude = parsed
        amc_type = (data.get("amc_type") or "").upper()
        if amc_type not in ConsumerPump.AmcType.values:
            return Response({"detail": "Select AMC or Non AMC."}, status=400)
    rec = RegistrationRequest.objects.create(
        kind=data["kind"],
        username=username,
        password_hash=make_password(data["password"]),
        first_name=data["first_name"].strip(),
        last_name=(data.get("last_name") or "").strip(),
        email=data["email"].strip(),
        phone=data["phone"].strip(),
        organization_name=(data.get("organization_name") or "").strip(),
        specialization=spec if data["kind"] == RegistrationRequest.Kind.VENDOR else "",
        consumer_pump=pump if data["kind"] == RegistrationRequest.Kind.CP_USER else None,
        latitude=latitude,
        longitude=longitude,
        amc_type=amc_type,
    )
    notify_registration(rec)
    return Response(RegistrationRequestSerializer(rec).data, status=201)


@api_view(["GET"])
def users_directory_view(request):
    if request.user.role not in OFFICER_ROLES:
        return Response({"detail": "Only officers can view the user directory."}, status=403)
    qs = (
        User.objects.filter(
            role__in=[
                User.Role.CP_USER,
                User.Role.VENDOR,
                User.Role.ADMIN,
                User.Role.SALES_OFFICER,
                User.Role.ENGINEERING_OFFICER,
                User.Role.DO_OFFICER,
            ],
            is_active=True,
        )
        .select_related("consumer_pump", "sales_area", "sales_area__divisional_office", "divisional_office", "vendor_profile")
        .prefetch_related("sales_area__districts")
        .order_by("role", "first_name", "username")
    )
    return Response(UserPublicSerializer(qs, many=True, context={"request": request}).data)


class RegistrationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RegistrationRequestSerializer
    permission_classes = [IsAuthenticated, IsAdmin]
    queryset = RegistrationRequest.objects.select_related("consumer_pump", "reviewed_by")

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        rec = self.get_object()
        if rec.status != RegistrationRequest.Status.PENDING:
            return Response({"detail": "This request has already been reviewed."}, status=400)
        if User.objects.filter(username__iexact=rec.username).exists():
            return Response({"detail": "Username is already in use."}, status=400)
        user = User(
            username=rec.username,
            first_name=rec.first_name,
            last_name=rec.last_name,
            email=rec.email,
            phone=rec.phone,
            role=User.Role.VENDOR if rec.kind == RegistrationRequest.Kind.VENDOR else User.Role.CP_USER,
        )
        user.password = rec.password_hash
        if rec.kind == RegistrationRequest.Kind.CP_USER and rec.consumer_pump:
            user.consumer_pump = rec.consumer_pump
            user.sales_area = rec.consumer_pump.sales_area
        user.save()
        if rec.kind == RegistrationRequest.Kind.CP_USER and rec.consumer_pump:
            pump = rec.consumer_pump
            changed = []
            if rec.latitude is not None and rec.longitude is not None:
                pump.latitude = rec.latitude
                pump.longitude = rec.longitude
                changed += ["latitude", "longitude"]
            if rec.amc_type:
                pump.amc_type = rec.amc_type
                changed.append("amc_type")
            if changed:
                pump.save(update_fields=changed)
        if rec.kind == RegistrationRequest.Kind.VENDOR:
            Vendor.objects.create(
                name=rec.organization_name or f"{rec.first_name} {rec.last_name}".strip() or rec.username,
                specialization=rec.specialization or Vendor.Specialization.OTHER,
                phone=rec.phone,
                email=rec.email,
                user=user,
            )
        rec.status = RegistrationRequest.Status.APPROVED
        rec.created_user = user
        rec.reviewed_by = request.user
        rec.reviewed_at = timezone.now()
        rec.admin_note = request.data.get("admin_note", rec.admin_note)
        rec.save()
        notify_registration_decision(rec, user)
        return Response(RegistrationRequestSerializer(rec).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        rec = self.get_object()
        if rec.status != RegistrationRequest.Status.PENDING:
            return Response({"detail": "This request has already been reviewed."}, status=400)
        rec.status = RegistrationRequest.Status.REJECTED
        rec.reviewed_by = request.user
        rec.reviewed_at = timezone.now()
        rec.admin_note = request.data.get("admin_note", "Rejected")
        rec.save()
        return Response(RegistrationRequestSerializer(rec).data)


@api_view(["GET", "PATCH", "PUT"])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def me_view(request):
    if request.method == "GET":
        user = User.objects.select_related("sales_area", "sales_area__divisional_office", "divisional_office").prefetch_related("sales_area__districts").get(pk=request.user.pk)
        return Response(UserPublicSerializer(user, context={"request": request}).data)
    serializer = UserProfileUpdateSerializer(request.user, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    request.user.refresh_from_db()
    return Response(UserPublicSerializer(request.user, context={"request": request}).data)


@api_view(["GET"])
def meta_view(request):
    officers = (
        User.objects.filter(role__in=OFFICER_ROLES)
        .select_related("sales_area", "sales_area__divisional_office", "divisional_office")
        .prefetch_related("sales_area__districts")
        .order_by("first_name")
    )
    return Response(
        {
            "problem_master": PROBLEM_MASTER,
            "sla_hours": SLA_HOURS,
            "status_flow": STATUS_FLOW,
            "sales_areas": SalesAreaSerializer(
                SalesArea.objects.select_related("divisional_office").prefetch_related("districts"),
                many=True,
            ).data,
            "divisional_offices": DivisionalOfficeSerializer(DivisionalOffice.objects.all(), many=True).data,
            "officers": UserPublicSerializer(officers, many=True, context={"request": request}).data,
            "site_issue_kinds": [
                {"value": value, "label": label} for value, label in VendorSiteIssue.Kind.choices
            ],
        }
    )


@api_view(["GET"])
def dashboard_view(request):
    complaints = scoped_complaints(request.user)
    pumps = scoped_pumps(request.user)
    active = complaints.exclude(status=Complaint.Status.CLOSED)
    aging_gt_24 = [c for c in active if c.aging_hours > 24]
    in_progress = active.filter(
        status__in=[
            Complaint.Status.VENDOR_ACKNOWLEDGED,
            Complaint.Status.ESTIMATION_PENDING,
            Complaint.Status.ESTIMATION_APPROVED,
            Complaint.Status.WORK_IN_PROGRESS,
        ]
    )
    awaiting = active.filter(
        status__in=[Complaint.Status.WORK_COMPLETION, Complaint.Status.USER_CONFIRMATION]
    )
    closed = complaints.filter(status=Complaint.Status.CLOSED)
    avg_rating = closed.aggregate(avg=Avg("feedback__rating"))["avg"] or 0

    by_category = {
        row["category"]: row["count"]
        for row in complaints.values("category").annotate(count=Count("id"))
    }
    aging_buckets = {"<24h": 0, "24-48h": 0, ">48h": 0}
    for c in active:
        if c.aging_hours < 24:
            aging_buckets["<24h"] += 1
        elif c.aging_hours <= 48:
            aging_buckets["24-48h"] += 1
        else:
            aging_buckets[">48h"] += 1

    area_pendency = []
    for area in SalesArea.objects.select_related("divisional_office"):
        area_qs = active.filter(pump__sales_area=area)
        if not area_qs.exists() and request.user.role != User.Role.ADMIN:
            continue
        area_pendency.append(
            {
                "area": f"{area.code} {area.name}",
                "do": area.divisional_office.name,
                "pending": area_qs.count(),
            }
        )

    priority = (
        active.filter(
            Q(assigned_vendor__isnull=True)
            | Q(status__in=[Complaint.Status.WORK_COMPLETION, Complaint.Status.USER_CONFIRMATION])
            | Q(status=Complaint.Status.SUBMITTED)
            | Q(escalation_count__gt=0)
            | Q(site_issues__isnull=False)
        )
        .distinct()
        .order_by("-escalation_count", "created_at")
    )

    sla_closed = list(closed)
    sla_met = 100.0
    if sla_closed:
        sla_met = round(
            sum(1 for c in sla_closed if c.aging_hours <= c.sla_hours) / len(sla_closed) * 100,
            1,
        )

    return Response(
        {
            "total_pumps": pumps.count(),
            "pumps_mapped_pct": 100 if pumps.exists() else 0,
            "active_complaints": active.count(),
            "aging_gt_24": len(aging_gt_24),
            "in_progress": in_progress.count(),
            "awaiting_confirm": awaiting.count(),
            "resolved": closed.count(),
            "avg_rating": round(avg_rating, 1),
            "sla_met": sla_met,
            "by_category": by_category,
            "by_status": {
                row["status"]: row["count"]
                for row in complaints.values("status").annotate(count=Count("id"))
            },
            "by_priority": {
                row["priority"]: row["count"]
                for row in active.values("priority").annotate(count=Count("id"))
            },
            "aging_buckets": aging_buckets,
            "area_pendency": area_pendency,
            "priority_items": ComplaintSerializer(priority, many=True, context={"request": request}).data,
            "pending_registrations": (
                RegistrationRequest.objects.filter(status=RegistrationRequest.Status.PENDING).count()
                if request.user.role == User.Role.ADMIN
                else 0
            ),
        }
    )


class PumpViewSet(viewsets.ModelViewSet):
    serializer_class = ConsumerPumpSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return scoped_pumps(self.request.user)

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsOfficer()]
        return super().get_permissions()


class VendorViewSet(viewsets.ModelViewSet):
    serializer_class = VendorSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    queryset = Vendor.objects.select_related("user")

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy", "bulk_upload"):
            return [IsAuthenticated(), IsOfficer()]
        return super().get_permissions()

    @action(detail=False, methods=["post"], url_path="bulk-upload")
    def bulk_upload(self, request):
        """CSV columns: name,specialization,phone,email"""
        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "CSV file is required."}, status=400)
        decoded = upload.read().decode("utf-8")
        reader = csv.DictReader(StringIO(decoded))
        created = []
        for row in reader:
            spec = (row.get("specialization") or "OTHER").upper()
            if spec not in Vendor.Specialization.values:
                spec = Vendor.Specialization.OTHER
            vendor = Vendor.objects.create(
                name=row.get("name", "").strip(),
                specialization=spec,
                phone=row.get("phone", "").strip(),
                email=row.get("email", "").strip(),
            )
            created.append(vendor)
        return Response(VendorSerializer(created, many=True).data, status=201)

    @action(detail=False, methods=["post"], url_path="remind")
    def remind(self, request):
        qs = scoped_complaints(request.user).exclude(status=Complaint.Status.CLOSED).filter(
            assigned_vendor__isnull=False
        )
        updated = qs.update(last_reminded_at=timezone.now())
        return Response({"reminded": updated})


class ComplaintViewSet(viewsets.ModelViewSet):
    serializer_class = ComplaintSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        qs = scoped_complaints(self.request.user)
        params = self.request.query_params
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        bucket = params.get("bucket")
        if bucket == "active":
            qs = qs.exclude(status=Complaint.Status.CLOSED)
        elif bucket == "closed":
            qs = qs.filter(status=Complaint.Status.CLOSED)
        elif bucket == "in_progress":
            qs = qs.filter(
                status__in=[
                    Complaint.Status.VENDOR_ACKNOWLEDGED,
                    Complaint.Status.ESTIMATION_PENDING,
                    Complaint.Status.ESTIMATION_APPROVED,
                    Complaint.Status.WORK_IN_PROGRESS,
                ]
            )
        elif bucket == "awaiting":
            qs = qs.filter(
                status__in=[
                    Complaint.Status.WORK_COMPLETION,
                    Complaint.Status.USER_CONFIRMATION,
                ]
            )
        elif bucket == "estimation":
            qs = qs.filter(status=Complaint.Status.ESTIMATION_PENDING)
        elif bucket == "unassigned":
            qs = qs.filter(assigned_vendor__isnull=True).exclude(status=Complaint.Status.CLOSED)
        elif bucket == "escalated":
            qs = qs.filter(escalation_count__gt=0).exclude(status=Complaint.Status.CLOSED)
        elif bucket == "site_issues":
            qs = qs.filter(site_issues__isnull=False).exclude(status=Complaint.Status.CLOSED).distinct()
        if params.get("category"):
            qs = qs.filter(category=params["category"])
        if params.get("sales_area"):
            qs = qs.filter(pump__sales_area_id=params["sales_area"])
        if params.get("vendor"):
            qs = qs.filter(assigned_vendor_id=params["vendor"])
        if params.get("pump"):
            qs = qs.filter(pump_id=params["pump"])
        if params.get("q"):
            q = params["q"]
            qs = qs.filter(
                Q(complaint_id__icontains=q)
                | Q(pump__name__icontains=q)
                | Q(specific_problem__icontains=q)
                | Q(description__icontains=q)
            )
        if params.get("from"):
            qs = qs.filter(created_at__date__gte=params["from"])
        if params.get("to"):
            qs = qs.filter(created_at__date__lte=params["to"])
        return qs

    def perform_create(self, serializer):
        complaint = serializer.save()
        files = self.request.FILES.getlist("photos") or self.request.FILES.getlist("photos[]")
        for f in files:
            kind = ComplaintMedia.Kind.VIDEO if f.content_type.startswith("video") else ComplaintMedia.Kind.USER_PHOTO
            ComplaintMedia.objects.create(
                complaint=complaint, kind=kind, file=f, uploaded_by=self.request.user
            )
        notify_new_complaint(complaint)

    @action(detail=True, methods=["post"], url_path="assign-vendor")
    def assign_vendor(self, request, pk=None):
        if request.user.role not in OFFICER_ROLES:
            return Response({"detail": "Only officers can assign vendors."}, status=403)
        complaint = self.get_object()
        if complaint.status == Complaint.Status.CLOSED:
            return Response({"detail": "Closed jobs cannot be reassigned."}, status=400)
        vendor_id = request.data.get("vendor_id")
        if not vendor_id:
            return Response({"detail": "Select a vendor."}, status=400)
        try:
            vendor = Vendor.objects.get(pk=vendor_id)
        except Vendor.DoesNotExist:
            return Response({"detail": "Vendor not found."}, status=400)
        previous = complaint.assigned_vendor
        reassign = previous is not None and previous.id != vendor.id
        complaint.assigned_vendor = vendor
        complaint.officer_remarks = request.data.get("officer_remarks", complaint.officer_remarks)
        if reassign:
            complaint.estimation_remarks = ""
            complaint.estimation_amount = None
            complaint.estimation_reviewed_by = None
            complaint.estimation_reviewed_at = None
            complaint.estimation_review_note = ""
        complaint.save()
        if reassign and previous and previous.user:
            notify(
                [previous.user],
                kind=Notification.Kind.STATUS,
                title=f"{complaint.complaint_id} was reassigned",
                body=f"This job was moved from {previous.name} to {vendor.name}.",
                link=f"/complaints?q={complaint.complaint_id}",
                complaint=complaint,
                exclude=request.user,
            )
        note = (
            f"Reassigned from {previous.name} to {vendor.name}"
            if reassign
            else f"Assigned {vendor.name}"
        )
        transition(complaint, Complaint.Status.ASSIGNED_TO_VENDOR, request.user, note)
        return Response(self.get_serializer(complaint).data)

    @action(detail=True, methods=["post"], url_path="update-work")
    def update_work(self, request, pk=None):
        complaint = self.get_object()
        if request.user.role != User.Role.VENDOR:
            return Response({"detail": "Only the assigned vendor can update work."}, status=403)
        profile = getattr(request.user, "vendor_profile", None)
        if not profile or complaint.assigned_vendor_id != profile.id:
            return Response({"detail": "This job is not assigned to you."}, status=403)
        if complaint.status == Complaint.Status.CLOSED:
            return Response({"detail": "Closed jobs cannot be edited."}, status=400)
        complaint.vendor_remarks = request.data.get("vendor_remarks", complaint.vendor_remarks)
        complaint.save(update_fields=["vendor_remarks", "updated_at"])
        photo_kind = (
            ComplaintMedia.Kind.AFTER_PROOF
            if complaint.status == Complaint.Status.WORK_COMPLETION
            else ComplaintMedia.Kind.BEFORE_PROOF
        )
        for f in request.FILES.getlist("photos") or request.FILES.getlist("photos[]"):
            ComplaintMedia.objects.create(
                complaint=complaint,
                kind=photo_kind,
                file=f,
                uploaded_by=request.user,
            )
        StatusHistory.objects.create(
            complaint=complaint,
            from_status=complaint.status,
            to_status=complaint.status,
            actor=request.user,
            note="Vendor updated job details",
        )
        return Response(self.get_serializer(complaint).data)

    @action(detail=True, methods=["post"], url_path="update-details")
    def update_details(self, request, pk=None):
        complaint = self.get_object()
        is_officer = request.user.role in OFFICER_ROLES
        is_customer = request.user.role == User.Role.CP_USER
        if not is_officer and not is_customer:
            return Response({"detail": "Only the customer or an officer can update this complaint."}, status=403)
        if is_customer and not (
            complaint.submitted_by_id == request.user.id
            or complaint.pump_id == request.user.consumer_pump_id
        ):
            return Response({"detail": "You can only update complaints for your pump."}, status=403)
        if complaint.status == Complaint.Status.CLOSED:
            return Response({"detail": "Closed jobs cannot be edited. File a new complaint if work is still needed."}, status=400)
        description = request.data.get("description")
        category = request.data.get("category")
        if description is not None:
            complaint.description = str(description).strip() or complaint.description
        if category and category in Complaint.Category.values:
            complaint.category = category
            complaint.specific_problem = complaint.get_category_display()
            complaint.sla_hours = SLA_HOURS.get(category, complaint.sla_hours)
        if complaint.category == Complaint.Category.DU:
            for field in ("du_make", "du_model", "du_serial"):
                if request.data.get(field) is not None:
                    setattr(complaint, field, str(request.data.get(field) or "").strip())
            if not (complaint.du_make and complaint.du_model and complaint.du_serial):
                return Response(
                    {"detail": "Make, Model and Sr. No. are required for DU related complaints."},
                    status=400,
                )
        else:
            complaint.du_make = ""
            complaint.du_model = ""
            complaint.du_serial = ""
        if is_officer and request.data.get("officer_remarks") is not None:
            complaint.officer_remarks = str(request.data.get("officer_remarks") or "")
        complaint.save()
        for f in request.FILES.getlist("photos") or request.FILES.getlist("photos[]"):
            kind = ComplaintMedia.Kind.VIDEO if getattr(f, "content_type", "").startswith("video") else ComplaintMedia.Kind.USER_PHOTO
            ComplaintMedia.objects.create(
                complaint=complaint, kind=kind, file=f, uploaded_by=request.user
            )
        StatusHistory.objects.create(
            complaint=complaint,
            from_status=complaint.status,
            to_status=complaint.status,
            actor=request.user,
            note="Complaint details updated",
        )
        return Response(self.get_serializer(complaint).data)

    @action(detail=True, methods=["post"])
    def refer(self, request, pk=None):
        if request.user.role not in OFFICER_ROLES:
            return Response({"detail": "Only officers can refer complaints."}, status=403)
        complaint = self.get_object()
        officer = User.objects.get(pk=request.data.get("officer_id"))
        complaint.sales_officer = officer
        complaint.save()
        transition(
            complaint,
            Complaint.Status.ASSIGNED_TO_OFFICER,
            request.user,
            f"Referred to {officer.get_full_name()}",
        )
        return Response(self.get_serializer(complaint).data)

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        complaint = self.get_object()
        if request.user.role != User.Role.VENDOR:
            return Response({"detail": "Only the assigned vendor can acknowledge."}, status=403)
        transition(complaint, Complaint.Status.VENDOR_ACKNOWLEDGED, request.user, "Vendor acknowledged")
        return Response(self.get_serializer(complaint).data)

    @action(detail=True, methods=["post"], url_path="submit-estimation")
    def submit_estimation(self, request, pk=None):
        complaint = self.get_object()
        if request.user.role != User.Role.VENDOR:
            return Response({"detail": "Only the assigned vendor can submit an estimation."}, status=403)
        if complaint.status not in (
            Complaint.Status.ASSIGNED_TO_VENDOR,
            Complaint.Status.VENDOR_ACKNOWLEDGED,
        ):
            return Response({"detail": "Estimation can be submitted after the job is assigned."}, status=400)
        remarks = (request.data.get("estimation_remarks") or "").strip()
        raw_amount = request.data.get("estimation_amount")
        if not remarks or raw_amount in (None, ""):
            return Response({"detail": "Estimation remarks and amount are required."}, status=400)
        try:
            amount = Decimal(str(raw_amount))
        except (InvalidOperation, ValueError):
            return Response({"detail": "Enter a valid estimation amount."}, status=400)
        if amount <= 0:
            return Response({"detail": "Estimation amount must be greater than zero."}, status=400)
        complaint.estimation_remarks = remarks
        complaint.estimation_amount = amount
        complaint.estimation_reviewed_by = None
        complaint.estimation_reviewed_at = None
        complaint.estimation_review_note = ""
        complaint.save()
        transition(
            complaint,
            Complaint.Status.ESTIMATION_PENDING,
            request.user,
            f"Estimation submitted: ₹{amount}",
        )
        return Response(self.get_serializer(complaint).data)

    @action(detail=True, methods=["post"], url_path="approve-estimation")
    def approve_estimation(self, request, pk=None):
        if request.user.role not in OFFICER_ROLES:
            return Response({"detail": "Only an officer can approve an estimation."}, status=403)
        complaint = self.get_object()
        if complaint.status != Complaint.Status.ESTIMATION_PENDING:
            return Response({"detail": "No estimation is waiting for approval."}, status=400)
        complaint.estimation_reviewed_by = request.user
        complaint.estimation_reviewed_at = timezone.now()
        complaint.estimation_review_note = (request.data.get("note") or "").strip()
        complaint.save()
        transition(complaint, Complaint.Status.ESTIMATION_APPROVED, request.user, "Estimation approved")
        return Response(self.get_serializer(complaint).data)

    @action(detail=True, methods=["post"], url_path="reject-estimation")
    def reject_estimation(self, request, pk=None):
        if request.user.role not in OFFICER_ROLES:
            return Response({"detail": "Only an officer can reject an estimation."}, status=403)
        complaint = self.get_object()
        if complaint.status != Complaint.Status.ESTIMATION_PENDING:
            return Response({"detail": "No estimation is waiting for approval."}, status=400)
        note = (request.data.get("note") or "").strip()
        if not note:
            return Response({"detail": "Please add a reason for sending the estimation back."}, status=400)
        complaint.estimation_reviewed_by = request.user
        complaint.estimation_reviewed_at = timezone.now()
        complaint.estimation_review_note = note
        complaint.save()
        transition(
            complaint,
            Complaint.Status.VENDOR_ACKNOWLEDGED,
            request.user,
            f"Estimation sent back: {note}",
        )
        return Response(self.get_serializer(complaint).data)

    @action(detail=True, methods=["post"], url_path="start-work")
    def start_work(self, request, pk=None):
        complaint = self.get_object()
        if request.user.role != User.Role.VENDOR:
            return Response({"detail": "Only the assigned vendor can update work."}, status=403)
        if complaint.status != Complaint.Status.ESTIMATION_APPROVED:
            return Response(
                {"detail": "Admin must approve the estimation before work can start."},
                status=400,
            )
        complaint.vendor_remarks = request.data.get("vendor_remarks", complaint.vendor_remarks)
        complaint.save()
        for f in request.FILES.getlist("photos") or request.FILES.getlist("photos[]"):
            ComplaintMedia.objects.create(
                complaint=complaint,
                kind=ComplaintMedia.Kind.BEFORE_PROOF,
                file=f,
                uploaded_by=request.user,
            )
        transition(complaint, Complaint.Status.WORK_IN_PROGRESS, request.user, "Work started")
        return Response(self.get_serializer(complaint).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        complaint = self.get_object()
        if request.user.role != User.Role.VENDOR:
            return Response({"detail": "Only the assigned vendor can complete work."}, status=403)
        complaint.vendor_remarks = request.data.get("vendor_remarks", complaint.vendor_remarks)
        complaint.save()
        for f in request.FILES.getlist("photos") or request.FILES.getlist("photos[]"):
            ComplaintMedia.objects.create(
                complaint=complaint,
                kind=ComplaintMedia.Kind.AFTER_PROOF,
                file=f,
                uploaded_by=request.user,
            )
        transition(
            complaint,
            Complaint.Status.WORK_COMPLETION,
            request.user,
            "Work completed — awaiting user confirmation",
        )
        return Response(self.get_serializer(complaint).data)

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        complaint = self.get_object()
        if request.user.role != User.Role.CP_USER and request.user.role not in OFFICER_ROLES:
            return Response({"detail": "Not allowed to confirm resolution."}, status=403)
        rating = int(request.data.get("rating") or 5)
        remarks = request.data.get("remarks", "")
        ComplaintFeedback.objects.update_or_create(
            complaint=complaint,
            defaults={
                "resolved": True,
                "rating": rating,
                "remarks": remarks,
                "submitted_by": request.user,
            },
        )
        for f in (
            request.FILES.getlist("certificate")
            or request.FILES.getlist("photos")
            or request.FILES.getlist("photos[]")
        ):
            ComplaintMedia.objects.create(
                complaint=complaint,
                kind=ComplaintMedia.Kind.CERTIFICATE,
                file=f,
                uploaded_by=request.user,
            )
        transition(complaint, Complaint.Status.USER_CONFIRMATION, request.user, "User confirmed", notify=False)
        transition(complaint, Complaint.Status.CLOSED, request.user, "Closed")
        vendor = complaint.assigned_vendor
        if vendor:
            ratings = ComplaintFeedback.objects.filter(
                complaint__assigned_vendor=vendor, complaint__status=Complaint.Status.CLOSED
            )
            avg = ratings.aggregate(avg=Avg("rating"))["avg"]
            if avg:
                vendor.rating = round(avg, 1)
                vendor.save(update_fields=["rating"])
        return Response(self.get_serializer(complaint).data)

    @action(detail=True, methods=["post"])
    def escalate(self, request, pk=None):
        complaint = self.get_object()
        if complaint.status == Complaint.Status.CLOSED:
            return Response({"detail": "Closed complaints cannot be escalated."}, status=400)
        if request.user.role != User.Role.CP_USER:
            return Response({"detail": "Only the customer can escalate this complaint."}, status=403)
        if not (
            complaint.submitted_by_id == request.user.id
            or complaint.pump_id == request.user.consumer_pump_id
        ):
            return Response({"detail": "You can only escalate complaints for your pump."}, status=403)
        note = (request.data.get("note") or "").strip()
        if len(note) < 8:
            return Response({"detail": "Please describe why this needs escalation (at least 8 characters)."}, status=400)
        complaint.priority = Complaint.Priority.HIGH
        complaint.escalated_at = timezone.now()
        complaint.escalation_note = note
        complaint.escalation_count = (complaint.escalation_count or 0) + 1
        complaint.save(
            update_fields=["priority", "escalated_at", "escalation_note", "escalation_count", "updated_at"]
        )
        StatusHistory.objects.create(
            complaint=complaint,
            from_status=complaint.status,
            to_status=complaint.status,
            actor=request.user,
            note=f"User escalated (#{complaint.escalation_count}): {note[:200]}",
        )
        notify_escalation(complaint, request.user, note)
        return Response(self.get_serializer(complaint).data)

    @action(detail=True, methods=["post"], url_path="site-issue")
    def site_issue(self, request, pk=None):
        complaint = self.get_object()
        if request.user.role != User.Role.VENDOR:
            return Response({"detail": "Only the assigned vendor can report a site problem."}, status=403)
        profile = getattr(request.user, "vendor_profile", None)
        if not profile or complaint.assigned_vendor_id != profile.id:
            return Response({"detail": "This job is not assigned to you."}, status=403)
        if complaint.status == Complaint.Status.CLOSED:
            return Response({"detail": "Closed jobs cannot take a site report."}, status=400)
        kind = (request.data.get("kind") or "").strip().upper()
        if kind not in VendorSiteIssue.Kind.values:
            return Response({"detail": "Select a valid site problem type."}, status=400)
        description = (request.data.get("description") or "").strip()
        if len(description) < 8:
            return Response({"detail": "Please describe the problem at site (at least 8 characters)."}, status=400)
        issue = VendorSiteIssue.objects.create(
            complaint=complaint,
            reported_by=request.user,
            kind=kind,
            description=description,
        )
        photo = request.FILES.get("photo")
        if photo:
            issue.photo = photo
            issue.save(update_fields=["photo"])
        complaint.priority = Complaint.Priority.HIGH
        complaint.save(update_fields=["priority", "updated_at"])
        StatusHistory.objects.create(
            complaint=complaint,
            from_status=complaint.status,
            to_status=complaint.status,
            actor=request.user,
            note=f"Vendor site issue ({issue.get_kind_display()}): {description[:180]}",
        )
        notify_site_issue(issue)
        return Response(self.get_serializer(complaint).data)


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()[:50]
        unread = self.get_queryset().filter(is_read=False).count()
        return Response(
            {
                "unread": unread,
                "results": NotificationSerializer(qs, many=True).data,
            }
        )

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        rec = self.get_object()
        rec.is_read = True
        rec.save(update_fields=["is_read"])
        return Response(NotificationSerializer(rec).data)

    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        updated = self.get_queryset().filter(is_read=False).update(is_read=True)
        return Response({"updated": updated})


@api_view(["GET"])
def reports_export(request):
    qs = scoped_complaints(request.user)
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    if request.GET.get("category"):
        qs = qs.filter(category=request.GET["category"])
    if request.GET.get("sales_area"):
        qs = qs.filter(pump__sales_area_id=request.GET["sales_area"])
    if request.GET.get("pump"):
        qs = qs.filter(pump_id=request.GET["pump"])
    if request.GET.get("vendor"):
        qs = qs.filter(assigned_vendor_id=request.GET["vendor"])
    if request.GET.get("from"):
        qs = qs.filter(created_at__date__gte=request.GET["from"])
    if request.GET.get("to"):
        qs = qs.filter(created_at__date__lte=request.GET["to"])

    fmt = request.GET.get("format", "json")
    if fmt == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="pahle-complaints.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "Complaint ID",
                "Date",
                "Consumer Pump",
                "Area & DO",
                "Category",
                "DU Make",
                "DU Model",
                "DU Sr. No.",
                "Issue",
                "Vendor",
                "Aging Days",
                "Status",
                "User Rating",
            ]
        )
        for c in qs:
            area = c.pump.sales_area
            rating = getattr(getattr(c, "feedback", None), "rating", "")
            writer.writerow(
                [
                    c.complaint_id,
                    c.created_at.strftime("%Y-%m-%d %H:%M"),
                    c.pump.name,
                    f"{area.code} {area.name} ({area.divisional_office.name})",
                    c.get_category_display(),
                    c.du_make,
                    c.du_model,
                    c.du_serial,
                    c.specific_problem,
                    c.assigned_vendor.name if c.assigned_vendor else "Unassigned",
                    c.aging_days if c.aging_days is not None else "",
                    c.get_status_display(),
                    rating,
                ]
            )
        return response
    return Response(ComplaintSerializer(qs, many=True, context={"request": request}).data)
