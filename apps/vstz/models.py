"""What each member owns, and who can be found by it.

`Rack` is one row per member holding their plugin keys — the same shape as the
BodieZ equipment bank. A JSON list rather than a join table because it is read
whole on every profile load and never queried for one plugin in isolation; the
matching happens in `matches` below, over a set.

Nothing here executes anything. See catalog.py for why.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from . import catalog


class Rack(models.Model):
    """A member's plugin collection."""

    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name="vst_rack")
    plugins = models.JSONField(default=list, blank=True)
    # A desktop scan can fill this in later; typed-in racks stay unverified.
    # Kept separate from `plugins` so "I own Serum" and "we saw Serum on your
    # machine" are never confused — one is a claim, the other is evidence.
    scanned = models.JSONField(default=list, blank=True)
    scanned_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Rack<{self.owner_id}> {len(self.plugins)} plugins"

    def set_plugins(self, values):
        self.plugins = catalog.normalize_keys(values)
        return self.plugins

    def record_scan(self, values):
        """Results from a desktop plugin-folder scan. Everything scanned is also
        owned — finding it on disk is a stronger claim than typing it in."""
        found = catalog.normalize_keys(values)
        self.scanned = found
        self.scanned_at = timezone.now()
        merged = list(self.plugins)
        for key in found:
            if key not in merged:
                merged.append(key)
        self.plugins = merged
        return found

    @property
    def verified(self):
        """Plugins we have evidence for, not just a member's word."""
        return [k for k in self.plugins if k in set(self.scanned)]

    def payload(self, full=False):
        out = {
            "plugins": self.plugins,
            "count": len(self.plugins),
            "verified_count": len(self.verified),
            "scanned_at": self.scanned_at.isoformat() if self.scanned_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if full:
            scanned = set(self.scanned)
            out["detail"] = [
                dict(catalog.plugin_payload(k) or {"key": k}, verified=k in scanned)
                for k in self.plugins
            ]
        return out


def rack_for(user):
    rack, _ = Rack.objects.get_or_create(owner=user)
    return rack


def matches(rack_plugins, wanted, mode="all"):
    """Does this rack satisfy the request?

    `all` — they need every plugin asked for (the strict collaborator search).
    `any` — one is enough (the "can you open my session at all" search).

    An empty `wanted` matches everybody, because filtering on nothing should not
    quietly return nobody.
    """
    wanted = set(catalog.normalize_keys(wanted))
    if not wanted:
        return True
    have = set(rack_plugins or [])
    return wanted <= have if mode == "all" else bool(wanted & have)


def missing_from(rack_plugins, wanted):
    """What they'd still need — so a near-match can say what's missing rather
    than just disappearing from the results."""
    have = set(rack_plugins or [])
    return [k for k in catalog.normalize_keys(wanted) if k not in have]
