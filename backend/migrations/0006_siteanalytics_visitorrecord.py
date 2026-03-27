from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0005_seed_additional_socialapps'),
    ]

    operations = [
        migrations.CreateModel(
            name='SiteAnalytics',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(default='global', max_length=32, unique=True)),
                ('total_visits', models.PositiveIntegerField(default=0)),
                ('unique_visitors', models.PositiveIntegerField(default=0)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='VisitorRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('visitor_key', models.CharField(max_length=128, unique=True)),
                ('visit_count', models.PositiveIntegerField(default=1)),
                ('first_seen_at', models.DateTimeField(auto_now_add=True)),
                ('last_seen_at', models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
