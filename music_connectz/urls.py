"""Music ConnectZ — Main URL configuration (merged).

Your existing apps, unchanged, plus the new creator apps, SkillZ training, and
DawZ voting. Safe to replace your music_connectz/urls.py with this — the first
block is identical to yours.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path('admin/', admin.site.urls),

    # ── Existing apps (unchanged) ────────────────────────────────────────
   # path('api/', include('apps.accounts.urls')),
    path('api/', include('apps.ai.urls')),
    path('api/', include('apps.profiles.urls')),
    path('api/', include('apps.personas.urls')),
    path('api/', include('apps.examples.urls')),
    path('api/', include('apps.collabs.urls')),
    path('api/', include('apps.messages.urls')),
    path('api/', include('apps.tasks.urls')),
    path('api/', include('apps.battles.urls')),
    path('api/', include('apps.transactions.urls')),
    path('api/', include('apps.mixes.urls')),
    path('api/', include('apps.releases.urls')),
    path('api/', include('apps.memberships.urls')),
    path('api/', include('apps.storage.urls')),
    path('api/', include('apps.votes.urls')),
    path('api/', include('apps.referrals.urls')),
    path('api/', include('apps.notifications.urls')),

    # ── New: creator apps ────────────────────────────────────────────────
    path('api/', include('apps.designz.urls')),        # /designz/...
    path('api/', include('apps.shotz.urls')),          # /shotz/... (+train)
    path('api/', include('apps.writez.urls')),         # /writez/... (+train)
    path('api/', include('apps.managez.urls')),        # /managez/... (18+)
    path('api/', include('apps.developz.urls')),       # /developz/...
    path('api/', include('apps.scoutz.urls')),         # /scoutz/... (A&R; 18+; minors excluded)
    path('api/', include('apps.producez.urls')),       # /producez/train/...
    path('api/', include('apps.mixez.urls')),          # /mixez/train/...

    # ── New: DawZ voting + SkillZ shared endpoints ───────────────────────
    path('api/', include('apps.dawz.urls')),           # /dawz/proposals/, /dawz/vote/
    path('api/', include('apps.skillz.urls')),         # /skillz/progress/<id>/, /skillz/capabilities/
    path('api/', include('apps.common.urls')),         # /me/age/, /age/verification-webhook/
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
