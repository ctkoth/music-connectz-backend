from django.test import SimpleTestCase

from . import catalog as C


class CleanModesTests(SimpleTestCase):
    def test_it_says_how_much_never_whether(self):
        n = {t: C.limits_for(t)["clean_modes"] for t in ("free", "premium", "statz")}
        self.assertEqual(n, {"free": 1, "premium": 2, "statz": None})      # None = all three ways
        self.assertGreaterEqual(n["free"], 1)                              # nobody is shut out of Clean ConnectZ
