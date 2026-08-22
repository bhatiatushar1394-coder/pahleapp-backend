PROBLEM_MASTER = {
    "ELECTRICAL": [
        "DU Issue (Dispensing Unit failure / meter error)",
        "Servo/CVT/Battery Issue (Voltage fluctuation / backup)",
        "Canopy/Pole Light Issue (Illumination / wiring)",
        "Generator Issue (Starter failure / fuel leakage)",
    ],
    "TANK": [
        "Tank Leakage (Seepage / contamination risk)",
    ],
    "CIVIL": [
        "Kerb wall repair/Painting",
        "Shed repair/painting",
        "SOP/Signage board repair/replacement",
    ],
    "OTHER": [
        "Any other issues (Pneumatic line, air compressor, CCTV, general)",
    ],
}

SLA_HOURS = {
    "ELECTRICAL": 24,
    "TANK": 48,
    "CIVIL": 72,
    "OTHER": 48,
}

STATUS_FLOW = [
    "SUBMITTED",
    "ASSIGNED_TO_OFFICER",
    "ASSIGNED_TO_VENDOR",
    "VENDOR_ACKNOWLEDGED",
    "WORK_IN_PROGRESS",
    "WORK_COMPLETION",
    "USER_CONFIRMATION",
    "CLOSED",
]
