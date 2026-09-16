"""The address every reward cap is keyed on.

Five modules each had their own copy of four lines that read
X-Forwarded-For[0]. Each proxy APPENDS, so [0] is whatever the SENDER wrote —
and every one of those five is a control that reads it:

    postz   mints 🍥 per "distinct authenticated user + IP", and says in its
            own comment that the cap stops "rotating IPs / accounts" farming
            it. Rotating IPs was one header.
    links   pays +5 ⚡ per genuine visit, capped per address per day
    adz     pays per ad view, capped per address per day
    dupez   records the address an account SIGNED UP from
    trial   gated the one free no-account take
"""
from django.test import TestCase

from .clientip import client_ip


class R:
    def __init__(self, fwd=None, remote="10.0.0.1"):
        self.META = {"REMOTE_ADDR": remote}
        if fwd is not None:
            self.META["HTTP_X_FORWARDED_FOR"] = fwd


class TheCallerCannotChooseItsOwnAddressTests(TestCase):

    def test_the_spoofed_entry_is_ignored(self):
        self.assertEqual(client_ip(R("1.2.3.4, 203.0.113.9")), "203.0.113.9")

    def test_a_long_spoofed_chain_is_still_ignored(self):
        self.assertEqual(
            client_ip(R("9.9.9.9, 8.8.8.8, 7.7.7.7, 203.0.113.9")), "203.0.113.9")

    def test_a_single_entry_is_the_proxys_own(self):
        self.assertEqual(client_ip(R("203.0.113.9")), "203.0.113.9")

    def test_no_header_falls_back_to_remote_addr(self):
        self.assertEqual(client_ip(R()), "10.0.0.1")

    def test_a_blank_header_falls_back(self):
        self.assertEqual(client_ip(R("")), "10.0.0.1")

    def test_junk_never_raises_inside_a_rate_limiter(self):
        self.assertEqual(client_ip(object()), "")
        self.assertEqual(client_ip(None), "")

    def test_it_fits_the_columns_that_store_it(self):
        self.assertLessEqual(len(client_ip(R("x" * 300))), 64)


class EverybodyReadsTheOneReaderTests(TestCase):
    """A sixth copy appearing is how this comes back."""

    def test_no_module_reads_the_header_itself(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        offenders = []
        for f in root.rglob("*.py"):
            if f.name.startswith("test_") or f.name == "clientip.py":
                continue
            if "HTTP_X_FORWARDED_FOR" in f.read_text(encoding="utf-8"):
                offenders.append(str(f.relative_to(root)))
        self.assertEqual(offenders, [],
                         "read the address through clientip.client_ip, not the header")
