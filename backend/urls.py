
# --- User/AI/Payment APIs ---
path('api/user/personas/', views.user_personas, name='user_personas'),
path('api/ai/suggest-skill-prices/', views.ai_suggest_skill_prices, name='ai_suggest_skill_prices'),
path('api/user/contributor-earnings/', views.user_contributor_earnings, name='user_contributor_earnings'),
path('api/user/payment-logs/', views.user_payment_logs, name='user_payment_logs'),
# --- PayPal Webhook ---
path('api/paypal/webhook/', views.paypal_webhook, name='paypal_webhook'),
# --- Post APIs ---
path('api/posts/create-or-update/', views.create_or_update_post, name='create_or_update_post'),
path('api/posts/<int:post_id>/toggle-sharing/', views.toggle_post_sharing, name='toggle_post_sharing'),
path('api/posts/<int:post_id>/export/', views.export_post, name='export_post'),
path('api/posts/<int:post_id>/download/', views.download_post, name='download_post'),
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
    path('api/auth/google/available', views.google_available),
    path('api/auth/google/config-status/', views.google_available, name='google_config_status'),
    path('api/auth/providers/status/', views.oauth_providers_status, name='oauth_providers_status'),
    path('api/auth/users/', views.api_auth_users, name='api_auth_users'),
    path('api/auth/me/', views.api_auth_me, name='api_auth_me'),
    path('api/auth/connected-accounts/', views.api_connected_accounts, name='api_connected_accounts'),
    path('api/auth/csrf/', views.auth_csrf, name='auth_csrf'),
    path('api/auth/email/send-code/', views.send_email_verification_code, name='send_email_verification_code'),
    path('api/auth/email/verify/', views.verify_email_code, name='verify_email_code'),
    path('api/auth/phone/send-code/', views.send_phone_verification_code, name='send_phone_verification_code'),
    path('api/auth/phone/verify/', views.verify_phone_code, name='verify_phone_code'),
    path('api/auth/notifications/settings/', views.get_notification_settings, name='get_notification_settings'),
    path('api/auth/notifications/settings/update/', views.update_notification_settings, name='update_notification_settings'),
    path('api/auth/complete-profile/', views.complete_oauth_profile, name='complete_oauth_profile'),
    path('api/auth/register/', views.api_register, name='api_register'),
    path('api/login', views.api_login, name='api_login'),
    path('api/login/', views.api_login, name='api_login_slash'),
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

    # --- Distribution MVP APIs ---
    path('api/distribution/accounts/', views.list_distribution_accounts, name='list_distribution_accounts'),
    path('api/distribution/accounts/connect/', views.connect_distribution_account, name='connect_distribution_account'),
    path('api/distribution/accounts/<int:account_id>/', views.delete_distribution_account, name='delete_distribution_account'),
    path('api/distribution/releases/', views.distribution_releases, name='distribution_releases'),
    path('api/distribution/releases/<int:release_id>/', views.distribution_release_detail, name='distribution_release_detail'),
    path('api/distribution/releases/<int:release_id>/submission-fields/', views.distribution_release_submission_fields, name='distribution_release_submission_fields'),
    path('api/distribution/releases/<int:release_id>/tracks/', views.distribution_release_tracks, name='distribution_release_tracks'),
    path('api/distribution/releases/<int:release_id>/tracks/<int:track_id>/', views.distribution_release_track_detail, name='distribution_release_track_detail'),
    path('api/distribution/releases/<int:release_id>/validate/', views.validate_distribution_release, name='validate_distribution_release'),
    path('api/distribution/releases/<int:release_id>/submit/', views.submit_distribution_release, name='submit_distribution_release'),
    path('api/distribution/releases/<int:release_id>/status/', views.distribution_release_status, name='distribution_release_status'),
    path('api/distribution/releases/<int:release_id>/contributors/', views.distribution_release_contributors, name='distribution_release_contributors'),
    path('api/distribution/releases/<int:release_id>/contributors/<int:contributor_id>/', views.distribution_release_contributor_detail, name='distribution_release_contributor_detail'),
    path('api/distribution/webhooks/<str:provider>/', views.distribution_provider_webhook, name='distribution_provider_webhook'),

    # --- Distribution Analytics APIs ---
    path('api/distribution/releases/<int:release_id>/analytics/', views.release_analytics, name='release_analytics'),
    path('api/distribution/releases/<int:release_id>/tracks/<int:track_id>/analytics/', views.track_analytics, name='track_analytics'),
    path('api/distribution/releases/<int:release_id>/earnings/', views.contributor_earnings, name='contributor_earnings'),
    path('api/user/earnings/', views.user_total_earnings, name='user_total_earnings'),
    path('api/analytics/oauth-provider-profit/', views.oauth_provider_profit_analytics, name='oauth_provider_profit_analytics'),
    path('api/analytics/apple-oauth-profit-summary/', views.apple_oauth_profit_summary, name='apple_oauth_profit_summary'),

    # --- Premium Features API ---
    path('api/premium/features/', views.list_premium_features, name='list_premium_features'),
    path('api/premium/bundles/', views.list_premium_bundles, name='list_premium_bundles'),
    path('api/user/premium/', views.user_premium_features, name='user_premium_features'),
    path('api/premium/subscribe/<str:feature_key>/', views.subscribe_to_feature, name='subscribe_to_feature'),
    path('api/premium/cancel/<str:feature_key>/', views.cancel_feature_subscription, name='cancel_feature_subscription'),
    path('api/user/interests/', views.user_interests, name='user_interests'),
    path('api/marketing/weekly/generate/', views.generate_weekly_marketing_promotions, name='generate_weekly_marketing_promotions'),
    path('api/marketing/weekly/', views.my_weekly_promotions, name='my_weekly_promotions'),
    path('api/marketing/weekly/<int:promotion_id>/claim/', views.claim_weekly_promotion, name='claim_weekly_promotion'),
    path('api/marketing/in-app-ads/', views.in_app_feature_ads, name='in_app_feature_ads'),
    # --- Reliability Rating & Review APIs ---
    path('api/collab/<int:agreement_id>/reliability/<int:ratee_id>/', views.set_reliability_rating, name='set_reliability_rating'),
    path('api/collab/<int:agreement_id>/reliability/', views.get_reliability_ratings, name='get_reliability_ratings'),
    path('api/collab/<int:agreement_id>/review/<int:reviewee_id>/', views.set_collab_review, name='set_collab_review'),
    path('api/collab/<int:agreement_id>/reviews/', views.get_collab_reviews, name='get_collab_reviews'),
    path('api/user/<int:user_id>/shared-reviews/', views.get_shared_reviews_for_user, name='get_shared_reviews_for_user'),
]
