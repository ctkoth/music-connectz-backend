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
import openai
from django.views.decorators.csrf import csrf_exempt
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
from io import BytesIO
# --- Royalty Agreement PDF Download Endpoint ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def download_royalty_agreement_pdf(request, agreement_id):
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
def register_with_referral(request):
    referral_code = request.data.get('referral_code')
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
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
def api_register(request):
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
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
def api_login(request):
    identifier = (request.data.get('identifier') or request.data.get('email') or '').strip()
    password = (request.data.get('password') or '').strip()

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
    # Try email lookup
    if '@' in identifier:
        try:
            u = User.objects.get(email__iexact=identifier)
            user = authenticate(request, username=u.username, password=password)
        except User.DoesNotExist:
            pass
    # Try phone lookup
    if user is None and _re.match(r'^\+?\d[\d\s\-(). ]{5,}$', identifier):
        try:
            prof = UserProfile.objects.get(phone_number=identifier)
            user = authenticate(request, username=prof.user.username, password=password)
        except UserProfile.DoesNotExist:
            pass
    # Try username lookup
    if user is None:
        user = authenticate(request, username=identifier, password=password)

    if user is None:
        _record_auth_event(
            request,
            event='login',
            outcome='failure',
            identifier=identifier,
            details={'reason': 'invalid_credentials'},
        )
        return Response({'error': 'Invalid credentials.'}, status=status.HTTP_401_UNAUTHORIZED)

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
        return JsonResponse({
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
    return JsonResponse({'authenticated': False}, status=401)


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
        'spotify': 'spotify',
        'soundcloud': 'soundcloud',
        'tiktok': 'tiktok',
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
