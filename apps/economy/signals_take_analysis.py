"""Signals to trigger take analysis on upload."""
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.apps import apps
from .take_analyzer import analyze_take_audio


@receiver(post_save, sender='economy.Upload')
def analyze_take_on_upload(sender, instance, created, **kwargs):
    """Automatically analyze uploaded takes for pitch and timing.

    Only runs for audio uploads (kind in [singz, rapz, guitarz, bassz, etc])
    """
    if not created:
        return

    app_keys = {
        'singz', 'rapz', 'guitarz', 'bassz', 'keyz', 'drumz', 'violinz'
    }

    if instance.app_key not in app_keys:
        return

    try:
        analyze_take_audio(instance.id)
    except Exception as e:
        print(f"Failed to analyze take {instance.id}: {e}")


def ready():
    """Called when app is ready. Import this in apps.py AppConfig.ready()"""
    pass
