#!/usr/bin/env python
"""
Grant premium access to a specific user by email.
Usage: python grant_premium.py ctkoth@gmail.com
"""

import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from django.contrib.auth.models import User
from backend.models import UserProfile

if len(sys.argv) < 2:
    print("Usage: python grant_premium.py <email>")
    sys.exit(1)

email = sys.argv[1]

try:
    user = User.objects.get(email=email)
    profile, created = UserProfile.objects.get_or_create(user=user)
    profile.is_premium = True
    profile.save()
    print(f"✓ Premium access granted to {user.username} ({email})")
    print(f"  Profile created: {created}")
except User.DoesNotExist:
    print(f"✗ User with email '{email}' not found.")
    print("  Please create the account first and run this script again.")
    sys.exit(1)
except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)
