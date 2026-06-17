from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static


def try_include(prefix, module):
    try:
        return path(prefix, include(module))
    except ModuleNotFoundError:
        return None


urlpatterns = [
    path('admin/', admin.site.urls),
]

safe_apps = [
    ('api/accounts/',     'apps.accounts.urls'),
    ('api/ai/',           'apps.ai.urls'),
    ('api/analytics/',    'apps.analytics.urls'),
    ('api/battles/',      'apps.battles.urls'),
    ('api/collabs/',      'apps.collabs.urls'),
    ('api/common/',       'apps.common.urls'),
    ('api/dawz/',         'apps.dawz.urls'),
    ('api/designz/',      'apps.designz.urls'),
    # ('api/direct/',     'apps.direct.urls'),  # commented out in INSTALLED_APPS
    ('api/events/',       'apps.events.urls'),
    ('api/managez/',      'apps.managez.urls'),
    ('api/memberships/',  'apps.memberships.urls'),
    ('api/messages/',     'apps.messages.urls'),
    ('api/mixez/',        'apps.mixez.urls'),
    ('api/notifications/','apps.notifications.urls'),
    ('api/payments/',     'apps.payments.urls'),
    ('api/personas/',     'apps.personas.urls'),
    ('api/producez/',     'apps.producez.urls'),
    ('api/profiles/',     'apps.profiles.urls'),
    ('api/referrals/',    'apps.referrals.urls'),
    ('api/releases/',     'apps.releases.urls'),
    ('api/scoutz/',       'apps.scoutz.urls'),
    ('api/search/',       'apps.search.urls'),
    ('api/shotz/',        'apps.shotz.urls'),
    ('api/skillz/',       'apps.skillz.urls'),
    ('api/storage/',      'apps.storage.urls'),
    ('api/subscriptions/','apps.subscriptions.urls'),
    ('api/tasks/',        'apps.tasks.urls'),
    ('api/transactions/', 'apps.transactions.urls'),
    ('api/video/',        'apps.video.urls'),
    ('api/votes/',        'apps.votes.urls'),
    ('api/writez/',       'apps.writez.urls'),
]

for prefix, module in safe_apps:
    result = try_include(prefix, module)
    if result:
        urlpatterns.append(result)

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)