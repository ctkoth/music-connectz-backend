from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

def try_include(module):
    try:
        return include(module)
    except ModuleNotFoundError:
        return None

urlpatterns = [
    path('admin/', admin.site.urls),
]

safe_apps = [
    'apps.accounts.urls',
    'apps.ai.urls',
    'apps.profiles.urls',
    'apps.personas.urls',
    'apps.memberships.urls',
    'apps.referrals.urls',
    'apps.notifications.urls',
    'apps.designz.urls',
    'apps.shotz.urls',
    'apps.writez.urls',
    'apps.search.urls',
    'apps.events.urls',
    'apps.direct.urls',
    'apps.video.urls',
    'apps.storage.urls',
    'apps.tasks.urls',
    'apps.transactions.urls',
    'apps.votes.urls',
    'apps.analytics.urls',
]

for app_urls in safe_apps:
    result = try_include(app_urls)
    if result:
        urlpatterns.append(path('api/', result))

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)