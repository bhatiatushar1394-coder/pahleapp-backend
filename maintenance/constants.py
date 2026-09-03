PROBLEM_MASTER = {
    "TANK": [
        "Water Ingress",
        "Tank Leakage",
        "Vent Pipe Issue",
        "Fill Pipe Issue",
    ],
    "DU": [
        "Hose Pipe",
        "Nozzle Issue",
        "Keypad Problem",
        "Electronics Parts Issue",
        "Display Problem",
    ],
    "CIVIL": [
        "Painting Work",
        "Brickwork",
        "Structural Work",
        "Canopy Related",
    ],
    "ELECTRICAL": [
        "Replacement of Servo",
        "Replacement of CVT",
        "Cable Related",
    ],
    "OTHER": [],
}

SLA_HOURS = {
    "TANK": 48,
    "DU": 24,
    "CIVIL": 72,
    "ELECTRICAL": 24,
    "OTHER": 48,
}

STATUS_FLOW = [
    "SUBMITTED",
    "ASSIGNED_TO_OFFICER",
    "ASSIGNED_TO_VENDOR",
    "VENDOR_ACKNOWLEDGED",
    "ESTIMATION_PENDING",
    "WORK_IN_PROGRESS",
    "WORK_COMPLETION",
    "USER_CONFIRMATION",
    "CLOSED",
]


def subtypes_for(category):
    return list(PROBLEM_MASTER.get(category) or [])


def match_subtype(category, *texts):
    allowed = subtypes_for(category)
    if not allowed:
        return "Others"
    blob = " ".join((t or "").strip() for t in texts).lower()
    for item in allowed:
        if item.lower() in blob or blob == item.lower():
            return item
    return ""


def normalize_subtype(category, value, existing=""):
    """Return a stored sub-category, or raise ValueError if a mapped type is missing one."""
    allowed = subtypes_for(category)
    value = (value or "").strip()
    existing = (existing or "").strip()
    if not allowed:
        return value or "Others"
    if value in allowed:
        return value
    matched = match_subtype(category, value)
    if matched:
        return matched
    if existing and (not value or value == existing):
        return existing
    raise ValueError("Select a sub-category for this task type.")
