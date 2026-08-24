from django.core.management.base import BaseCommand

from maintenance.ibsa import PASSWORD, apply_ibsa_officers


class Command(BaseCommand):
    help = "Create IBSA sales officers, areas, and district mapping without wiping other data."

    def handle(self, *args, **options):
        rows = apply_ibsa_officers()
        self.stdout.write(self.style.SUCCESS("IBSA officers ready. Password for all: " + PASSWORD))
        for officer, created, spec in rows:
            action = "created" if created else "updated"
            districts = ", ".join(spec["districts"])
            self.stdout.write(
                f"  {action}: {officer.get_full_name()}  {officer.username}  {spec['area_name']}  [{districts}]"
            )
