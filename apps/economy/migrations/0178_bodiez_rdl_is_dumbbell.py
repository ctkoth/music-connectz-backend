"""The library's Romanian Deadlift is a dumbbell lift: convert it.

Corey's call. The only footage is a dumbbell RDL, and 0177 had added a second
"Dumbbell Romanian Deadlift" row beside the barbell one. Two rows for one
lift is the split this undoes: the ORIGINAL row (which may already carry
logged sets, goals and routines) becomes the dumbbell exercise and takes the
clip, and the 0177 duplicate is folded into it and removed.

Folding comes before deleting because `BodieZSet.exercise` cascades — deleting
the duplicate first would silently delete anything logged against it. Routine
exercise lists are JSON, so they are rewritten by hand, de-duplicating a
routine that somehow held both.
"""
from django.db import migrations

OLD, NEW = "Romanian Deadlift", "Dumbbell Romanian Deadlift"
URL = "/exercise-demos/Dumbbell%20Romanian%20Deadlift.mp4"


def forwards(apps, schema_editor):
    Ex = apps.get_model("economy", "BodieZExercise")
    Set = apps.get_model("economy", "BodieZSet")
    Goal = apps.get_model("economy", "BodieZGoal")
    Routine = apps.get_model("economy", "BodieZRoutine")

    orig = Ex.objects.filter(name=OLD).first()
    dup = Ex.objects.filter(name=NEW).first()
    if orig is None:
        return  # nothing to convert; the 0177 row (if any) is already the dumbbell one
    if dup is not None and dup.id != orig.id:
        Set.objects.filter(exercise_id=dup.id).update(exercise_id=orig.id)
        Goal.objects.filter(exercise_id=dup.id).update(exercise_id=orig.id)
        for r in Routine.objects.all():
            rows = r.exercises if isinstance(r.exercises, list) else []
            if not any(isinstance(e, dict) and e.get("exercise_id") == dup.id for e in rows):
                continue
            seen, out = set(), []
            for e in rows:
                if isinstance(e, dict) and e.get("exercise_id") == dup.id:
                    e = {**e, "exercise_id": orig.id}
                key = e.get("exercise_id") if isinstance(e, dict) else None
                if key is not None and key in seen:
                    continue
                seen.add(key)
                out.append(e)
            r.exercises = out
            r.save(update_fields=["exercises"])
        dup.delete()
    orig.name = NEW
    orig.equipment = "dumbbell"
    orig.demo_url = orig.demo_url or URL
    orig.save()


class Migration(migrations.Migration):
    dependencies = [("economy", "0177_bodiez_access_tags_and_new_exercises")]
    # One-way on purpose: a reverse would have to guess which rows were ever
    # barbell. The data it changes is a name, an equipment tag and a clip.
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
