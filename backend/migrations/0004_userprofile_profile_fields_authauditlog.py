from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0003_userprofile_verification_and_notifications'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='avatar_url',
            field=models.URLField(blank=True, default='', max_length=512),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='birthday',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='first_name',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='gender',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='last_name',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='location',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
        migrations.CreateModel(
            name='AuthAuditLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event', models.CharField(choices=[('register', 'Register'), ('login', 'Login'), ('oauth_profile_complete', 'OAuth Profile Complete'), ('oauth_account_connect', 'OAuth Account Connect')], max_length=32)),
                ('outcome', models.CharField(choices=[('success', 'Success'), ('failure', 'Failure')], max_length=16)),
                ('provider', models.CharField(blank=True, default='', max_length=32)),
                ('identifier', models.CharField(blank=True, default='', max_length=255)),
                ('ip_address', models.CharField(blank=True, default='', max_length=64)),
                ('user_agent', models.CharField(blank=True, default='', max_length=512)),
                ('details', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='auth_audit_logs', to='auth.user')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]