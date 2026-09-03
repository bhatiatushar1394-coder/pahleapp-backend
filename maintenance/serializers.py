from django.conf import settings
from rest_framework import serializers

from .constants import SLA_HOURS, normalize_subtype
from .geo import google_maps_url
from .models import (
    Complaint,
    ComplaintFeedback,
    ComplaintMedia,
    ConsumerPump,
    DivisionalOffice,
    JobCompletionCertificate,
    PumpFacility,
    RegistrationRequest,
    SalesArea,
    StatusHistory,
    User,
    Vendor,
    Notification,
    VendorSiteIssue,
)


def file_public_url(file_field, request=None):
    if not file_field:
        return None
    url = file_field.url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if request:
        return request.build_absolute_uri(url)
    base = (getattr(settings, "BACKEND_PUBLIC_URL", "") or "").rstrip("/")
    return f"{base}{url}" if base else url


class UserPublicSerializer(serializers.ModelSerializer):
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    full_name = serializers.SerializerMethodField()
    sales_area_label = serializers.SerializerMethodField()
    do_label = serializers.SerializerMethodField()
    pump_name = serializers.SerializerMethodField()
    vendor_id = serializers.SerializerMethodField()
    vendor_name = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()
    district_area = serializers.SerializerMethodField()
    amc_type = serializers.SerializerMethodField()
    amc_type_label = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "full_name",
            "first_name",
            "last_name",
            "email",
            "phone",
            "role",
            "role_label",
            "sales_area",
            "sales_area_label",
            "divisional_office",
            "do_label",
            "consumer_pump",
            "pump_name",
            "vendor_id",
            "vendor_name",
            "designation",
            "employee_code",
            "bio",
            "avatar_url",
            "district_area",
            "amc_type",
            "amc_type_label",
        ]
        read_only_fields = fields

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username

    def get_sales_area_label(self, obj):
        if obj.role in (User.Role.ADMIN, User.Role.DO_OFFICER) and obj.divisional_office:
            name = (obj.divisional_office.name or "").strip()
            if name.upper().startswith("DO "):
                return f"{name[3:].strip()} DO"
            return name
        if not obj.sales_area:
            return ""
        return f"{obj.sales_area.code} {obj.sales_area.name} ({obj.sales_area.divisional_office.name})"

    def get_do_label(self, obj):
        return obj.divisional_office.name if obj.divisional_office else ""

    def get_pump_name(self, obj):
        return obj.consumer_pump.name if obj.consumer_pump else ""

    def get_vendor_id(self, obj):
        try:
            return obj.vendor_profile.id
        except Vendor.DoesNotExist:
            return None

    def get_vendor_name(self, obj):
        try:
            return obj.vendor_profile.name
        except Vendor.DoesNotExist:
            return ""

    def get_avatar_url(self, obj):
        return file_public_url(obj.avatar, self.context.get("request"))

    def get_district_area(self, obj):
        if not obj.sales_area_id:
            return ""
        names = [d.name for d in obj.sales_area.districts.all()]
        return ", ".join(names)

    def get_amc_type(self, obj):
        return obj.consumer_pump.amc_type if obj.consumer_pump else ""

    def get_amc_type_label(self, obj):
        if not obj.consumer_pump or not obj.consumer_pump.amc_type:
            return ""
        return obj.consumer_pump.get_amc_type_display()


class UserProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "designation",
            "employee_code",
            "bio",
            "avatar",
        ]

    def update(self, instance, validated_data):
        avatar = validated_data.pop("avatar", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        if avatar is not None:
            instance.avatar = avatar
        instance.save()
        try:
            vendor = instance.vendor_profile
        except Vendor.DoesNotExist:
            vendor = None
        if vendor:
            if "phone" in validated_data:
                vendor.phone = instance.phone
            if "email" in validated_data:
                vendor.email = instance.email
            vendor.save(update_fields=["phone", "email"])
        return instance


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class SalesAreaSerializer(serializers.ModelSerializer):
    divisional_office_name = serializers.CharField(source="divisional_office.name", read_only=True)
    districts = serializers.SerializerMethodField()

    class Meta:
        model = SalesArea
        fields = ["id", "code", "name", "zone", "divisional_office", "divisional_office_name", "districts"]

    def get_districts(self, obj):
        return [d.name for d in obj.districts.all()]


class DivisionalOfficeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DivisionalOffice
        fields = ["id", "code", "name"]


class PumpFacilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = PumpFacility
        fields = ["id", "label"]


class ConsumerPumpSerializer(serializers.ModelSerializer):
    sales_area_detail = SalesAreaSerializer(source="sales_area", read_only=True)
    sales_officer_detail = UserPublicSerializer(source="sales_officer", read_only=True)
    engineering_officer_detail = UserPublicSerializer(source="engineering_officer", read_only=True)
    facilities = PumpFacilitySerializer(many=True, read_only=True)
    facility_labels = serializers.ListField(
        child=serializers.CharField(), write_only=True, required=False
    )
    active_issues = serializers.SerializerMethodField()
    amc_type_label = serializers.CharField(source="get_amc_type_display", read_only=True)
    maps_url = serializers.SerializerMethodField()

    class Meta:
        model = ConsumerPump
        extra_kwargs = {
            "pump_code": {"required": False, "allow_blank": True},
            "latitude": {"required": False, "allow_null": True},
            "longitude": {"required": False, "allow_null": True},
            "amc_type": {"required": False, "allow_blank": True},
        }
        fields = [
            "id",
            "pump_code",
            "name",
            "address",
            "city",
            "sales_area",
            "sales_area_detail",
            "sales_officer",
            "sales_officer_detail",
            "engineering_officer",
            "engineering_officer_detail",
            "latitude",
            "longitude",
            "amc_type",
            "amc_type_label",
            "maps_url",
            "is_active",
            "facilities",
            "facility_labels",
            "active_issues",
        ]

    def get_active_issues(self, obj):
        return obj.complaints.exclude(status=Complaint.Status.CLOSED).count()

    def get_maps_url(self, obj):
        return google_maps_url(obj.latitude, obj.longitude, obj.name, obj.address, obj.city, obj.pump_code)

    def create(self, validated_data):
        labels = validated_data.pop("facility_labels", [])
        if not validated_data.get("pump_code"):
            last = ConsumerPump.objects.order_by("-id").first()
            n = 101
            if last:
                try:
                    n = int(last.pump_code.split("-")[-1]) + 1
                except ValueError:
                    n = ConsumerPump.objects.count() + 101
            validated_data["pump_code"] = f"CP-{n}"
        pump = ConsumerPump.objects.create(**validated_data)
        for label in labels:
            PumpFacility.objects.create(pump=pump, label=label)
        return pump


class VendorSerializer(serializers.ModelSerializer):
    specialization_label = serializers.CharField(source="get_specialization_display", read_only=True)
    username = serializers.SerializerMethodField()
    active_jobs = serializers.SerializerMethodField()
    resolved_jobs = serializers.SerializerMethodField()
    sla_compliance = serializers.SerializerMethodField()

    class Meta:
        model = Vendor
        fields = [
            "id",
            "name",
            "specialization",
            "specialization_label",
            "phone",
            "email",
            "username",
            "rating",
            "is_active",
            "active_jobs",
            "resolved_jobs",
            "sla_compliance",
        ]

    def get_username(self, obj):
        return obj.user.username if obj.user else ""

    def get_active_jobs(self, obj):
        return obj.complaints.exclude(status=Complaint.Status.CLOSED).count()

    def get_resolved_jobs(self, obj):
        return obj.complaints.filter(status=Complaint.Status.CLOSED).count()

    def get_sla_compliance(self, obj):
        closed = list(obj.complaints.filter(status=Complaint.Status.CLOSED))
        total = len(closed)
        if not total:
            return 96.5
        on_time = sum(1 for c in closed if c.aging_hours <= c.sla_hours)
        return round((on_time / total) * 100, 1)


class ComplaintMediaSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()

    class Meta:
        model = ComplaintMedia
        fields = ["id", "kind", "url", "preview_url", "uploaded_at"]

    def get_url(self, obj):
        return file_public_url(obj.file, self.context.get("request"))

    def get_preview_url(self, obj):
        from .media_preview import ensure_media_preview, is_image_name

        if obj.file and is_image_name(obj.file.name):
            return file_public_url(obj.file, self.context.get("request"))
        ensure_media_preview(obj)
        return file_public_url(obj.preview, self.context.get("request"))


class ComplaintFeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComplaintFeedback
        fields = ["resolved", "rating", "remarks", "submitted_at"]


class StatusHistorySerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = StatusHistory
        fields = ["from_status", "to_status", "actor_name", "note", "created_at"]

    def get_actor_name(self, obj):
        return obj.actor.get_full_name() if obj.actor else ""


class VendorSiteIssueSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    reported_by_name = serializers.SerializerMethodField()
    photo_url = serializers.SerializerMethodField()

    class Meta:
        model = VendorSiteIssue
        fields = [
            "id",
            "kind",
            "kind_label",
            "description",
            "photo_url",
            "reported_by_name",
            "created_at",
        ]

    def get_reported_by_name(self, obj):
        if not obj.reported_by:
            return ""
        return obj.reported_by.get_full_name() or obj.reported_by.username

    def get_photo_url(self, obj):
        return file_public_url(obj.photo, self.context.get("request"))


class JobCompletionCertificateSerializer(serializers.ModelSerializer):
    stage_label = serializers.CharField(source="get_stage_display", read_only=True)
    signature_url = serializers.SerializerMethodField()
    uploaded_pdf_url = serializers.SerializerMethodField()
    generated_pdf_url = serializers.SerializerMethodField()
    pdf_url = serializers.SerializerMethodField()
    prepared_by_name = serializers.SerializerMethodField()
    signed_by_name = serializers.SerializerMethodField()
    bill_submitted_by_name = serializers.SerializerMethodField()

    class Meta:
        model = JobCompletionCertificate
        fields = [
            "id",
            "stage",
            "stage_label",
            "certificate_date",
            "vendor_name",
            "vendor_address",
            "nature_of_job",
            "customer_name",
            "job_completion_date",
            "work_satisfactory",
            "signature_url",
            "uploaded_pdf_url",
            "generated_pdf_url",
            "pdf_url",
            "prepared_by_name",
            "prepared_at",
            "signed_by_name",
            "signed_at",
            "bill_submitted_by_name",
            "bill_submitted_at",
        ]

    def _url(self, field):
        return file_public_url(field, self.context.get("request"))

    def get_signature_url(self, obj):
        return self._url(obj.signature)

    def get_uploaded_pdf_url(self, obj):
        return self._url(obj.uploaded_pdf)

    def get_generated_pdf_url(self, obj):
        return self._url(obj.generated_pdf)

    def get_pdf_url(self, obj):
        return self._url(obj.generated_pdf) or self._url(obj.uploaded_pdf)

    def get_prepared_by_name(self, obj):
        if not obj.prepared_by:
            return ""
        return obj.prepared_by.get_full_name() or obj.prepared_by.username

    def get_signed_by_name(self, obj):
        if not obj.signed_by:
            return ""
        return obj.signed_by.get_full_name() or obj.signed_by.username

    def get_bill_submitted_by_name(self, obj):
        if not obj.bill_submitted_by:
            return ""
        return obj.bill_submitted_by.get_full_name() or obj.bill_submitted_by.username


class ComplaintSerializer(serializers.ModelSerializer):
    pump_name = serializers.CharField(source="pump.name", read_only=True)
    pump_code = serializers.CharField(source="pump.pump_code", read_only=True)
    sales_area_label = serializers.SerializerMethodField()
    sales_officer_name = serializers.SerializerMethodField()
    vendor_name = serializers.CharField(source="assigned_vendor.name", read_only=True)
    submitted_by_name = serializers.SerializerMethodField()
    category_label = serializers.CharField(source="get_category_display", read_only=True)
    priority_label = serializers.CharField(source="get_priority_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    aging_hours = serializers.IntegerField(read_only=True)
    aging_days = serializers.IntegerField(read_only=True, allow_null=True)
    is_overdue = serializers.BooleanField(read_only=True)
    estimation_reviewed_by_name = serializers.SerializerMethodField()
    pump_address = serializers.CharField(source="pump.address", read_only=True)
    pump_maps_url = serializers.SerializerMethodField()
    media = ComplaintMediaSerializer(many=True, read_only=True)
    feedback = ComplaintFeedbackSerializer(read_only=True)
    history = StatusHistorySerializer(many=True, read_only=True)
    site_issues = VendorSiteIssueSerializer(many=True, read_only=True)
    user_rating = serializers.SerializerMethodField()
    job_certificate = serializers.SerializerMethodField()
    customer_contact_name = serializers.SerializerMethodField()
    customer_contact_phone = serializers.SerializerMethodField()
    vendor_contact_name = serializers.SerializerMethodField()
    vendor_contact_phone = serializers.SerializerMethodField()
    contacts_visible = serializers.SerializerMethodField()

    class Meta:
        model = Complaint
        fields = [
            "id",
            "complaint_id",
            "pump",
            "pump_name",
            "pump_code",
            "pump_address",
            "pump_maps_url",
            "sales_area_label",
            "submitted_by",
            "submitted_by_name",
            "sales_officer",
            "sales_officer_name",
            "assigned_vendor",
            "vendor_name",
            "category",
            "category_label",
            "specific_problem",
            "du_make",
            "du_model",
            "du_serial",
            "description",
            "priority",
            "priority_label",
            "status",
            "status_label",
            "officer_remarks",
            "vendor_remarks",
            "estimation_remarks",
            "estimation_amount",
            "estimation_reviewed_by_name",
            "estimation_reviewed_at",
            "estimation_review_note",
            "po_number",
            "sla_hours",
            "aging_hours",
            "aging_days",
            "is_overdue",
            "escalated_at",
            "escalation_note",
            "escalation_count",
            "created_at",
            "updated_at",
            "closed_at",
            "media",
            "feedback",
            "history",
            "site_issues",
            "user_rating",
            "job_certificate",
            "customer_contact_name",
            "customer_contact_phone",
            "vendor_contact_name",
            "vendor_contact_phone",
            "contacts_visible",
        ]
        read_only_fields = [
            "complaint_id",
            "submitted_by",
            "sales_officer",
            "status",
            "sla_hours",
            "closed_at",
            "escalated_at",
            "escalation_note",
            "escalation_count",
            "estimation_remarks",
            "estimation_amount",
            "estimation_reviewed_at",
            "estimation_review_note",
        ]

    def get_sales_area_label(self, obj):
        area = obj.pump.sales_area
        return f"{area.code} {area.name} ({area.divisional_office.name})"

    def get_sales_officer_name(self, obj):
        name = obj.sales_officer.get_full_name()
        return f"{name} (SO)" if name else obj.sales_officer.username

    def get_submitted_by_name(self, obj):
        return obj.submitted_by.get_full_name() or obj.submitted_by.username

    def get_user_rating(self, obj):
        fb = getattr(obj, "feedback", None)
        return fb.rating if fb else None

    def get_estimation_reviewed_by_name(self, obj):
        user = obj.estimation_reviewed_by
        if not user:
            return None
        return user.get_full_name() or user.username

    def get_pump_maps_url(self, obj):
        pump = obj.pump
        return google_maps_url(pump.latitude, pump.longitude, pump.name, pump.address, pump.city, pump.pump_code)

    def get_job_certificate(self, obj):
        cert = getattr(obj, "job_certificate", None)
        if not cert:
            return None
        return JobCompletionCertificateSerializer(cert, context=self.context).data

    def _contacts_unlocked(self, obj):
        return obj.status in {
            Complaint.Status.VENDOR_ACKNOWLEDGED,
            Complaint.Status.ESTIMATION_PENDING,
            Complaint.Status.ESTIMATION_APPROVED,
            Complaint.Status.WORK_IN_PROGRESS,
            Complaint.Status.WORK_COMPLETION,
            Complaint.Status.USER_CONFIRMATION,
            Complaint.Status.CLOSED,
        }

    def get_contacts_visible(self, obj):
        return self._contacts_unlocked(obj)

    def get_customer_contact_name(self, obj):
        if not self._contacts_unlocked(obj):
            return ""
        return obj.submitted_by.get_full_name() or obj.submitted_by.username

    def get_customer_contact_phone(self, obj):
        if not self._contacts_unlocked(obj):
            return ""
        return (obj.submitted_by.phone or "").strip()

    def get_vendor_contact_name(self, obj):
        if not self._contacts_unlocked(obj) or not obj.assigned_vendor:
            return ""
        return obj.assigned_vendor.name or ""

    def get_vendor_contact_phone(self, obj):
        if not self._contacts_unlocked(obj) or not obj.assigned_vendor:
            return ""
        vendor = obj.assigned_vendor
        phone = (vendor.phone or "").strip()
        if not phone and vendor.user_id:
            phone = (vendor.user.phone or "").strip()
        return phone

    def validate(self, attrs):
        category = attrs.get("category") or getattr(self.instance, "category", None)
        if category == Complaint.Category.DU:
            for field, label in (("du_make", "Make"), ("du_model", "Model"), ("du_serial", "Sr. No.")):
                value = (attrs.get(field) if field in attrs else getattr(self.instance, field, "") or "").strip()
                if field in attrs:
                    attrs[field] = value
                if not value:
                    raise serializers.ValidationError({field: f"{label} is required for DU related complaints."})
        elif "category" in attrs:
            attrs["du_make"] = ""
            attrs["du_model"] = ""
            attrs["du_serial"] = ""
        if "specific_problem" in attrs or "category" in attrs:
            raw = attrs.get("specific_problem")
            if raw is None:
                raw = getattr(self.instance, "specific_problem", "")
            existing = getattr(self.instance, "specific_problem", "") if self.instance else ""
            try:
                attrs["specific_problem"] = normalize_subtype(category, raw, existing=existing)
            except ValueError as exc:
                raise serializers.ValidationError({"specific_problem": str(exc)})
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request and getattr(request.user, "role", None) == User.Role.CP_USER:
            data["estimation_amount"] = None
            data["estimation_remarks"] = ""
            data["estimation_reviewed_by_name"] = None
            data["estimation_reviewed_at"] = None
            data["estimation_review_note"] = ""
            data["po_number"] = ""
            data["media"] = [m for m in (data.get("media") or []) if m.get("kind") not in ("QUOTATION", "PO")]
        return data

    def create(self, validated_data):
        request = self.context["request"]
        pump = validated_data["pump"]
        if request.user.role == User.Role.CP_USER and request.user.consumer_pump:
            pump = request.user.consumer_pump
            validated_data["pump"] = pump
        category = validated_data["category"]
        label = dict(Complaint.Category.choices).get(category, category)
        try:
            validated_data["specific_problem"] = normalize_subtype(
                category, validated_data.get("specific_problem"), existing=""
            )
        except ValueError:
            validated_data["specific_problem"] = (validated_data.get("specific_problem") or "").strip() or label
        complaint = Complaint.objects.create(
            complaint_id=self._next_id(),
            submitted_by=request.user,
            sales_officer=pump.sales_officer,
            sla_hours=SLA_HOURS.get(category, 48),
            status=Complaint.Status.ASSIGNED_TO_OFFICER,
            **validated_data,
        )
        StatusHistory.objects.create(
            complaint=complaint,
            to_status=Complaint.Status.SUBMITTED,
            actor=request.user,
            note="Complaint lodged",
        )
        StatusHistory.objects.create(
            complaint=complaint,
            from_status=Complaint.Status.SUBMITTED,
            to_status=Complaint.Status.ASSIGNED_TO_OFFICER,
            actor=request.user,
            note=f"Auto-mapped to {pump.sales_area.code}",
        )
        return complaint

    def _next_id(self):
        from django.utils import timezone

        year = timezone.now().year
        prefix = f"CMP-{year}-"
        last = (
            Complaint.objects.filter(complaint_id__startswith=prefix)
            .order_by("-complaint_id")
            .first()
        )
        seq = 1
        if last:
            try:
                seq = int(last.complaint_id.split("-")[-1]) + 1
            except ValueError:
                seq = Complaint.objects.count() + 1
        return f"{prefix}{seq:03d}"


class RegistrationCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["CP_USER", "VENDOR"])
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(min_length=8, write_only=True)
    first_name = serializers.CharField(max_length=80)
    last_name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=20)
    organization_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    specialization = serializers.CharField(max_length=32, required=False, allow_blank=True)
    consumer_pump = serializers.IntegerField(required=False, allow_null=True)
    coordinates = serializers.CharField(required=False, allow_blank=True)
    latitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=False, allow_null=True)
    amc_type = serializers.CharField(max_length=16, required=False, allow_blank=True)


class RegistrationRequestSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    pump_name = serializers.CharField(source="consumer_pump.name", read_only=True)
    reviewed_by_name = serializers.SerializerMethodField()
    amc_type_label = serializers.SerializerMethodField()
    maps_url = serializers.SerializerMethodField()

    class Meta:
        model = RegistrationRequest
        fields = [
            "id",
            "kind",
            "kind_label",
            "status",
            "status_label",
            "username",
            "first_name",
            "last_name",
            "email",
            "phone",
            "organization_name",
            "specialization",
            "consumer_pump",
            "pump_name",
            "latitude",
            "longitude",
            "amc_type",
            "amc_type_label",
            "maps_url",
            "admin_note",
            "created_at",
            "reviewed_at",
            "reviewed_by_name",
        ]

    def get_reviewed_by_name(self, obj):
        return obj.reviewed_by.get_full_name() if obj.reviewed_by else ""

    def get_amc_type_label(self, obj):
        return dict(ConsumerPump.AmcType.choices).get(obj.amc_type, obj.amc_type or "")

    def get_maps_url(self, obj):
        return google_maps_url(obj.latitude, obj.longitude, obj.organization_name, obj.address, obj.city)


class NotificationSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "kind",
            "kind_label",
            "title",
            "body",
            "link",
            "is_read",
            "created_at",
            "complaint",
            "registration",
        ]
