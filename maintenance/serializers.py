from rest_framework import serializers

from .constants import SLA_HOURS
from .models import (
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
)


class UserPublicSerializer(serializers.ModelSerializer):
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    full_name = serializers.SerializerMethodField()
    sales_area_label = serializers.SerializerMethodField()
    do_label = serializers.SerializerMethodField()
    pump_name = serializers.SerializerMethodField()
    vendor_id = serializers.SerializerMethodField()
    vendor_name = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()

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
        ]

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username

    def get_sales_area_label(self, obj):
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
        if not obj.avatar:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.avatar.url)
        return obj.avatar.url


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

    class Meta:
        model = SalesArea
        fields = ["id", "code", "name", "zone", "divisional_office", "divisional_office_name"]


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

    class Meta:
        model = ConsumerPump
        extra_kwargs = {"pump_code": {"required": False, "allow_blank": True}}
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
            "is_active",
            "facilities",
            "facility_labels",
            "active_issues",
        ]

    def get_active_issues(self, obj):
        return obj.complaints.exclude(status=Complaint.Status.CLOSED).count()

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

    class Meta:
        model = ComplaintMedia
        fields = ["id", "kind", "url", "uploaded_at"]

    def get_url(self, obj):
        request = self.context.get("request")
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return obj.file.url if obj.file else None


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
    is_overdue = serializers.BooleanField(read_only=True)
    media = ComplaintMediaSerializer(many=True, read_only=True)
    feedback = ComplaintFeedbackSerializer(read_only=True)
    history = StatusHistorySerializer(many=True, read_only=True)
    user_rating = serializers.SerializerMethodField()

    class Meta:
        model = Complaint
        fields = [
            "id",
            "complaint_id",
            "pump",
            "pump_name",
            "pump_code",
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
            "description",
            "priority",
            "priority_label",
            "status",
            "status_label",
            "officer_remarks",
            "vendor_remarks",
            "sla_hours",
            "aging_hours",
            "is_overdue",
            "created_at",
            "updated_at",
            "closed_at",
            "media",
            "feedback",
            "history",
            "user_rating",
        ]
        read_only_fields = [
            "complaint_id",
            "submitted_by",
            "sales_officer",
            "status",
            "sla_hours",
            "closed_at",
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

    def create(self, validated_data):
        request = self.context["request"]
        pump = validated_data["pump"]
        if request.user.role == User.Role.CP_USER and request.user.consumer_pump:
            pump = request.user.consumer_pump
            validated_data["pump"] = pump
        category = validated_data["category"]
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


class RegistrationRequestSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    pump_name = serializers.CharField(source="consumer_pump.name", read_only=True)
    reviewed_by_name = serializers.SerializerMethodField()

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
            "admin_note",
            "created_at",
            "reviewed_at",
            "reviewed_by_name",
        ]

    def get_reviewed_by_name(self, obj):
        return obj.reviewed_by.get_full_name() if obj.reviewed_by else ""


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
