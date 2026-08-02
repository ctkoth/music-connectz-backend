"""DRF exception handling for the economy's own errors.

`WalletFrozen` is raised deep inside `pay_between`, which is the choke point
every member-to-member payment goes through. That's the right place to enforce
it and the wrong place to render it — so it was reaching the client as a 500.

Handled once here rather than in each of the dozen views that move money. A
try/except per caller is a try/except somebody forgets, and the one they forget
is the one that 500s at the moment a member is already being told no.
"""
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .models import WalletFrozen
from .nextstep import wallet_on_hold


def economy_exception_handler(exc, context):
    """DRF's handler, plus the economy's own exceptions."""
    if isinstance(exc, WalletFrozen):
        return Response(wallet_on_hold(exc.wallet),
                        status=status.HTTP_403_FORBIDDEN)
    return drf_exception_handler(exc, context)
