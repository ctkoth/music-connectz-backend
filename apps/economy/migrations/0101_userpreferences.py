# Generated migration for UserPreferences model

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('economy', '0100_habit'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserPreferences',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('notifications_enabled', models.BooleanField(default=True, help_text='Receive daily habit reminders')),
                ('language', models.CharField(choices=[('en', 'English'), ('es', 'Español'), ('fr', 'Français'), ('de', 'Deutsch'), ('pt', 'Português'), ('ja', '日本語')], default='en', max_length=5)),
                ('sound_enabled', models.BooleanField(default=True, help_text='Play sound effects')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='onboarding_preferences', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
