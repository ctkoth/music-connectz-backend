#!/usr/bin/env python
"""
Populate premium features and bundles.
Usage: python seed_premium_features.py
"""

import os
import sys
import django
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from backend.models import PremiumFeature, PremiumBundle

# Clear existing features (optional)
print("Seeding premium features and bundles...\n")

# Define features
features_data = [
    {
        'feature_key': 'distribution',
        'feature_type': 'distribution',
        'display_name': 'Music Distribution',
        'description': 'Distribute your releases to Spotify, Apple Music, and 100+ platforms',
        'monthly_price': Decimal('9.99'),
        'yearly_price': Decimal('95.99'),
    },
    {
        'feature_key': 'unlimited_contributors',
        'feature_type': 'unlimited_contributors',
        'display_name': 'Unlimited Contributors',
        'description': 'Add unlimited collaborators per release (writers, producers, engineers, designers, etc.)',
        'monthly_price': Decimal('4.99'),
        'yearly_price': Decimal('47.99'),
    },
    {
        'feature_key': 'advanced_analytics',
        'feature_type': 'advanced_analytics',
        'display_name': 'Advanced Analytics',
        'description': 'Real-time streams, revenue, listeners, platform breakdown, and contributor earnings tracking',
        'monthly_price': Decimal('8.99'),
        'yearly_price': Decimal('86.99'),
    },
    {
        'feature_key': 'pending_edits',
        'feature_type': 'pending_edits',
        'display_name': 'Pending Release Edits',
        'description': 'Edit releases, tracks, and contributor info even after submission',
        'monthly_price': Decimal('3.99'),
        'yearly_price': Decimal('38.99'),
    },
    {
        'feature_key': 'lyrics_management',
        'feature_type': 'lyrics_management',
        'display_name': 'Lyrics Management',
        'description': 'Upload and sync lyrics with major platforms',
        'monthly_price': Decimal('2.99'),
        'yearly_price': Decimal('28.99'),
    },
    {
        'feature_key': 'priority_support',
        'feature_type': 'priority_support',
        'display_name': 'Priority Support',
        'description': '24/7 priority email and chat support',
        'monthly_price': Decimal('5.99'),
        'yearly_price': Decimal('57.99'),
    },
    {
        'feature_key': 'api_access',
        'feature_type': 'api_access',
        'display_name': 'API Access',
        'description': 'Full REST API access for automation and custom integrations',
        'monthly_price': Decimal('9.99'),
        'yearly_price': Decimal('95.99'),
    },
    {
        'feature_key': 'pro_settle_fast',
        'feature_type': 'pro_settle_fast',
        'display_name': 'Fast Settlement (48 hours)',
        'description': 'Get paid in 48 hours instead of standard monthly settlement',
        'monthly_price': Decimal('8.99'),
        'yearly_price': Decimal('86.99'),
    },
    {
        'feature_key': 'daw_integration',
        'feature_type': 'daw_integration',
        'display_name': 'DAW Integration',
        'description': 'Direct integration with Ableton, Logic Pro, FL Studio, and other DAWs for direct release upload',
        'monthly_price': Decimal('4.99'),
        'yearly_price': Decimal('47.99'),
    },
    {
        'feature_key': 'design_tools',
        'feature_type': 'design_tools',
        'display_name': 'Design Tools',
        'description': 'Built-in cover art editor, design templates, and Photoshop/Canva integration',
        'monthly_price': Decimal('4.99'),
        'yearly_price': Decimal('47.99'),
    },
    {
        'feature_key': 'custom_branding',
        'feature_type': 'custom_branding',
        'display_name': 'Custom Branding',
        'description': 'Customize theme colors, artist profiles, and white label your releases',
        'monthly_price': Decimal('2.99'),
        'yearly_price': Decimal('28.99'),
    },
    {
        'feature_key': 'docs_integration',
        'feature_type': 'docs_integration',
        'display_name': 'Docs Integration',
        'description': 'Microsoft Word/Google Docs integration for lyrics, liner notes, and credits',
        'monthly_price': Decimal('2.99'),
        'yearly_price': Decimal('28.99'),
    },
]

created_features = {}
for feat_data in features_data:
    feature, created = PremiumFeature.objects.update_or_create(
        feature_key=feat_data['feature_key'],
        defaults={
            'feature_type': feat_data['feature_type'],
            'display_name': feat_data['display_name'],
            'description': feat_data['description'],
            'monthly_price': feat_data['monthly_price'],
            'yearly_price': feat_data['yearly_price'],
            'is_active': True,
        }
    )
    created_features[feat_data['feature_key']] = feature
    status = "✓ Created" if created else "✓ Updated"
    print(f"{status}: {feature.display_name} (${feature.monthly_price}/mo)")

print("\nSeeding premium bundles...\n")

# Define bundles
bundles_data = [
    {
        'bundle_key': 'creator_starter',
        'bundle_name': 'Creator Basic',
        'description': 'Core distribution plus essential creator tools at a low monthly price',
        'features': ['distribution', 'lyrics_management', 'pending_edits'],
        'monthly_price': Decimal('12.99'),
        'yearly_price': Decimal('124.99'),
        'display_order': 1,
    },
    {
        'bundle_key': 'creator_pro',
        'bundle_name': 'Creator Pro',
        'description': 'Everything you need to grow your music career',
        'features': ['distribution', 'unlimited_contributors', 'advanced_analytics', 'pending_edits', 'lyrics_management', 'priority_support', 'daw_integration'],
        'monthly_price': Decimal('24.99'),
        'yearly_price': Decimal('239.99'),
        'display_order': 2,
    },
    {
        'bundle_key': 'label_studio',
        'bundle_name': 'Label Studio',
        'description': 'For labels and producers managing multiple artists',
        'features': ['distribution', 'unlimited_contributors', 'advanced_analytics', 'pending_edits', 'lyrics_management', 'priority_support', 'api_access', 'pro_settle_fast'],
        'monthly_price': Decimal('64.99'),
        'yearly_price': Decimal('619.99'),
        'display_order': 3,
    },
    {
        'bundle_key': 'ultimate_creator',
        'bundle_name': 'Ultimate Creator Studio',
        'description': 'Everything you need - all distribution, tools, analytics, and support',
        'features': ['distribution', 'unlimited_contributors', 'advanced_analytics', 'pending_edits', 'lyrics_management', 'priority_support', 'api_access', 'pro_settle_fast', 'daw_integration', 'design_tools', 'custom_branding', 'docs_integration'],
        'monthly_price': Decimal('49.99'),
        'yearly_price': Decimal('479.99'),
        'display_order': 4,
    },
]

for bundle_data in bundles_data:
    bundle, created = PremiumBundle.objects.update_or_create(
        bundle_key=bundle_data['bundle_key'],
        defaults={
            'bundle_name': bundle_data['bundle_name'],
            'description': bundle_data['description'],
            'monthly_price': bundle_data['monthly_price'],
            'yearly_price': bundle_data['yearly_price'],
            'is_active': True,
            'display_order': bundle_data['display_order'],
        }
    )
    
    # Clear and re-add features
    bundle.features.clear()
    for feature_key in bundle_data['features']:
        if feature_key in created_features:
            bundle.features.add(created_features[feature_key])
    
    status = "✓ Created" if created else "✓ Updated"
    feature_count = bundle.features.count()
    print(f"{status}: {bundle.bundle_name} - ${bundle.monthly_price}/mo ({feature_count} features)")

print("\n✅ Premium features and bundles seeded successfully!")
