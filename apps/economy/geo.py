"""Geocode a venue address with Google, server-side. Never raises: no key, no match, or a
failed request all return None, and the venue still saves with its address and no pin."""
import logging

import requests
from django.conf import settings

log = logging.getLogger(__name__)
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


def geocode(address):
    """(lat, lng) for an address, or None."""
    key = getattr(settings, "GOOGLE_MAPS_API_KEY", "")
    address = (address or "").strip()
    if not key or not address:
        return None
    try:
        r = requests.get(GEOCODE_URL, params={"address": address, "key": key}, timeout=5)
        data = r.json()
    except Exception:  # network, bad JSON — the venue saves regardless
        log.warning("geocode request failed")
        return None
    if data.get("status") != "OK" or not data.get("results"):
        return None
    loc = data["results"][0]["geometry"]["location"]
    return float(loc["lat"]), float(loc["lng"])
