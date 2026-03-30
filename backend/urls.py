"""
URL configuration for backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView, TemplateView
from django.views.static import serve
from django.conf import settings
from . import views

_FRONTEND_ERROR_URL = 'https://musicconnectz.net/?login_error=1'

urlpatterns = [
    path('', views.home, name='home'),
    path('admin/', admin.site.urls),
    path('google70f5d8bcf10dfb1c.html', serve, {'path': 'google70f5d8bcf10dfb1c.html', 'document_root': settings.STATIC_ROOT}),
    path('api/openai-chat', views.openai_chat, name='openai_chat'),
    path(
        'accounts/3rdparty/login/error/',
        RedirectView.as_view(url=_FRONTEND_ERROR_URL, permanent=False),
        name='thirdparty_login_error',
    ),
    path(
        'accounts/social/login/error/',
        RedirectView.as_view(url=_FRONTEND_ERROR_URL, permanent=False),
        name='socialaccount_login_error',
    ),
    path('accounts/', include('allauth.urls')),
    path('upload/', views.upload_work, name='upload_work'),
    path('api/auth/google/available', views.google_available),
    path('api/auth/google/config-status/', views.google_available, name='google_config_status'),
    path('api/auth/providers/status/', views.oauth_providers_status, name='oauth_providers_status'),
    path('api/auth/me/', views.api_auth_me, name='api_auth_me'),
    path('api/auth/register/', views.api_register, name='api_register'),
    path('api/referral/stats/', views.referral_stats, name='referral_stats'),
    path('api/auth/register-with-referral/', views.register_with_referral, name='register_with_referral'),
    path('api/royalty-agreement/<int:agreement_id>/download/', views.download_royalty_agreement_pdf, name='download_royalty_agreement_pdf'),
    path('api/agreement-templates/', views.list_agreement_templates, name='list_agreement_templates'),
    path('api/agreement-templates/create/', views.create_agreement_template, name='create_agreement_template'),
    path('api/royalty-agreement/<int:agreement_id>/new-version/', views.create_agreement_version, name='create_agreement_version'),
    path('api/royalty-split/<int:split_id>/sign/', views.sign_royalty_split, name='sign_royalty_split'),
    path('api/royalty-agreement/<int:agreement_id>/history/', views.agreement_change_history, name='agreement_change_history'),
    path('api/royalty-agreement/<int:agreement_id>/export/json/', views.export_agreement_json, name='export_agreement_json'),
    path('api/royalty-agreement/<int:agreement_id>/export/csv/', views.export_agreement_csv, name='export_agreement_csv'),
    path('api/royalty-agreement/<int:agreement_id>/reminder/', views.send_agreement_reminder, name='send_agreement_reminder'),
    path('api/analytics/site/', views.site_analytics, name='site_analytics'),
    path('api/create-subscription-checkout', views.create_subscription_checkout, name='create_subscription_checkout'),
    path('api/create-purchase-checkout', views.create_purchase_checkout, name='create_purchase_checkout'),
    path('api/cancel-subscription', views.cancel_subscription, name='cancel_subscription'),
    path('api/use-collaboration-request', views.use_collaboration_request, name='use_collaboration_request'),

    # --- Reliability Rating & Review APIs ---
    path('api/collab/<int:agreement_id>/reliability/<int:ratee_id>/', views.set_reliability_rating, name='set_reliability_rating'),
    path('api/collab/<int:agreement_id>/reliability/', views.get_reliability_ratings, name='get_reliability_ratings'),
    path('api/collab/<int:agreement_id>/review/<int:reviewee_id>/', views.set_collab_review, name='set_collab_review'),
    path('api/collab/<int:agreement_id>/reviews/', views.get_collab_reviews, name='get_collab_reviews'),
    path('api/user/<int:user_id>/shared-reviews/', views.get_shared_reviews_for_user, name='get_shared_reviews_for_user'),
]
