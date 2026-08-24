from maintenance.models import Complaint, ConsumerPump, District, DivisionalOffice, SalesArea, User

PASSWORD = "Pahle@123"

IBSA_OFFICERS = [
    {
        "username": "shubhnag.prasad",
        "first_name": "Shubhnag",
        "last_name": "Prasad",
        "designation": "Sales Officer, Lucknow-1 IBSA",
        "do_code": "DO-LKO",
        "do_name": "DO Lucknow",
        "area_code": "LKO-1-IBSA",
        "area_name": "Lucknow-1 IBSA",
        "zone": "Lucknow",
        "districts": ["Lucknow", "Hardoi"],
    },
    {
        "username": "sumit.tiwari",
        "first_name": "Sumit Kumar",
        "last_name": "Tiwari",
        "designation": "Sales Officer, Lucknow-2 IBSA",
        "do_code": "DO-LKO",
        "do_name": "DO Lucknow",
        "area_code": "LKO-2-IBSA",
        "area_name": "Lucknow-2 IBSA",
        "zone": "Lucknow",
        "districts": ["Unnao", "Fatehpur", "Barabanki", "Raebareli", "Sitapur"],
    },
    {
        "username": "vishal.singh",
        "first_name": "Vishal",
        "last_name": "Singh",
        "designation": "Sales Officer, Kanpur IBSA",
        "do_code": "DO-KNP",
        "do_name": "DO Kanpur",
        "area_code": "KNP-IBSA",
        "area_name": "Kanpur IBSA",
        "zone": "Kanpur",
        "districts": [
            "Kanpur Nagar",
            "Kanpur Dehat",
            "Jhansi",
            "Lalitpur",
            "Orai (Jalaun)",
            "Mahoba",
            "Hamirpur",
        ],
    },
    {
        "username": "sharad.srivastava",
        "first_name": "Sharad",
        "last_name": "Srivastava",
        "designation": "Sales Officer, Gorakhpur IBSA",
        "do_code": "DO-GKP",
        "do_name": "DO Gorakhpur",
        "area_code": "GKP-IBSA",
        "area_name": "Gorakhpur IBSA",
        "zone": "Gorakhpur",
        "districts": [
            "Gorakhpur",
            "Maharajganj",
            "Siddharthnagar",
            "Deoria",
            "Basti",
            "Sant Kabir Nagar",
            "Sravasti",
            "Bahraich",
            "Gonda",
            "Balrampur",
            "Kushinagar",
        ],
    },
]


def apply_ibsa_officers():
    created_users = []
    for spec in IBSA_OFFICERS:
        do, _ = DivisionalOffice.objects.get_or_create(code=spec["do_code"], defaults={"name": spec["do_name"]})
        if do.name != spec["do_name"]:
            do.name = spec["do_name"]
            do.save(update_fields=["name"])
        area, _ = SalesArea.objects.get_or_create(
            code=spec["area_code"],
            defaults={
                "name": spec["area_name"],
                "zone": spec["zone"],
                "divisional_office": do,
            },
        )
        area.name = spec["area_name"]
        area.zone = spec["zone"]
        area.divisional_office = do
        area.save()

        wanted = set(spec["districts"])
        for name in spec["districts"]:
            District.objects.get_or_create(sales_area=area, name=name)
        District.objects.filter(sales_area=area).exclude(name__in=wanted).delete()

        officer, created = User.objects.get_or_create(
            username=spec["username"],
            defaults={
                "first_name": spec["first_name"],
                "last_name": spec["last_name"],
                "email": f"{spec['username'].replace('.', '_')}@pahle.iocl.local",
                "role": User.Role.SALES_OFFICER,
                "designation": spec["designation"],
                "sales_area": area,
                "divisional_office": do,
                "is_staff": True,
            },
        )
        officer.first_name = spec["first_name"]
        officer.last_name = spec["last_name"]
        officer.role = User.Role.SALES_OFFICER
        officer.designation = spec["designation"]
        officer.sales_area = area
        officer.divisional_office = do
        officer.is_staff = True
        officer.is_active = True
        officer.set_password(PASSWORD)
        officer.save()

        pumps = ConsumerPump.objects.none()
        for name in spec["districts"]:
            pumps = pumps | ConsumerPump.objects.filter(city__iexact=name)
        pump_ids = list(pumps.values_list("id", flat=True))
        ConsumerPump.objects.filter(id__in=pump_ids).update(sales_area=area, sales_officer=officer)
        Complaint.objects.filter(pump_id__in=pump_ids).update(sales_officer=officer)
        created_users.append((officer, created, spec))
    return created_users
