#!/usr/bin/env python
"""
Seed weekly promotion templates for premium-feature-based marketing.
Usage: python seed_weekly_promotion_templates.py
"""

import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from backend.models import PremiumFeature, WeeklyPromotionTemplate

print("Seeding weekly promotion templates...\n")

TEMPLATES = [
    {
        'template_key': 'weekly-distribution-boost',
        'title': 'Boost Your Next Release',
        'description': 'This week only: discount on distribution upgrades for artists pushing new singles.',
        'feature_key': 'distribution',
        'interest_tags_json': ['release', 'single', 'album', 'distribution', 'spotify'],
        'discount_percent': 20,
    },
    {
        'template_key': 'weekly-analytics-pro',
        'title': 'Know Your Audience Better',
        'description': 'Unlock deeper fan insights and weekly listener trends at a discounted rate.',
        'feature_key': 'advanced_analytics',
        'interest_tags_json': ['analytics', 'growth', 'audience', 'listeners'],
        'discount_percent': 18,
    },
    {
        'template_key': 'weekly-collab-unlimited',
        'title': 'Collab Without Limits',
        'description': 'Invite more writers, producers, and engineers with this weekly collaborator offer.',
        'feature_key': 'unlimited_contributors',
        'interest_tags_json': ['collab', 'producer', 'writer', 'engineer', 'team'],
        'discount_percent': 22,
    },
    {
        'template_key': 'weekly-lyrics-pro',
        'title': 'Lyrics Sync Week',
        'description': 'Save this week on lyrics management and sync your catalog faster.',
        'feature_key': 'lyrics_management',
        'interest_tags_json': ['lyrics', 'songwriting', 'publishing'],
        'discount_percent': 15,
    },
    {
        'template_key': 'weekly-edit-flex',
        'title': 'Need Last-Minute Changes?',
        'description': 'Special offer for editing pending releases after submission.',
        'feature_key': 'pending_edits',
        'interest_tags_json': ['release', 'edit', 'fix', 'deadline'],
        'discount_percent': 17,
    },
    {
        'template_key': 'weekly-daw-direct',
        'title': 'DAW to Distribution',
        'description': 'Ship from your DAW directly with this week\'s creator tools promo.',
        'feature_key': 'daw_integration',
        'interest_tags_json': ['daw', 'fl studio', 'logic', 'ableton', 'workflow'],
        'discount_percent': 16,
    },
    {
        'template_key': 'weekly-design-cover',
        'title': 'Cover Art Creator Deal',
        'description': 'Discounted design tools for better cover art and release visuals.',
        'feature_key': 'design_tools',
        'interest_tags_json': ['design', 'cover art', 'branding', 'photoshop', 'canva'],
        'discount_percent': 16,
    },
    {
        'template_key': 'weekly-api-automation',
        'title': 'Automate Your Label Ops',
        'description': 'Weekly deal on API access for power users and labels.',
        'feature_key': 'api_access',
        'interest_tags_json': ['api', 'automation', 'label', 'integration'],
        'discount_percent': 14,
    },
]

created = 0
updated = 0
skipped = 0

for row in TEMPLATES:
    feature = PremiumFeature.objects.filter(feature_key=row['feature_key']).first()
    if not feature:
        skipped += 1
        print(f"- Skipped {row['template_key']}: premium feature '{row['feature_key']}' not found")
        continue

    obj, was_created = WeeklyPromotionTemplate.objects.update_or_create(
        template_key=row['template_key'],
        defaults={
            'title': row['title'],
            'description': row['description'],
            'target_feature': feature,
            'interest_tags_json': row['interest_tags_json'],
            'discount_percent': row['discount_percent'],
            'is_active': True,
        },
    )
    if was_created:
        created += 1
        print(f"+ Created {obj.template_key} ({obj.discount_percent}% for {feature.display_name})")
    else:
        updated += 1
        print(f"~ Updated {obj.template_key} ({obj.discount_percent}% for {feature.display_name})")

print("\nDone.")
print(f"Created: {created}")
print(f"Updated: {updated}")
print(f"Skipped: {skipped}")

if skipped > 0:
    print("\nTip: run seed_premium_features.py first, then run this script again.")

sys.exit(0)
