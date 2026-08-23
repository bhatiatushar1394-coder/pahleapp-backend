from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send a PAHLE-APP test email via Resend to one or more real addresses."

    def add_arguments(self, parser):
        parser.add_argument("emails", nargs="+", help="Recipient email addresses")

    def handle(self, *args, **options):
        if not settings.EMAIL_HOST_PASSWORD:
            raise CommandError(
                "EMAIL_HOST_PASSWORD is not set. Add the Resend API key to the environment first."
            )
        emails = [e.strip() for e in options["emails"] if e.strip()]
        if not emails:
            raise CommandError("Pass at least one email address.")
        sent = send_mail(
            subject="PAHLE-APP: test email",
            message=(
                "This is a test from PAHLE-APP.\n\n"
                "If you received this, Resend and pahle-app.in are working.\n"
                f"Open the app: {settings.FRONTEND_URL}"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=emails,
            fail_silently=False,
        )
        self.stdout.write(self.style.SUCCESS(f"Sent {sent} test email(s) to {', '.join(emails)}"))
