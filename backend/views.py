from rest_framework import viewsets, permissions
from .models import Post, PostRating, OCCLog
from .serializers import PostSerializer, PostRatingSerializer, OCCLogSerializer

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
        suggestions.append("You’re getting close! Keep learning and collaborating—at 8 or higher, you’ll be ready to teach others!")
        top_teachers = UserProfile.objects.filter(location=location).annotate(rating=Avg('user__received_reliability_ratings__score')).filter(rating__gte=8).order_by('-rating')[:2]
        for t in top_teachers:
            teacher_recommendations.append({
                'username': t.user.username,
                'rating': round(t.rating or 0, 2),
                'location': t.location,
            })
    if avg_rating >= 8:
        become_teacher = {
            'message': "You’re almost ready to teach! Your high rating means you could inspire others. Consider becoming a teacher or mentor on Music ConnectZ.",
            'how_to': "Go to your profile settings and click 'Become a Teacher' to start sharing your skills and earning SpinaZ!"
        }
    elif avg_rating >= 6:
        become_teacher = {
            'message': "If you want to be a teacher, keep working hard to be a great role model! Offer more, help others, and you’ll be ready to teach soon.",
            'how_to': "Focus on building your skills and supporting your peers—when your rating hits 8, you’ll unlock the teacher path!"
        }
    else:
        if user_profile and getattr(user_profile, 'is_teacher', False):
            become_teacher = {
                'message': "Your rating has dropped below 6. To regain your teacher status, focus on improving your skills, collaborating, and learning from top mentors. You can earn your way back—Music ConnectZ believes in comebacks!",
                'how_to': "Once your rating is 6 or higher again, you’ll be eligible to teach and inspire others!"
            }
        else:
            become_teacher = {
                'message': "Improve your skills and confidence before teaching others. Take lessons, collaborate, and learn from top mentors to get ready!",
                'how_to': "Once your rating is 6 or higher, you’ll unlock the path to becoming a teacher."
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
            'message': "Yo! 🎤 Keep grinding, your next big moment is just around the corner. I’m here if you need a boost! 🤙"
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
                suggestion = (current_price or 10) * 1.10
                reason = f"High reliability rating ({avg_rating:.1f}/10). Consider raising your price."
            elif avg_rating < 6:
                suggestion = (current_price or 10) * 0.90
                reason = f"Low reliability rating ({avg_rating:.1f}/10). Consider lowering your price."
            else:
                suggestion = current_price or 10
                reason = f"Average reliability rating ({avg_rating:.1f}/10). Price is reasonable."
            skill_suggestions.append({
                'persona': persona.name,
                'skill': skill.name,
                'current_price': float(current_price) if current_price else None,
                'suggested_price': round(float(suggestion), 2),
                'reason': reason,
                'demand': demand,
            })
    return Response({'suggestions': skill_suggestions})

# --- User Contributor Earnings API ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_contributor_earnings(request):
    """
    List all ContributorEarnings records for the authenticated user (as participant).
    """
    from .models import ContributorEarnings
    from .serializers import ContributorEarningsSerializer
    earnings = ContributorEarnings.objects.filter(participant=request.user).order_by('-created_at')
    serializer = ContributorEarningsSerializer(earnings, many=True)
    return Response(serializer.data)
from .paymentlog_serializer import PaymentLogSerializer

# --- User Payment Log API ---
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_payment_logs(request):
    """
    List all payment transactions for the authenticated user.
    """
    from .models import PaymentLog
    logs = PaymentLog.objects.filter(user=request.user).order_by('-created_at')
    serializer = PaymentLogSerializer(logs, many=True)
    return Response(serializer.data)
import json
import requests
# --- PayPal Webhook Endpoint ---
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def paypal_webhook(request):
    """
    PayPal webhook endpoint to securely verify payment events.
    Only grant premium after verifying payment with PayPal API.
    """
    # Parse webhook event
    try:
        event = json.loads(request.body.decode('utf-8'))
    except Exception:
        return JsonResponse({'error': 'Invalid payload'}, status=400)

    # Example: handle completed payment event
    if event.get('event_type') == 'CHECKOUT.ORDER.APPROVED':
        order_id = event['resource']['id']
        # Verify order with PayPal API
        access_token = get_paypal_access_token()
        order_info = get_paypal_order_info(order_id, access_token)
        if not order_info or order_info.get('status') != 'COMPLETED':
            return JsonResponse({'error': 'Order not completed'}, status=400)
        # Lookup user by custom_id (set in PayPal order creation)
        try:
            custom_id = order_info['purchase_units'][0].get('custom_id')
            if not custom_id:
                return JsonResponse({'error': 'No custom_id in order'}, status=400)
            from django.contrib.auth import get_user_model
            User = get_user_model()
            user = User.objects.get(id=custom_id)
        except Exception:
            return JsonResponse({'error': 'User not found for custom_id'}, status=404)
        # Activate premium for user (example: set is_premium True)
        userprofile = getattr(user, 'userprofile', None)
        if userprofile:
            userprofile.is_premium = True
            userprofile.save(update_fields=['is_premium'])
        # Log transaction for auditing
        from .models import PaymentLog
        try:
            PaymentLog.objects.create(
                user=user,
                provider='paypal',
                order_id=order_id,
                amount=order_info['purchase_units'][0]['amount']['value'],
                currency=order_info['purchase_units'][0]['amount'].get('currency_code', 'USD'),
                status=order_info.get('status', ''),
                raw_data=order_info,
            )
        except Exception as e:
            # Log error or ignore if logging fails
            pass
        return JsonResponse({'success': True, 'user_id': user.id})
    # Add more event types as needed
    return JsonResponse({'ok': True})

def get_paypal_access_token():
    """Obtain OAuth2 access token from PayPal."""
    client_id = os.environ.get('PAYPAL_CLIENT_ID')
    secret = os.environ.get('PAYPAL_SECRET')
    url = 'https://api-m.paypal.com/v1/oauth2/token'
    resp = requests.post(url, auth=(client_id, secret), data={'grant_type': 'client_credentials'})
    if resp.status_code == 200:
        return resp.json()['access_token']
    return None

def get_paypal_order_info(order_id, access_token):
    """Fetch order details from PayPal to verify payment status."""
    url = f'https://api-m.paypal.com/v2/checkout/orders/{order_id}'
    headers = {'Authorization': f'Bearer {access_token}'}
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        return resp.json()
    return None
from django.shortcuts import render
from django.conf import settings
from django.contrib.auth import authenticate, login as auth_login
import os
import re as _re
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.http import JsonResponse

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

# Add missing User import
from django.contrib.auth.models import User

# --- OpenAI Chat API Endpoint ---
@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def openai_chat(request):
    """
    Proxy endpoint for OpenAI ChatCompletion API.
    POST body: {"message": "your question"}
    """
    data = request.data
    user_message = data.get('message', '')
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return JsonResponse({'error': 'OpenAI API key not set.'}, status=500)
    try:
        import openai
        openai.api_key = api_key
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": user_message}]
        )
        reply = response['choices'][0]['message']['content']
        return JsonResponse({'reply': reply})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
from .models import CollabReliabilityRating, CollabReview, Post
from .serializers import CollabReliabilityRatingSerializer, CollabReviewSerializer, PostSerializer
# --- Post API Endpoints ---
from rest_framework.permissions import IsAuthenticated

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_or_update_post(request):
    """
    Create a new post or update an existing one (if id is provided and user is author).
    POST body: {"id": optional, "title": ..., "content": ..., "post_type": ..., "is_public": ...}
    """
    data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
    # Only allow certain fields to be set by user
    allowed_fields = {'id', 'title', 'content', 'post_type', 'is_public'}
    sanitized = {k: v for k, v in data.items() if k in allowed_fields}
    post_id = sanitized.get('id')
    if post_id:
        try:
            post = Post.objects.get(id=post_id)
        except Post.DoesNotExist:
            return JsonResponse({'error': 'Post not found.'}, status=404)
        if post.author != request.user:
            return JsonResponse({'error': 'Not authorized.'}, status=403)
        serializer = PostSerializer(post, data=sanitized, partial=True)
    else:
        serializer = PostSerializer(data={**sanitized, 'author': request.user.id})
    if serializer.is_valid():
        post = serializer.save(author=request.user)
        return JsonResponse(PostSerializer(post).data, status=201)
    return JsonResponse(serializer.errors, status=400)

@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def toggle_post_sharing(request, post_id):
    """
    Toggle the is_public (shareable) status of a post.
    PATCH body: {"is_public": true/false}
    """
    try:
        post = Post.objects.get(id=post_id, author=request.user)
    except Post.DoesNotExist:
        return JsonResponse({'error': 'Post not found or not authorized.'}, status=404)
    is_public = request.data.get('is_public')
    if is_public is None:
        return JsonResponse({'error': 'is_public required.'}, status=400)
    post.is_public = bool(is_public)
    post.save(update_fields=['is_public'])
    return JsonResponse({'id': post.id, 'is_public': post.is_public})

@api_view(['GET'])
@permission_classes([AllowAny])
def export_post(request, post_id):
    """
    Export a post as JSON (public posts only, or if user is author).
    """
    try:
        post = Post.objects.get(id=post_id)
    except Post.DoesNotExist:
        return JsonResponse({'error': 'Post not found.'}, status=404)
    if not post.is_public and (not request.user.is_authenticated or post.author != request.user):
        return JsonResponse({'error': 'Not authorized.'}, status=403)
    return JsonResponse(PostSerializer(post).data)

@api_view(['GET'])
@permission_classes([AllowAny])
def download_post(request, post_id):
    """
    Download a post as a text file (public posts only, or if user is author).
    """
    try:
        post = Post.objects.get(id=post_id)
    except Post.DoesNotExist:
        return JsonResponse({'error': 'Post not found.'}, status=404)
    if not post.is_public and (not request.user.is_authenticated or post.author != request.user):
        return JsonResponse({'error': 'Not authorized.'}, status=403)
    content = f"Title: {post.title}\nType: {post.post_type}\nAuthor: {post.author.username}\n\n{post.content}"
    from django.http import HttpResponse
    response = HttpResponse(content, content_type='text/plain')
    response['Content-Disposition'] = f'attachment; filename=post_{post.id}.txt'
    return response
# --- Reliability Rating API ---
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def set_reliability_rating(request, agreement_id, ratee_id):
    """
    Set or update reliability rating for a collaborator in an agreement.
    Only participants can rate each other.
    """
    user = request.user
    try:
        agreement = CollabRoyaltyAgreement.objects.get(id=agreement_id)
        ratee = User.objects.get(id=ratee_id)
    except (CollabRoyaltyAgreement.DoesNotExist, User.DoesNotExist):
        return Response({'error': 'Agreement or user not found.'}, status=404)
    # Must be a participant
    if not CollabRoyaltySplit.objects.filter(agreement=agreement, participant=user).exists() or not CollabRoyaltySplit.objects.filter(agreement=agreement, participant=ratee).exists():
        return Response({'error': 'Not authorized.'}, status=403)
    score = int(request.data.get('score', 0))
    if score < 0 or score > 10:
        return Response({'error': 'Score must be 0-10.'}, status=400)
    obj, _ = CollabReliabilityRating.objects.update_or_create(
        agreement=agreement, rater=user, ratee=ratee,
        defaults={'score': score}
    )
    return Response(CollabReliabilityRatingSerializer(obj).data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_reliability_ratings(request, agreement_id):
    """
    Get all reliability ratings for an agreement.
    """
    ratings = CollabReliabilityRating.objects.filter(agreement_id=agreement_id)
    return Response(CollabReliabilityRatingSerializer(ratings, many=True).data)

# --- Collab Review API ---
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def set_collab_review(request, agreement_id, reviewee_id):
    """
    Set or update a review for a collaborator in an agreement.
    Only participants can review each other.
    """
    user = request.user
    try:
        agreement = CollabRoyaltyAgreement.objects.get(id=agreement_id)
        reviewee = User.objects.get(id=reviewee_id)
    except (CollabRoyaltyAgreement.DoesNotExist, User.DoesNotExist):
        return Response({'error': 'Agreement or user not found.'}, status=404)
    if not CollabRoyaltySplit.objects.filter(agreement=agreement, participant=user).exists() or not CollabRoyaltySplit.objects.filter(agreement=agreement, participant=reviewee).exists():
        return Response({'error': 'Not authorized.'}, status=403)
    text = request.data.get('text', '')
    is_shared = bool(request.data.get('is_shared', False))
    obj, _ = CollabReview.objects.update_or_create(
        agreement=agreement, reviewer=user, reviewee=reviewee,
        defaults={'text': text, 'is_shared': is_shared}
    )
    return Response(CollabReviewSerializer(obj).data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_collab_reviews(request, agreement_id):
    """
    Get all reviews for an agreement.
    """
    reviews = CollabReview.objects.filter(agreement_id=agreement_id)
    return Response(CollabReviewSerializer(reviews, many=True).data)

@api_view(['GET'])
@permission_classes([AllowAny])
def get_shared_reviews_for_user(request, user_id):
    """
    Get all shared reviews for a user (for profile display).
    """
    reviews = CollabReview.objects.filter(reviewee_id=user_id, is_shared=True)
    return Response(CollabReviewSerializer(reviews, many=True).data)
import requests

# --- LibreTranslate API Integration ---
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
@api_view(['POST'])
@permission_classes([AllowAny])
def translate_text(request):
    """
    Translate text using the LibreTranslate public API.
    POST body: {"q": "text", "source": "en", "target": "es"}
    """
    data = request.data
    q = data.get('q', '')
    source = data.get('source', 'auto')
    target = data.get('target', 'en')
    if not q or not target:
        return JsonResponse({'error': 'Missing text or target language.'}, status=400)
    try:
        resp = requests.post(
            'https://libretranslate.com/translate',
            data={
                'q': q,
                'source': source,
                'target': target,
                'format': 'text'
            },
            timeout=10
        )
        resp.raise_for_status()
        translated = resp.json().get('translatedText', '')
        return JsonResponse({'translated': translated})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
from .serializers import AgreementTemplateSerializer, CollabRoyaltyAgreementSerializer, AgreementChangeLogSerializer, CollabRoyaltySplitSerializer
from rest_framework.parsers import JSONParser
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core import serializers as dj_serializers
import csv
import json

# --- Agreement Template Endpoints ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_agreement_templates(request):
    templates = AgreementTemplate.objects.all()
    serializer = AgreementTemplateSerializer(templates, many=True)
    return Response(serializer.data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_agreement_template(request):
    serializer = AgreementTemplateSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save(created_by=request.user)
        return Response(serializer.data, status=201)
    return Response(serializer.errors, status=400)

# --- Agreement Versioning ---
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_agreement_version(request, agreement_id):
    try:
        agreement = CollabRoyaltyAgreement.objects.get(id=agreement_id)
    except CollabRoyaltyAgreement.DoesNotExist:
        return Response({'error': 'Agreement not found.'}, status=404)
    data = request.data.copy()
    data['previous_version'] = agreement.id
    data['version'] = agreement.version + 1
    serializer = CollabRoyaltyAgreementSerializer(data=data)
    if serializer.is_valid():
        new_agreement = serializer.save(created_by=request.user)
        AgreementChangeLog.objects.create(
            agreement=new_agreement,
            changed_by=request.user,
            change_summary='New version created',
            old_text=agreement.agreement_text,
            new_text=new_agreement.agreement_text,
        )
        return Response(CollabRoyaltyAgreementSerializer(new_agreement).data, status=201)
    return Response(serializer.errors, status=400)

# --- E-signature/Acceptance ---
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def sign_royalty_split(request, split_id):
    try:
        split = CollabRoyaltySplit.objects.get(id=split_id, participant=request.user)
    except CollabRoyaltySplit.DoesNotExist:
        return Response({'error': 'Split not found or not authorized.'}, status=404)
    split.accepted = True
    split.e_signature = request.data.get('e_signature', 'signed')
    split.accepted_at = timezone.now()
    split.save()
    return Response({'success': 'Agreement signed.'})

# --- Change History ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def agreement_change_history(request, agreement_id):
    logs = AgreementChangeLog.objects.filter(agreement_id=agreement_id).order_by('-change_time')
    serializer = AgreementChangeLogSerializer(logs, many=True)
    return Response(serializer.data)

# --- Export Endpoints ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def export_agreement_json(request, agreement_id):
    try:
        agreement = CollabRoyaltyAgreement.objects.get(id=agreement_id)
    except CollabRoyaltyAgreement.DoesNotExist:
        return Response({'error': 'Agreement not found.'}, status=404)
    serializer = CollabRoyaltyAgreementSerializer(agreement)
    return Response(serializer.data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def export_agreement_csv(request, agreement_id):
    try:
        agreement = CollabRoyaltyAgreement.objects.get(id=agreement_id)
    except CollabRoyaltyAgreement.DoesNotExist:
        return Response({'error': 'Agreement not found.'}, status=404)
    splits = CollabRoyaltySplit.objects.filter(agreement=agreement)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="royalty_agreement_{agreement.id}.csv"'
    writer = csv.writer(response)
    writer.writerow(['Participant', 'Percentage', 'Accepted', 'Accepted At', 'E-signature'])
    for split in splits:
        writer.writerow([split.participant.username, split.percentage, split.accepted, split.accepted_at, split.e_signature])
    return response

# --- Notification/Reminder Stub ---
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_agreement_reminder(request, agreement_id):
    # Stub: In production, send email notifications to unsigned participants
    return Response({'success': 'Reminder sent (stub).'}, status=200)
from django.http import HttpResponse, Http404
from .models import CollabRoyaltyAgreement, CollabRoyaltySplit, AgreementTemplate, AgreementChangeLog
from django.utils import timezone
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from io import BytesIO
# --- Royalty Agreement PDF Download Endpoint ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def download_royalty_agreement_pdf(request, agreement_id):
    # Import PDF dependencies lazily so missing/broken ReportLab does not break app startup.
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
    except Exception:
        return Response({'error': 'PDF generation is temporarily unavailable.'}, status=503)

    try:
        agreement = CollabRoyaltyAgreement.objects.get(id=agreement_id)
    except CollabRoyaltyAgreement.DoesNotExist:
        raise Http404("Agreement not found")
    if not agreement.is_finalized:
        return Response({'error': 'Agreement not finalized.'}, status=400)
    # Only participants or creator can download
    user = request.user
    is_participant = CollabRoyaltySplit.objects.filter(agreement=agreement, participant=user).exists()
    if not (is_participant or agreement.created_by == user):
        return Response({'error': 'Not authorized.'}, status=403)
    # Generate PDF
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    y = height - 40
    p.setFont("Helvetica-Bold", 16)
    p.drawString(40, y, f"Royalty Agreement: {agreement.title}")
    y -= 30
    p.setFont("Helvetica", 12)
    p.drawString(40, y, f"Created by: {agreement.created_by.username}  |  Date: {agreement.created_at.strftime('%Y-%m-%d')}")
    y -= 30
    p.setFont("Helvetica", 11)
    p.drawString(40, y, "Description:")
    y -= 18
    for line in agreement.description.splitlines():
        p.drawString(60, y, line)
        y -= 15
    y -= 10
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, "Royalty Splits:")
    y -= 20
    splits = CollabRoyaltySplit.objects.filter(agreement=agreement)
    for split in splits:
        status = "Accepted" if split.accepted else "Pending"
        p.setFont("Helvetica", 11)
        p.drawString(60, y, f"{split.participant.username}: {split.percentage}%  ({status})")
        y -= 15
    y -= 10
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, "Agreement Text:")
    y -= 18
    p.setFont("Helvetica", 10)
    for line in agreement.agreement_text.splitlines():
        p.drawString(60, y, line)
        y -= 13
        if y < 60:
            p.showPage()
            y = height - 40
    p.showPage()
    p.save()
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="royalty_agreement_{agreement.id}.pdf"'
    return response
import os
import requests
import random
from datetime import timedelta

from allauth.socialaccount.models import SocialApp
from allauth.socialaccount.models import SocialAccount
from django.db import transaction
from django.core.mail import send_mail
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.authentication import SessionAuthentication
from .models import AuthAuditLog, SiteAnalytics, VisitorRecord, UserProfile, Referral
from .serializers import RegisterSerializer, UserProfileSerializer, ReferralSerializer
# --- Referral System API Endpoints ---
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView


class CsrfExemptSessionAuthentication(SessionAuthentication):
    def enforce_csrf(self, request):
        return


@api_view(['GET'])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def auth_csrf(request):
    return Response({'success': True, 'message': 'CSRF cookie set.'})


def _request_ip(request):
    forwarded_for = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
    return forwarded_for or (request.META.get('REMOTE_ADDR') or '')


def _record_auth_event(request, *, event, outcome, user=None, identifier='', provider='', details=None):
    safe_details = details if isinstance(details, dict) else {}
    try:
        AuthAuditLog.objects.create(
            user=user if getattr(user, 'pk', None) else None,
            event=event,
            outcome=outcome,
            provider=(provider or '')[:32],
            identifier=(identifier or '')[:255],
            ip_address=_request_ip(request)[:64],
            user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:512],
            details=safe_details,
        )
    except Exception:
        pass


def _safe_auth_login(request, user):
    """Best-effort session login. Registration must not fail if session write fails."""
    try:
        auth_login(request, user)
        return True
    except Exception:
        return False

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def referral_stats(request):
    user = request.user
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        return Response({'error': 'Profile not found.'}, status=404)
    referrals = Referral.objects.filter(referrer=user)
    serializer = ReferralSerializer(referrals, many=True)
    return Response({
        'referral_code': profile.referral_code,
        'referral_count': referrals.count(),
        'referrals': serializer.data,
    })

@api_view(['POST'])
@permission_classes([AllowAny])
@authentication_classes([CsrfExemptSessionAuthentication])
def register_with_referral(request):
    referral_code = request.data.get('referral_code')
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        _safe_auth_login(request, user)
        if referral_code:
            try:
                referrer_profile = UserProfile.objects.get(referral_code=referral_code)
                Referral.objects.create(referrer=referrer_profile.user, referred=user)
                user.profile.referred_by = referrer_profile
                user.profile.save()
            except UserProfile.DoesNotExist:
                pass  # Invalid code, ignore
        _record_auth_event(
            request,
            event='register',
            outcome='success',
            user=user,
            identifier=user.email or user.username,
            details={'referral_code_used': bool(referral_code)},
        )
        return Response({"success": "User registered successfully."}, status=status.HTTP_201_CREATED)
    _record_auth_event(
        request,
        event='register',
        outcome='failure',
        identifier=(request.data.get('email') or request.data.get('username') or request.data.get('phone_number') or '')[:255],
        details={'errors': serializer.errors},
    )
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# API endpoint for user registration
@api_view(['POST'])
@permission_classes([AllowAny])
@authentication_classes([CsrfExemptSessionAuthentication])
def api_register(request):
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        _safe_auth_login(request, user)
        _record_auth_event(
            request,
            event='register',
            outcome='success',
            user=user,
            identifier=user.email or user.username,
        )
        return Response({
            "success": "User registered successfully.",
            "user": {
                'id': user.id,
                'email': user.email,
                'username': user.username,
            }
        }, status=status.HTTP_201_CREATED)
    _record_auth_event(
        request,
        event='register',
        outcome='failure',
        identifier=(request.data.get('email') or request.data.get('username') or request.data.get('phone_number') or '')[:255],
        details={'errors': serializer.errors},
    )
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
@authentication_classes([CsrfExemptSessionAuthentication])
def api_login(request):
    identifier = (request.data.get('identifier') or request.data.get('email') or '').strip()
    # Preserve the exact password value; trimming can break valid credentials.
    password = request.data.get('password') or ''

    if not identifier or not password:
        _record_auth_event(
            request,
            event='login',
            outcome='failure',
            identifier=identifier,
            details={'reason': 'missing_credentials'},
        )
        return Response({'error': 'Identifier and password are required.'}, status=status.HTTP_400_BAD_REQUEST)

    user = None

    def _normalize_phone(value):
        return ''.join(ch for ch in str(value or '') if ch.isdigit())

    # Try email lookup
    if '@' in identifier:
        try:
            u = User.objects.get(email__iexact=identifier)
            user = authenticate(request, username=u.username, password=password)
        except User.DoesNotExist:
            pass

    # Try phone lookup
    if user is None and _re.match(r'^\+?\d[\d\s\-(). ]{5,}$', identifier):
        normalized_input = _normalize_phone(identifier)
        profiles = UserProfile.objects.exclude(phone_number='').select_related('user')
        for prof in profiles:
            if _normalize_phone(prof.phone_number) == normalized_input:
                user = authenticate(request, username=prof.user.username, password=password)
                if user is not None:
                    break

    # Try username lookup
    if user is None:
        user = authenticate(request, username=identifier, password=password)
    if user is None:
        u = User.objects.filter(username__iexact=identifier).first()
        if u is not None:
            user = authenticate(request, username=u.username, password=password)

    if user is None:
        _record_auth_event(
            request,
            event='login',
            outcome='failure',
            identifier=identifier,
            details={'reason': 'invalid_credentials'},
        )
        return Response({'error': 'Invalid credentials.'}, status=status.HTTP_401_UNAUTHORIZED)

    if not user.is_active:
        _record_auth_event(
            request,
            event='login',
            outcome='failure',
            user=user,
            identifier=identifier,
            details={'reason': 'inactive_account'},
        )
        return Response({'error': 'Account is inactive.'}, status=status.HTTP_403_FORBIDDEN)

    auth_login(request, user)
    profile = UserProfile.objects.filter(user=user).first()
    phone_number = (profile.phone_number or '') if profile else ''
    _record_auth_event(
        request,
        event='login',
        outcome='success',
        user=user,
        identifier=identifier or user.email or user.username,
    )
    return Response({
        'success': True,
        'user': {
            'id': user.id,
            'email': user.email,
            'username': user.username,
            'phone_number': phone_number,
        }
    })


def _generate_verification_code():
    return f"{random.randint(0, 999999):06d}"


def _notification_settings_payload(profile):
    return {
        'email_notifications': bool(profile.email_notifications),
        'push_notifications': bool(profile.push_notifications),
        'phone_notifications': bool(profile.phone_notifications),
        'marketing_notifications': bool(profile.marketing_notifications),
    }


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_email_verification_code(request):
    user = request.user
    profile, _ = UserProfile.objects.get_or_create(user=user)
    email = (user.email or '').strip()
    if not email:
        return Response({'error': 'Set an email on your account first.'}, status=status.HTTP_400_BAD_REQUEST)

    code = _generate_verification_code()
    profile.email_verification_code = code
    profile.email_verification_expires = timezone.now() + timedelta(minutes=10)
    profile.save(update_fields=['email_verification_code', 'email_verification_expires'])

    try:
        send_mail(
            subject='Music ConnectZ Email Verification Code',
            message=f'Your verification code is: {code}. It expires in 10 minutes.',
            from_email=None,
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception:
        return Response({'error': 'Unable to send verification email right now.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response({'success': True, 'message': 'Verification code sent to your email.'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_email_code(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    code = (request.data.get('code') or '').strip()
    if not code:
        return Response({'error': 'Verification code is required.'}, status=status.HTTP_400_BAD_REQUEST)
    if not profile.email_verification_code or not profile.email_verification_expires:
        return Response({'error': 'No active verification code. Request a new one.'}, status=status.HTTP_400_BAD_REQUEST)
    if timezone.now() > profile.email_verification_expires:
        return Response({'error': 'Verification code expired. Request a new one.'}, status=status.HTTP_400_BAD_REQUEST)
    if code != profile.email_verification_code:
        return Response({'error': 'Invalid verification code.'}, status=status.HTTP_400_BAD_REQUEST)

    profile.email_verified = True
    profile.email_verification_code = ''
    profile.email_verification_expires = None
    profile.save(update_fields=['email_verified', 'email_verification_code', 'email_verification_expires'])
    return Response({'success': True, 'email_verified': True})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_phone_verification_code(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    phone = (profile.phone_number or '').strip()
    if not phone:
        return Response({'error': 'Set a phone number on your account first.'}, status=status.HTTP_400_BAD_REQUEST)

    code = _generate_verification_code()
    profile.phone_verification_code = code
    profile.phone_verification_expires = timezone.now() + timedelta(minutes=10)
    profile.save(update_fields=['phone_verification_code', 'phone_verification_expires'])

    # SMS provider integration can be added later (Twilio, Vonage, etc.).
    print(f"[PHONE_VERIFICATION] user={request.user.id} phone={phone} code={code}")

    return Response({'success': True, 'message': 'Verification code generated for your phone.'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_phone_code(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    code = (request.data.get('code') or '').strip()
    if not code:
        return Response({'error': 'Verification code is required.'}, status=status.HTTP_400_BAD_REQUEST)
    if not profile.phone_verification_code or not profile.phone_verification_expires:
        return Response({'error': 'No active verification code. Request a new one.'}, status=status.HTTP_400_BAD_REQUEST)
    if timezone.now() > profile.phone_verification_expires:
        return Response({'error': 'Verification code expired. Request a new one.'}, status=status.HTTP_400_BAD_REQUEST)
    if code != profile.phone_verification_code:
        return Response({'error': 'Invalid verification code.'}, status=status.HTTP_400_BAD_REQUEST)

    profile.phone_verified = True
    profile.phone_verification_code = ''
    profile.phone_verification_expires = None
    profile.save(update_fields=['phone_verified', 'phone_verification_code', 'phone_verification_expires'])
    return Response({'success': True, 'phone_verified': True})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_notification_settings(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return Response({
        'settings': _notification_settings_payload(profile),
        'email_verified': bool(profile.email_verified),
        'phone_verified': bool(profile.phone_verified),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_notification_settings(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    payload = request.data if isinstance(request.data, dict) else {}

    email_notifications = bool(payload.get('email_notifications', profile.email_notifications))
    push_notifications = bool(payload.get('push_notifications', profile.push_notifications))
    phone_notifications = bool(payload.get('phone_notifications', profile.phone_notifications))
    marketing_notifications = bool(payload.get('marketing_notifications', profile.marketing_notifications))

    if email_notifications and not profile.email_verified:
        return Response({'error': 'Verify email before enabling email notifications.'}, status=status.HTTP_400_BAD_REQUEST)
    if phone_notifications and not profile.phone_verified:
        return Response({'error': 'Verify phone before enabling SMS notifications.'}, status=status.HTTP_400_BAD_REQUEST)

    profile.email_notifications = email_notifications
    profile.push_notifications = push_notifications
    profile.phone_notifications = phone_notifications
    profile.marketing_notifications = marketing_notifications
    profile.save(update_fields=['email_notifications', 'push_notifications', 'phone_notifications', 'marketing_notifications'])

    return Response({'success': True, 'settings': _notification_settings_payload(profile)})


from django.http import JsonResponse


@api_view(['GET'])
@permission_classes([AllowAny])
def api_auth_me(request):
    user = getattr(request, 'user', None)
    if user and user.is_authenticated:
        try:
            profile, _ = UserProfile.objects.get_or_create(user=user)
            phone_number = (getattr(profile, 'phone_number', '') or '').strip()
            email_verified = bool(getattr(profile, 'email_verified', False))
            phone_verified = bool(getattr(profile, 'phone_verified', False))
            notification_settings = _notification_settings_payload(profile)
        except Exception:
            profile = None
            phone_number = ''
            email_verified = False
            phone_verified = False
            notification_settings = {
                'email_notifications': True,
                'push_notifications': True,
                'phone_notifications': False,
                'marketing_notifications': False,
            }

        profile_completed = bool((user.username or '').strip() and (user.email or '').strip() and phone_number)
        return Response({
            'authenticated': True,
            'user': {
                'id': user.id,
                'email': getattr(user, 'email', '') or '',
                'username': getattr(user, 'username', '') or '',
                'phone_number': phone_number,
                'profile_completed': profile_completed,
                'email_verified': email_verified,
                'phone_verified': phone_verified,
                'notification_settings': notification_settings,
            }
        })
    return Response({'authenticated': False}, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def api_auth_users(request):
    return Response({'totalUsers': User.objects.count()})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_connected_accounts(request):
    connected = list(
        SocialAccount.objects.filter(user=request.user)
        .order_by('provider')
        .values_list('provider', flat=True)
    )
    return Response({'connected': connected})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@authentication_classes([CsrfExemptSessionAuthentication])
def complete_oauth_profile(request):
    user = request.user
    username = (request.data.get('username') or '').strip()
    email = (request.data.get('email') or '').strip()
    phone_number = (request.data.get('phone_number') or '').strip()

    if not username or not email or not phone_number:
        _record_auth_event(
            request,
            event='oauth_profile_complete',
            outcome='failure',
            user=user,
            identifier=email or username,
            details={'reason': 'missing_required_fields'},
        )
        return Response({'error': 'username, email, and phone_number are required.'}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.exclude(pk=user.pk).filter(username__iexact=username).exists():
        _record_auth_event(
            request,
            event='oauth_profile_complete',
            outcome='failure',
            user=user,
            identifier=email or username,
            details={'reason': 'username_taken'},
        )
        return Response({'error': 'Username already taken.'}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.exclude(pk=user.pk).filter(email__iexact=email).exists():
        _record_auth_event(
            request,
            event='oauth_profile_complete',
            outcome='failure',
            user=user,
            identifier=email,
            details={'reason': 'email_taken'},
        )
        return Response({'error': 'Email already taken.'}, status=status.HTTP_400_BAD_REQUEST)

    user.username = username
    user.email = email
    user.save(update_fields=['username', 'email'])

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.phone_number = phone_number
    profile.save(update_fields=['phone_number'])

    provider = (
        SocialAccount.objects.filter(user=user)
        .order_by('id')
        .values_list('provider', flat=True)
        .first()
        or ''
    )
    _record_auth_event(
        request,
        event='oauth_profile_complete',
        outcome='success',
        user=user,
        identifier=email or username,
        provider=provider,
    )

    return Response({
        'success': 'Profile completed.',
        'user': {
            'id': user.id,
            'email': user.email,
            'username': user.username,
            'phone_number': profile.phone_number,
            'profile_completed': True,
        }
    }, status=status.HTTP_200_OK)


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
        'instagram': 'instagram',
        'twitter': 'twitter_oauth2',
        'linkedin': 'linkedin_oauth2',
        'github': 'github',
        'google': 'google',
        'amazon': 'amazon',
        'discogs': 'discogs',
        'patreon': 'patreon',
        'spotify': 'spotify',
        'soundcloud': 'soundcloud',
        'tiktok': 'tiktok',
        'twitch': 'twitch',
    }

    socialaccount_settings = getattr(settings, 'SOCIALACCOUNT_PROVIDERS', {})
    providers = {}
    for frontend_provider, allauth_provider in provider_map.items():
        app = SocialApp.objects.filter(provider=allauth_provider).order_by('id').first()
        db_configured = bool(app and app.client_id and app.secret)
        env_app = socialaccount_settings.get(allauth_provider, {}).get('APP', {})
        env_configured = bool(env_app.get('client_id') and env_app.get('secret'))
        providers[frontend_provider] = db_configured or env_configured

    return JsonResponse({
        'providers': providers,
        'any_available': any(providers.values()),
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def site_analytics(request):
    visitor_key = (request.GET.get('visitor_key') or '').strip()[:128]
    try:
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
    except Exception:
        try:
            analytics = SiteAnalytics.objects.filter(key='global').first()
            return Response({
                'totalVisits': int(getattr(analytics, 'total_visits', 0) or 0),
                'uniqueVisitors': int(getattr(analytics, 'unique_visitors', 0) or 0),
            })
        except Exception:
            return Response({'totalVisits': 0, 'uniqueVisitors': 0})


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
        # Let users enter coupon/promo codes directly in Stripe Checkout.
        'allow_promotion_codes': 'true',
    }


def _apply_checkout_discounts(checkout_payload, payload):
    """
    Optionally apply explicit Stripe discount IDs when provided by frontend.
    Frontend can send either:
    - promotion_code_id / stripe_promotion_code_id
    - coupon_id / stripe_coupon_id
    """
    promo_id = _payload_first(payload, 'promotion_code_id', 'stripe_promotion_code_id')
    coupon_id = _payload_first(payload, 'coupon_id', 'stripe_coupon_id')

    if promo_id:
        checkout_payload['discounts[0][promotion_code]'] = str(promo_id)
    elif coupon_id:
        checkout_payload['discounts[0][coupon]'] = str(coupon_id)

    return bool(promo_id or coupon_id)


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


def _normalize_plan_type(value):
    plan_type = str(value or 'premium').strip().lower()
    if plan_type in ('stats', 'analytics', 'stats_connectz'):
        return 'stats'
    if plan_type in ('bundle', 'premium_plus_stats', 'premium-stats'):
        return 'bundle'
    return 'premium'


def _resolve_subscription_price_id(requested_price_id, billing_period, plan_type):
    # Frontend sends placeholders in dev; prefer backend env vars when placeholders are used.
    placeholders = {
        'price_premium_monthly',
        'price_premium_yearly',
        'price_stats_monthly',
        'price_stats_yearly',
        'price_bundle_monthly',
        'price_bundle_yearly',
    }
    if requested_price_id and requested_price_id not in placeholders:
        return requested_price_id

    period = (billing_period or '').lower()
    plan = _normalize_plan_type(plan_type)
    env_map = {
        ('premium', 'monthly'): 'STRIPE_PREMIUM_MONTHLY_PRICE_ID',
        ('premium', 'yearly'): 'STRIPE_PREMIUM_YEARLY_PRICE_ID',
        ('stats', 'monthly'): 'STRIPE_STATS_MONTHLY_PRICE_ID',
        ('stats', 'yearly'): 'STRIPE_STATS_YEARLY_PRICE_ID',
        ('bundle', 'monthly'): 'STRIPE_BUNDLE_MONTHLY_PRICE_ID',
        ('bundle', 'yearly'): 'STRIPE_BUNDLE_YEARLY_PRICE_ID',
    }
    env_key = env_map.get((plan, period), 'STRIPE_PREMIUM_MONTHLY_PRICE_ID')
    return os.environ.get(env_key, '').strip()


def _payload_first(payload, *keys, default=None):
    for key in keys:
        if key in payload and payload.get(key) not in (None, ''):
            return payload.get(key)
    return default


def _normalize_billing_period(value):
    period = str(value or 'monthly').strip().lower()
    if period in ('year', 'annual', 'annually', 'yearly'):
        return 'yearly'
    return 'monthly'


@api_view(['POST'])
@permission_classes([AllowAny])
def create_subscription_checkout(request):
    if not _stripe_secret_key():
        return Response({'error': 'Stripe is not configured on the backend.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    payload = request.data if isinstance(request.data, dict) else {}
    billing_period = _normalize_billing_period(
        _payload_first(payload, 'billingPeriod', 'billing_period', 'period', default='monthly')
    )
    plan_type = _normalize_plan_type(_payload_first(payload, 'planType', 'plan_type', 'plan', default='premium'))
    requested_price_id = _payload_first(payload, 'priceId', 'price_id')
    user_id = _payload_first(payload, 'userId', 'user_id', 'uid', default='')

    price_id = _resolve_subscription_price_id(requested_price_id, billing_period, plan_type)
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
        'client_reference_id': str(user_id),
        'metadata[userId]': str(user_id),
        'metadata[billingPeriod]': str(billing_period),
        'metadata[planType]': str(plan_type),
    })

    explicit_discount_applied = _apply_checkout_discounts(checkout_payload, payload)

    stripe_res, data = _create_stripe_checkout_session(checkout_payload)
    if stripe_res.status_code >= 400:
        return Response({'error': data.get('error', {}).get('message', 'Stripe checkout creation failed.')}, status=stripe_res.status_code)

    return Response({
        'url': data.get('url'),
        'id': data.get('id'),
        'promotion_codes_enabled': True,
        'explicit_discount_applied': explicit_discount_applied,
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def create_purchase_checkout(request):
    if not _stripe_secret_key():
        return Response({'error': 'Stripe is not configured on the backend.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    payload = request.data if isinstance(request.data, dict) else {}
    amount = _payload_first(payload, 'amount', 'price', 'total', 'value')
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

    explicit_discount_applied = _apply_checkout_discounts(checkout_payload, payload)

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

    return Response({
        'url': data.get('url'),
        'id': data.get('id'),
        'promotion_codes_enabled': True,
        'explicit_discount_applied': explicit_discount_applied,
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def cancel_subscription(request):
    # Frontend expects an OK response. Full Stripe subscription cancellation
    # requires persisted subscription IDs, which are not yet stored.
    return Response({'oClipZk': True, 'message': 'Cancellation request acknowledged.'})


@api_view(['POST'])
@permission_classes([AllowAny])
def use_collaboration_request(request):
    # Temporary permissive implementation until per-user quota persistence is added.
    return Response({'ok': True, 'remaining': -1})


def _release_validation_errors(release):
    errors = {}
    if not (release.title or '').strip():
        errors['title'] = 'Release title is required.'
    if not (release.primary_artist or '').strip():
        errors['primary_artist'] = 'Primary artist is required.'
    if not release.cover_art_file:
        errors['cover_art_file'] = 'Cover art is required.'
    if release.tracks.count() == 0:
        errors['tracks'] = 'At least one track is required.'
    else:
        for track in release.tracks.all():
            if not (track.title or '').strip():
                errors[f'track_{track.id}_title'] = 'Track title is required.'
            if not track.audio_file:
                errors[f'track_{track.id}_audio_file'] = 'Track audio file is required.'
    return errors


def _parse_webhook_event_time(raw_value):
    from django.utils.dateparse import parse_datetime

    value = str(raw_value or '').strip()
    if not value:
        return timezone.now()
    parsed = parse_datetime(value)
    if parsed is None:
        return timezone.now()
    if timezone.is_naive(parsed):
        try:
            return timezone.make_aware(parsed)
        except Exception:
            return timezone.now()
    return parsed


def _normalize_release_status_from_event(event_type, provider_status):
    et = str(event_type or '').strip().lower()
    ps = str(provider_status or '').strip().lower()
    source = f"{et} {ps}".strip()

    if any(token in source for token in ['failed', 'rejected', 'error', 'declined']):
        return 'failed'
    if any(token in source for token in ['delivered', 'live', 'published', 'active']):
        return 'delivered'
    if any(token in source for token in ['processing', 'queued', 'ingest', 'pending', 'review']):
        return 'processing'
    if any(token in source for token in ['submitted', 'received']):
        return 'submitted'
    return ''


def _normalize_release_submission_field_payload(payload):
    editable_fields = {
        'title',
        'version_title',
        'primary_artist',
        'release_type',
        'genre',
        'language',
        'explicit',
        'upc',
        'planned_release_date',
        'original_release_date',
    }

    cleaned = {}
    for key in editable_fields:
        if key not in payload:
            continue
        value = payload.get(key)
        if key in {'title', 'version_title', 'primary_artist', 'genre', 'upc'}:
            cleaned[key] = str(value or '').strip()
        elif key == 'language':
            cleaned[key] = str(value or '').strip().lower()[:32]
        elif key == 'release_type':
            cleaned[key] = str(value or '').strip().lower()
        else:
            cleaned[key] = value
    return cleaned


def _env_flag(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {'1', 'true', 'yes', 'on'}


def _user_has_distribution_premium(user):
    if not user or not user.is_authenticated:
        return False
    if user.is_staff or user.is_superuser:
        return True

    if getattr(settings, 'DISTRIBUTION_PREMIUM_ENFORCED', True) is False:
        return True

    if _env_flag('DISTRIBUTION_PREMIUM_ENFORCED', True) is False:
        return True

    allow_usernames = {
        x.strip().lower()
        for x in str(os.environ.get('DISTRIBUTION_PREMIUM_ALLOW_USERNAMES', '')).split(',')
        if x.strip()
    }
    allow_user_ids = {
        x.strip()
        for x in str(os.environ.get('DISTRIBUTION_PREMIUM_ALLOW_USER_IDS', '')).split(',')
        if x.strip()
    }

    if str(user.username).strip().lower() in allow_usernames:
        return True
    if str(user.id) in allow_user_ids:
        return True

    profile = getattr(user, 'userprofile', None)
    if profile is not None and hasattr(profile, 'is_premium') and bool(profile.is_premium):
        return True

    return False


def _user_has_feature(user, feature_key):
    """Check if user has access to a specific premium feature."""
    if not user or not user.is_authenticated:
        return False
    
    # Staff/superuser always have access
    if user.is_staff or user.is_superuser:
        return True
    
    # Check if full premium is enabled
    if _user_has_distribution_premium(user):
        return True
    
    # Check for specific feature subscription
    from .models import UserPremiumFeature
    subscription = UserPremiumFeature.objects.filter(
        user=user,
        feature__feature_key=feature_key,
    ).first()
    
    if subscription and subscription.is_active_now():
        return True
    
    return False


def _get_user_collab_agreement(user, agreement_id):
    from .models import CollabRoyaltyAgreement, CollabRoyaltySplit

    if not agreement_id:
        return None

    agreement = CollabRoyaltyAgreement.objects.filter(id=agreement_id).first()
    if not agreement:
        return None

    is_creator = agreement.created_by_id == user.id
    is_participant = CollabRoyaltySplit.objects.filter(agreement=agreement, participant=user).exists()
    if not (is_creator or is_participant):
        return None
    return agreement


def _apply_collab_royalties_to_release(release):
    from .models import CollabRoyaltySplit, ReleaseRoyaltySplit

    if not release.collab_agreement or not release.auto_apply_collab_royalties:
        return []

    agreement_splits = list(
        CollabRoyaltySplit.objects.filter(agreement=release.collab_agreement).select_related('participant')
    )
    if not agreement_splits:
        return []

    ReleaseRoyaltySplit.objects.filter(release=release).delete()
    created = []
    for split in agreement_splits:
        created.append(
            ReleaseRoyaltySplit.objects.create(
                release=release,
                participant=split.participant,
                percentage=split.percentage,
                source='agreement',
                agreement_split=split,
            )
        )
    return created


def _apply_collab_contributors_to_release(release):
    """Auto-snapshot collaborators from agreement as contributors with their roles."""
    from .models import CollabRoyaltySplit, ReleaseContributor

    if not release.collab_agreement or not release.auto_apply_collab_royalties:
        return []

    agreement_splits = list(
        CollabRoyaltySplit.objects.filter(agreement=release.collab_agreement).select_related('participant')
    )
    if not agreement_splits:
        return []

    ReleaseContributor.objects.filter(release=release, source='agreement').delete()
    created = []
    for split in agreement_splits:
        default_role = 'performer'
        role_meta = getattr(split, 'role_metadata_json', {})
        if isinstance(role_meta, dict):
            role_meta = split.role_metadata_json if hasattr(split, 'role_metadata_json') else {}
        role = str(role_meta.get('role')) if isinstance(role_meta, dict) else None
        if not role or role not in dict(ReleaseContributor.ROLE_CHOICES):
            role = default_role

        created.append(
            ReleaseContributor.objects.create(
                release=release,
                participant=split.participant,
                role=role,
                percentage=split.percentage,
                source='agreement',
                agreement_split=split,
                notes=f'Auto-applied from collaboration agreement {release.collab_agreement_id}',
            )
        )
    return created


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_distribution_accounts(request):
    from .models import DistributionAccount
    from .serializers import DistributionAccountSerializer

    accounts = DistributionAccount.objects.filter(user=request.user).order_by('-updated_at')
    return Response(DistributionAccountSerializer(accounts, many=True).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def connect_distribution_account(request):
    from .models import DistributionAccount
    from .serializers import DistributionAccountSerializer

    payload = request.data if isinstance(request.data, dict) else {}
    provider = str(payload.get('provider') or '').strip()
    if not provider:
        return Response({'error': 'provider is required.'}, status=status.HTTP_400_BAD_REQUEST)

    external_id = str(payload.get('external_account_id') or '').strip()
    scopes = str(payload.get('scopes_granted') or '').strip()
    account, _ = DistributionAccount.objects.update_or_create(
        user=request.user,
        provider=provider,
        external_account_id=external_id,
        defaults={
            'status': 'active',
            'scopes_granted': scopes,
        },
    )
    return Response(DistributionAccountSerializer(account).data, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_distribution_account(request, account_id):
    from .models import DistributionAccount

    account = DistributionAccount.objects.filter(id=account_id, user=request.user).first()
    if not account:
        return Response({'error': 'Distribution account not found.'}, status=status.HTTP_404_NOT_FOUND)
    account.delete()
    return Response({'success': True})


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def distribution_releases(request):
    from .models import Release
    from .serializers import ReleaseSerializer

    if request.method == 'GET':
        releases = Release.objects.filter(user=request.user).order_by('-updated_at')
        return Response(ReleaseSerializer(releases, many=True).data)

    payload = request.data if isinstance(request.data, dict) else {}
    collab_agreement_id = payload.get('collab_agreement')
    if collab_agreement_id:
        agreement = _get_user_collab_agreement(request.user, collab_agreement_id)
        if not agreement:
            return Response({'error': 'Invalid collab agreement for this user.'}, status=status.HTTP_403_FORBIDDEN)

    serializer = ReleaseSerializer(data=payload)
    if serializer.is_valid():
        release = serializer.save(user=request.user, status='draft')
        return Response(ReleaseSerializer(release).data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def distribution_release_detail(request, release_id):
    from .models import Release
    from .serializers import ReleaseSerializer

    release = Release.objects.filter(id=release_id, user=request.user).first()
    if not release:
        return Response({'error': 'Release not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(ReleaseSerializer(release).data)

    # For PATCH: Check if release is pending and user is not premium
    pending_statuses = ['submitted', 'processing', 'delivered']
    is_pending = release.status in pending_statuses
    is_premium = _user_has_distribution_premium(request.user)

    if is_pending and not is_premium:
        return Response(
            {
                'error': 'Cannot edit pending releases without premium access.',
                'requires_premium': True,
                'release_status': release.status,
            },
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )

    payload = request.data if isinstance(request.data, dict) else {}
    collab_agreement_id = payload.get('collab_agreement')
    if collab_agreement_id:
        agreement = _get_user_collab_agreement(request.user, collab_agreement_id)
        if not agreement:
            return Response({'error': 'Invalid collab agreement for this user.'}, status=status.HTTP_403_FORBIDDEN)

    serializer = ReleaseSerializer(release, data=payload, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(ReleaseSerializer(release).data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def distribution_release_submission_fields(request, release_id):
    from .models import Release, DistributionJob
    from .serializers import ReleaseSerializer

    release = Release.objects.filter(id=release_id, user=request.user).first()
    if not release:
        return Response({'error': 'Release not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(
            {
                'release_id': release.id,
                'editable_fields': [
                    'title',
                    'version_title',
                    'primary_artist',
                    'release_type',
                    'genre',
                    'language',
                    'explicit',
                    'upc',
                    'planned_release_date',
                    'original_release_date',
                ],
                'submission': {
                    'title': release.title,
                    'version_title': release.version_title,
                    'primary_artist': release.primary_artist,
                    'release_type': release.release_type,
                    'genre': release.genre,
                    'language': release.language,
                    'explicit': release.explicit,
                    'upc': release.upc,
                    'planned_release_date': release.planned_release_date,
                    'original_release_date': release.original_release_date,
                },
            }
        )

    pending_statuses = ['submitted', 'processing', 'delivered']
    if release.status in pending_statuses and not _user_has_distribution_premium(request.user):
        return Response(
            {
                'error': 'Cannot edit submitted release fields without premium access.',
                'requires_premium': True,
                'release_status': release.status,
            },
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )

    payload = request.data if isinstance(request.data, dict) else {}
    cleaned_payload = _normalize_release_submission_field_payload(payload)
    if not cleaned_payload:
        return Response({'error': 'No editable submission fields were provided.'}, status=status.HTTP_400_BAD_REQUEST)

    serializer = ReleaseSerializer(release, data=cleaned_payload, partial=True)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    serializer.save()
    DistributionJob.objects.create(
        release=release,
        provider=release.provider or 'generic_partner',
        operation='update_release_fields',
        request_payload_json=cleaned_payload,
        response_payload_json={'release_status': release.status},
        status='succeeded',
    )
    return Response({'success': True, 'release': ReleaseSerializer(release).data})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def distribution_release_tracks(request, release_id):
    from .models import Release
    from .serializers import TrackSerializer

    release = Release.objects.filter(id=release_id, user=request.user).first()
    if not release:
        return Response({'error': 'Release not found.'}, status=status.HTTP_404_NOT_FOUND)

    pending_statuses = ['submitted', 'processing', 'delivered']
    is_pending = release.status in pending_statuses
    is_premium = _user_has_distribution_premium(request.user)

    if is_pending and not is_premium:
        return Response(
            {
                'error': 'Cannot add tracks to pending releases without premium access.',
                'requires_premium': True,
                'release_status': release.status,
            },
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )

    serializer = TrackSerializer(data=request.data)
    if serializer.is_valid():
        track = serializer.save(release=release)
        return Response(TrackSerializer(track).data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def distribution_release_track_detail(request, release_id, track_id):
    from .models import Release, Track
    from .serializers import TrackSerializer

    release = Release.objects.filter(id=release_id, user=request.user).first()
    if not release:
        return Response({'error': 'Release not found.'}, status=status.HTTP_404_NOT_FOUND)

    track = Track.objects.filter(id=track_id, release=release).first()
    if not track:
        return Response({'error': 'Track not found.'}, status=status.HTTP_404_NOT_FOUND)

    pending_statuses = ['submitted', 'processing', 'delivered']
    is_pending = release.status in pending_statuses
    is_premium = _user_has_distribution_premium(request.user)

    if is_pending and not is_premium:
        return Response(
            {
                'error': 'Cannot edit tracks in pending releases without premium access.',
                'requires_premium': True,
                'release_status': release.status,
            },
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )

    serializer = TrackSerializer(track, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(TrackSerializer(track).data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def validate_distribution_release(request, release_id):
    from .models import Release

    release = Release.objects.filter(id=release_id, user=request.user).first()
    if not release:
        return Response({'error': 'Release not found.'}, status=status.HTTP_404_NOT_FOUND)

    errors = _release_validation_errors(release)
    release.validation_errors_json = errors
    release.save(update_fields=['validation_errors_json', 'updated_at'])
    if errors:
        return Response({'valid': False, 'errors': errors}, status=status.HTTP_400_BAD_REQUEST)
    return Response({'valid': True, 'errors': {}})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_distribution_release(request, release_id):
    from .models import Release, DistributionJob
    from .serializers import ReleaseSerializer

    release = Release.objects.filter(id=release_id, user=request.user).first()
    if not release:
        return Response({'error': 'Release not found.'}, status=status.HTTP_404_NOT_FOUND)

    if release.premium_required and not _user_has_distribution_premium(request.user):
        return Response(
            {
                'error': 'Premium distribution is required to submit releases.',
                'requires_premium': True,
            },
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )

    if release.collab_agreement_id:
        agreement = _get_user_collab_agreement(request.user, release.collab_agreement_id)
        if not agreement:
            return Response({'error': 'Invalid collab agreement for this user.'}, status=status.HTTP_403_FORBIDDEN)

    errors = _release_validation_errors(release)
    if release.collab_agreement_id and release.auto_apply_collab_royalties:
        created_splits = _apply_collab_royalties_to_release(release)
        if not created_splits:
            errors['royalty_splits'] = 'No royalty splits found on linked collaboration agreement.'
        created_contributors = _apply_collab_contributors_to_release(release)

    release.validation_errors_json = errors
    if errors:
        release.status = 'failed'
        release.save(update_fields=['validation_errors_json', 'status', 'updated_at'])
        return Response({'error': 'Release validation failed.', 'validation_errors': errors}, status=status.HTTP_400_BAD_REQUEST)

    payload = request.data if isinstance(request.data, dict) else {}
    provider = str(payload.get('provider') or release.provider or 'generic_partner').strip()
    provider_release_id = payload.get('provider_release_id') or f"local-{release.id}-{int(timezone.now().timestamp())}"

    release.provider = provider
    release.provider_release_id = str(provider_release_id)
    release.status = 'submitted'
    release.save(update_fields=['provider', 'provider_release_id', 'status', 'validation_errors_json', 'updated_at'])

    contributors_by_role = {}
    for contrib in release.contributors.select_related('participant').all().order_by('role', '-percentage'):
        role = contrib.get_role_display()
        if role not in contributors_by_role:
            contributors_by_role[role] = []
        contributors_by_role[role].append({
            'participant_id': contrib.participant_id,
            'participant_username': contrib.participant.username,
            'percentage': str(contrib.percentage),
            'source': contrib.source,
        })

    DistributionJob.objects.create(
        release=release,
        provider=provider,
        operation='submit_release',
        request_payload_json={
            'release_id': release.id,
            'collab_agreement_id': release.collab_agreement_id,
            'royalty_splits': [
                {
                    'participant_id': s.participant_id,
                    'percentage': str(s.percentage),
                    'source': s.source,
                }
                for s in release.royalty_splits.all().order_by('-percentage', 'participant_id')
            ],
            'contributors': contributors_by_role,
        },
        response_payload_json={'provider_release_id': release.provider_release_id},
        status='succeeded',
    )

    return Response({'success': True, 'release': ReleaseSerializer(release).data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def distribution_release_status(request, release_id):
    from .models import Release

    release = Release.objects.filter(id=release_id, user=request.user).first()
    if not release:
        return Response({'error': 'Release not found.'}, status=status.HTTP_404_NOT_FOUND)
    return Response({
        'release_id': release.id,
        'status': release.status,
        'provider': release.provider,
        'provider_release_id': release.provider_release_id,
        'collab_agreement_id': release.collab_agreement_id,
        'premium_required': release.premium_required,
        'royalty_splits': [
            {
                'participant_id': split.participant_id,
                'participant_username': split.participant.username,
                'percentage': str(split.percentage),
                'source': split.source,
            }
            for split in release.royalty_splits.select_related('participant').all().order_by('-percentage', 'participant_id')
        ],
        'validation_errors': release.validation_errors_json,
        'updated_at': release.updated_at,
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def distribution_provider_webhook(request, provider):
    import hashlib
    import hmac

    from .models import DistributionEvent, DistributionJob, Release

    provider_key = str(provider or '').strip().lower()
    if provider_key not in {'ditto', 'generic_partner'}:
        return Response({'error': 'Unsupported distribution provider.'}, status=status.HTTP_404_NOT_FOUND)

    payload = request.data if isinstance(request.data, dict) else {}
    if not payload:
        try:
            payload = json.loads((request.body or b'{}').decode('utf-8'))
        except Exception:
            payload = {}

    if provider_key == 'ditto':
        signature = (
            request.headers.get('X-Ditto-Signature')
            or request.headers.get('X-DITTO-SIGNATURE')
            or request.META.get('HTTP_X_DITTO_SIGNATURE')
            or ''
        ).strip()
        secret = str(os.environ.get('DITTO_WEBHOOK_SECRET', '')).strip()
        allow_unsigned = _env_flag('DITTO_WEBHOOK_ALLOW_UNSIGNED', default=False)

        signature_valid = False
        if secret and signature:
            digest = hmac.new(secret.encode('utf-8'), request.body or b'', hashlib.sha256).hexdigest()
            signature_valid = hmac.compare_digest(digest.lower(), signature.lower())
        elif allow_unsigned:
            signature_valid = True

        if not signature_valid:
            return Response({'error': 'Invalid webhook signature.'}, status=status.HTTP_401_UNAUTHORIZED)
    else:
        signature_valid = True

    provider_release_id = str(
        payload.get('provider_release_id')
        or payload.get('release_id')
        or payload.get('external_release_id')
        or (payload.get('data') or {}).get('provider_release_id')
        or (payload.get('data') or {}).get('release_id')
        or ''
    ).strip()

    release = None
    if provider_release_id:
        release = Release.objects.filter(provider=provider_key, provider_release_id=provider_release_id).order_by('-id').first()

    if release is None:
        local_release_id = payload.get('local_release_id') or (payload.get('data') or {}).get('local_release_id')
        if local_release_id:
            release = Release.objects.filter(id=local_release_id).order_by('-id').first()

    if release is None:
        return Response({'error': 'Release not found for webhook payload.'}, status=status.HTTP_404_NOT_FOUND)

    event_type = str(payload.get('event_type') or payload.get('type') or payload.get('event') or 'status_update').strip()[:64]
    provider_status = str(payload.get('status') or (payload.get('data') or {}).get('status') or '').strip()
    event_time = _parse_webhook_event_time(
        payload.get('event_time')
        or payload.get('occurred_at')
        or payload.get('timestamp')
        or (payload.get('data') or {}).get('event_time')
    )

    existing_event = DistributionEvent.objects.filter(
        release=release,
        provider=provider_key,
        event_type=event_type,
        event_time=event_time,
    ).order_by('-id').first()
    if existing_event and existing_event.payload_json == payload:
        return Response({'success': True, 'duplicate': True, 'release_status': release.status})

    event = DistributionEvent.objects.create(
        release=release,
        provider=provider_key,
        event_type=event_type,
        event_time=event_time,
        payload_json=payload,
        signature_valid=signature_valid,
        processed=False,
    )

    normalized_status = _normalize_release_status_from_event(event_type, provider_status)
    if normalized_status and normalized_status != release.status:
        release.status = normalized_status
        release.save(update_fields=['status', 'updated_at'])

    event.processed = True
    event.save(update_fields=['processed'])

    DistributionJob.objects.create(
        release=release,
        provider=provider_key,
        operation='webhook_event',
        request_payload_json=payload,
        response_payload_json={
            'event_id': event.id,
            'normalized_status': normalized_status or release.status,
            'signature_valid': signature_valid,
        },
        status='succeeded',
    )

    return Response(
        {
            'success': True,
            'event_id': event.id,
            'release_id': release.id,
            'release_status': release.status,
        }
    )


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def distribution_release_contributors(request, release_id):
    from .models import Release, ReleaseContributor
    from .serializers import ReleaseContributorSerializer

    release = Release.objects.filter(id=release_id, user=request.user).first()
    if not release:
        return Response({'error': 'Release not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        query = ReleaseContributor.objects.filter(release=release).select_related('participant')
        role_filter = request.query_params.get('role')
        if role_filter:
            query = query.filter(role=role_filter)
        contributors = query.order_by('role', '-percentage')
        return Response(ReleaseContributorSerializer(contributors, many=True).data)

    pending_statuses = ['submitted', 'processing', 'delivered']
    is_pending = release.status in pending_statuses
    is_premium = _user_has_distribution_premium(request.user)

    if is_pending and not is_premium:
        return Response(
            {
                'error': 'Cannot add contributors to pending releases without premium access.',
                'requires_premium': True,
                'release_status': release.status,
            },
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )

    payload = request.data if isinstance(request.data, dict) else {}
    participant_id = payload.get('participant')
    role = payload.get('role')
    percentage = payload.get('percentage')

    if not participant_id or not role or percentage is None:
        return Response(
            {'error': 'participant, role, and percentage are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        participant = User.objects.get(id=participant_id)
    except User.DoesNotExist:
        return Response({'error': 'Participant not found.'}, status=status.HTTP_404_NOT_FOUND)

    contributor, created = ReleaseContributor.objects.update_or_create(
        release=release,
        participant=participant,
        role=role,
        defaults={
            'percentage': percentage,
            'source': 'manual',
            'notes': payload.get('notes', ''),
        },
    )
    status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return Response(ReleaseContributorSerializer(contributor).data, status=status_code)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def distribution_release_contributor_detail(request, release_id, contributor_id):
    from .models import Release, ReleaseContributor
    from .serializers import ReleaseContributorSerializer

    release = Release.objects.filter(id=release_id, user=request.user).first()
    if not release:
        return Response({'error': 'Release not found.'}, status=status.HTTP_404_NOT_FOUND)

    contributor = ReleaseContributor.objects.filter(id=contributor_id, release=release).first()
    if not contributor:
        return Response({'error': 'Contributor not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(ReleaseContributorSerializer(contributor).data)

    pending_statuses = ['submitted', 'processing', 'delivered']
    is_pending = release.status in pending_statuses
    is_premium = _user_has_distribution_premium(request.user)

    if is_pending and not is_premium:
        return Response(
            {
                'error': 'Cannot edit or remove contributors from pending releases without premium access.',
                'requires_premium': True,
                'release_status': release.status,
            },
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )

    if request.method == 'DELETE':
        contributor.delete()
        return Response({'success': True})

    payload = request.data if isinstance(request.data, dict) else {}
    serializer = ReleaseContributorSerializer(contributor, data=payload, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(ReleaseContributorSerializer(contributor).data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def release_analytics(request, release_id):
    from .models import Release, ReleaseAnalytics
    from .serializers import ReleaseAnalyticsSerializer

    release = Release.objects.filter(id=release_id, user=request.user).first()
    if not release:
        return Response({'error': 'Release not found.'}, status=status.HTTP_404_NOT_FOUND)

    analytics, created = ReleaseAnalytics.objects.get_or_create(release=release)
    return Response(ReleaseAnalyticsSerializer(analytics).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def track_analytics(request, release_id, track_id):
    from .models import Release, Track, TrackAnalytics
    from .serializers import TrackAnalyticsSerializer

    release = Release.objects.filter(id=release_id, user=request.user).first()
    if not release:
        return Response({'error': 'Release not found.'}, status=status.HTTP_404_NOT_FOUND)

    track = Track.objects.filter(id=track_id, release=release).first()
    if not track:
        return Response({'error': 'Track not found.'}, status=status.HTTP_404_NOT_FOUND)

    analytics, created = TrackAnalytics.objects.get_or_create(track=track)
    return Response(TrackAnalyticsSerializer(analytics).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def contributor_earnings(request, release_id):
    from .models import Release, ContributorEarnings
    from .serializers import ContributorEarningsSerializer

    release = Release.objects.filter(id=release_id, user=request.user).first()
    if not release:
        return Response({'error': 'Release not found.'}, status=status.HTTP_404_NOT_FOUND)

    earnings = ContributorEarnings.objects.filter(release=release).select_related('participant')
    data = {
        'release_id': release.id,
        'release_title': release.title,
        'total_contributors': earnings.count(),
        'contributors': ContributorEarningsSerializer(earnings, many=True).data,
    }
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_total_earnings(request):
    from .models import ContributorEarnings
    from decimal import Decimal

    earnings = ContributorEarnings.objects.filter(participant=request.user).select_related('release')
    total_earned = sum(e.participant_share for e in earnings) or Decimal('0')
    total_pending = sum(e.participant_share for e in earnings.filter(payout_status='pending')) or Decimal('0')
    total_paid = sum(e.settled_amount for e in earnings.filter(payout_status='paid')) or Decimal('0')

    return Response({
        'user_id': request.user.id,
        'username': request.user.username,
        'total_earned': str(total_earned),
        'total_pending': str(total_pending),
        'total_paid': str(total_paid),
        'releases_contributed_to': earnings.values('release_id').distinct().count(),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def oauth_provider_profit_analytics(request):
    """
    Revenue attribution by auth provider for product/marketing decisions.
    Query params:
    - days: lookback window (default 30, max 365)
    """
    from decimal import Decimal
    from .models import AuthAuditLog, UserPremiumFeature

    try:
        days = int(request.query_params.get('days', 30))
    except Exception:
        days = 30
    if days < 1:
        days = 1
    if days > 365:
        days = 365

    since = timezone.now() - timedelta(days=days)

    # Use the earliest successful provider-tagged auth event as acquisition source.
    provider_events = (
        AuthAuditLog.objects
        .filter(outcome='success', user__isnull=False)
        .exclude(provider='')
        .values('user_id', 'provider', 'created_at')
        .order_by('user_id', 'created_at')
    )

    user_provider = {}
    for row in provider_events:
        uid = row['user_id']
        if uid not in user_provider:
            user_provider[uid] = (row['provider'] or 'unknown').strip().lower() or 'unknown'

    # Revenue events in lookback window.
    payments = UserPremiumFeature.objects.filter(
        last_payment_date__isnull=False,
        last_payment_date__gte=since,
        paid_amount__gt=0,
    ).select_related('user', 'feature')

    summary = {}
    total_revenue = Decimal('0')
    total_payers = set()

    for payment in payments:
        provider = user_provider.get(payment.user_id, 'unknown')
        if provider not in summary:
            summary[provider] = {
                'provider': provider,
                'revenue': Decimal('0'),
                'payments': 0,
                'payers': set(),
                'features_sold': {},
            }

        row = summary[provider]
        amount = payment.paid_amount or Decimal('0')
        row['revenue'] += amount
        row['payments'] += 1
        row['payers'].add(payment.user_id)
        feature_key = payment.feature_id
        row['features_sold'][feature_key] = row['features_sold'].get(feature_key, 0) + 1

        total_revenue += amount
        total_payers.add(payment.user_id)

    providers = []
    for provider, row in sorted(summary.items(), key=lambda kv: kv[1]['revenue'], reverse=True):
        rev = row['revenue']
        payer_count = len(row['payers'])
        arppu = (rev / payer_count) if payer_count else Decimal('0')
        revenue_share_pct = (rev * Decimal('100') / total_revenue) if total_revenue > 0 else Decimal('0')
        providers.append(
            {
                'provider': provider,
                'revenue': f"{rev:.2f}",
                'payments': row['payments'],
                'payers': payer_count,
                'arppu': f"{arppu:.2f}",
                'revenue_share_pct': f"{revenue_share_pct:.2f}",
                'features_sold': row['features_sold'],
            }
        )

    return Response(
        {
            'lookback_days': days,
            'since': since,
            'total_revenue': f"{total_revenue:.2f}",
            'total_payers': len(total_payers),
            'providers': providers,
        }
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def apple_oauth_profit_summary(request):
    from decimal import Decimal
    from .models import AuthAuditLog, UserPremiumFeature

    try:
        days = int(request.query_params.get('days', 30))
    except Exception:
        days = 30
    if days < 1:
        days = 1
    if days > 365:
        days = 365

    since = timezone.now() - timedelta(days=days)

    # Users with successful Apple-auth linked events.
    apple_user_ids = set(
        AuthAuditLog.objects.filter(
            outcome='success',
            provider='apple',
            user__isnull=False,
        ).values_list('user_id', flat=True)
    )

    payments = UserPremiumFeature.objects.filter(
        user_id__in=apple_user_ids,
        last_payment_date__isnull=False,
        last_payment_date__gte=since,
        paid_amount__gt=0,
    ).select_related('feature')

    revenue = Decimal('0')
    payer_ids = set()
    feature_counts = {}
    for row in payments:
        amount = row.paid_amount or Decimal('0')
        revenue += amount
        payer_ids.add(row.user_id)
        feature_counts[row.feature_id] = feature_counts.get(row.feature_id, 0) + 1

    payer_count = len(payer_ids)
    arppu = (revenue / payer_count) if payer_count else Decimal('0')

    return Response(
        {
            'provider': 'apple',
            'lookback_days': days,
            'apple_oauth_users': len(apple_user_ids),
            'payers': payer_count,
            'revenue': f"{revenue:.2f}",
            'arppu': f"{arppu:.2f}",
            'features_sold': feature_counts,
            'conversion_pct': f"{(Decimal(payer_count) * Decimal('100') / Decimal(len(apple_user_ids)) if apple_user_ids else Decimal('0')):.2f}",
            'since': since,
        }
    )


@api_view(['GET'])
@permission_classes([AllowAny])
def list_premium_features(request):
    from .models import PremiumFeature
    from .serializers import PremiumFeatureSerializer

    features = PremiumFeature.objects.filter(is_active=True).order_by('monthly_price')
    return Response(PremiumFeatureSerializer(features, many=True).data)


@api_view(['GET'])
@permission_classes([AllowAny])
def list_premium_bundles(request):
    from .models import PremiumBundle
    from .serializers import PremiumBundleSerializer

    bundles = PremiumBundle.objects.filter(is_active=True).order_by('display_order')
    return Response(PremiumBundleSerializer(bundles, many=True).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_premium_features(request):
    from .models import UserPremiumFeature
    from .serializers import UserPremiumFeatureSerializer

    features = UserPremiumFeature.objects.filter(user=request.user).select_related('feature').order_by('-subscription_start')
    return Response(UserPremiumFeatureSerializer(features, many=True).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def subscribe_to_feature(request, feature_key):
    from .models import PremiumFeature, UserPremiumFeature
    from .serializers import UserPremiumFeatureSerializer
    from datetime import timedelta
    from django.utils import timezone

    try:
        feature = PremiumFeature.objects.get(feature_key=feature_key, is_active=True)
    except PremiumFeature.DoesNotExist:
        return Response({'error': 'Feature not found.'}, status=status.HTTP_404_NOT_FOUND)

    payload = request.data if isinstance(request.data, dict) else {}
    billing_cycle = payload.get('billing_cycle', 'monthly')
    
    if billing_cycle not in ['monthly', 'yearly']:
        return Response({'error': 'billing_cycle must be monthly or yearly.'}, status=status.HTTP_400_BAD_REQUEST)

    # Get or create subscription
    subscription, created = UserPremiumFeature.objects.get_or_create(
        user=request.user,
        feature=feature,
        defaults={
            'status': 'active',
            'billing_cycle': billing_cycle,
            'auto_renew': True,
            'paid_amount': feature.yearly_price if billing_cycle == 'yearly' else feature.monthly_price,
            'last_payment_date': timezone.now(),
            'renewal_date': timezone.now().date() + timedelta(days=365 if billing_cycle == 'yearly' else 30),
        }
    )

    if not created:
        # Reactivate if cancelled
        subscription.status = 'active'
        subscription.billing_cycle = billing_cycle
        subscription.auto_renew = True
        subscription.last_payment_date = timezone.now()
        subscription.renewal_date = timezone.now().date() + timedelta(days=365 if billing_cycle == 'yearly' else 30)
        subscription.save()

    return Response(
        {
            'success': True,
            'subscription': UserPremiumFeatureSerializer(subscription).data,
            'requires_payment': True,
            'checkout_url': f'/checkout?feature={feature_key}&cycle={billing_cycle}',
        },
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_feature_subscription(request, feature_key):
    from .models import UserPremiumFeature

    subscription = UserPremiumFeature.objects.filter(
        user=request.user,
        feature__feature_key=feature_key,
    ).first()

    if not subscription:
        return Response({'error': 'Subscription not found.'}, status=status.HTTP_404_NOT_FOUND)

    subscription.status = 'cancelled'
    subscription.save()

    return Response({'success': True, 'message': f'Subscription to {subscription.feature.display_name} cancelled.'})


# --- Only show promos to active users except for the superuser (you) ---
# Replace with your actual user ID or email if needed
EXEMPT_EMAILS = ['ctkoth@gmail.com']
def _week_bounds(today=None):
    current = today or timezone.now().date()
    start = current - timedelta(days=current.weekday())
    end = start + timedelta(days=6)
    return start, end


def _build_promo_code(user_id, template_key):
    seed = f"{template_key}-{user_id}-{int(timezone.now().timestamp())}"
    return f"MCZ-{abs(hash(seed)) % 10000000:07d}"


def _related_feature_keys(feature_key):
    mapping = {
        'distribution': ['advanced_analytics', 'lyrics_management', 'pending_edits'],
        'advanced_analytics': ['api_access', 'pro_settle_fast'],
        'unlimited_contributors': ['pending_edits', 'priority_support'],
        'daw_integration': ['design_tools', 'distribution'],
        'design_tools': ['custom_branding', 'distribution'],
        'lyrics_management': ['distribution', 'advanced_analytics'],
    }
    return mapping.get(feature_key, [])


def _build_in_app_feature_ads(user):
    from .models import PremiumFeature, UserPremiumFeature, UserInterest, UserWeeklyPromotion

    interests = list(
        UserInterest.objects.filter(user=user, is_active=True).order_by('-weight').values_list('interest', flat=True)
    )
    interest_set = {x.lower() for x in interests}

    active_subscriptions = list(
        UserPremiumFeature.objects.filter(user=user, status='active').select_related('feature')
    )
    owned = {s.feature.feature_key for s in active_subscriptions if s.is_active_now()}

    week_start, _ = _week_bounds()
    promos = list(
        UserWeeklyPromotion.objects.filter(user=user, week_start=week_start, claimed=False).select_related('template', 'template__target_feature')
    )
    promo_by_feature = {}
    for p in promos:
        if p.template and p.template.target_feature_id:
            promo_by_feature[p.template.target_feature_id] = p

    ads = []
    candidate_keys = set()
    for owned_key in owned:
        for related in _related_feature_keys(owned_key):
            if related not in owned:
                candidate_keys.add(related)

    # Fallback for new users with no owned features.
    if not candidate_keys:
        candidate_keys = {'distribution', 'advanced_analytics', 'unlimited_contributors'}

    features = PremiumFeature.objects.filter(feature_key__in=candidate_keys, is_active=True).order_by('monthly_price')
    for feature in features:
        promo = promo_by_feature.get(feature.feature_key)
        reason = 'upgrade'
        if promo and promo.matched_interest:
            reason = f"interest:{promo.matched_interest}"
        elif interest_set:
            text = f"{feature.display_name} {feature.description}".lower()
            for tag in interest_set:
                if tag in text:
                    reason = f"interest:{tag}"
                    break

        monthly = str(feature.monthly_price)
        discount_percent = promo.discount_percent if promo else 0
        discounted_monthly = monthly
        if discount_percent > 0:
            discounted_value = feature.monthly_price * (100 - discount_percent) / 100
            discounted_monthly = f"{discounted_value:.2f}"

        ads.append(
            {
                'feature_key': feature.feature_key,
                'title': feature.display_name,
                'description': feature.description,
                'monthly_price': monthly,
                'discount_percent': discount_percent,
                'discounted_monthly_price': discounted_monthly,
                'promo_code': promo.promo_code if promo else '',
                'reason': reason,
                'cta': {
                    'type': 'subscribe_feature',
                    'url': f"/api/premium/subscribe/{feature.feature_key}/",
                },
            }
        )

    return ads


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def user_interests(request):
    from .models import UserInterest
    from .serializers import UserInterestSerializer

    if request.method == 'GET':
        rows = UserInterest.objects.filter(user=request.user, is_active=True).order_by('-weight', 'interest')
        return Response(UserInterestSerializer(rows, many=True).data)

    payload = request.data if isinstance(request.data, dict) else {}
    interest = str(payload.get('interest') or '').strip().lower()
    if not interest:
        return Response({'error': 'interest is required.'}, status=status.HTTP_400_BAD_REQUEST)
    weight = int(payload.get('weight') or 1)
    if weight < 1:
        weight = 1
    if weight > 10:
        weight = 10

    row, _ = UserInterest.objects.update_or_create(
        user=request.user,
        interest=interest,
        defaults={'weight': weight, 'is_active': bool(payload.get('is_active', True))},
    )
    return Response(UserInterestSerializer(row).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_weekly_marketing_promotions(request):
    from .models import UserInterest, UserPremiumFeature, WeeklyPromotionTemplate, UserWeeklyPromotion
    from .serializers import UserWeeklyPromotionSerializer

    week_start, week_end = _week_bounds()
    expires_at = timezone.now() + timedelta(days=7)

    active_subscriptions = UserPremiumFeature.objects.filter(user=request.user, status='active').select_related('feature')
    feature_keys = {s.feature.feature_key for s in active_subscriptions if s.is_active_now()}
    if not feature_keys:
        return Response({'generated': 0, 'promotions': [], 'message': 'No active premium features to target.'})

    interests = list(
        UserInterest.objects.filter(user=request.user, is_active=True).order_by('-weight').values_list('interest', flat=True)
    )
    interest_set = set(interests)

    templates = list(
        WeeklyPromotionTemplate.objects.filter(is_active=True, target_feature__feature_key__in=feature_keys).select_related('target_feature')
    )

    # Fallback templates if admin templates are not created yet.
    if not templates:
        for feature_key in feature_keys:
            fallback_key = f"auto-{feature_key}"
            template, _ = WeeklyPromotionTemplate.objects.get_or_create(
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
        return AgreementSignature.objects.filter(models.Q(user=user) | models.Q(agreement__owner=user) | models.Q(agreement__royalty_splits__user=user)).distinct()

class RoyaltySplitViewSet(viewsets.ModelViewSet):
    queryset = RoyaltySplit.objects.all()
    serializer_class = RoyaltySplitSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerForSplitOrPayment]
    def get_queryset(self):
        user = self.request.user
        return RoyaltySplit.objects.filter(models.Q(user=user) | models.Q(agreement__owner=user)).distinct()

class RoyaltyPaymentViewSet(viewsets.ModelViewSet):
    queryset = RoyaltyPayment.objects.all()
    serializer_class = RoyaltyPaymentSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerForSplitOrPayment]
    def get_queryset(self):
        user = self.request.user
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


