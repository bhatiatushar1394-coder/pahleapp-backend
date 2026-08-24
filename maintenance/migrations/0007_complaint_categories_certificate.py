from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("maintenance", "0006_estimation"),
    ]

    operations = [
        migrations.AlterField(
            model_name="complaint",
            name="category",
            field=models.CharField(
                choices=[
                    ("TANK", "Tank Related"),
                    ("DU", "DU related"),
                    ("CIVIL", "Civil Work"),
                    ("ELECTRICAL", "Electrical Work"),
                    ("OTHER", "Others"),
                ],
                max_length=32,
            ),
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
                ],
                max_length=32,
            ),
        ),
    ]
