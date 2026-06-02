from django.contrib import admin
from .models import Prospect, ScoutingReport, Task
for m in (Prospect, ScoutingReport, Task):
    admin.site.register(m)
