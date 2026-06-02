from django.contrib import admin

from .models import (Booking, Client, Contract, Deal, Invoice, Payout,
                     RosterArtist, Task)

for m in (RosterArtist, Client, Contract, Booking, Deal, Invoice, Payout, Task):
    admin.site.register(m)
