from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.core.models import Membership


class Command(BaseCommand):
    help = "Set a user's membership tier: set_tier <username> <free|premium|statz>"

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("tier", choices=["free", "premium", "statz"])

    def handle(self, *args, **opts):
        User = get_user_model()
        try:
            user = User.objects.get(username=opts["username"])
        except User.DoesNotExist:
            raise CommandError("No such user")
        m, _ = Membership.objects.get_or_create(user=user)
        m.tier = opts["tier"]; m.save()
        self.stdout.write(self.style.SUCCESS(f"{user.username} -> {m.tier}"))
