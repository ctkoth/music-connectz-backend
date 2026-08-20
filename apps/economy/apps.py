from django.apps import AppConfig
from django.core.checks import Warning as CheckWarning, register


@register()
def uploads_are_durable(app_configs, **kwargs):
    """Fail loudly in the DEPLOY LOG when uploads are going somewhere temporary.

    A system check because `manage.py migrate` runs the checks, and build.sh
    runs migrate on every deploy — so this lands in the Render build output
    right where somebody is already watching a deploy go out.

    A Warning and not an Error on purpose: an Error fails the check, and
    `set -o errexit` in build.sh would then turn "your uploads aren't durable"
    into "the deploy is refused", which takes the whole site down over a
    misconfiguration that the site can technically run with. Loud, not fatal.
    """
    from .storage_health import DOCS, upload_storage_state

    state = upload_storage_state()
    if not state["ephemeral"]:
        return []
    return [CheckWarning(
        "Member uploads are stored on an ephemeral container disk and will be "
        "DELETED on the next deploy.",
        hint=f"Files are going to {state['where']}, which is part of this "
             f"container and is rebuilt every time anything merges to main. "
             f"The Upload rows survive in Postgres, so the app keeps serving "
             f"links to files that no longer exist. {DOCS}",
        id="economy.W001",
    )]


class EconomyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.economy"
    verbose_name = "Economy"

    def ready(self):
        # And in the RUNNING service's log. gunicorn does not run system
        # checks, so without this the only place the warning appears is a build
        # log nobody reads twice.
        from .storage_health import warn_once
        warn_once()
