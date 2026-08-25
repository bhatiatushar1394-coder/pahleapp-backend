from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("maintenance", "0009_du_amc_coords_storedfile"),
    ]

    operations = [
        migrations.AddField(
            model_name="complaint",
            name="po_number",
            field=models.CharField(blank=True, max_length=64, verbose_name="PO number"),
        ),
        migrations.AlterField(
            model_name="complaintmedia",
            name="kind",
            field=models.CharField(
                choices=[
                    ("USER_PHOTO", "User Photo"),
                    ("BEFORE_PROOF", "Before Proof"),
                    ("AFTER_PROOF", "After Proof"),
                    ("CERTIFICATE", "Work Completion Certificate"),
                    ("VIDEO", "Video"),
                    ("QUOTATION", "Vendor Quotation"),
                ],
                max_length=32,
            ),
        ),
    ]
