from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Officer / Admin"
        SALES_OFFICER = "SALES_OFFICER", "Sales Officer"
        ENGINEERING_OFFICER = "ENGINEERING_OFFICER", "Engineering Officer"
        DO_OFFICER = "DO_OFFICER", "Divisional Office"
        CP_USER = "CP_USER", "Customer"
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
    designation = models.CharField(max_length=120, blank=True)
    employee_code = models.CharField(max_length=40, blank=True)
    bio = models.TextField(blank=True)
    avatar = models.ImageField(upload_to="avatars/%Y/%m/", blank=True)

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


class District(models.Model):
    name = models.CharField(max_length=80)
    sales_area = models.ForeignKey(SalesArea, on_delete=models.CASCADE, related_name="districts")

    class Meta:
        ordering = ["name"]
        unique_together = ("sales_area", "name")

    def __str__(self):
        return f"{self.name} ({self.sales_area.code})"


class ConsumerPump(models.Model):
    class AmcType(models.TextChoices):
        AMC = "AMC", "AMC"
        NON_AMC = "NON_AMC", "Non AMC"

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
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    amc_type = models.CharField(max_length=16, choices=AmcType.choices, blank=True)
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
        TANK = "TANK", "Tank Related"
        DU = "DU", "DU related"
        CIVIL = "CIVIL", "Civil Work"
        ELECTRICAL = "ELECTRICAL", "Electrical Work"
        OTHER = "OTHER", "Others"

    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High (Sales Halt Risk)"

    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted"
        ASSIGNED_TO_OFFICER = "ASSIGNED_TO_OFFICER", "Assigned to Officer"
        ASSIGNED_TO_VENDOR = "ASSIGNED_TO_VENDOR", "Assigned to Vendor"
        VENDOR_ACKNOWLEDGED = "VENDOR_ACKNOWLEDGED", "Vendor Acknowledged"
        ESTIMATION_PENDING = "ESTIMATION_PENDING", "Estimation Pending Approval"
        ESTIMATION_APPROVED = "ESTIMATION_APPROVED", "Estimation Approved"
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
    du_make = models.CharField(max_length=80, blank=True)
    du_model = models.CharField(max_length=80, blank=True)
    du_serial = models.CharField(max_length=80, blank=True)
    description = models.TextField()
    priority = models.CharField(max_length=16, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.SUBMITTED)
    officer_remarks = models.TextField(blank=True)
    vendor_remarks = models.TextField(blank=True)
    estimation_remarks = models.TextField(blank=True)
    estimation_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    estimation_reviewed_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_estimations",
    )
    estimation_reviewed_at = models.DateTimeField(null=True, blank=True)
    estimation_review_note = models.TextField(blank=True)
    po_number = models.CharField("PO number", max_length=64, blank=True)
    sla_hours = models.PositiveIntegerField(default=48)
    last_reminded_at = models.DateTimeField(null=True, blank=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    escalation_note = models.TextField(blank=True)
    escalation_count = models.PositiveSmallIntegerField(default=0)
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
    def aging_days(self):
        allotted = None
        for row in self.history.all():
            if row.to_status != self.Status.ASSIGNED_TO_VENDOR:
                continue
            if allotted is None or row.created_at < allotted:
                allotted = row.created_at
        if allotted is None:
            return None
        end = timezone.localtime(self.closed_at or timezone.now()).date()
        start = timezone.localtime(allotted).date()
        return max(0, (end - start).days)

    @property
    def is_overdue(self):
        return self.status != self.Status.CLOSED and self.aging_hours > self.sla_hours


class ComplaintMedia(models.Model):
    class Kind(models.TextChoices):
        USER_PHOTO = "USER_PHOTO", "User Photo"
        BEFORE_PROOF = "BEFORE_PROOF", "Before Proof"
        AFTER_PROOF = "AFTER_PROOF", "After Proof"
        CERTIFICATE = "CERTIFICATE", "Work Completion Certificate"
        VIDEO = "VIDEO", "Video"
        QUOTATION = "QUOTATION", "Vendor Quotation"

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="media")
    kind = models.CharField(max_length=32, choices=Kind.choices)
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


class JobCompletionCertificate(models.Model):
    class Stage(models.TextChoices):
        VENDOR_DRAFT = "VENDOR_DRAFT", "Vendor filled the form"
        CUSTOMER_SIGNED = "CUSTOMER_SIGNED", "Customer signed"
        BILL_SUBMITTED = "BILL_SUBMITTED", "Officer submitted the bill"

    complaint = models.OneToOneField(Complaint, on_delete=models.CASCADE, related_name="job_certificate")
    stage = models.CharField(max_length=32, choices=Stage.choices, default=Stage.VENDOR_DRAFT)
    certificate_date = models.DateField()
    vendor_name = models.CharField(max_length=200)
    vendor_address = models.TextField(blank=True)
    nature_of_job = models.CharField(max_length=255)
    customer_name = models.CharField(max_length=200)
    job_completion_date = models.DateField()
    work_satisfactory = models.BooleanField(default=True)
    signature = models.ImageField(upload_to="certificates/signatures/%Y/%m/", blank=True)
    uploaded_pdf = models.FileField(upload_to="certificates/uploads/%Y/%m/", blank=True)
    generated_pdf = models.FileField(upload_to="certificates/generated/%Y/%m/", blank=True)
    prepared_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="prepared_certificates"
    )
    prepared_at = models.DateTimeField(null=True, blank=True)
    signed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="signed_certificates"
    )
    signed_at = models.DateTimeField(null=True, blank=True)
    bill_submitted_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="billed_certificates"
    )
    bill_submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.complaint.complaint_id} certificate ({self.stage})"


class VendorSiteIssue(models.Model):
    class Kind(models.TextChoices):
        ACCESS = "ACCESS", "Site access / permission blocked"
        SAFETY = "SAFETY", "Safety or shutdown risk"
        PARTS = "PARTS", "Parts / material not available"
        EXTRA_WORK = "EXTRA_WORK", "Additional damage found on site"
        CUSTOMER_UNAVAILABLE = "CUSTOMER_UNAVAILABLE", "Customer / site contact unavailable"
        OTHER = "OTHER", "Other site problem"

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="site_issues")
    reported_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="site_issues")
    kind = models.CharField(max_length=32, choices=Kind.choices)
    description = models.TextField()
    photo = models.ImageField(upload_to="site_issues/%Y/%m/", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.complaint.complaint_id}: {self.get_kind_display()}"


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
        CP_USER = "CP_USER", "Customer"
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
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    amc_type = models.CharField(max_length=16, blank=True)
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


class Notification(models.Model):
    class Kind(models.TextChoices):
        NEW_COMPLAINT = "NEW_COMPLAINT", "New complaint"
        ASSIGN_VENDOR = "ASSIGN_VENDOR", "Assign vendor"
        VENDOR_ASSIGNED = "VENDOR_ASSIGNED", "Assigned to vendor"
        STATUS = "STATUS", "Status update"
        REGISTRATION = "REGISTRATION", "Registration"
        ESCALATION = "ESCALATION", "User escalation"
        SITE_ISSUE = "SITE_ISSUE", "Vendor site issue"

    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=32, choices=Kind.choices)
    title = models.CharField(max_length=180)
    body = models.CharField(max_length=400, blank=True)
    link = models.CharField(max_length=255, blank=True)
    complaint = models.ForeignKey(
        Complaint, null=True, blank=True, on_delete=models.CASCADE, related_name="notifications"
    )
    registration = models.ForeignKey(
        RegistrationRequest, null=True, blank=True, on_delete=models.CASCADE, related_name="notifications"
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "is_read", "-created_at"])]

    def __str__(self):
        return f"{self.recipient_id}: {self.title}"


class StoredFile(models.Model):
    path = models.CharField(max_length=255, unique=True)
    data = models.BinaryField()
    content_type = models.CharField(max_length=100, default="application/octet-stream")
    size = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.path
