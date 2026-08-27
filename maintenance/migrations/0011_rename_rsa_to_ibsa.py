from django.db import migrations


def rename_rsa_to_ibsa(apps, schema_editor):
    SalesArea = apps.get_model("maintenance", "SalesArea")
    for area in SalesArea.objects.all():
        fields = []
        if area.name and "RSA" in area.name:
            area.name = area.name.replace("RSA", "IBSA")
            fields.append("name")
        if area.code and "RSA" in area.code:
            area.code = area.code.replace("RSA", "IBSA")
            fields.append("code")
        if fields:
            area.save(update_fields=fields)


class Migration(migrations.Migration):

    dependencies = [
        ("maintenance", "0010_quotation_po_number"),
    ]

    operations = [
        migrations.RunPython(rename_rsa_to_ibsa, migrations.RunPython.noop),
    ]
