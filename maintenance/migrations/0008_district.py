from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("maintenance", "0007_complaint_categories_certificate"),
    ]

    operations = [
        migrations.CreateModel(
            name="District",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80)),
                (
                    "sales_area",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="districts",
                        to="maintenance.salesarea",
                    ),
                ),
            ],
            options={
                "ordering": ["name"],
                "unique_together": {("sales_area", "name")},
            },
        ),
    ]
