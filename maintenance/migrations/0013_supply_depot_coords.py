from django.db import migrations
from django.db.models import Q


def set_supply_depot_coords(apps, schema_editor):
    ConsumerPump = apps.get_model("maintenance", "ConsumerPump")
    ConsumerPump.objects.filter(Q(name__icontains="Supply Depot Lucknow") | Q(pump_code="CP-LKO-01")).update(
        latitude="26.825374",
        longitude="80.950264",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("maintenance", "0012_jobcompletioncertificate"),
    ]

    operations = [
        migrations.RunPython(set_supply_depot_coords, migrations.RunPython.noop),
    ]
