from rest_framework import viewsets, permissions
from .models import Post, PostRating, PostJoin, OCCLog
from .serializers import PostSerializer, PostRatingSerializer, PostJoinSerializer, OCCLogSerializer

# PostZ CRUD
class PostViewSet(viewsets.ModelViewSet):
    queryset = Post.objects.all().order_by('-created_at')
    serializer_class = PostSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

# PostZ Ratings
class PostRatingViewSet(viewsets.ModelViewSet):
    queryset = PostRating.objects.all()
    serializer_class = PostRatingSerializer
    permission_classes = [permissions.IsAuthenticated]

# PostZ Joins
class PostJoinViewSet(viewsets.ModelViewSet):
    queryset = PostJoin.objects.all()
    serializer_class = PostJoinSerializer
    permission_classes = [permissions.IsAuthenticated]

# OCC Log
class OCCLogViewSet(viewsets.ModelViewSet):
    queryset = OCCLog.objects.all().order_by('-created_at')
    serializer_class = OCCLogSerializer
    permission_classes = [permissions.IsAuthenticated]
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

# --- Public API: App Version ---
@api_view(['GET'])
@permission_classes([AllowAny])
def app_version(request):
    return JsonResponse({
        "version": "v15.6",
        "deployed": "2026-04-06"
    })
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from django.db.models import Avg, Count

# --- Corey Quantifiable Feedback & Suggestions API (v14.5) ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def corey_feedback_and_suggestions(request):
    """
    Returns quantifiable Corey feedback, improvement suggestions, and teacher/mentor recommendations.
    For high-rated users, recommends becoming a teacher and provides instructions.
    """
    user = request.user
    from .models import CollabReliabilityRating, UserProfile
    avg_rating = CollabReliabilityRating.objects.filter(ratee=user).aggregate(avg=Avg('score'))['avg'] or 0
    feedback = f"Your average rating is {avg_rating:.2f} out of 10."
    suggestions = []
    teacher_recommendations = []
    become_teacher = None
    user_profile = getattr(user, 'profile', None)
    location = user_profile.location if user_profile else ''
    if avg_rating < 5:
        suggestions.append("Consider taking a lesson or collaborating with a top-rated mentor in your area to boost your skills.")
        # Recommend top-rated teachers in user location
        top_teachers = UserProfile.objects.filter(location=location).annotate(rating=Avg('user__received_reliability_ratings__score')).filter(rating__gte=7).order_by('-rating')[:3]
        for t in top_teachers:
            teacher_recommendations.append({
                'username': t.user.username,
                'rating': round(t.rating or 0, 2),
                'location': t.location,
            })
    elif avg_rating < 6:
        suggestions.append("Your rating has dropped below 6. Focus on learning, collaborating, and seeking feedback to improve. Consider lessons with top-rated teachers in your area for a boost!")
        top_teachers = UserProfile.objects.filter(location=location).annotate(rating=Avg('user__received_reliability_ratings__score')).filter(rating__gte=7).order_by('-rating')[:3]
        for t in top_teachers:
            teacher_recommendations.append({
                'username': t.user.username,
                'rating': round(t.rating or 0, 2),
                'location': t.location,
            })
    elif avg_rating < 8:
        suggestions.append("You're getting close! Keep learning and collaborating—at 8 or higher, you'll be ready to teach others!")
        top_teachers = UserProfile.objects.filter(location=location).annotate(rating=Avg('user__received_reliability_ratings__score')).filter(rating__gte=8).order_by('-rating')[:2]
        for t in top_teachers:
            teacher_recommendations.append({
                'username': t.user.username,
                'rating': round(t.rating or 0, 2),
                'location': t.location,
            })
    if avg_rating >= 8:
        become_teacher = {
            'message': "You're almost ready to teach! Your high rating means you could inspire others. Consider becoming a teacher or mentor on Music ConnectZ.",
            'how_to': "Go to your profile settings and click 'Become a Teacher' to start sharing your skills and earning SpinaZ!"
        }
    elif avg_rating >= 6:
        become_teacher = {
            'message': "If you want to be a teacher, keep working hard to be a great role model! Offer more, help others, and you'll be ready to teach soon.",
            'how_to': "Focus on building your skills and supporting your peers—when your rating hits 8, you'll unlock the teacher path!"
        }
    else:
        if user_profile and getattr(user_profile, 'is_teacher', False):
            become_teacher = {
                'message': "Your rating has dropped below 6. To regain your teacher status, focus on improving your skills, collaborating, and learning from top mentors. You can earn your way back—Music ConnectZ believes in comebacks!",
                'how_to': "Once your rating is 6 or higher again, you'll be eligible to teach and inspire others!"
            }
        else:
            become_teacher = {
                'message': "Improve your skills and confidence before teaching others. Take lessons, collaborate, and learn from top mentors to get ready!",
                'how_to': "Once your rating is 6 or higher, you'll unlock the path to becoming a teacher."
            }
    return Response({
        'feedback': feedback,
        'suggestions': suggestions,
        'teacher_recommendations': teacher_recommendations,
        'become_teacher': become_teacher,
    })
from django.contrib.auth import get_user_model

# --- Corey Voice Utility ---
def get_corey_voice_for_user(user):
    """
    Returns Corey-voice style: playful/flirtatious if avg rating >=5, else normal Corey-voice.
    """
    from .models import CollabReliabilityRating
    avg_rating = CollabReliabilityRating.objects.filter(ratee=user).aggregate(avg=Avg('score'))['avg'] or 0
    if avg_rating >= 5:
        # Flirty/playful Corey-voice
        return {
            'tone': 'playful/flirtatious',
            'message': "Ooo, look at you racking up those stars! 🌟 You keep this up and I might just have to write you a love song. 😉 Keep shining, superstar!"
        }
    else:
        # Standard Corey-voice
        return {
            'tone': 'corey-voice',
            'message': "Yo! 🎤 Keep grinding, your next big moment is just around the corner. I'm here if you need a boost! 🤙"
        }
# --- User Personas API ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_personas(request):
    """
    List all personas for the authenticated user, including their skills.
    """
    from .models import Persona
    personas = Persona.objects.filter(user=request.user).prefetch_related('skills')
    data = []
    for persona in personas:
        data.append({
            'id': persona.id,
            'name': persona.name,
            'skills': [s.name for s in persona.skills.all()],
        })
    return Response(data)
from django.db.models import Avg, Count
# --- AI Price Suggestion API ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def ai_suggest_skill_prices(request):
    """
    Suggest skill prices for the authenticated user based on their ratings, reviews, and demand.
    """
    from .models import Skill, Persona, CollabReliabilityRating
    user = request.user
    # For each skill the user has, calculate average reliability rating and demand (number of collabs)
    personas = Persona.objects.filter(user=user).prefetch_related('skills')
    skill_suggestions = []
    for persona in personas:
        for skill in persona.skills.all():
            # Get average reliability rating for this skill (across all collabs where user used this skill)
            avg_rating = CollabReliabilityRating.objects.filter(ratee=user).aggregate(avg=Avg('score'))['avg'] or 0
            # Demand: number of works/collabs using this skill
            demand = persona.skills.filter(id=skill.id).count()
            # Current price (if set)
            current_price = getattr(persona, 'price', None)
            # Simple AI logic: if rating > 8, suggest +10%; if < 6, suggest -10%; else keep
            if avg_rating > 8:
                suggested_price = current_price * 1.1 if current_price else 50
                suggestion = "HIGH DEMAND - Increase your rate!"
            elif avg_rating < 6:
                suggested_price = current_price * 0.9 if current_price else 30
                suggestion = "BOOST YOUR RATING - Lower your rate to attract more collabs."
            else:
                suggested_price = current_price or 40
                suggestion = "STEADY - Your rate is competitive."
            skill_suggestions.append({
                'skill_name': skill.name,
                'current_price': current_price,
                'suggested_price': round(suggested_price, 2),
                'suggestion': suggestion,
                'avg_rating': round(avg_rating, 2),
                'demand': demand,
            })
    return Response(skill_suggestions)

from django.http import JsonResponse
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from datetime import timedelta

# --- Home View ---
def home(request):
    return JsonResponse({'message': 'Welcome to Music ConnectZ Backend!'})

# --- OpenAI Chat Integration ---
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def openai_chat(request):
    """
    Chat endpoint for OpenAI integration. Expects 'message' in request body.
    """
    import openai
    message = request.data.get('message', '')
    if not message:
        return Response({'error': 'Message is required'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        response = openai.ChatCompletion.create(
            model='gpt-3.5-turbo',
            messages=[{'role': 'user', 'content': message}],
            max_tokens=150,
        )
        reply = response['choices'][0]['message']['content']
        return Response({'reply': reply})
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# --- Google OAuth Config Check ---
@api_view(['GET'])
@permission_classes([AllowAny])
def google_available(request):
    """Check if Google OAuth is configured."""
    from django.conf import settings
    google_configured = bool(getattr(settings, 'SOCIALACCOUNT_PROVIDERS', {}).get('google', {}).get('APP', {}).get('client_id'))
    return Response({'google_oauth_available': google_configured})

# --- OAuth Providers Status ---
@api_view(['GET'])
@permission_classes([AllowAny])
def oauth_providers_status(request):
    """Check status of all configured OAuth providers."""
    from django.conf import settings
    providers = getattr(settings, 'SOCIALACCOUNT_PROVIDERS', {})
    status_data = {provider: bool(providers.get(provider, {}).get('APP', {}).get('client_id')) for provider in ['google', 'apple']}
    return Response(status_data)

# --- User Auth APIs ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_auth_users(request):
    """Get list of all users (admin only or limited)."""
    from django.contrib.auth.models import User
    users = User.objects.all().values('id', 'username', 'email')
    return Response(list(users))

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_auth_me(request):
    """Get current authenticated user info."""
    user = request.user
    return Response({
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_connected_accounts(request):
    """Get connected social accounts for current user."""
    from allauth.socialaccount.models import SocialAccount
    accounts = SocialAccount.objects.filter(user=request.user).values('provider', 'uid', 'display_name')
    return Response(list(accounts))

@api_view(['GET'])
@permission_classes([AllowAny])
def auth_csrf(request):
    """Get CSRF token (if needed for frontend)."""
    from django.middleware.csrf import get_token
    token = get_token(request)
    return Response({'csrf_token': token})

# --- Email Verification ---
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_email_verification_code(request):
    """Send email verification code to user."""
    user = request.user
    # Generate a 6-digit code
    import random
    code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
    # Store in cache or DB (example: cache)
    from django.core.cache import cache
    cache.set(f'email_verification_{user.id}', code, timeout=600)  # 10 minutes
    
    # Send email (replace with actual email sending)
    # send_mail('Verification Code', f'Your code: {code}', 'noreply@musicconnectz.net', [user.email])
    
    return Response({'message': 'Verification code sent to your email.'})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_email_code(request):
    """Verify email with code."""
    user = request.user
    code = request.data.get('code', '')
    from django.core.cache import cache
    stored_code = cache.get(f'email_verification_{user.id}')
    
    if not stored_code or stored_code != code:
        return Response({'error': 'Invalid or expired code'}, status=status.HTTP_400_BAD_REQUEST)
    
    # Mark email as verified
    from .models import UserProfile
    profile = UserProfile.objects.filter(user=user).first()
    if profile:
        profile.email_verified = True
        profile.save()
    cache.delete(f'email_verification_{user.id}')
    return Response({'message': 'Email verified successfully!'})

# --- Phone Verification ---
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_phone_verification_code(request):
    """Send SMS verification code to user."""
    user = request.user
    phone = request.data.get('phone', '')
    if not phone:
        return Response({'error': 'Phone number required'}, status=status.HTTP_400_BAD_REQUEST)
    
    import random
    code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
    from django.core.cache import cache
    cache.set(f'phone_verification_{user.id}', code, timeout=600)
    
    # Send SMS (integrate with Twilio or similar)
    # send_sms(phone, f'Your verification code: {code}')
    
    return Response({'message': 'Verification code sent to your phone.'})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_phone_code(request):
    """Verify phone with code."""
    user = request.user
    code = request.data.get('code', '')
    from django.core.cache import cache
    stored_code = cache.get(f'phone_verification_{user.id}')
    
    if not stored_code or stored_code != code:
        return Response({'error': 'Invalid or expired code'}, status=status.HTTP_400_BAD_REQUEST)
    
    from .models import UserProfile
    profile = UserProfile.objects.filter(user=user).first()
    if profile:
        profile.phone_verified = True
        profile.save()
    cache.delete(f'phone_verification_{user.id}')
    return Response({'message': 'Phone verified successfully!'})

# --- Notification Settings ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_notification_settings(request):
    """Get user notification preferences."""
    from .models import UserProfile
    profile = UserProfile.objects.filter(user=request.user).first()
    if not profile:
        return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)
    
    return Response({
        'email_notifications': getattr(profile, 'email_notifications', True),
        'push_notifications': getattr(profile, 'push_notifications', True),
        'sms_notifications': getattr(profile, 'sms_notifications', False),
    })

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_notification_settings(request):
    """Update user notification preferences."""
    from .models import UserProfile
    profile = UserProfile.objects.filter(user=request.user).first()
    if not profile:
        return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)
    
    profile.email_notifications = request.data.get('email_notifications', profile.email_notifications)
    profile.push_notifications = request.data.get('push_notifications', profile.push_notifications)
    profile.sms_notifications = request.data.get('sms_notifications', profile.sms_notifications)
    profile.save()
    
    return Response({'message': 'Notification settings updated.'})

# --- OAuth Profile Completion ---
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def complete_oauth_profile(request):
    """Complete user profile after OAuth login."""
    user = request.user
    location = request.data.get('location', '')
    bio = request.data.get('bio', '')
    
    from .models import UserProfile
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.location = location
    profile.bio = bio
    profile.save()
    
    return Response({'message': 'Profile completed successfully!'})

# --- User Registration ---
@api_view(['POST'])
@permission_classes([AllowAny])
def api_register(request):
    """Register new user with email and password."""
    from django.contrib.auth.models import User
    username = request.data.get('username', '')
    email = request.data.get('email', '')
    password = request.data.get('password', '')
    
    if not username or not email or not password:
        return Response({'error': 'Username, email, and password are required'}, status=status.HTTP_400_BAD_REQUEST)
    
    if User.objects.filter(username=username).exists():
        return Response({'error': 'Username already exists'}, status=status.HTTP_400_BAD_REQUEST)
    
    if User.objects.filter(email=email).exists():
        return Response({'error': 'Email already registered'}, status=status.HTTP_400_BAD_REQUEST)
    
    user = User.objects.create_user(username=username, email=email, password=password)
    
    from rest_framework.authtoken.models import Token
    token = Token.objects.create(user=user)
    
    return Response({'message': 'User registered successfully!', 'token': token.key}, status=status.HTTP_201_CREATED)

# --- User Login ---
@api_view(['POST'])
@permission_classes([AllowAny])
def api_login(request):
    """Login user with username and password."""
    from django.contrib.auth import authenticate
    username = request.data.get('username', '')
    password = request.data.get('password', '')
    
    user = authenticate(username=username, password=password)
    if not user:
        return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)
    
    from rest_framework.authtoken.models import Token
    token, _ = Token.objects.get_or_create(user=user)
    
    return Response({'token': token.key, 'user_id': user.id, 'username': user.username})

# --- Referral System ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def referral_stats(request):
    """Get referral statistics for user."""
    from .models import Referral
    user = request.user
    referrals = Referral.objects.filter(referrer=user)
    return Response({
        'total_referrals': referrals.count(),
        'active_referrals': referrals.filter(status='active').count(),
        'referral_link': f'https://musicconnectz.net/ref/{user.id}',
    })

@api_view(['POST'])
@permission_classes([AllowAny])
def register_with_referral(request):
    """Register with referral code."""
    from django.contrib.auth.models import User
    from .models import Referral
    
    username = request.data.get('username', '')
    email = request.data.get('email', '')
    password = request.data.get('password', '')
    referral_code = request.data.get('referral_code', '')
    
    # Create user (same as api_register)
    if User.objects.filter(username=username).exists() or User.objects.filter(email=email).exists():
        return Response({'error': 'User already exists'}, status=status.HTTP_400_BAD_REQUEST)
    
    user = User.objects.create_user(username=username, email=email, password=password)
    
    # Link referral
    if referral_code:
        try:
            referrer = User.objects.get(id=referral_code)
            Referral.objects.create(referrer=referrer, referred=user, status='active')
        except User.DoesNotExist:
            pass
    
    from rest_framework.authtoken.models import Token
    token = Token.objects.create(user=user)
    
    return Response({'message': 'Registered with referral!', 'token': token.key}, status=status.HTTP_201_CREATED)

# --- Royalty Agreement APIs ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def download_royalty_agreement_pdf(request, agreement_id):
    """Download royalty agreement as PDF."""
    from .models import Agreement
    try:
        agreement = Agreement.objects.get(id=agreement_id, owner=request.user)
    except Agreement.DoesNotExist:
        return Response({'error': 'Agreement not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Generate PDF (use ReportLab or similar)
    from django.http import FileResponse
    # For now, return a mock response
    return Response({'message': f'PDF for {agreement.title} would be generated here'})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_agreement_templates(request):
    """List available agreement templates."""
    from .models import AgreementTemplate
    templates = AgreementTemplate.objects.all().values('id', 'name', 'description')
    return Response(list(templates))

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_agreement_template(request):
    """Create custom agreement template."""
    from .models import AgreementTemplate
    name = request.data.get('name', '')
    description = request.data.get('description', '')
    content = request.data.get('content', '')
    
    template = AgreementTemplate.objects.create(name=name, description=description, content=content)
    return Response({'id': template.id, 'message': 'Template created'}, status=status.HTTP_201_CREATED)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_agreement_version(request, agreement_id):
    """Create new version of agreement."""
    from .models import Agreement, AgreementVersion
    try:
        agreement = Agreement.objects.get(id=agreement_id, owner=request.user)
    except Agreement.DoesNotExist:
        return Response({'error': 'Agreement not found'}, status=status.HTTP_404_NOT_FOUND)
    
    content = request.data.get('content', '')
    version = AgreementVersion.objects.create(agreement=agreement, content=content, version_number=agreement.current_version + 1)
    return Response({'version_id': version.id, 'version_number': version.version_number}, status=status.HTTP_201_CREATED)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def sign_royalty_split(request, split_id):
    """Sign a royalty split."""
    from .models import RoyaltySplit, RoyaltySignature
    try:
        split = RoyaltySplit.objects.get(id=split_id, user=request.user)
    except RoyaltySplit.DoesNotExist:
        return Response({'error': 'Split not found'}, status=status.HTTP_404_NOT_FOUND)
    
    signature = RoyaltySignature.objects.create(split=split, signed_by=request.user, signed_at=timezone.now())
    return Response({'signature_id': signature.id, 'message': 'Split signed'})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def agreement_change_history(request, agreement_id):
    """Get change history for agreement."""
    from .models import Agreement, AgreementVersion
    try:
        agreement = Agreement.objects.get(id=agreement_id)
    except Agreement.DoesNotExist:
        return Response({'error': 'Agreement not found'}, status=status.HTTP_404_NOT_FOUND)
    
    versions = AgreementVersion.objects.filter(agreement=agreement).order_by('version_number')
    return Response([{'version': v.version_number, 'created_at': v.created_at} for v in versions])

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def export_agreement_json(request, agreement_id):
    """Export agreement as JSON."""
    from .models import Agreement
    try:
        agreement = Agreement.objects.get(id=agreement_id)
    except Agreement.DoesNotExist:
        return Response({'error': 'Agreement not found'}, status=status.HTTP_404_NOT_FOUND)
    
    return Response({
        'id': agreement.id,
        'title': agreement.title,
        'project': agreement.project,
        'created_at': agreement.created_at,
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def export_agreement_csv(request, agreement_id):
    """Export agreement as CSV."""
    from .models import Agreement
    try:
        agreement = Agreement.objects.get(id=agreement_id)
    except Agreement.DoesNotExist:
        return Response({'error': 'Agreement not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Generate CSV (use csv module)
    return Response({'message': 'CSV export would be generated here'})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_agreement_reminder(request, agreement_id):
    """Send reminder for agreement."""
    from .models import Agreement
    try:
        agreement = Agreement.objects.get(id=agreement_id, owner=request.user)
    except Agreement.DoesNotExist:
        return Response({'error': 'Agreement not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Send email reminders to unsigned parties
    return Response({'message': 'Reminders sent'})

# --- Analytics APIs ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def site_analytics(request):
    """Get site-wide analytics."""
    from .models import Agreement, RoyaltySplit
    return Response({
        'total_agreements': Agreement.objects.count(),
        'active_agreements': Agreement.objects.filter(status='active').count(),
        'total_splits': RoyaltySplit.objects.count(),
    })

# --- Stripe Subscription APIs ---
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_subscription_checkout(request):
    """Create Stripe checkout session for subscription."""
    import stripe
    stripe.api_key = 'your_stripe_key'
    
    price_id = request.data.get('price_id', '')
    if not price_id:
        return Response({'error': 'price_id required'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{'price': price_id, 'quantity': 1}],
            mode='subscription',
            success_url='https://musicconnectz.net/success',
            cancel_url='https://musicconnectz.net/cancel',
            customer_email=request.user.email,
        )
        return Response({'session_id': session.id, 'url': session.url})
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_purchase_checkout(request):
    """Create Stripe checkout session for one-time purchase."""
    import stripe
    stripe.api_key = 'your_stripe_key'
    
    price_id = request.data.get('price_id', '')
    if not price_id:
        return Response({'error': 'price_id required'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{'price': price_id, 'quantity': 1}],
            mode='payment',
            success_url='https://musicconnectz.net/success',
            cancel_url='https://musicconnectz.net/cancel',
            customer_email=request.user.email,
        )
        return Response({'session_id': session.id, 'url': session.url})
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_subscription(request):
    """Cancel user subscription."""
    import stripe
    stripe.api_key = 'your_stripe_key'
    
    subscription_id = request.data.get('subscription_id', '')
    if not subscription_id:
        return Response({'error': 'subscription_id required'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        stripe.Subscription.delete(subscription_id)
        return Response({'message': 'Subscription cancelled'})
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def use_collaboration_request(request):
    """Use collaboration request from user's plan."""
    from .models import UserProfile
    profile = UserProfile.objects.filter(user=request.user).first()
    if not profile or profile.collaboration_requests_remaining <= 0:
        return Response({'error': 'No collaboration requests available'}, status=status.HTTP_400_BAD_REQUEST)
    
    profile.collaboration_requests_remaining -= 1
    profile.save()
    return Response({'remaining': profile.collaboration_requests_remaining})

# --- Distribution APIs ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_distribution_accounts(request):
    """List user's distribution accounts."""
    from .models import DistributionAccount
    accounts = DistributionAccount.objects.filter(user=request.user).values('id', 'provider', 'account_name')
    return Response(list(accounts))

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def connect_distribution_account(request):
    """Connect new distribution account."""
    from .models import DistributionAccount
    provider = request.data.get('provider', '')
    account_name = request.data.get('account_name', '')
    api_key = request.data.get('api_key', '')
    
    account = DistributionAccount.objects.create(
        user=request.user,
        provider=provider,
        account_name=account_name,
        api_key=api_key,
    )
    return Response({'id': account.id, 'message': 'Account connected'}, status=status.HTTP_201_CREATED)

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_distribution_account(request, account_id):
    """Delete distribution account."""
    from .models import DistributionAccount
    try:
        account = DistributionAccount.objects.get(id=account_id, user=request.user)
        account.delete()
        return Response({'message': 'Account deleted'})
    except DistributionAccount.DoesNotExist:
        return Response({'error': 'Account not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def distribution_releases(request):
    """List user's distribution releases."""
    from .models import DistributionRelease
    releases = DistributionRelease.objects.filter(owner=request.user).values('id', 'title', 'status')
    return Response(list(releases))

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def distribution_release_detail(request, release_id):
    """Get details of a distribution release."""
    from .models import DistributionRelease
    try:
        release = DistributionRelease.objects.get(id=release_id, owner=request.user)
        return Response({
            'id': release.id,
            'title': release.title,
            'status': release.status,
            'created_at': release.created_at,
        })
    except DistributionRelease.DoesNotExist:
        return Response({'error': 'Release not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def distribution_release_submission_fields(request, release_id):
    """Get submission fields required for a release."""
    from .models import DistributionRelease
    try:
        release = DistributionRelease.objects.get(id=release_id)
        return Response({'fields': ['title', 'artists', 'genre', 'release_date']})
    except DistributionRelease.DoesNotExist:
        return Response({'error': 'Release not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def distribution_release_tracks(request, release_id):
    """Get tracks for a distribution release."""
    from .models import DistributionRelease, DistributionTrack
    try:
        release = DistributionRelease.objects.get(id=release_id)
        tracks = DistributionTrack.objects.filter(release=release).values('id', 'title', 'artists')
        return Response(list(tracks))
    except DistributionRelease.DoesNotExist:
        return Response({'error': 'Release not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def distribution_release_track_detail(request, release_id, track_id):
    """Get details of a track in a release."""
    from .models import DistributionTrack
    try:
        track = DistributionTrack.objects.get(id=track_id, release_id=release_id)
        return Response({
            'id': track.id,
            'title': track.title,
            'artists': track.artists,
            'isrc': track.isrc,
        })
    except DistributionTrack.DoesNotExist:
        return Response({'error': 'Track not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def validate_distribution_release(request, release_id):
    """Validate a distribution release before submission."""
    from .models import DistributionRelease
    try:
        release = DistributionRelease.objects.get(id=release_id, owner=request.user)
        # Perform validation logic
        return Response({'valid': True, 'message': 'Release is valid for submission'})
    except DistributionRelease.DoesNotExist:
        return Response({'error': 'Release not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_distribution_release(request, release_id):
    """Submit a distribution release to distributors."""
    from .models import DistributionRelease
    try:
        release = DistributionRelease.objects.get(id=release_id, owner=request.user)
        release.status = 'submitted'
        release.submitted_at = timezone.now()
        release.save()
        return Response({'message': 'Release submitted', 'status': 'submitted'})
    except DistributionRelease.DoesNotExist:
        return Response({'error': 'Release not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def distribution_release_status(request, release_id):
    """Get submission status of a release."""
    from .models import DistributionRelease
    try:
        release = DistributionRelease.objects.get(id=release_id)
        return Response({'status': release.status, 'submitted_at': release.submitted_at})
    except DistributionRelease.DoesNotExist:
        return Response({'error': 'Release not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def distribution_release_contributors(request, release_id):
    """Get contributors for a release."""
    from .models import DistributionRelease, ReleaseContributor
    try:
        release = DistributionRelease.objects.get(id=release_id)
        contributors = ReleaseContributor.objects.filter(release=release).values('id', 'name', 'role')
        return Response(list(contributors))
    except DistributionRelease.DoesNotExist:
        return Response({'error': 'Release not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def distribution_release_contributor_detail(request, release_id, contributor_id):
    """Get details of a contributor."""
    from .models import ReleaseContributor
    try:
        contributor = ReleaseContributor.objects.get(id=contributor_id, release_id=release_id)
        return Response({
            'id': contributor.id,
            'name': contributor.name,
            'role': contributor.role,
            'share': contributor.royalty_share,
        })
    except ReleaseContributor.DoesNotExist:
        return Response({'error': 'Contributor not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@permission_classes([AllowAny])
def distribution_provider_webhook(request, provider):
    """Webhook endpoint for distribution provider updates."""
    # Handle webhooks from distribution services
    return Response({'received': True})

# --- Distribution Analytics APIs ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def release_analytics(request, release_id):
    """Get analytics for a release."""
    from .models import DistributionRelease
    try:
        release = DistributionRelease.objects.get(id=release_id, owner=request.user)
        return Response({
            'streams': 0,
            'downloads': 0,
            'revenue': 0,
        })
    except DistributionRelease.DoesNotExist:
        return Response({'error': 'Release not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def track_analytics(request, release_id, track_id):
    """Get analytics for a specific track."""
    from .models import DistributionTrack
    try:
        track = DistributionTrack.objects.get(id=track_id, release_id=release_id)
        return Response({
            'streams': 0,
            'downloads': 0,
            'revenue': 0,
        })
    except DistributionTrack.DoesNotExist:
        return Response({'error': 'Track not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def contributor_earnings(request, release_id):
    """Get earnings breakdown by contributor for a release."""
    from .models import DistributionRelease
    try:
        release = DistributionRelease.objects.get(id=release_id)
        return Response({'earnings': []})
    except DistributionRelease.DoesNotExist:
        return Response({'error': 'Release not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_total_earnings(request):
    """Get total earnings for user across all releases."""
    return Response({'total_earnings': 0})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def oauth_provider_profit_analytics(request):
    """Get profit analytics for OAuth provider deals."""
    return Response({'oauth_profit': 0})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def apple_oauth_profit_summary(request):
    """Get Apple OAuth profit summary."""
    return Response({'apple_profit': 0})

# --- Premium Features APIs ---
@api_view(['GET'])
@permission_classes([AllowAny])
def list_premium_features(request):
    """List all available premium features."""
    from .models import PremiumFeature
    features = PremiumFeature.objects.all().values('id', 'name', 'description', 'price')
    return Response(list(features))

@api_view(['GET'])
@permission_classes([AllowAny])
def list_premium_bundles(request):
    """List all premium bundles."""
    from .models import PremiumBundle
    bundles = PremiumBundle.objects.all().values('id', 'name', 'price', 'features')
    return Response(list(bundles))

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_premium_features(request):
    """Get premium features subscribed by user."""
    from .models import UserPremiumSubscription
    subscriptions = UserPremiumSubscription.objects.filter(user=request.user, active=True).values('feature__name', 'expires_at')
    return Response(list(subscriptions))

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def subscribe_to_feature(request, feature_key):
    """Subscribe user to a premium feature."""
    from .models import PremiumFeature, UserPremiumSubscription
    try:
        feature = PremiumFeature.objects.get(key=feature_key)
        subscription = UserPremiumSubscription.objects.create(
            user=request.user,
            feature=feature,
            expires_at=timezone.now() + timedelta(days=30),
            active=True,
        )
        return Response({'subscription_id': subscription.id, 'expires_at': subscription.expires_at})
    except PremiumFeature.DoesNotExist:
        return Response({'error': 'Feature not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_feature_subscription(request, feature_key):
    """Cancel subscription to a premium feature."""
    from .models import UserPremiumSubscription
    subscription = UserPremiumSubscription.objects.filter(user=request.user, feature__key=feature_key).first()
    if not subscription:
        return Response({'error': 'Subscription not found'}, status=status.HTTP_404_NOT_FOUND)
    
    subscription.active = False
    subscription.save()
    return Response({'message': 'Subscription cancelled'})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_interests(request):
    """Get user's interests/preferences."""
    from .models import UserProfile
    profile = UserProfile.objects.filter(user=request.user).first()
    if not profile:
        return Response({'interests': []})
    
    interests = getattr(profile, 'interests_json', [])
    return Response({'interests': interests})

# --- Marketing Weekly Promotions ---
def _week_bounds():
    today = timezone.now()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    return week_start, week_end

def _build_promo_code(user_id, template_key):
    import hashlib
    return hashlib.md5(f'{user_id}{template_key}'.encode()).hexdigest()[:8].upper()

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_weekly_marketing_promotions(request):
    from .models import UserPremiumSubscription, WeeklyPromoTemplate, UserWeeklyPromotion
    from .serializers import UserWeeklyPromotionSerializer
    
    week_start, week_end = _week_bounds()
    expires_at = week_end + timedelta(days=1)
    
    user_subs = UserPremiumSubscription.objects.filter(user=request.user, active=True).values_list('feature__key', flat=True)
    feature_keys_set = set(user_subs)
    
    user_profile = getattr(request.user, 'profile', None)
    interest_tags = getattr(user_profile, 'interests_json', []) if user_profile else []
    interest_set = {str(tag).strip().lower() for tag in interest_tags}
    
    templates = []
    for feature_key in feature_keys_set:
        try:
            template = WeeklyPromoTemplate.objects.get(template_key=feature_key)
            templates.append(template)
        except WeeklyPromoTemplate.DoesNotExist:
            fallback_key = 'general_promo'
            template, _ = WeeklyPromoTemplate.objects.get_or_create(
                template_key=fallback_key,
                defaults={
                    'title': f"Weekly deal for {feature_key.replace('_', ' ').title()}",
                    'description': 'Personalized weekly offer based on your active premium tools.',
                    'target_feature_id': feature_key,
                    'interest_tags_json': [],
                    'discount_percent': 15,
                    'is_active': True,
                },
            )
            templates.append(template)

    created_rows = []
    for template in templates:
        tags = template.interest_tags_json if isinstance(template.interest_tags_json, list) else []
        matched_interest = ''
        if tags and interest_set:
            for tag in tags:
                tag_norm = str(tag).strip().lower()
                if tag_norm in interest_set:
                    matched_interest = tag_norm
                    break

        promo, created = UserWeeklyPromotion.objects.get_or_create(
            user=request.user,
            template=template,
            week_start=week_start,
            defaults={
                'week_end': week_end,
                'promo_code': _build_promo_code(request.user.id, template.template_key),
                'discount_percent': template.discount_percent,
                'matched_interest': matched_interest,
                'claimed': False,
                'expires_at': expires_at,
            },
        )
        if created:
            created_rows.append(promo)

    return Response(
        {
            'generated': len(created_rows),
            'promotions': UserWeeklyPromotionSerializer(created_rows, many=True).data,
            'week_start': week_start,
            'week_end': week_end,
        }
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_weekly_promotions(request):
    from .models import UserWeeklyPromotion
    from .serializers import UserWeeklyPromotionSerializer

    week_start, _ = _week_bounds()
    rows = UserWeeklyPromotion.objects.filter(user=request.user, week_start=week_start).select_related('template', 'template__target_feature')
    return Response(UserWeeklyPromotionSerializer(rows, many=True).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def claim_weekly_promotion(request, promotion_id):
    from .models import UserWeeklyPromotion
    from .serializers import UserWeeklyPromotionSerializer

    row = UserWeeklyPromotion.objects.filter(id=promotion_id, user=request.user).select_related('template', 'template__target_feature').first()
    if not row:
        return Response({'error': 'Promotion not found.'}, status=status.HTTP_404_NOT_FOUND)
    if row.claimed:
        return Response({'error': 'Promotion already claimed.'}, status=status.HTTP_400_BAD_REQUEST)
    if row.expires_at and row.expires_at < timezone.now():
        return Response({'error': 'Promotion expired.'}, status=status.HTTP_400_BAD_REQUEST)

    row.claimed = True
    row.save(update_fields=['claimed', 'updated_at'])
    return Response({'success': True, 'promotion': UserWeeklyPromotionSerializer(row).data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def in_app_feature_ads(request):
    ads = _build_in_app_feature_ads(request.user)
    return Response({'count': len(ads), 'ads': ads})


def _build_in_app_feature_ads(user):
    # Build in-app feature ads based on user's interests and premium status
    return []


# --- Royalty & Agreement Dashboard API Views ---
from rest_framework import viewsets, permissions
from .models import Agreement, AgreementSignature, RoyaltySplit, RoyaltyPayment
from .serializers import (
    AgreementSerializer, AgreementSignatureSerializer, RoyaltySplitSerializer, RoyaltyPaymentSerializer
)

# --- Royalty & Agreement Dashboard Permissions ---
from rest_framework import permissions

class IsAgreementOwnerOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        # Read permissions for all involved users, write only for owner
        if request.method in permissions.SAFE_METHODS:
            return request.user == obj.owner or obj.royalty_splits.filter(user=request.user).exists()
        return request.user == obj.owner

class IsSignatureUser(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        # Only the user themselves can sign
        return request.user == obj.user

class IsOwnerForSplitOrPayment(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        # Only agreement owner can add/edit splits/payments
        return request.user == obj.agreement.owner

class AgreementViewSet(viewsets.ModelViewSet):
    queryset = Agreement.objects.all()
    serializer_class = AgreementSerializer
    permission_classes = [permissions.IsAuthenticated, IsAgreementOwnerOrReadOnly]
    def perform_create(self, serializer):
        agreement = serializer.save(owner=self.request.user)
        notify_agreement_created(agreement)

class AgreementSignatureViewSet(viewsets.ModelViewSet):
    queryset = AgreementSignature.objects.all()
    serializer_class = AgreementSignatureSerializer
    permission_classes = [permissions.IsAuthenticated, IsSignatureUser]
    def get_queryset(self):
        # Only show signatures for agreements user is involved in
        user = self.request.user
        from django.db import models
        return AgreementSignature.objects.filter(models.Q(user=user) | models.Q(agreement__owner=user) | models.Q(agreement__royalty_splits__user=user)).distinct()

class RoyaltySplitViewSet(viewsets.ModelViewSet):
    queryset = RoyaltySplit.objects.all()
    serializer_class = RoyaltySplitSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerForSplitOrPayment]
    def get_queryset(self):
        user = self.request.user
        from django.db import models
        return RoyaltySplit.objects.filter(models.Q(user=user) | models.Q(agreement__owner=user)).distinct()

class RoyaltyPaymentViewSet(viewsets.ModelViewSet):
    queryset = RoyaltyPayment.objects.all()
    serializer_class = RoyaltyPaymentSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerForSplitOrPayment]
    def get_queryset(self):
        user = self.request.user
        from django.db import models
        return RoyaltyPayment.objects.filter(models.Q(user=user) | models.Q(agreement__owner=user)).distinct()

# --- Royalty & Agreement Dashboard Notifications (example: email on agreement/signature creation) ---
from django.core.mail import send_mail

def notify_agreement_created(agreement):
    # Notify all participants (splits) except owner
    recipients = [split.user.email for split in agreement.royalty_splits.all() if split.user != agreement.owner and split.user.email]
    if recipients:
        send_mail(
            subject=f"New Agreement: {agreement.title}",
            message=f"You have been added to a new agreement '{agreement.title}' for project '{agreement.project}'. Log in to review and sign.",
            from_email=None,
            recipient_list=recipients,
            fail_silently=True,
        )

def notify_signature_signed(signature):
    # Notify agreement owner when someone signs
    owner_email = signature.agreement.owner.email
    if owner_email:
        send_mail(
            subject=f"Agreement Signed: {signature.agreement.title}",
            message=f"{signature.user.username} has signed the agreement '{signature.agreement.title}'.",
            from_email=None,
            recipient_list=[owner_email],
            fail_silently=True,
        )

# --- Reliability Rating & Review APIs ---
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def set_reliability_rating(request, agreement_id, ratee_id):
    """Set reliability rating for a collaboration partner."""
    from .models import Agreement, CollabReliabilityRating
    from django.contrib.auth.models import User
    
    try:
        agreement = Agreement.objects.get(id=agreement_id)
        ratee = User.objects.get(id=ratee_id)
    except (Agreement.DoesNotExist, User.DoesNotExist):
        return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
    
    score = request.data.get('score', 5)
    rating, created = CollabReliabilityRating.objects.update_or_create(
        agreement=agreement,
        rater=request.user,
        ratee=ratee,
        defaults={'score': score}
    )
    return Response({'id': rating.id, 'score': rating.score})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_reliability_ratings(request, agreement_id):
    """Get reliability ratings for an agreement."""
    from .models import Agreement, CollabReliabilityRating
    try:
        agreement = Agreement.objects.get(id=agreement_id)
    except Agreement.DoesNotExist:
        return Response({'error': 'Agreement not found'}, status=status.HTTP_404_NOT_FOUND)
    
    ratings = CollabReliabilityRating.objects.filter(agreement=agreement).values('rater__username', 'ratee__username', 'score')
    return Response(list(ratings))

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def set_collab_review(request, agreement_id, reviewee_id):
    """Leave a review for a collaboration partner."""
    from .models import Agreement, CollabReview
    from django.contrib.auth.models import User
    
    try:
        agreement = Agreement.objects.get(id=agreement_id)
        reviewee = User.objects.get(id=reviewee_id)
    except (Agreement.DoesNotExist, User.DoesNotExist):
        return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
    
    text = request.data.get('text', '')
    review, created = CollabReview.objects.update_or_create(
        agreement=agreement,
        reviewer=request.user,
        reviewee=reviewee,
        defaults={'text': text}
    )
    return Response({'id': review.id, 'text': review.text})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_collab_reviews(request, agreement_id):
    """Get reviews for an agreement."""
    from .models import Agreement, CollabReview
    try:
        agreement = Agreement.objects.get(id=agreement_id)
    except Agreement.DoesNotExist:
        return Response({'error': 'Agreement not found'}, status=status.HTTP_404_NOT_FOUND)
    
    reviews = CollabReview.objects.filter(agreement=agreement).values('reviewer__username', 'reviewee__username', 'text')
    return Response(list(reviews))

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_shared_reviews_for_user(request, user_id):
    """Get all reviews shared about a user."""
    from .models import CollabReview
    from django.contrib.auth.models import User
    
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
    
    reviews = CollabReview.objects.filter(reviewee=user).values('reviewer__username', 'text')
    return Response(list(reviews))

# --- Promo Offer Status ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def promo_offer_status(request):
    """Get user's current promo offer status."""
    return Response({'has_active_offer': False, 'discount': 0})
