import os
import requests

from allauth.socialaccount.models import SocialApp
from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import SiteAnalytics, VisitorRecord
from .serializers import RegisterSerializer

# API endpoint for user registration
@api_view(['POST'])
@permission_classes([AllowAny])
def api_register(request):
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response({"success": "User registered successfully."}, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
from django.http import JsonResponse


def api_auth_me(request):
    user = getattr(request, 'user', None)
    if user and user.is_authenticated:
        return JsonResponse({
            'authenticated': True,
            'user': {
                'id': user.id,
                'email': getattr(user, 'email', '') or '',
                'username': getattr(user, 'username', '') or '',
            }
        })
    return JsonResponse({'authenticated': False}, status=401)


def google_available(request):
    env_client_id_set = bool(os.getenv('GOOGLE_CLIENT_ID'))
    env_client_secret_set = bool(os.getenv('GOOGLE_CLIENT_SECRET'))
    social_app = SocialApp.objects.filter(provider='google').first()
    db_socialapp_set = bool(social_app and social_app.client_id and social_app.secret)

    return JsonResponse({
        "available": env_client_id_set and env_client_secret_set or db_socialapp_set,
        "env_client_id_set": env_client_id_set,
        "env_client_secret_set": env_client_secret_set,
        "db_socialapp_set": db_socialapp_set,
    })


def oauth_providers_status(request):
    provider_map = {
        'apple': 'apple',
        'microsoft': 'microsoft',
        'facebook': 'facebook',
        'twitter': 'twitter_oauth2',
        'linkedin': 'linkedin_oauth2',
        'github': 'github',
        'google': 'google',
        'spotify': 'spotify',
        'soundcloud': 'soundcloud',
    }

    providers = {}
    for frontend_provider, allauth_provider in provider_map.items():
        app = SocialApp.objects.filter(provider=allauth_provider).order_by('id').first()
        providers[frontend_provider] = bool(app and app.client_id and app.secret)

    return JsonResponse({
        'providers': providers,
        'any_available': any(providers.values()),
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def site_analytics(request):
    visitor_key = (request.GET.get('visitor_key') or '').strip()[:128]

    with transaction.atomic():
        analytics, _ = SiteAnalytics.objects.select_for_update().get_or_create(
            key='global',
            defaults={'total_visits': 0, 'unique_visitors': 0},
        )

        is_new_visitor = False
        if visitor_key:
            visitor, created = VisitorRecord.objects.get_or_create(
                visitor_key=visitor_key,
                defaults={'visit_count': 1},
            )
            is_new_visitor = created
            if not created:
                visitor.visit_count += 1
                visitor.save(update_fields=['visit_count', 'last_seen_at'])

        analytics.total_visits += 1
        if is_new_visitor:
            analytics.unique_visitors += 1
        analytics.save(update_fields=['total_visits', 'unique_visitors', 'updated_at'])

    return Response({
        'totalVisits': analytics.total_visits,
        'uniqueVisitors': analytics.unique_visitors,
    })


def _frontend_url():
    return os.environ.get('FRONTEND_URL', 'https://musicconnectz.net').rstrip('/')


def _stripe_secret_key():
    return os.environ.get('STRIPE_SECRET_KEY', '').strip()


def _stripe_headers():
    return {
        'Authorization': f'Bearer {_stripe_secret_key()}',
        'Content-Type': 'application/x-www-form-urlencoded',
    }


def _stripe_checkout_base_payload():
    frontend_url = _frontend_url()
    success_url = os.environ.get('STRIPE_SUCCESS_URL', f'{frontend_url}/?checkout=success')
    cancel_url = os.environ.get('STRIPE_CANCEL_URL', f'{frontend_url}/?checkout=cancel')
    return {
        'success_url': success_url,
        'cancel_url': cancel_url,
    }


def _default_payment_method_types():
    # Prioritize widely used global/local methods for Checkout payments.
    return [
        'card',
        'link',
        'paypal',
        'us_bank_account',
        'cashapp',
        'affirm',
        'afterpay_clearpay',
        'klarna',
        'amazon_pay',
        'revolut_pay',
        'alipay',
        'wechat_pay',
        'ideal',
        'bancontact',
        'eps',
        'p24',
        'sofort',
        'sepa_debit',
        'acss_debit',
        'bacs_debit',
    ]


def _stripe_payment_method_types():
    raw = os.environ.get('STRIPE_PAYMENT_METHOD_TYPES', '').strip()
    if not raw:
        return _default_payment_method_types()
    return [item.strip() for item in raw.split(',') if item.strip()]


def _add_payment_method_types(payload, methods):
    for idx, method in enumerate(methods):
        payload[f'payment_method_types[{idx}]'] = method


def _create_stripe_checkout_session(checkout_payload):
    stripe_res = requests.post(
        'https://api.stripe.com/v1/checkout/sessions',
        data=checkout_payload,
        headers=_stripe_headers(),
        timeout=30,
    )
    data = stripe_res.json()
    return stripe_res, data


def _resolve_subscription_price_id(requested_price_id, billing_period):
    # Frontend currently sends placeholders; allow backend env vars to override.
    if requested_price_id and not requested_price_id.startswith('price_premium_'):
        return requested_price_id

    period = (billing_period or '').lower()
    if period == 'yearly':
        return os.environ.get('STRIPE_PREMIUM_YEARLY_PRICE_ID', '').strip()
    return os.environ.get('STRIPE_PREMIUM_MONTHLY_PRICE_ID', '').strip()


@api_view(['POST'])
@permission_classes([AllowAny])
def create_subscription_checkout(request):
    if not _stripe_secret_key():
        return Response({'error': 'Stripe is not configured on the backend.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    payload = request.data if isinstance(request.data, dict) else {}
    billing_period = payload.get('billingPeriod', 'monthly')
    price_id = _resolve_subscription_price_id(payload.get('priceId'), billing_period)
    if not price_id:
        return Response({'error': 'Missing Stripe subscription price ID.'}, status=status.HTTP_400_BAD_REQUEST)

    checkout_payload = _stripe_checkout_base_payload()
    checkout_payload.update({
        'mode': 'subscription',
        'line_items[0][price]': price_id,
        'line_items[0][quantity]': '1',
        'automatic_tax[enabled]': 'true',
        'billing_address_collection': 'required',
        'tax_id_collection[enabled]': 'true',
        'client_reference_id': str(payload.get('userId', '')),
        'metadata[userId]': str(payload.get('userId', '')),
        'metadata[billingPeriod]': str(billing_period),
    })

    stripe_res, data = _create_stripe_checkout_session(checkout_payload)
    if stripe_res.status_code >= 400:
        return Response({'error': data.get('error', {}).get('message', 'Stripe checkout creation failed.')}, status=stripe_res.status_code)

    return Response({'url': data.get('url'), 'id': data.get('id')})


@api_view(['POST'])
@permission_classes([AllowAny])
def create_purchase_checkout(request):
    if not _stripe_secret_key():
        return Response({'error': 'Stripe is not configured on the backend.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    payload = request.data if isinstance(request.data, dict) else {}
    amount = payload.get('amount')
    try:
        amount_cents = int(round(float(amount) * 100))
    except Exception:
        return Response({'error': 'Invalid purchase amount.'}, status=status.HTTP_400_BAD_REQUEST)

    if amount_cents <= 0:
        return Response({'error': 'Amount must be greater than zero.'}, status=status.HTTP_400_BAD_REQUEST)

    description = str(payload.get('description') or 'Music ConnectZ Purchase')
    purchase_type = str(payload.get('purchaseType') or 'one_time')

    checkout_payload = _stripe_checkout_base_payload()
    checkout_payload.update({
        'mode': 'payment',
        'line_items[0][price_data][currency]': 'usd',
        'line_items[0][price_data][tax_behavior]': 'exclusive',
        'line_items[0][price_data][unit_amount]': str(amount_cents),
        'line_items[0][price_data][product_data][name]': description,
        'line_items[0][quantity]': '1',
        'automatic_tax[enabled]': 'true',
        'billing_address_collection': 'required',
        'tax_id_collection[enabled]': 'true',
        'customer_creation': 'always',
        'client_reference_id': str(payload.get('userId', '')),
        'metadata[userId]': str(payload.get('userId', '')),
        'metadata[purchaseType]': purchase_type,
    })

    _add_payment_method_types(checkout_payload, _stripe_payment_method_types())

    stripe_res, data = _create_stripe_checkout_session(checkout_payload)
    if stripe_res.status_code >= 400:
        # Fallback: if the account does not support one of the configured methods,
        # retry with universally-supported methods.
        checkout_payload = dict(checkout_payload)
        keys_to_remove = [k for k in checkout_payload.keys() if k.startswith('payment_method_types[')]
        for key in keys_to_remove:
            checkout_payload.pop(key, None)
        checkout_payload['payment_method_types[0]'] = 'card'
        checkout_payload['payment_method_types[1]'] = 'link'
        stripe_res, data = _create_stripe_checkout_session(checkout_payload)

    if stripe_res.status_code >= 400:
        return Response({'error': data.get('error', {}).get('message', 'Stripe checkout creation failed.')}, status=stripe_res.status_code)

    return Response({'url': data.get('url'), 'id': data.get('id')})


@api_view(['POST'])
@permission_classes([AllowAny])
def cancel_subscription(request):
    # Frontend expects an OK response. Full Stripe subscription cancellation
    # requires persisted subscription IDs, which are not yet stored.
    return Response({'ok': True, 'message': 'Cancellation request acknowledged.'})


@api_view(['POST'])
@permission_classes([AllowAny])
def use_collaboration_request(request):
    # Temporary permissive implementation until per-user quota persistence is added.
    return Response({'ok': True, 'remaining': -1})

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .forms import WorkForm
from .models import Work

def home(request):
    return render(request, "home.html")


@login_required
def upload_work(request):
    if request.method == 'POST':
        form = WorkForm(request.POST, request.FILES)
        if form.is_valid():
            work = form.save(commit=False)
            work.uploaded_by = request.user
            work.save()
            return redirect('home')
    else:
        form = WorkForm()
    return render(request, 'upload_work.html', {'form': form})
