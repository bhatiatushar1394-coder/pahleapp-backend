import re
from decimal import Decimal, InvalidOperation
from urllib.parse import quote_plus

COORD_RE = re.compile(
    r"@(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)"
    r"|(-?\d+(?:\.\d+)?)\s*[,/\s]\s*(-?\d+(?:\.\d+)?)"
)

# Exact pins so Google Maps opens the point, not a text search.
KNOWN_MAP_PINS = {
    "supply depot lucknow": (Decimal("26.825374"), Decimal("80.950264")),
}


def parse_coordinates(raw="", latitude=None, longitude=None):
    lat = lng = None
    if latitude not in (None, "") and longitude not in (None, ""):
        try:
            lat = Decimal(str(latitude))
            lng = Decimal(str(longitude))
        except (InvalidOperation, ValueError, TypeError):
            lat = lng = None
    if lat is None:
        text = (raw or "").strip()
        if not text:
            return None
        match = COORD_RE.search(text)
        if not match:
            return None
        lat = Decimal(match.group(1) or match.group(3))
        lng = Decimal(match.group(2) or match.group(4))
    if lat < Decimal("-90") or lat > Decimal("90") or lng < Decimal("-180") or lng > Decimal("180"):
        return None
    quant = Decimal("0.0000001")
    return lat.quantize(quant), lng.quantize(quant)


def _known_pin(*place_parts):
    blob = " ".join(str(part).strip() for part in place_parts if part and str(part).strip()).lower()
    for key, coords in KNOWN_MAP_PINS.items():
        if key in blob:
            return coords
    return None


def google_maps_url(latitude=None, longitude=None, *place_parts):
    """Open the exact map pin. Never fall back to a place-name search when a pin is known."""
    parsed = parse_coordinates(latitude=latitude, longitude=longitude)
    if not parsed:
        parsed = _known_pin(*place_parts)
    if parsed:
        lat = f"{float(parsed[0]):.6f}"
        lng = f"{float(parsed[1]):.6f}"
        return (
            f"https://www.google.com/maps/place/{lat},{lng}"
            f"/@{lat},{lng},17z/data=!3m1!4b1!4m4!3m3!8m2!3d{lat}!4d{lng}"
        )
    query = " ".join(str(part).strip() for part in place_parts if part and str(part).strip())
    if not query:
        return ""
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}"
