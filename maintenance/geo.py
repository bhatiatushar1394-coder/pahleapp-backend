import re
from decimal import Decimal, InvalidOperation
from urllib.parse import quote_plus

COORD_RE = re.compile(
    r"@(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)"
    r"|(-?\d+(?:\.\d+)?)\s*[,/\s]\s*(-?\d+(?:\.\d+)?)"
)


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


def google_maps_url(latitude=None, longitude=None, *place_parts):
    """Pin by coordinates when present; otherwise search Google Maps by address."""
    if latitude is not None and longitude is not None:
        return f"https://www.google.com/maps?q={latitude},{longitude}"
    query = " ".join(str(part).strip() for part in place_parts if part and str(part).strip())
    if not query:
        return ""
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}"
