"""Non-invasive per-user flags. Stores the inputs to age verification and the
DERIVED age_status the gates read. 'adult' is NEVER self-asserted — it requires
adult_verified (set by your KYC webhook / admin), and 'youth' requires
parental_consent. Everything else stays 'unknown' (fail-closed).
"""
import datetime

from django.conf import settings
from django.db import models

from .agegate import AGE_ADULT, AGE_CHOICES, AGE_UNKNOWN, AGE_YOUTH


class UserFlags(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="mcz_flags")
    age_status = models.CharField(max_length=8, choices=AGE_CHOICES, default=AGE_UNKNOWN)  # derived
    dob = models.DateField(null=True, blank=True)
    adult_verified = models.BooleanField(default=False)   # set ONLY by KYC/admin
    parental_consent = models.BooleanField(default=False)  # set after guardian confirm
    stripe_session_id = models.CharField(max_length=120, blank=True, default="")  # Stripe Identity session
    updated_at = models.DateTimeField(auto_now=True)

    def age_years(self):
        if not self.dob:
            return None
        t = datetime.date.today()
        return t.year - self.dob.year - ((t.month, t.day) < (self.dob.month, self.dob.day))

    def recompute(self):
        """Derive age_status from the verified inputs. Fails closed."""
        age = self.age_years()
        if age is not None and age >= 18 and self.adult_verified:
            self.age_status = AGE_ADULT
        elif age is not None and age < 18 and self.parental_consent:
            self.age_status = AGE_YOUTH
        else:
            self.age_status = AGE_UNKNOWN
        return self.age_status

    def __str__(self):
        return f"UserFlags({self.user_id}: {self.age_status})"
