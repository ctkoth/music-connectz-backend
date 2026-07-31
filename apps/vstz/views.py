from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import catalog
from .models import Rack, matches, missing_from, rack_for


class CatalogView(APIView):
    """GET the plugin catalog. Public — it's a picker, not member data."""

    permission_classes = [AllowAny]

    def get(self, request):
        payload = catalog.catalog_payload()
        kind = request.query_params.get("kind")
        price = request.query_params.get("price")
        fmt = request.query_params.get("format")
        search = (request.query_params.get("q") or "").strip().lower()

        rows = payload["plugins"]
        if kind in catalog.KIND_KEYS:
            rows = [p for p in rows if p["kind"] == kind]
        if price in catalog.PRICE_KEYS:
            rows = [p for p in rows if p["price"] == price]
        if fmt in catalog.FORMAT_KEYS:
            rows = [p for p in rows if fmt in p["formats"]]
        if search:
            rows = [p for p in rows
                    if search in p["name"].lower() or search in p["vendor"].lower()]
        payload["plugins"] = rows
        payload["filtered"] = len(rows)
        return Response(payload)


class RackView(APIView):
    """GET what you own; PUT to replace it; POST to add or remove."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(rack_for(request.user).payload(full=True))

    def put(self, request):
        rack = rack_for(request.user)
        sent = (request.data or {}).get("plugins")
        if not isinstance(sent, (list, tuple)):
            return Response({"detail": "plugins must be a list."},
                            status=status.HTTP_400_BAD_REQUEST)
        kept = rack.set_plugins(sent)
        rack.save(update_fields=["plugins", "updated_at"])
        dropped = [str(s)[:60] for s in sent
                   if catalog.normalize_key(s) is None]
        body = rack.payload(full=True)
        if dropped:
            # Say what didn't stick. Silently dropping a plugin someone typed is
            # how they end up believing their rack is set when it isn't.
            body["unrecognised"] = dropped
        return Response(body)

    def post(self, request):
        d = request.data or {}
        rack = rack_for(request.user)
        add = catalog.normalize_keys(d.get("add") or [])
        remove = set(catalog.normalize_keys(d.get("remove") or []))
        plugins = [p for p in rack.plugins if p not in remove]
        for key in add:
            if key not in plugins:
                plugins.append(key)
        rack.plugins = plugins
        rack.save(update_fields=["plugins", "updated_at"])
        return Response(rack.payload(full=True))


class ScanView(APIView):
    """POST results from a desktop plugin-folder scan.

    The web app can't produce these — only the desktop build can walk a real
    plugin folder. Kept separate from the typed-in rack so a claim and a
    verified find are never confused with each other.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        found = (request.data or {}).get("found")
        if not isinstance(found, (list, tuple)):
            return Response({"detail": "found must be a list of plugin names."},
                            status=status.HTTP_400_BAD_REQUEST)
        rack = rack_for(request.user)
        recognised = rack.record_scan(found)
        rack.save(update_fields=["plugins", "scanned", "scanned_at", "updated_at"])
        return Response({
            **rack.payload(full=True),
            "recognised": recognised,
            "unrecognised": [str(f)[:80] for f in found
                             if catalog.normalize_key(f) is None],
        })


class SearchView(APIView):
    """GET members who own the plugins you need.

    `?plugins=serum,pro-q-3&mode=all` — the collaborator search the spec asks
    for. `mode=any` widens it, and near-misses report what they're missing
    rather than vanishing, so "nobody has all three" still shows who has two.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        raw = (request.query_params.get("plugins") or "").strip()
        wanted = catalog.normalize_keys([p for p in raw.split(",") if p.strip()])
        mode = request.query_params.get("mode") or "all"
        if mode not in ("all", "any"):
            mode = "all"
        if not wanted:
            return Response({"detail": "Name at least one plugin.",
                             "plugins": []},
                            status=status.HTTP_400_BAD_REQUEST)

        rows, near = [], []
        qs = Rack.objects.select_related("owner").exclude(owner=request.user)
        for rack in qs[:2000]:
            entry = {
                "username": rack.owner.username,
                "owns": [k for k in wanted if k in set(rack.plugins)],
                "missing": missing_from(rack.plugins, wanted),
                "verified": bool(rack.scanned_at),
            }
            if matches(rack.plugins, wanted, mode=mode):
                rows.append(entry)
            elif entry["owns"]:
                near.append(entry)

        rows.sort(key=lambda r: (-len(r["owns"]), not r["verified"]))
        near.sort(key=lambda r: -len(r["owns"]))
        return Response({
            "plugins": wanted, "mode": mode,
            "matches": rows,
            # Shown separately and labelled, so a strict search that finds
            # nobody still tells you who came closest.
            "near_matches": near[:25],
        })
