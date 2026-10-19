# What each "What I can do" answer leaves of the exercise library, and how many
# have a demo clip. The BodieZ Play listing quotes these numbers, so re-run this
# before every release and fix play/bodiez/listing/full-description.txt (frontend
# repo) if they moved — a number stated in a store listing that has drifted is the
# "20 free prompts" failure with a price tag on it.
#
#   python manage.py shell < tools/count_adaptive_exercises.py
from types import SimpleNamespace as N

from apps.economy.bodiez import accessible
from apps.economy.models import BodieZExercise

exercises = list(BodieZExercise.objects.all())


def ask(**kw):
    base = dict(seated_or_lying_only=False, arms_ok=True, one_arm_only=False,
                legs_ok=True, one_leg_only=False)
    base.update(kw)
    return N(**base)


cases = {
    "everything": ask(),
    "seated or lying only": ask(seated_or_lying_only=True),
    "cannot use legs": ask(legs_ok=False),
    "cannot use arms": ask(arms_ok=False),
    "one arm only": ask(one_arm_only=True),
    "one leg only": ask(one_leg_only=True),
    "cannot use arms or legs": ask(arms_ok=False, legs_ok=False),
}
for label, access in cases.items():
    print(f"{label:26s} {sum(accessible(e, access) for e in exercises):3d} of {len(exercises)}")
with_demo = sum(1 for e in exercises if e.demo_url)
print(f"{'with a demo clip':26s} {with_demo:3d} of {len(exercises)}  ({len(exercises) - with_demo} without)")
