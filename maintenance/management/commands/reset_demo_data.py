from django.core.management.base import BaseCommand
from django.db import transaction

from maintenance.models import (
    Complaint,
    ConsumerPump,
    Notification,
    RegistrationRequest,
    User,
    Vendor,
)

KEEP_USERNAMES = {
    "himanshu.saxena",
    "shubhnag.prasad",
    "sumit.tiwari",
    "vishal.singh",
    "sharad.srivastava",
    "supplydepot.cp",
    "deepak.vendor",
}
KEEP_PUMP_CODE = "CP-LKO-01"


class Command(BaseCommand):
    help = "Remove demo complaints, approvals, and extra accounts. Keep Himanshu, IBSA officers, one user, one vendor."

    def add_arguments(self, parser):
        parser.add_argument("--email", default="", help="Real email for himanshu.saxena")
        parser.add_argument("--phone", default="", help="Real phone for himanshu.saxena")

    def handle(self, *args, **options):
        with transaction.atomic():
            complaints = Complaint.objects.count()
            registrations = RegistrationRequest.objects.count()
            notifications = Notification.objects.count()
            Complaint.objects.all().delete()
            Notification.objects.all().delete()
            RegistrationRequest.objects.all().delete()

            himanshu = User.objects.get(username="himanshu.saxena")
            keep_pump = ConsumerPump.objects.filter(pump_code=KEEP_PUMP_CODE).first()
            if keep_pump:
                shubhnag = User.objects.filter(username="shubhnag.prasad").first()
                keep_pump.sales_officer = shubhnag or himanshu
                keep_pump.engineering_officer = himanshu
                keep_pump.save(update_fields=["sales_officer", "engineering_officer"])
            ConsumerPump.objects.exclude(pump_code=KEEP_PUMP_CODE).delete()

            keep_vendor_user = User.objects.filter(username="deepak.vendor").first()
            Vendor.objects.exclude(user=keep_vendor_user).delete()

            extra_users = User.objects.exclude(username__in=KEEP_USERNAMES).exclude(is_superuser=True)
            removed_users = list(extra_users.values_list("username", flat=True))
            extra_users.delete()

            himanshu.role = User.Role.ADMIN
            himanshu.designation = "Admin / Sales Officer"
            himanshu.is_staff = True
            himanshu.is_active = True
            update = ["role", "designation", "is_staff", "is_active"]
            if options["email"]:
                himanshu.email = options["email"].strip()
                update.append("email")
            if options["phone"]:
                himanshu.phone = options["phone"].strip()
                update.append("phone")
            himanshu.save(update_fields=update)

        self.stdout.write(self.style.SUCCESS("Demo data cleared."))
        self.stdout.write(f"  deleted complaints={complaints} registrations={registrations} notifications={notifications}")
        self.stdout.write(f"  removed users={', '.join(removed_users) or 'none'}")
        self.stdout.write("  kept: " + ", ".join(sorted(KEEP_USERNAMES)))
        self.stdout.write(f"  himanshu email={himanshu.email} phone={himanshu.phone}")
