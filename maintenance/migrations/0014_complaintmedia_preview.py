from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("maintenance", "0013_supply_depot_coords"),
    ]

    operations = [
        migrations.AddField(
            model_name="complaintmedia",
            name="preview",
            field=models.ImageField(blank=True, upload_to="complaints/previews/%Y/%m/"),
        ),
    ]
