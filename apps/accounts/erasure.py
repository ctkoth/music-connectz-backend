"""Deleting an account has to delete what it uploaded, not only the rows.

`user.delete()` cascades the ROWS — the `Upload`, the `Face`, the avatar's
`Profile` — and a Django `FileField` never deletes its bytes when its row goes.
There was no `post_delete` signal, no cleanup package and no sweep anywhere, so
every track, video, photo and avatar a member had ever uploaded stayed on the
disk (or in the bucket) after the member was gone. The privacy policy and the
delete-account page both said "your uploads" were deleted; the database said so
and the storage did not.

That matters more than it sounds: `Face` images and avatars are pictures of
people, and "delete my account" is the one request where leaving a copy behind
is the whole failure.

So the files are found BEFORE the delete (afterwards the rows that name them
are gone) and removed once it has COMMITTED. Order is the point:

- Before the delete, because the row is the only record of the name.
- After the commit, because a delete that rolls back must not leave rows
  pointing at files somebody already removed — that is the same "player that
  404s" failure `Upload.missing_since` exists to name.
- A storage error is logged, never raised. The member asked to be deleted and
  the rows are gone; a bucket having a bad minute is not a reason to answer 500
  and leave a half-deleted account to be retried by hand. `reconcile_uploads`
  is the place that walks storage for what a failure left behind.

The models are FOUND, not listed. Seven of them own a file today (Upload, Face,
Profile.avatar, BugReport.shot, MerchItem.image, KeyboardSkin.wallpaper,
Game.bundle) and an eighth is one migration away; a hand-written list is the
version of this that is correct on the day it is written. Only a foreign key to
the user with `on_delete=CASCADE` counts — a SET_NULL row is KEPT (detached from
the account), and so are its bytes.
"""
import logging

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import models, transaction

log = logging.getLogger(__name__)


def collect_files(user):
    """[(storage, name), ...] for every file a CASCADE row of `user` holds."""
    User = get_user_model()
    found = []
    for model in apps.get_models():
        file_fields = [f for f in model._meta.get_fields() if isinstance(f, models.FileField)]
        if not file_fields:
            continue
        owners = [
            f for f in model._meta.get_fields()
            if f.concrete and (f.many_to_one or f.one_to_one)
            and f.related_model is User and f.remote_field.on_delete is models.CASCADE
        ]
        for owner in owners:
            # _base_manager: a model's default manager may hide rows, and a
            # hidden row's file is still the member's.
            for obj in model._base_manager.filter(**{owner.name: user}):
                for field in file_fields:
                    stored = getattr(obj, field.name)
                    if stored and stored.name:
                        found.append((stored.storage, stored.name))
    return found


def purge_files(files):
    """Remove each stored file. Never raises; failures are logged."""
    for storage, name in files:
        try:
            storage.delete(name)
        except Exception:  # noqa: BLE001 — see the module docstring
            log.exception("account erasure: could not remove stored file %r", name)


def delete_user(user, *, billing_stopped=False):
    """Cancel their billing, `user.delete()`, then the stored files once it commits.

    Raises `CancelFailed` (a `ValueError`) BEFORE touching anything if a Stripe
    subscription could not be cancelled: see `economy/stripe_cancel.py` for why
    that refuses the delete rather than going ahead. `billing_stopped` is for the
    one caller that has already done it, so a retry or a second door does not
    pay for the same round trips twice.
    """
    if not billing_stopped:
        from apps.economy.stripe_cancel import cancel_for
        cancel_for(user)
    files = collect_files(user)
    with transaction.atomic():
        user.delete()
        transaction.on_commit(lambda: purge_files(files))
