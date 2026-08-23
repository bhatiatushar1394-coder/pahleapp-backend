from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Officer / Admin"
        SALES_OFFICER = "SALES_OFFICER", "Sales Officer"
        ENGINEERING_OFFICER = "ENGINEERING_OFFICER", "Engineering Officer"
        DO_OFFICER = "DO_OFFICER", "Divisional Office"
        CP_USER = "CP_USER", "Consumer Pump User"
        VENDOR = "VENDOR", "Vendor / Technician"

    role = models.CharField(max_length=32, choices=Role.choices, default=Role.CP_USER)
    phone = models.CharField(max_length=20, blank=True)
    sales_area = models.ForeignKey(
        "SalesArea", null=True, blank=True, on_delete=models.SET_NULL, related_name="users"
    )
    divisional_office = models.ForeignKey(
        "DivisionalOffice", null=True, blank=True, on_delete=models.SET_NULL, related_name="users"
    )
    consumer_pump = models.ForeignKey(
        "ConsumerPump", null=True, blank=True, on_delete=models.SET_NULL, related_name="portal_users"
    )

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"


class DivisionalOffice(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)

    def __str__(self):
        return self.name


class SalesArea(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    zone = models.CharField(max_length=80, blank=True)
    divisional_office = models.ForeignKey(
        DivisionalOffice, on_delete=models.CASCADE, related_name="sales_areas"
    )

    def __str__(self):
        return f"{self.code} {self.name}"


class ConsumerPump(models.Model):
    pump_code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=80)
    sales_area = models.ForeignKey(SalesArea, on_delete=models.PROTECT, related_name="pumps")
    sales_officer = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="so_pumps"
    )
    engineering_officer = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="eo_pumps"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.pump_code})"


class PumpFacility(models.Model):
    pump = models.ForeignKey(ConsumerPump, on_delete=models.CASCADE, related_name="facilities")
    label = models.CharField(max_length=120)

    def __str__(self):
        return f"{self.pump.pump_code}: {self.label}"


class Vendor(models.Model):
    class Specialization(models.TextChoices):
        ELECTRICAL = "ELECTRICAL", "Electrical Specialist"
        TANK = "TANK", "Tank Specialist"
        CIVIL = "CIVIL", "Civil Specialist"
        OTHER = "OTHER", "Other Specialist"

    name = models.CharField(max_length=200)
    specialization = models.CharField(max_length=32, choices=Specialization.choices)
    phone = models.CharField(max_length=20)
    email = models.EmailField()
    user = models.OneToOneField(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="vendor_profile"
    )
    rating = models.DecimalField(max_digits=3, decimal_places=1, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Complaint(models.Model):
    class Category(models.TextChoices):
        ELECTRICAL = "ELECTRICAL", "Electrical"
        TANK = "TANK", "Tank"
        CIVIL = "CIVIL", "Civil"
        OTHER = "OTHER", "Other"

    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High (Sales Halt Risk)"

    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted"
        ASSIGNED_TO_OFFICER = "ASSIGNED_TO_OFFICER", "Assigned to Officer"
        ASSIGNED_TO_VENDOR = "ASSIGNED_TO_VENDOR", "Assigned to Vendor"
        VENDOR_ACKNOWLEDGED = "VENDOR_ACKNOWLEDGED", "Vendor Acknowledged"
        WORK_IN_PROGRESS = "WORK_IN_PROGRESS", "Work in Progress"
        WORK_COMPLETION = "WORK_COMPLETION", "Work Completion"
        USER_CONFIRMATION = "USER_CONFIRMATION", "User Confirmation"
        CLOSED = "CLOSED", "Closed"

    complaint_id = models.CharField(max_length=32, unique=True)
    pump = models.ForeignKey(ConsumerPump, on_delete=models.PROTECT, related_name="complaints")
    submitted_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="submitted_complaints"
    )
    sales_officer = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="officer_complaints"
    )
    assigned_vendor = models.ForeignKey(
        Vendor, null=True, blank=True, on_delete=models.SET_NULL, related_name="complaints"
    )
    category = models.CharField(max_length=32, choices=Category.choices)
    specific_problem = models.CharField(max_length=200)
    description = models.TextField()
    priority = models.CharField(max_length=16, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.SUBMITTED)
    officer_remarks = models.TextField(blank=True)
    vendor_remarks = models.TextField(blank=True)
    sla_hours = models.PositiveIntegerField(default=48)
    last_reminded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.complaint_id

    @property
    def aging_hours(self):
        end = self.closed_at or timezone.now()
        return int((end - self.created_at).total_seconds() // 3600)

    @property
    def is_overdue(self):
        return self.status != self.Status.CLOSED and self.aging_hours > self.sla_hours


class ComplaintMedia(models.Model):
    class Kind(models.TextChoices):
        USER_PHOTO = "USER_PHOTO", "User Photo"
        BEFORE_PROOF = "BEFORE_PROOF", "Before Proof"
        AFTER_PROOF = "AFTER_PROOF", "After Proof"
        VIDEO = "VIDEO", "Video"

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="media")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    file = models.FileField(upload_to="complaints/%Y/%m/")
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)


class ComplaintFeedback(models.Model):
    complaint = models.OneToOneField(Complaint, on_delete=models.CASCADE, related_name="feedback")
    resolved = models.BooleanField(default=True)
    rating = models.PositiveSmallIntegerField(default=5)
    remarks = models.TextField(blank=True)
    submitted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    submitted_at = models.DateTimeField(auto_now_add=True)


class StatusHistory(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="history")
    from_status = models.CharField(max_length=32, blank=True)
    to_status = models.CharField(max_length=32)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]


class RegistrationRequest(models.Model):
    class Kind(models.TextChoices):
        CP_USER = "CP_USER", "Consumer Pump User"
        VENDOR = "VENDOR", "Vendor / Technician"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending approval"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    username = models.CharField(max_length=150)
    password_hash = models.CharField(max_length=128)
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80, blank=True)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    organization_name = models.CharField(max_length=200, blank=True)
    specialization = models.CharField(max_length=32, blank=True)
    consumer_pump = models.ForeignKey(
        ConsumerPump, null=True, blank=True, on_delete=models.SET_NULL, related_name="registration_requests"
    )
    admin_note = models.CharField(max_length=255, blank=True)
    created_user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_from_registration"
    )
    reviewed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_registrations"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.username} ({self.kind}) {self.status}"
