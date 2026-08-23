from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("maintenance", "0005_escalation_site_issue"),
    ]

    operations = [
        migrations.AddField(
            model_name="complaint",
            name="estimation_amount",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="complaint",
            name="estimation_remarks",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="complaint",
            name="estimation_review_note",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="complaint",
            name="estimation_reviewed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="complaint",
            name="estimation_reviewed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="reviewed_estimations",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="complaint",
            name="status",
            field=models.CharField(
                choices=[
                    ("SUBMITTED", "Submitted"),
                    ("ASSIGNED_TO_OFFICER", "Assigned to Officer"),
                    ("ASSIGNED_TO_VENDOR", "Assigned to Vendor"),
                    ("VENDOR_ACKNOWLEDGED", "Vendor Acknowledged"),
                    ("ESTIMATION_PENDING", "Estimation Pending Approval"),
                    ("ESTIMATION_APPROVED", "Estimation Approved"),
                    ("WORK_IN_PROGRESS", "Work in Progress"),
                    ("WORK_COMPLETION", "Work Completion"),
                    ("USER_CONFIRMATION", "User Confirmation"),
                    ("CLOSED", "Closed"),
                ],
                default="SUBMITTED",
                max_length=32,
            ),
        ),
    ]
