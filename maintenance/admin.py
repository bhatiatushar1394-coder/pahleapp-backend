from django.contrib import admin

from .models import (
    Complaint,
    ComplaintFeedback,
    ComplaintMedia,
    ConsumerPump,
    District,
    DivisionalOffice,
    PumpFacility,
    SalesArea,
    StatusHistory,
    User,
    Vendor,
    RegistrationRequest,
    Notification,
    VendorSiteIssue,
    JobCompletionCertificate,
)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("username", "email", "role", "phone", "sales_area", "is_active")
    list_filter = ("role",)


admin.site.register(DivisionalOffice)
admin.site.register(SalesArea)
admin.site.register(District)
admin.site.register(ConsumerPump)
admin.site.register(PumpFacility)
admin.site.register(Vendor)
admin.site.register(Complaint)
admin.site.register(ComplaintMedia)
admin.site.register(ComplaintFeedback)
admin.site.register(VendorSiteIssue)
admin.site.register(JobCompletionCertificate)
admin.site.register(StatusHistory)
admin.site.register(RegistrationRequest)
admin.site.register(Notification)
