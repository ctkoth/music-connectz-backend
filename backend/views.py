from rest_framework import viewsets, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.http import JsonResponse
from rest_framework import status
from django.db.models import Avg, Count
from django.contrib.auth import get_user_model
from django.utils import timezone
from .models import Post, PostJoin, UserWeeklyPromotion, WeeklyPromotionTemplate
from .serializers import PostSerializer, PostJoinSerializer, UserWeeklyPromotionSerializer

# ============================================================================
# WORKING VIEWS - These use models that exist in models.py
# ============================================================================

# --- PostZ CRUD ---
class PostViewSet(viewsets.ModelViewSet):
    queryset = Post.objects.all().order_by('-created_at')
    serializer_class = PostSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

# --- PostZ Joins ---
class PostJoinViewSet(viewsets.ModelViewSet):
    queryset = PostJoin.objects.all()
    serializer_class = PostJoinSerializer
    permission_classes = [permissions.IsAuthenticated]

# --- Public API: App Version ---
@api_view(['GET'])
@permission_classes([AllowAny])
def app_version(request):
    return JsonResponse({
        "version": "v15.6",
        "deployed": "2026-04-06"
    })

# --- Weekly Promotions API ---
def _week_bounds():
    """Helper: Get start and end dates for current week (Monday-Sunday)"""
    from datetime import timedelta
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    return week_start, week_end

def _build_promo_code(user_id, template_key):
    """Helper: Generate promo code"""
    return f"PROMO_{user_id}_{template_key}".upper()[:40]

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_weekly_promotions(request):
    """Get authenticated user's weekly promotions"""
    week_start, _ = _week_bounds()
    rows = UserWeeklyPromotion.objects.filter(
        user=request.user, 
        week_start=week_start
    ).select_related('template', 'template__target_feature')
    return Response(UserWeeklyPromotionSerializer(rows, many=True).data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def claim_weekly_promotion(request, promotion_id):
    """Claim a weekly promotion"""
    row = UserWeeklyPromotion.objects.filter(
        id=promotion_id, 
        user=request.user
    ).select_related('template', 'template__target_feature').first()
    
    if not row:
        return Response({'error': 'Promotion not found.'}, status=status.HTTP_404_NOT_FOUND)
    if row.claimed:
        return Response({'error': 'Promotion already claimed.'}, status=status.HTTP_400_BAD_REQUEST)
    if row.expires_at and row.expires_at < timezone.now():
        return Response({'error': 'Promotion expired.'}, status=status.HTTP_400_BAD_REQUEST)
    
    row.claimed = True
    row.save(update_fields=['claimed', 'updated_at'])
    return Response({'success': True, 'promotion': UserWeeklyPromotionSerializer(row).data})

# ============================================================================
# MISSING MODELS - These views are commented out until models are created
# ============================================================================

# TODO: PostRatingViewSet - Requires PostRating model
# class PostRatingViewSet(viewsets.ModelViewSet):
#     queryset = PostRating.objects.all()
#     serializer_class = PostRatingSerializer
#     permission_classes = [permissions.IsAuthenticated]

# TODO: OCCLogViewSet - Requires OCCLog model
# class OCCLogViewSet(viewsets.ModelViewSet):
#     queryset = OCCLog.objects.all().order_by('-created_at')
#     serializer_class = OCCLogSerializer
#     permission_classes = [permissions.IsAuthenticated]

# TODO: corey_feedback_and_suggestions - Requires CollabReliabilityRating and UserProfile models
# @api_view(['GET'])
# @permission_classes([IsAuthenticated])
# def corey_feedback_and_suggestions(request):
#     """
#     Returns quantifiable Corey feedback, improvement suggestions, and teacher/mentor recommendations.
#     For high-rated users, recommends becoming a teacher and provides instructions.
#     """
#     from .models import CollabReliabilityRating, UserProfile
#     # ... implementation

# TODO: get_corey_voice_for_user - Requires CollabReliabilityRating model
# def get_corey_voice_for_user(user):
#     """
#     Returns Corey-voice style: playful/flirtatious if avg rating >=5, else normal Corey-voice.
#     """
#     from .models import CollabReliabilityRating
#     # ... implementation

# TODO: user_personas - Requires Persona model
# @api_view(['GET'])
# @permission_classes([IsAuthenticated])
# def user_personas(request):
#     """
#     List all personas for the authenticated user, including their skills.
#     """
#     from .models import Persona
#     # ... implementation

# TODO: ai_suggest_skill_prices - Requires Persona, Skill, CollabReliabilityRating models
# @api_view(['GET'])
# @permission_classes([IsAuthenticated])
# def ai_suggest_skill_prices(request):
#     """
#     Suggest skill prices for the authenticated user based on their ratings, reviews, and demand.
#     """
#     from .models import Skill, Persona, CollabReliabilityRating
#     # ... implementation

# TODO: generate_weekly_promotions - Requires additional models
# @api_view(['POST'])
# @permission_classes([IsAuthenticated])
# def generate_weekly_promotions(request):
#     """
#     Generate personalized weekly promotions for the authenticated user.
#     """
#     # ... implementation

# TODO: in_app_feature_ads - Requires additional helper models
# @api_view(['GET'])
# @permission_classes([IsAuthenticated])
# def in_app_feature_ads(request):
#     """
#     Get in-app feature ads for the authenticated user.
#     """
#     # ... implementation

# TODO: Agreement & Royalty Views - Require Agreement, AgreementSignature, RoyaltySplit, RoyaltyPayment models
# from rest_framework import viewsets, permissions
# from .models import Agreement, AgreementSignature, RoyaltySplit, RoyaltyPayment
# from .serializers import (
#     AgreementSerializer, AgreementSignatureSerializer, RoyaltySplitSerializer, RoyaltyPaymentSerializer
# )
# 
# class IsAgreementOwnerOrReadOnly(permissions.BasePermission):
#     def has_object_permission(self, request, view, obj):
#         if request.method in permissions.SAFE_METHODS:
#             return request.user == obj.owner or obj.royalty_splits.filter(user=request.user).exists()
#         return request.user == obj.owner
#
# class IsSignatureUser(permissions.BasePermission):
#     def has_object_permission(self, request, view, obj):
#         return request.user == obj.user
#
# class IsOwnerForSplitOrPayment(permissions.BasePermission):
#     def has_object_permission(self, request, view, obj):
#         return request.user == obj.agreement.owner
#
# class AgreementViewSet(viewsets.ModelViewSet):
#     queryset = Agreement.objects.all()
#     serializer_class = AgreementSerializer
#     permission_classes = [permissions.IsAuthenticated, IsAgreementOwnerOrReadOnly]
#     def perform_create(self, serializer):
#         agreement = serializer.save(owner=self.request.user)
#         notify_agreement_created(agreement)
#
# class AgreementSignatureViewSet(viewsets.ModelViewSet):
#     queryset = AgreementSignature.objects.all()
#     serializer_class = AgreementSignatureSerializer
#     permission_classes = [permissions.IsAuthenticated, IsSignatureUser]
#     def get_queryset(self):
#         user = self.request.user
#         return AgreementSignature.objects.filter(
#             models.Q(user=user) | models.Q(agreement__owner=user) | models.Q(agreement__royalty_splits__user=user)
#         ).distinct()
#
# class RoyaltySplitViewSet(viewsets.ModelViewSet):
#     queryset = RoyaltySplit.objects.all()
#     serializer_class = RoyaltySplitSerializer
#     permission_classes = [permissions.IsAuthenticated, IsOwnerForSplitOrPayment]
#     def get_queryset(self):
#         user = self.request.user
#         return RoyaltySplit.objects.filter(
#             models.Q(user=user) | models.Q(agreement__owner=user)
#         ).distinct()
#
# class RoyaltyPaymentViewSet(viewsets.ModelViewSet):
#     queryset = RoyaltyPayment.objects.all()
#     serializer_class = RoyaltyPaymentSerializer
#     permission_classes = [permissions.IsAuthenticated, IsOwnerForSplitOrPayment]
#     def get_queryset(self):
#         user = self.request.user
#         return RoyaltyPayment.objects.filter(
#             models.Q(user=user) | models.Q(agreement__owner=user)
#         ).distinct()
#
# def notify_agreement_created(agreement):
#     from django.core.mail import send_mail
#     recipients = [split.user.email for split in agreement.royalty_splits.all() if split.user != agreement.owner and split.user.email]
#     if recipients:
#         send_mail(
#             subject=f"New Agreement: {agreement.title}",
#             message=f"You have been added to a new agreement '{agreement.title}' for project '{agreement.project}'. Log in to review and sign.",
#             from_email=None,
#             recipient_list=recipients,
#             fail_silently=True,
#         )
#
# def notify_signature_signed(signature):
#     from django.core.mail import send_mail
#     owner_email = signature.agreement.owner.email
#     if owner_email:
#         send_mail(
#             subject=f"Agreement Signed: {signature.agreement.title}",
#             message=f"{signature.user.username} has signed the agreement '{signature.agreement.title}'.",
#             from_email=None,
#             recipient_list=[owner_email],
#             fail_silently=True,
#         )
