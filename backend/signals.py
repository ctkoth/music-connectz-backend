from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from allauth.socialaccount.signals import social_account_added
from .models import UserProfile

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    profile, _ = UserProfile.objects.get_or_create(user=instance)
    profile.save()


@receiver(social_account_added)
def ensure_social_user_profile(request, sociallogin, **kwargs):
    user = getattr(sociallogin, 'user', None)
    if user:
        UserProfile.objects.get_or_create(user=user)
