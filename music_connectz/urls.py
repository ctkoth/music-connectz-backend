from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('apps.accounts.urls')),
    path('api/', include('apps.ai.urls')),
    path('api/', include('apps.profiles.urls')),
    path('api/', include('apps.personas.urls')),
    path('api/', include('apps.battles.urls')),
    path('api/', include('apps.memberships.urls')),
    path('api/', include('apps.referrals.urls')),
    path('api/', include('apps.releases.urls')),
    path('api/', include('apps.storage.urls')),
    path('api/', include('apps.tasks.urls')),
    path('api/', include('apps.transactions.urls')),
    path('api/', include('apps.votes.urls')),
    path('api/', include('apps.notifications.urls')),
    path('api/', include('apps.designz.urls')),
    path('api/', include('apps.shotz.urls')),
    path('api/', include('apps.writez.urls')),
    path('api/', include('apps.managez.urls')),
    path('api/', include('apps.developz.urls')),
    path('api/', include('apps.scoutz.urls')),
    path('api/', include('apps.producez.urls')),
    path('api/', include('apps.mixez.urls')),
    path('api/', include('apps.dawz.urls')),
    path('api/', include('apps.skillz.urls')),
    path('api/', include('apps.common.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)