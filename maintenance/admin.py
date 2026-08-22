from django.contrib import admin

from .models import (
    Complaint,
    ComplaintFeedback,
    ComplaintMedia,
    ConsumerPump,
    DivisionalOffice,
    PumpFacility,
    SalesArea,
    StatusHistory,
    User,
    Vendor,
)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("username", "email", "role", "sales_area", "is_active")
    list_filter = ("role",)


admin.site.register(DivisionalOffice)
admin.site.register(SalesArea)
admin.site.register(ConsumerPump)
admin.site.register(PumpFacility)
admin.site.register(Vendor)
admin.site.register(Complaint)
admin.site.register(ComplaintMedia)
admin.site.register(ComplaintFeedback)
admin.site.register(StatusHistory)
